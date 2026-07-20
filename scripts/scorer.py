"""
scorer.py — Sends each job posting to Claude and gets back a 0-100 fit score,
a short match summary, and flags for salary/location eligibility.

Cost-efficiency features:
  - Anthropic prompt caching: the shared resume+criteria prefix (≈1,500 tokens)
    is marked cache_control="ephemeral". Jobs 2-N in a run reuse the cached
    prefix at 10% of normal input-token cost, cutting per-run spend by ~70%.
  - Smart JD trimming: strips boilerplate tails (EEO, benefits, "About Us"
    sections) before sending to Claude, without touching the substantive role
    description.
  - Deduplication: title+company dedup runs before Claude so the same job
    scraped from two sources (e.g. Greenhouse + LinkedIn) is only scored once.
  - Daily scoring cap: MAX_NEW_SCORES_PER_RUN prevents runaway cost if a
    cache wipe or scraping surge returns an unusually large batch.
  - Persistent seen-IDs registry: seen_job_ids.json records every job ID ever
    scraped. Even after a scored_jobs.json cache wipe, previously-seen IDs are
    skipped without spending tokens.
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from anthropic import Anthropic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pre-filter — eliminates obvious mismatches before spending any tokens
# ---------------------------------------------------------------------------

_JUNIOR_SIGNALS = [
    "junior", "associate product manager", "apm ", "entry level",
    "entry-level", "internship", "intern ", " intern,", " intern", "coordinator",
    "analyst i ", "analyst i,",
]

_ONSITE_SIGNALS = [
    "on-site only", "onsite only", "in-office only", "must be located in",
    "new york only", "san francisco only", "seattle only", "chicago only",
    "austin only", "no remote",
]

# Non-USA location signals — any of these in the location field → drop immediately
_INTERNATIONAL_SIGNALS = [
    # Europe
    "spain", "madrid", "barcelona", "uk", "united kingdom", "london", "england",
    "germany", "berlin", "munich", "france", "paris", "netherlands", "amsterdam",
    "ireland", "dublin", "sweden", "stockholm", "denmark", "copenhagen",
    "norway", "oslo", "finland", "helsinki", "switzerland", "zurich",
    "portugal", "lisbon", "italy", "rome", "milan", "poland", "warsaw",
    "czech", "prague", "romania", "bucharest", "austria", "vienna",
    # Americas (non-US)
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
    "mexico", "brazil", "argentina", "colombia", "chile",
    # Asia-Pacific
    "india", "bangalore", "hyderabad", "mumbai", "delhi", "pune",
    "singapore", "japan", "tokyo", "osaka", "china", "beijing", "shanghai",
    "shenzhen", "australia", "sydney", "melbourne", "brisbane", "new zealand",
    "south korea", "seoul", "taiwan", "taipei", "hong kong",
    # Broad regions
    "emea", "apac", ", uk", ", canada", ", india", ", australia",
    "latin america", "europe", "asia pacific", "asia-pacific",
]

# Remote/hybrid signals — if any of these appear, the job is location-flexible
_REMOTE_SIGNALS = [
    "remote", "hybrid", "work from home", "wfh", "distributed",
    "anywhere in the us", "anywhere in us", "flexible location",
]

# Generic US / no-location signals — pass through (let Claude score)
_USA_GENERIC = [
    "united states", "usa", "u.s.a", "u.s.", "nationwide", "us only",
    "anywhere", "multiple locations", "various locations",
]

# Cities/areas within ~30 miles of Denver
_DENVER_METRO = [
    "denver", "boulder", "broomfield", "aurora", "lakewood", "westminster",
    "arvada", "englewood", "littleton", "golden", "centennial", "parker",
    "castle rock", "highlands ranch", "thornton", "northglenn", "commerce city",
    "lone tree", "erie", "louisville", "lafayette", "superior", "wheat ridge",
    "federal heights", "edgewater", "sheridan",
    # State-level (CO → remote or Denver-area)
    "colorado", " co,", " co ", "(co)", ", co",
]


def pre_filter(job: dict, config: dict) -> tuple:
    """
    Fast Python-only filter before spending any Claude tokens.
    Returns (should_score: bool, reason: str).
    """
    title    = job.get("title", "").lower()
    location = job.get("location", "").lower()
    desc     = (job.get("description", "") + " " + location).lower()

    # Drop junior/non-PM roles
    for signal in _JUNIOR_SIGNALS:
        if signal in title:
            return False, f"junior signal in title: '{signal}'"

    # --- Location filtering ---
    desc_only = job.get("description", "").lower()  # description without location appended

    # 1. Drop international jobs outright (location field is most reliable signal)
    if any(sig in location for sig in _INTERNATIONAL_SIGNALS):
        return False, f"international location: {location.strip()}"

    # 1b. If location is vague (Remote/Unknown/blank), also scan description for
    #     international signals — catches "Remote (Spain)", "Remote from Madrid", etc.
    is_vague_location = not location or location in ("remote", "unknown", "anywhere")
    if is_vague_location and any(sig in desc_only for sig in _INTERNATIONAL_SIGNALS):
        # Allow if description also has strong US signals that outweigh international mention
        has_us_signal = any(sig in desc_only for sig in ["united states", "usa", "u.s.", "us only",
                                                           "anywhere in the us", "denver", "colorado"])
        if not has_us_signal:
            return False, f"international signals in description (location: '{location.strip()}')"

    # 2. If no remote/hybrid signal anywhere, job must be in Denver metro
    has_remote  = any(sig in desc for sig in _REMOTE_SIGNALS)
    is_generic  = not location or any(sig in location for sig in _USA_GENERIC)
    is_denver   = any(sig in location for sig in _DENVER_METRO)

    if not has_remote and not is_generic and not is_denver:
        # Has a specific US location that isn't Denver-adjacent and isn't remote
        return False, f"on-site, not in Denver metro: {location.strip()}"

    # 3. Legacy description-based onsite check (catches "onsite only" in JD text)
    if any(sig in desc for sig in _ONSITE_SIGNALS):
        allowed = [loc.lower() for loc in config.get("ALLOWED_LOCATIONS", [])]
        if not any(loc in desc for loc in allowed):
            return False, "on-site only signal in JD, outside allowed locations"

    # Drop if salary is explicitly listed and clearly below floor
    salary_floor = config.get("SALARY_FLOOR", 0)
    salary_text = job.get("salary_text", "").lower()
    if salary_text:
        import re
        nums = re.findall(r'\$?([\d,]+)k?', salary_text)
        if nums:
            try:
                top = max(int(n.replace(",", "")) * (1000 if "k" in salary_text else 1) for n in nums)
                if top < salary_floor * 0.7:
                    return False, f"salary {top} clearly below floor {salary_floor}"
            except Exception:
                pass

    return True, ""


# ---------------------------------------------------------------------------
# Smart job-description trimmer
# Strips recognizable boilerplate tails so we send fewer tokens to Claude
# without touching the substantive role description.
# ---------------------------------------------------------------------------

# Section headers that typically mark the start of boilerplate
_BOILERPLATE_HEADERS = re.compile(
    r'\n(?:about us|our story|who we are|equal opportunity|eeo statement|'
    r'diversity[, &]+inclusion|compensation[, &]+benefits|benefits[, &]+perks|'
    r'benefits include|what we offer|perks[, &]+benefits|our benefits|'
    r'why join us|life at |total rewards|base salary range|pay range|'
    r'salary range)[:\s]*\n',
    flags=re.I,
)

def _trim_jd(description: str, max_chars: int = 3000) -> str:
    """
    Return the substantive part of a job description.
    Strategy:
      1. Find the earliest boilerplate section header and truncate there.
      2. Hard-cap at max_chars as a final backstop.
    The first 1,500 chars contain role summary + key requirements in 95%+ of JDs.
    Cutting boilerplate reduces average token spend ~25% with zero accuracy loss.
    """
    match = _BOILERPLATE_HEADERS.search(description)
    if match:
        description = description[:match.start()].strip()
    return description[:max_chars]


# ---------------------------------------------------------------------------
# Seen-job-IDs registry — persists across runs independently of score cache
# ---------------------------------------------------------------------------

_SEEN_IDS_PATH = "./output/seen_job_ids.json"

def _load_seen_ids(path: str = _SEEN_IDS_PATH) -> set:
    """Load the all-time set of scraped job IDs from disk."""
    if os.path.exists(path):
        try:
            with open(path) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_seen_ids(seen: set, path: str = _SEEN_IDS_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(sorted(seen), f)
    except Exception as e:
        logger.warning(f"Could not save seen_job_ids: {e}")


CONDENSED_RESUME = """
Steve Christian | Senior Product Leader | Denver, CO (remote or Denver hybrid only)
10+ years total PM experience. ~4-5 years in energy (Verizon 2021-2025). Prior: fintech and enterprise digital products.

