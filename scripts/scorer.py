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
Steve Christian | Senior PM | Denver, CO (remote or Denver hybrid only)
10+ years: DER orchestration, VPPs, demand response, grid-edge optimization, fintech payments platforms.
Verizon (2020-2025): Incubated 5 x 0->1 products, secured $6M funding. Led AI-driven DER platform (VPP/demand response). Patent: energy usage optimization. Python/SQL analytics.
Accenture (2017-2020): Airbnb payments platform ($10B+ annual volume, pre-IPO). Disney Parks PM (1M+ app downloads, 30K Cast Member workforce platform).
Skills: DER/DERMS/VPP/V2G, APIs (REST/GraphQL), SQL, Python, AI/ML, Agile/SAFe.
Strengths: Platform/API products, 0->1 incubation, growth/monetization. Not interested in ops/process PM, healthcare, pharma, telecom, or mining roles.
MBA + dual BS (Info Systems, Psychology) — Appalachian State.
""".strip()


def build_scoring_prompt(job: dict, resume: str, criteria: dict) -> str:
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
- Salary floor: ${criteria['salary_floor']:,}/yr. If salary is listed and clearly below floor, heavily penalize.
- Preferred locations: {', '.join(criteria['allowed_locations'])}. Remote roles score well. Fully on-site outside Denver/Boulder = penalize.
- Company tier bonus: Climatetech/energy/DER/VPP/DERMS companies get +15 pts. Fintech/AI/startups get +5 pts.
- Target company list: {', '.join(criteria.get('target_companies', [])[:30])} (and more). Being on this list gives +10 pts.
- Preferred titles: {', '.join(criteria['preferred_titles'])}. Exact or close title match +5 pts.
- Seniority: Must be senior-level (Sr PM, Group PM, Staff PM, Director, Head, VP). Junior roles score < 30.
- High-signal keywords in JD: {', '.join(criteria['high_signal_keywords'])}. Each relevant keyword match +2 pts (cap +10).
- Startup/smaller company preference: +5 pts if startup signals (Series A/B, small team, early stage).
- Candidate strengths to match: DER/VPP platform experience, 0→1 product, fintech payments ($10B volume), cross-functional leadership, Python/SQL analytics, energy patent.
- Penalty keywords: {', '.join(criteria['negative_keywords'])}. Each match -10 pts.
- Role type bonus: Platform/API products +8 pts. 0->1 / new product incubation +8 pts. Growth/monetization +5 pts. Ops-only/process PM roles -10 pts.
- Industry penalty: Healthcare, medtech, pharma, telecom, mining = automatic -20 pts (candidate explicitly excludes these).
- Company stage: No preference — score on role quality, not stage.

=== YOUR TASK ===
Return ONLY valid JSON (no markdown, no explanation outside the JSON):

{{
  "score": <integer 0-100>,
  "title_match": <"strong" | "good" | "weak" | "poor">,
  "location_ok": <true | false>,
  "salary_ok": <true | false | "unknown">,
  "company_tier": <"climatetech" | "fintech_ai" | "other">,
  "is_target_company": <true | false>,
  "seniority_ok": <true | false>,
  "top_strengths": [<string>, <string>, <string>],
  "top_gaps": [<string>, <string>],
  "match_summary": "<2-3 sentence plain-English summary of fit. Be specific to THIS job and THIS candidate's background.>",
  "apply_recommendation": <"strong yes" | "yes" | "maybe" | "no">,
  "work_type": <"remote" | "hybrid" | "on-site" | "unknown">,
  "salary_estimate": "<If salary listed, echo it. If not, estimate a realistic market range for this title/company in USD, e.g. '$140K–$175K'. Never leave blank.>",
  "short_description": "<1 sentence: what the company does + what this PM will own. Max 120 chars.>"
}}
"""


def score_job(job: dict, config: dict, client: Anthropic) -> dict:
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

    prompt = build_scoring_prompt(job, config["RESUME_TEXT"], criteria)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # fast + cheap for scoring
                max_tokens=600,
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
            job["title_match"]        = result.get("title_match", "unknown")
            job["location_ok"]        = result.get("location_ok", False)
            job["salary_ok"]          = result.get("salary_ok", "unknown")
            job["company_tier"]       = result.get("company_tier", "other")
            job["is_target_company"]  = result.get("is_target_company", False)
            job["seniority_ok"]       = result.get("seniority_ok", True)
            job["top_strengths"]      = result.get("top_strengths", [])
            job["top_gaps"]           = result.get("top_gaps", [])
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
            job = score_job(job, config, client)
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
