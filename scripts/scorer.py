"""
scorer.py — Sends each job posting to Claude and gets back a 0-100 fit score,
a short match summary, and flags for salary/location eligibility.
"""

import os
import json
import time
import logging
from anthropic import Anthropic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pre-filter — eliminates obvious mismatches before spending any tokens
# ---------------------------------------------------------------------------

_JUNIOR_SIGNALS = [
    "junior", "associate product manager", "apm ", "entry level",
    "entry-level", "internship", "intern ", " intern,", "coordinator",
    "analyst i ", "analyst i,",
]

_ONSITE_SIGNALS = [
    "on-site only", "onsite only", "in-office only", "must be located in",
    "new york only", "san francisco only", "seattle only", "chicago only",
    "austin only", "no remote",
]

def pre_filter(job: dict, config: dict) -> tuple:
    """
    Fast Python-only filter before spending any Claude tokens.
    Returns (should_score: bool, reason: str).
    """
    title = job.get("title", "").lower()
    desc  = (job.get("description", "") + " " + job.get("location", "")).lower()

    # Drop junior/non-PM roles
    for signal in _JUNIOR_SIGNALS:
        if signal in title:
            return False, f"junior signal in title: '{signal}'"

    # Drop clearly on-site roles outside allowed locations
    allowed = [loc.lower() for loc in config.get("ALLOWED_LOCATIONS", [])]
    if any(sig in desc for sig in _ONSITE_SIGNALS):
        if not any(loc in desc for loc in allowed):
            return False, "on-site only, outside allowed locations"

    # Drop if salary is explicitly listed and clearly below floor
    salary_floor = config.get("SALARY_FLOOR", 0)
    salary_text = job.get("salary_text", "").lower()
    if salary_text:
        import re
        nums = re.findall(r'\$?([\d,]+)k?', salary_text)
        if nums:
            try:
                top = max(int(n.replace(",", "")) * (1000 if "k" in salary_text else 1) for n in nums)
                if top < salary_floor * 0.7:   # only drop if clearly below (70% of floor)
                    return False, f"salary {top} clearly below floor {salary_floor}"
            except Exception:
                pass

    return True, ""


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
{job['description'][:3000]}

=== SCORING CRITERIA ===

POSITIVE SIGNALS (add to score):
- Energy/climate/DER/VPP/DERMS/grid company: +15 pts
- Target company list hit ({', '.join(criteria.get('target_companies', [])[:20])} and more): +10 pts
- CRM proven fit — this company is in the CRM feedback list above (Steve got an interview or offer here): +8 pts
- Strategic ownership language ("own product strategy", "define vision", "set roadmap", "drive business outcomes", "general manager mindset", "build from ambiguity", "executive communication", "portfolio ownership"): +10 pts
- 0->1 / new product incubation: +8 pts
- Platform or API product: +8 pts
- AI-first organization or AI/ML product: +8 pts
- Title match (Senior Product Manager, Staff PM, Principal PM, Director of Product, Head of Product, VP Product, Group PM, Product Lead, or semantic equivalents): +8 pts. Director/Head/VP/GM title: +5 bonus.
- Founding PM or first PM hire ("you'll be our first PM", "founding PM", "building the PM function"): +10 pts (high ownership signal)
- Small PM team (2-5 PMs, high visibility, broad scope): +5 pts
- Cross-functional leadership language ("lead cross-functional teams", "influence without authority", "executive stakeholders", "matrix leadership"): +5 pts
- Growth or monetization focus: +5 pts
- Product-led organization: +5 pts
- Experimentation/analytics culture ("experimentation", "A/B testing", "KPIs", "product analytics", "hypothesis-driven", "growth loops"): +5 pts
- Series A/B/C startup with strong ownership signals: +5 pts
- Fintech/payments/enterprise SaaS (moderate match): +3 pts

{crm_signal}