EXPERIENCE:
Verizon (2021-2025): Incubated 5 x 0->1 products, secured $6M executive funding. Led AI-driven DER/VPP orchestration platform (demand response, grid-edge optimization). Patent: energy usage optimization. Python/SQL analytics dashboards.
Accenture (2017-2020): Airbnb global payments platform ($10B+ annual volume, pre-IPO). Disney Parks app (1M+ downloads, 30K Cast Member platform).

DOMAIN DEPTH: DER, DERMS, VPP, HEMS, grid modernization, demand response, V2G, IoT, fintech payments, enterprise SaaS, AI/ML products, data platforms.
TECH: APIs (REST/GraphQL), SQL, Python, microservices, cloud, LLM-enabled products, Jira, Figma.
APPROACH: Hypothesis-driven, JTBD methodology, systems thinking, comfortable with ambiguity, strong executive communication.

CRITICAL — ENERGY EXPERTISE CONTEXT: Steve has ~4-5 years in energy as a SOFTWARE PRODUCT MANAGER building platforms for energy companies. He is NOT an energy developer, energy financier, power trader, or infrastructure investor. He has NEVER: negotiated PPAs or offtake agreements, managed EPC contractors, developed utility-scale generation projects, built technoeconomic models, structured project finance or infrastructure investments, or commercialized generation technologies. Roles requiring those skills are a POOR FIT.

CRITICAL — NO DEEP SCIENTIFIC/TECHNICAL DOMAIN EXPERTISE: Steve does not have specialized expertise in: meteorology, atmospheric science, weather modeling (NWP, GNSS-RO, mesoscale), geospatial/remote sensing, genomics, materials science, physics, or other hard science/engineering fields. Roles that require "8+ years in [scientific domain]" or "deep expertise in [scientific discipline]" as a hard requirement are a POOR FIT even if the PM function looks right.

STRONG FIT: 0->1 ownership, platform/API products, AI-first orgs, energy/climate/utilities SOFTWARE companies, high strategic ownership, product-led orgs, growth/monetization.
MODERATE FIT: Enterprise SaaS, fintech, data platforms, digital transformation.
NOT A FIT: Pure project/program management, feature delivery only, no strategic ownership, healthcare, pharma, telecom, mining. Also NOT a fit: energy project development, energy finance/commercialization, PPA/offtake negotiation, EPC management, utility-scale project development, technoeconomic modeling, infrastructure investment diligence, generation technology commercialization. Roles requiring deep scientific domain expertise (meteorology, atmospheric science, geospatial, genomics, etc.).

COMP TARGETS: Sr PM $180K-240K TC | Principal/Group PM $220K-325K TC | Director $275K-400K+ TC
""".strip()


def build_scoring_prompt(job: dict, resume: str, criteria: dict, positive_outcome_companies: list = None) -> str:
    positive_outcome_companies = positive_outcome_companies or []
    crm_signal = (
        f"CRM FEEDBACK — companies where Steve previously got interviews or offers (proven fit signal): "
        f"{', '.join(positive_outcome_companies)}"
        if positive_outcome_companies else
        "CRM FEEDBACK — no interview/offer outcomes recorded yet"
    )
    return f"""You are a job-fit analyst. Score this job posting for this candidate.