NEGATIVE SIGNALS (subtract from score):
- MAJOR (-15 each): project coordination only, feature factory, requirements gathering only, Jira administration, no product ownership language
- MINOR (-5 each): scrum ceremonies focus, release management only, backlog management only
- Domain mismatch — company sells into healthcare/pharma/telecom/mining but role is generic PM: -10 pts
- Regulated domain requiring direct expertise (FDA, medical devices, mining engineering, telecom infrastructure): -20 pts
- Wrong function in energy (-25 pts): Role is in energy project development, energy finance, infrastructure investment, or generation commercialization — NOT software product management. Signals: requires PPA/offtake negotiation experience, EPC contractor management, utility-scale project development, technoeconomic modeling, project finance, infrastructure investment diligence, venture-style energy investing, or commercializing generation technologies. These are energy developer/financier skills Steve does not have. Apply this penalty even if the company is a strong climate/energy target company.
- Required deep scientific/technical domain expertise (-25 pts): Role requires years of hands-on expertise in a hard science or engineering discipline Steve does not have. Signals: "8+ years in [scientific field]", requires deep expertise in meteorology/NWP/atmospheric science/GNSS-RO, geospatial/remote sensing, genomics, materials science, radar/satellite data processing, climate modeling, or similar. Apply even if the job title is "Product Manager" — domain expertise as a hard requirement disqualifies regardless of PM function.
- Salary clearly below $130K floor: -20 pts
- Fully on-site outside Denver/Boulder/Colorado: -15 pts
- Junior/APM/intern role: score < 25
- Large PM organization (50+ PMs, highly matrixed, limited strategic scope per PM): -5 pts
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
  "salary_estimate": "<If salary listed, echo it. If not, estimate a realistic market range for this title/company in USD, e.g. '$140K–$175K'. Never leave blank.>",
  "short_description": "<1 sentence: what the company does + what this PM will own. Max 120 chars.>"
}}
"""


def score_job(job: dict, config: dict, client: Anthropic, positive_outcome_companies: list = None) -> dict:
    """
    Call Claude to score a single job. Returns the job dict with score fields populated.
    Retries once on failure.
    """
    criteria = {
        "salary_floor":        config["SALARY_FLOOR"],
        "allowed_locations":   config["ALLOWED_LOCATIONS"],
        "preferred_titles":    config["PREFERRED_TITLES"],
        "high_signal_keywords": config["HIGH_SIGNAL_KEYWORDS"],
        "negative_keywords":   config["NEGATIVE_KEYWORDS"],
        "target_companies":    config.get("ALL_TARGET_COMPANIES", []),
    }

    prompt = build_scoring_prompt(job, config["RESUME_TEXT"], criteria, positive_outcome_companies)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # fast + cheap for scoring
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

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
            logger.warning(f"Score attempt {attempt+1} failed for '{job['title']}' at {job['company']}: {e}")
            if attempt == 0:
                time.sleep(2)

    # Fallback if both attempts fail
    job["score"] = 0
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


def score_all_jobs(
    jobs: list[dict],
    config: dict,
    min_score: int = 55,
    delay_between: float = 0.5,
    cache_path: str = "./output/scored_jobs.json",
    positive_outcome_companies: list = None,
) -> list[dict]:
    """
    Score every job, skipping any already scored in cache.
    Filters below min_score, returns sorted descending by score.
    """
    api_key = config.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Add it to config.py or export it as an env var.")

    client = Anthropic(api_key=api_key)
    cache = _load_score_cache(cache_path)

    scored = []
    new_count = 0
    cached_count = 0
    total = len(jobs)

    filtered_count = 0
    for i, job in enumerate(jobs, 1):
        if job["id"] in cache:
            cached_job = cache[job["id"]]
            scored.append(cached_job)
            cached_count += 1
            print(f"  [{i}/{total}] (cached) {job['title']} @ {job['company']} → {cached_job['score']}")
        else:
            ok, reason = pre_filter(job, config)
            if not ok:
                filtered_count += 1
                print(f"  [{i}/{total}] (filtered) {job['title']} @ {job['company']} — {reason}")
                continue
            print(f"  [{i}/{total}] Scoring: {job['title']} @ {job['company']}...", end=" ", flush=True)
            job = score_job(job, config, client, positive_outcome_companies)
            print(f"→ {job['score']}")
            scored.append(job)
            new_count += 1
            time.sleep(delay_between)

    print(f"\n  {new_count} new scored, {cached_count} from cache, {filtered_count} pre-filtered (no tokens used)")

    # Filter and sort
    qualifying = [j for j in scored if (j["score"] or 0) >= min_score]
    qualifying.sort(key=lambda j: j["score"], reverse=True)

    logger.info(
        f"Scoring complete: {len(scored)} scored, "
        f"{len(qualifying)} above min score {min_score}"
    )
    return qualifying