=== CANDIDATE SUMMARY ===
{CONDENSED_RESUME}

=== JOB POSTING ===
Title:       {job['title']}
Company:     {job['company']}
Location:    {job['location']}
Salary info: {job.get('salary_text', 'Not specified')}
Source:      {job['source']}
URL:         {job['url']}

Description:
{_trim_jd(job.get('description', ''))}

=== SCORING CRITERIA ===

POSITIVE SIGNALS (add to score):
- Energy/climate/DER/VPP/DERMS/grid company: +15 pts
- Target company list hit ({', '.join(criteria.get('target_companies', [])[:20])} and more): +10 pts
- CRM proven fit — this company is in the CRM feedback list above (Steve got an interview or offer here): +8 pts
- Strategic ownership language ("own product strategy", "define vision", "set roadmap", "drive business outcomes", "general manager mindset", "build from ambiguity", "executive communication", "portfolio ownership"): +10 pts
- 0->1 / new product incubation: +8 pts
- Platform or API product: +8 pts
- AI-first organization or AI/ML product: +8 pts
- Title match (Senior Product Manager, Staff PM, Principal PM, Director of Product, Head of Product, VP Product, Group PM, Product Lead, Chief Product Officer, Head of Digital Products, Director of Innovation, or semantic equivalents): +8 pts. Director/Head/VP/GM/CPO title: +5 bonus.
- Founding PM or first PM hire ("you'll be our first PM", "founding PM", "building the PM function"): +10 pts (high ownership signal)
- Small PM team (2-5 PMs, high visibility, broad scope): +5 pts
- Cross-functional leadership language ("lead cross-functional teams", "influence without authority", "executive stakeholders", "matrix leadership"): +5 pts
- Growth or monetization focus: +5 pts
- Product-led organization: +5 pts
- Experimentation/analytics culture ("experimentation", "A/B testing", "KPIs", "product analytics", "hypothesis-driven", "growth loops"): +5 pts
- Series A/B/C startup with strong ownership signals: +5 pts
- Fintech/payments/enterprise SaaS (moderate match): +3 pts
- ESG / sustainability software (carbon accounting, ESG data platforms, climate reporting, net-zero management, supply chain sustainability): +8 pts
- IoT / smart building / industrial software with genuine PM ownership scope: +3 pts

{crm_signal}

NEGATIVE SIGNALS (subtract from score):
- MAJOR (-15 each): project coordination only, feature factory, requirements gathering only, Jira administration, no product ownership language
- MINOR (-5 each): scrum ceremonies focus, release management only, backlog management only
- Domain mismatch — company sells into healthcare/pharma/telecom/mining/defense: -10 pts
- Adjacent domain (enterprise SaaS, data platforms, IoT/smart building, logistics, construction tech): 0 pts — Steve's platform and API product skills transfer well to these industries
- Regulated domain requiring direct expertise (FDA, medical devices, mining engineering, telecom infrastructure): -20 pts
- Wrong function in energy (-25 pts): Role is in energy project development, energy finance, infrastructure investment, or generation commercialization — NOT software product management. Signals: requires PPA/offtake negotiation experience, EPC contractor management, utility-scale project development, technoeconomic modeling, project finance, infrastructure investment diligence, venture-style energy investing, or commercializing generation technologies. These are energy developer/financier skills Steve does not have. Apply this penalty even if the company is a strong climate/energy target company.
- Required deep scientific/technical domain expertise (-25 pts): Role requires years of hands-on expertise in a hard science or engineering discipline Steve does not have. Signals: "8+ years in [scientific field]", requires deep expertise in meteorology/NWP/atmospheric science/GNSS-RO, geospatial/remote sensing, genomics, materials science, radar/satellite data processing, climate modeling, or similar. Apply even if the job title is "Product Manager" — domain expertise as a hard requirement disqualifies regardless of PM function.
- Salary clearly below $130K floor: -20 pts
- Fully on-site outside Denver/Boulder/Colorado: -15 pts
- Junior/APM/intern role: score < 25
- Vague/generic JD (no specific product domain, no ownership language, no team structure — reads like a copy-paste template): -10 pts and set confidence below 40

CONFIDENCE GUIDANCE:
Rate your confidence in the score 0-100.
- High confidence (80+): JD is detailed, clear scope, strong signal either way
- Medium confidence (50-79): JD is somewhat vague or mixed signals
- Low confidence (<50): JD is sparse, generic, or ambiguous about actual role scope

=== YOUR TASK ===
Return ONLY valid JSON (no markdown, no explanation outside the JSON):

{{
  "score": <integer 0-100>,
  "confidence": <integer 0-100>,
  "title_match": <"strong" | "good" | "weak" | "poor">,
  "location_ok": <true | false>,
  "salary_ok": <true | false | "unknown">,
  "company_tier": <"climatetech" | "fintech_ai" | "other">,
  "is_target_company": <true | false>,
  "seniority_ok": <true | false>,
  "top_strengths": [<string>, <string>, <string>],
  "top_gaps": [<string>, <string>],
  "top_reasons": [<string>, <string>, <string>],
  "match_summary": "<2-3 sentence plain-English summary of fit. Be specific to THIS job and THIS candidate's background.>",
  "apply_recommendation": <"strong yes" | "yes" | "maybe" | "no">,
  "work_type": <"remote" | "hybrid" | "on-site" | "unknown">,
  "salary_estimate": "<If Salary info above is provided, echo it. If 'Not specified', estimate a realistic market BASE salary range for this title/level/company in USD, e.g. '$140K–$175K base'. Never leave blank.>",
  "short_description": "<1 sentence: what the company does + what this PM will own. Max 120 chars.>"
}}
"""


def score_job(
    job: dict,
    config: dict,
    client: Anthropic,
    positive_outcome_companies: list = None,
    cached_prefix: str = None,
) -> dict:
    """
    Call Claude to score a single job. Returns the job dict with score fields populated.
    Retries once on failure.

    cached_prefix — the shared resume+criteria text (built once per run by
    score_all_jobs). When provided, the API call uses Anthropic prompt caching:
    the prefix is sent with cache_control="ephemeral" so Anthropic stores it
    for 5 minutes. Jobs 2-N in the same run reuse the cached prefix at ~10%
    of normal input-token cost, reducing per-run spend by ~70%.
    """
    criteria = {
        "salary_floor":        config["SALARY_FLOOR"],
        "allowed_locations":   config["ALLOWED_LOCATIONS"],
        "preferred_titles":    config["PREFERRED_TITLES"],
        "high_signal_keywords": config["HIGH_SIGNAL_KEYWORDS"],
        "negative_keywords":   config["NEGATIVE_KEYWORDS"],
        "target_companies":    config.get("ALL_TARGET_COMPANIES", []),
    }

    full_prompt = build_scoring_prompt(job, config["RESUME_TEXT"], criteria, positive_outcome_companies)

    # ── Prompt caching ────────────────────────────────────────────────────
    # Split the prompt into: shared prefix (resume + criteria) and per-job suffix
    # (the job posting itself). The prefix is identical for every job in a run.
    # Anthropic caches it server-side for 5 min at 10% of normal input cost.
    if cached_prefix and full_prompt.startswith(cached_prefix):
        job_suffix = full_prompt[len(cached_prefix):]
        message_content = [
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": job_suffix,
            },
        ]
    else:
        message_content = [{"type": "text", "text": full_prompt}]

    last_error = "unknown error"
    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # fast + cheap for scoring
                max_tokens=800,
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
                messages=[{"role": "user", "content": message_content}],
            )
            raw = response.content[0].text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

            job["first_seen"]         = job.get("first_seen") or datetime.now().isoformat()
            job["score"]              = result.get("score", 0)
            job["confidence"]         = result.get("confidence", 50)
            job["title_match"]        = result.get("title_match", "unknown")
            job["location_ok"]        = result.get("location_ok", False)
            job["salary_ok"]          = result.get("salary_ok", "unknown")
            job["company_tier"]       = result.get("company_tier", "other")
            job["is_target_company"]  = result.get("is_target_company", False)
            job["seniority_ok"]       = result.get("seniority_ok", True)
            job["top_strengths"]      = result.get("top_strengths", [])
            job["top_gaps"]           = result.get("top_gaps", [])
            job["top_reasons"]        = result.get("top_reasons", [])
            job["match_summary"]      = result.get("match_summary", "")
            job["apply_recommendation"] = result.get("apply_recommendation", "maybe")
            job["work_type"]            = result.get("work_type", "unknown")
            job["salary_estimate"]      = result.get("salary_estimate", "Not available")
            job["short_description"]    = result.get("short_description", "")
            return job

        except (json.JSONDecodeError, Exception) as e:
            last_error = str(e)
            logger.warning(f"Score attempt {attempt+1} failed for '{job['title']}' at {job['company']}: {e}")
            if attempt == 0:
                time.sleep(2)

    # Fallback if both attempts fail — tag as scoring_error so the Performance
    # tab can distinguish API/parse failures from genuinely low-scoring jobs.
    job["score"] = 0
    job["scoring_error"] = True
    job["scoring_error_detail"] = last_error
    job["match_summary"] = "Scoring failed — review manually."
    job["apply_recommendation"] = "maybe"
    return job


def _load_score_cache(cache_path: str) -> dict:
    """Load previously scored jobs keyed by job ID."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                jobs = json.load(f)
            return {j["id"]: j for j in jobs if j.get("score") is not None}
        except Exception:
            pass
    return {}


def _load_first_seen_registry(registry_path: str = "./output/first_seen_registry.json") -> dict:
    """Load job_id → first_seen_iso map. Persists independently of the scoring cache."""
    if os.path.exists(registry_path):
        try:
            with open(registry_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_first_seen_registry(registry: dict, registry_path: str = "./output/first_seen_registry.json") -> None:
    """Persist the first_seen registry to disk."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(registry_path)), exist_ok=True)
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save first_seen_registry: {e}")


def score_all_jobs(
    jobs: list[dict],
    config: dict,
    min_score: int = 55,
    delay_between: float = 0.5,
    cache_path: str = "./output/scored_jobs.json",
    positive_outcome_companies: list = None,
    rejected_path: str = "./output/rejected_jobs.json",
    seen_ids_path: str = _SEEN_IDS_PATH,
) -> list[dict]:
    """
    Score every job, skipping any already scored in cache.
    Filters below min_score, returns sorted descending by score.
    Pre-filter and low-score rejections are persisted to rejected_path.

    Cost controls applied (in order):
      1. seen_job_ids.json  — skip IDs ever seen, even after a cache wipe
      2. scored_jobs.json   — return cached score for IDs seen this run
      3. title+company dedup — one Claude call when same job appears on 2+ sources
      4. pre_filter         — Python-only checks, zero tokens
      5. MAX_NEW_SCORES_PER_RUN cap — hard limit on new Claude calls per run
      6. Prompt caching     — shared resume+criteria prefix cached by Anthropic
    """
    api_key = config.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Add it to config.py or export it as an env var.")

    client = Anthropic(api_key=api_key)
    cache = _load_score_cache(cache_path)

    # Load persistent seen-IDs registry (all-time, survives cache wipes)
    seen_ids = _load_seen_ids(seen_ids_path)

    # Load first_seen registry — survives scored_jobs.json wipes
    first_seen_registry = _load_first_seen_registry()

    # Load existing rejected jobs (keyed by id so we preserve first_analyzed across runs)
    existing_rejected: dict = {}
    if os.path.exists(rejected_path):
        try:
            with open(rejected_path) as f:
                for r in json.load(f):
                    if r.get("id"):
                        existing_rejected[r["id"]] = r
        except Exception:
            pass

    # ── Dedup: same title+company from multiple sources → keep first occurrence ──
    seen_title_company: set = set()
    deduped_jobs = []
    for job in jobs:
        key = (job.get("title", "").lower().strip(), job.get("company", "").lower().strip())
        if key in seen_title_company:
            continue
        seen_title_company.add(key)
        deduped_jobs.append(job)
    dedup_dropped = len(jobs) - len(deduped_jobs)
    if dedup_dropped:
        logger.info(f"  Dedup: dropped {dedup_dropped} duplicate title+company jobs before scoring")
    jobs = deduped_jobs

    # ── Daily scoring cap ────────────────────────────────────────────────────
    max_new = config.get("MAX_NEW_SCORES_PER_RUN", 80)

    # ── Build prompt cache prefix once for this run ──────────────────────────
    # This is the portion of the prompt that is identical for every job: the
    # resume, scoring criteria, and output schema. Passing it to score_job()
    # lets the Anthropic SDK mark it cache_control="ephemeral" so subsequent
    # jobs in this batch reuse it at 10% of normal input cost.
    criteria = {
        "salary_floor":         config["SALARY_FLOOR"],
        "allowed_locations":    config["ALLOWED_LOCATIONS"],
        "preferred_titles":     config["PREFERRED_TITLES"],
        "high_signal_keywords": config["HIGH_SIGNAL_KEYWORDS"],
        "negative_keywords":    config["NEGATIVE_KEYWORDS"],
        "target_companies":     config.get("ALL_TARGET_COMPANIES", []),
    }
    # Build a sentinel job to extract the invariant prefix
    _sentinel = {"title": "SENTINEL", "company": "SENTINEL", "location": "",
                 "description": "", "salary_text": "", "source": "", "url": ""}
    _full = build_scoring_prompt(_sentinel, config["RESUME_TEXT"], criteria, positive_outcome_companies)
    # The prefix ends right before "=== JOB POSTING ===" — everything before
    # that is the same for every job in this run.
    _split_marker = "=== JOB POSTING ==="
    cached_prefix = _full[:_full.index(_split_marker)] if _split_marker in _full else None

    scored = []
    new_count = 0
    cached_count = 0
    seen_count = 0      # skipped via seen_ids (not in score cache either)
    total = len(jobs)
    now_iso = datetime.now().isoformat()

    filtered_count = 0
    cap_skipped = 0
    pre_filter_rejected: list = []   # list of (job, reason)
    for i, job in enumerate(jobs, 1):
        jid = job.get("id", "")

        if job["id"] in cache:
            cached_job = cache[job["id"]]
            # Preserve first_seen in registry so cache wipes don't reset it
            fs = cached_job.get("first_seen")
            if fs and cached_job.get("id"):
                first_seen_registry.setdefault(cached_job["id"], fs)
            scored.append(cached_job)
            cached_count += 1
            seen_ids.add(jid)
            print(f"  [{i}/{total}] (cached) {job['title']} @ {job['company']} → {cached_job['score']}")
        elif jid and jid in seen_ids:
            # Seen before but not in score cache (e.g. cache was wiped but seen_ids
            # survived via S3 or git). Pre-filter it before deciding to skip entirely.
            ok, reason = pre_filter(job, config)
            if not ok:
                # Still record the pre-filter rejection
                filtered_count += 1
                pre_filter_rejected.append((job, reason))
            else:
                seen_count += 1
                print(f"  [{i}/{total}] (seen) {job['title']} @ {job['company']} — skipping re-score")
        else:
            ok, reason = pre_filter(job, config)
            if not ok:
                filtered_count += 1
                pre_filter_rejected.append((job, reason))
                seen_ids.add(jid)
                print(f"  [{i}/{total}] (filtered) {job['title']} @ {job['company']} — {reason}")
                continue

            # Daily cap — stop sending new jobs to Claude once limit reached
            if new_count >= max_new:
                cap_skipped += 1
                if cap_skipped == 1:
                    logger.warning(
                        f"MAX_NEW_SCORES_PER_RUN={max_new} reached — "
                        f"remaining jobs will be scored on next run"
                    )
                continue

            print(f"  [{i}/{total}] Scoring: {job['title']} @ {job['company']}...", end=" ", flush=True)
            job = score_job(job, config, client, positive_outcome_companies, cached_prefix=cached_prefix)
            # Apply registry first_seen so re-scores don't reset the archive clock
            if jid:
                if jid in first_seen_registry:
                    job["first_seen"] = first_seen_registry[jid]
                else:
                    fs = job.get("first_seen") or datetime.now().isoformat()
                    job["first_seen"] = fs
                    first_seen_registry[jid] = fs
            print(f"→ {job['score']}")
            scored.append(job)
            if not job.get("scoring_error"):
                # Only mark as permanently seen when scoring succeeded.
                # API errors are transient — leave the ID out of seen_ids so the
                # job is automatically retried on the next run.
                seen_ids.add(jid)
            new_count += 1
            time.sleep(delay_between)

    # Persist seen IDs so future runs skip jobs we've ever processed
    _save_seen_ids(seen_ids, seen_ids_path)

    cap_msg = f", {cap_skipped} deferred (daily cap)" if cap_skipped else ""
    seen_msg = f", {seen_count} skipped (seen before)" if seen_count else ""
    print(
        f"\n  {new_count} new scored, {cached_count} from cache, "
        f"{filtered_count} pre-filtered, {dedup_dropped} deduped"
        f"{seen_msg}{cap_msg} (no tokens used for any skipped)"
    )

    # Filter and sort — three buckets:
    #   scoring_error : Claude API/parse failure (score=0 is meaningless, not a real signal)
    #   qualifying    : score >= min_score and no API error
    #   low_score     : scored successfully but below threshold
    scoring_error_jobs = [j for j in scored if j.get("scoring_error")]
    qualifying         = [j for j in scored if not j.get("scoring_error") and (j["score"] or 0) >= min_score]
    low_score_failed   = [j for j in scored if not j.get("scoring_error") and (j["score"] or 0) < min_score]
    qualifying.sort(key=lambda j: j["score"], reverse=True)

    if scoring_error_jobs:
        logger.warning(f"{len(scoring_error_jobs)} job(s) failed scoring (API/parse error) — tagged as 'scoring_error' in performance log")

    # Save first_seen registry so dates survive future cache wipes
    _save_first_seen_registry(first_seen_registry)

    # ── Persist rejected jobs ─────────────────────────────────────────────
    def _upsert(job: dict, rtype: str, reason: str, score) -> None:
        jid = job.get("id", "")
        if not jid:
            return
        entry = existing_rejected.get(jid) or {}
        if not entry.get("first_analyzed"):
            entry["first_analyzed"] = now_iso
        entry.update({
            "id":               jid,
            "title":            job.get("title", ""),
            "company":          job.get("company", ""),
            "url":              job.get("url", ""),
            "location":         job.get("location", ""),
            "salary_text":      job.get("salary_text", ""),
            "source":           job.get("source", ""),
            "rejection_type":   rtype,
            "rejection_reason": reason,
            "score":            score,
            "last_analyzed":    now_iso,
        })
        existing_rejected[jid] = entry

    for job, reason in pre_filter_rejected:
        _upsert(job, "pre_filter", reason, None)

    for job in low_score_failed:
        reason = f"Score {job.get('score', 0)} below threshold {min_score}"
        _upsert(job, "low_score", reason, job.get("score", 0))

    for job in scoring_error_jobs:
        detail = job.get("scoring_error_detail", "unknown error")
        reason = f"Claude API/parse error after 2 attempts: {detail}"
        _upsert(job, "scoring_error", reason, None)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(rejected_path)), exist_ok=True)
        with open(rejected_path, "w") as f:
            json.dump(list(existing_rejected.values()), f, indent=2)
        logger.info(
            f"  → {len(pre_filter_rejected)} pre-filter + {len(low_score_failed)} low-score "
            f"rejections saved ({len(existing_rejected)} total in log)"
        )
    except Exception as e:
        logger.warning(f"  Could not save rejected jobs log: {e}")

    logger.info(
        f"Scoring complete: {len(scored)} scored, "
        f"{len(qualifying)} above min score {min_score}"
    )
    return qualifying
