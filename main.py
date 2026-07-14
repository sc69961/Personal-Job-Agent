#!/usr/bin/env python3
"""
main.py — Job Agent orchestrator
Run daily (manually or via cron) to scrape, score, and deliver job matches.

Usage:
  python main.py                  # full run
  python main.py --dry-run        # scrape + score only, skip Sheet/email
  python main.py --score-only     # re-score from last scrape (no network fetch)
  python main.py --email-only     # resend digest from last scored results
  python main.py --dashboard      # open GUI from cached results instantly (no scraping)
  python main.py --headless       # full run, no browser open (used in cloud/CI)
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("./output/job_agent.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# ── Main ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    from config.config import (
        ANTHROPIC_API_KEY, GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_ID,
        GMAIL_SENDER, GMAIL_APP_PASSWORD, DIGEST_EMAIL_TO, RESUME_TEXT, SALARY_FLOOR,
        ALLOWED_LOCATIONS, PREFERRED_TITLES, HIGH_SIGNAL_KEYWORDS,
        NEGATIVE_KEYWORDS, MAX_JOBS_PER_SOURCE, MIN_SCORE_TO_INCLUDE,
        TOP_N_FOR_EMAIL, YOUR_NAME, YOUR_EMAIL, YOUR_PHONE, YOUR_LINKEDIN,
        YOUR_LOCATION,
    )
    from config.target_companies import ALL_TARGET_COMPANIES

    return {
        # Env vars take priority over config.py (so GitHub Secrets override local values)
        "ANTHROPIC_API_KEY":       os.environ.get("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY,
        "GOOGLE_CREDENTIALS_PATH": GOOGLE_CREDENTIALS_PATH,
        "GOOGLE_SHEET_ID":         GOOGLE_SHEET_ID,
        "GMAIL_SENDER":            GMAIL_SENDER,
        "GMAIL_APP_PASSWORD":      os.environ.get("GMAIL_APP_PASSWORD") or GMAIL_APP_PASSWORD,
        "DIGEST_EMAIL_TO":         DIGEST_EMAIL_TO,
        "RESUME_TEXT":             RESUME_TEXT,
        "SALARY_FLOOR":            SALARY_FLOOR,
        "ALLOWED_LOCATIONS":       ALLOWED_LOCATIONS,
        "PREFERRED_TITLES":        PREFERRED_TITLES,
        "HIGH_SIGNAL_KEYWORDS":    HIGH_SIGNAL_KEYWORDS,
        "NEGATIVE_KEYWORDS":       NEGATIVE_KEYWORDS,
        "MAX_JOBS_PER_SOURCE":     MAX_JOBS_PER_SOURCE,
        "MIN_SCORE_TO_INCLUDE":    MIN_SCORE_TO_INCLUDE,
        "TOP_N_FOR_EMAIL":         TOP_N_FOR_EMAIL,
        "ALL_TARGET_COMPANIES":    ALL_TARGET_COMPANIES,
        "YOUR_NAME":               YOUR_NAME,
        "YOUR_EMAIL":              YOUR_EMAIL,
        "YOUR_PHONE":              YOUR_PHONE,
        "YOUR_LINKEDIN":           YOUR_LINKEDIN,
        "YOUR_LOCATION":           YOUR_LOCATION,
    }


def run(args):
    Path("./output").mkdir(exist_ok=True)
    Path("./public").mkdir(exist_ok=True)

    logger.info("=" * 55)
    logger.info(f"Job Agent run started — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"Mode: {'headless/cloud' if args.headless else 'local'}")
    logger.info("=" * 55)

    config = load_config()

    # ── CRM-ONLY MODE ────────────────────────────────────────────────────
    if args.crm_only:
        logger.info("Mode: CRM sync only (no scraping or scoring)")
        scored_path = "./output/scored_jobs.json"
        scored_jobs = []
        if os.path.exists(scored_path):
            with open(scored_path) as f:
                scored_jobs = json.load(f)
            logger.info(f"  Loaded {len(scored_jobs)} cached scored jobs for dashboard")
        try:
            from scripts.gmail_crm import sync_gmail_crm
            crm = sync_gmail_crm(config)
            from collections import Counter
            counts = Counter(a.get("status", "unknown") for a in crm.get("applications", []))
            for status, n in sorted(counts.items()):
                logger.info(f"    {status}: {n}")
        except Exception as e:
            logger.warning(f"CRM sync failed: {e}")
            crm = {}
        from scripts.dashboard import generate_dashboard
        out = "./public/index.html" if args.headless else "./output/dashboard.html"
        generate_dashboard(scored_jobs, crm=crm, output_path=out)
        logger.info(f"  Dashboard written → {out}")
        if not args.headless:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(out)}")
        return

    # ── DASHBOARD-ONLY MODE ───────────────────────────────────────────────
    if args.dashboard:
        scored_path = "./output/scored_jobs.json"
        crm_path    = "./output/crm.json"
        if not os.path.exists(scored_path):
            logger.error("No cached results found. Run a full dry-run first.")
            return
        with open(scored_path) as f:
            scored_jobs = json.load(f)
        crm = {}
        if os.path.exists(crm_path):
            with open(crm_path) as f:
                crm = json.load(f)
        logger.info(f"Opening dashboard from cache ({len(scored_jobs)} jobs, {len(crm.get('applications',[]))} CRM entries)")
        from scripts.dashboard import open_dashboard
        open_dashboard(scored_jobs, crm=crm)
        return

    # ── 1. SCRAPE ─────────────────────────────────────────────────────────
    raw_jobs_path = "./output/raw_jobs.json"

    if args.score_only or args.email_only:
        logger.info("Skipping scrape — loading last raw jobs")
        with open(raw_jobs_path) as f:
            raw_jobs = json.load(f)
    else:
        logger.info("Step 1/5 — Scraping job boards...")
        from scripts.scraper import scrape_all
        raw_jobs = scrape_all(max_per_source=config["MAX_JOBS_PER_SOURCE"])

        # Deduplicate by URL — same job posted on multiple boards
        seen_urls = set()
        deduped = []
        for job in raw_jobs:
            url = job.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            deduped.append(job)
        if len(deduped) < len(raw_jobs):
            logger.info(f"  → Removed {len(raw_jobs) - len(deduped)} duplicate URLs")
        raw_jobs = deduped

        with open(raw_jobs_path, "w") as f:
            json.dump(raw_jobs, f, indent=2)
        logger.info(f"  → {len(raw_jobs)} raw jobs saved")

        # ── MARKET STATS SNAPSHOT ──────────────────────────────────────────
        _append_market_snapshot(raw_jobs)

    # ── 2. SCORE ──────────────────────────────────────────────────────────
    scored_path = "./output/scored_jobs.json"

    # Load CRM outcomes to use as positive signals in scoring
    positive_outcome_companies = []
    crm_path = "./output/crm.json"
    if os.path.exists(crm_path):
        try:
            with open(crm_path) as f:
                crm_data = json.load(f)
            positive_outcome_companies = [
                app["company"] for app in crm_data.get("applications", [])
                if app.get("status") in ("interview_requested", "offer")
                and app.get("company")
            ]
            if positive_outcome_companies:
                logger.info(f"  → CRM: {len(positive_outcome_companies)} companies with positive outcomes loaded for scoring")
        except Exception:
            pass

    if args.email_only:
        logger.info("Skipping scoring — loading last scored jobs")
        with open(scored_path) as f:
            scored_jobs = json.load(f)
        known_job_ids = set()  # email_only always sends
    else:
        # Snapshot existing qualifying IDs — used to detect truly new jobs this run
        known_job_ids = set()
        if os.path.exists(scored_path):
            try:
                with open(scored_path) as f:
                    known_job_ids = {j["id"] for j in json.load(f)}
            except Exception:
                pass

        logger.info(f"Step 2/5 — Scoring {len(raw_jobs)} jobs with Claude...")
        from scripts.scorer import score_all_jobs
        scored_jobs = score_all_jobs(
            raw_jobs,
            config,
            min_score=config["MIN_SCORE_TO_INCLUDE"],
            cache_path=scored_path,
            positive_outcome_companies=positive_outcome_companies,
        )
        with open(scored_path, "w") as f:
            json.dump(scored_jobs, f, indent=2)
        logger.info(f"  → {len(scored_jobs)} qualifying jobs (score ≥ {config['MIN_SCORE_TO_INCLUDE']})")

    if not scored_jobs:
        logger.warning("No qualifying jobs found. Consider lowering MIN_SCORE_TO_INCLUDE.")
        return

    # Determine which jobs are new this run (not seen in previous scored cache)
    new_jobs = [j for j in scored_jobs if j["id"] not in known_job_ids]
    logger.info(f"  → {len(new_jobs)} new qualifying jobs this run")

    # ── 3. SYNC GMAIL CRM ────────────────────────────────────────────────
    logger.info("Step 3/5 — Syncing Gmail CRM...")
    crm = {}
    try:
        from scripts.gmail_crm import sync_gmail_crm
        crm = sync_gmail_crm(config)
        logger.info(f"  → {len(crm.get('applications', []))} applications tracked")
    except Exception as e:
        logger.warning(f"  Gmail CRM sync skipped: {e}")

    if args.dry_run:
        logger.info("Dry run — skipping Sheet write and email send")
        _print_summary(scored_jobs, config)
        if not args.headless:
            from scripts.dashboard import open_dashboard
            open_dashboard(scored_jobs, crm=crm)
        return

    # ── 4. GENERATE DASHBOARD HTML ────────────────────────────────────────
    logger.info("Step 4/5 — Generating dashboard...")
    try:
        from scripts.dashboard import generate_dashboard
        # Write to both output/ (local) and public/ (Firebase Hosting)
        generate_dashboard(scored_jobs, crm=crm, output_path="./output/dashboard.html")
        import shutil
        shutil.copy("./output/dashboard.html", "./public/index.html")
        logger.info("  → Dashboard written to public/index.html")
    except Exception as e:
        logger.warning(f"  Dashboard generation failed: {e}")

    # ── 5. SEND EMAIL DIGEST ──────────────────────────────────────────────
    logger.info("Step 5/5 — Sending Gmail digest...")

    # Daily email cap — one digest per calendar day regardless of run frequency
    email_flag_path = "./output/last_email_sent.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    already_sent_today = False
    if os.path.exists(email_flag_path) and not args.email_only:
        with open(email_flag_path) as f:
            already_sent_today = f.read().strip() == today

    if already_sent_today:
        logger.info("  → Digest already sent today — skipping to avoid duplicate emails")
    elif not new_jobs and not args.email_only:
        logger.info("  → No new jobs this run — skipping email to avoid noise")
    else:
        try:
            from scripts.gmail_sender import send_digest
            ok = send_digest(
                scored_jobs,
                config=config,
                total_scraped=len(raw_jobs),
                credentials_path=config["GOOGLE_CREDENTIALS_PATH"],
                crm=crm,
            )
            if ok:
                with open(email_flag_path, "w") as f:
                    f.write(today)
            logger.info(f"  → Email {'sent ✓' if ok else 'failed ✗'} ({len(new_jobs)} new jobs)")
        except Exception as e:
            logger.warning(f"  Email send failed: {e}")

    _print_summary(scored_jobs, config)

    if not args.headless:
        from scripts.dashboard import open_dashboard
        open_dashboard(scored_jobs, crm=crm)

    logger.info("Job Agent run complete.")


def _append_market_snapshot(raw_jobs: list[dict]):
    """
    After each scrape, append a market intelligence snapshot to output/market_stats.json.
    Tracks hiring activity per company over time so trends can be visualized.
    """
    stats_path = "./output/market_stats.json"
    today = datetime.now().strftime("%Y-%m-%d")

    # Per-company counts
    company_data = {}
    for job in raw_jobs:
        co = job.get("company", "Unknown")
        if co not in company_data:
            company_data[co] = {
                "company": co,
                "tier": job.get("company_tier", "other"),
                "total_roles": 0,
                "pm_roles": 0,
                "titles": [],
                "locations": [],
                "work_types": [],
                "sources": [],
            }
        d = company_data[co]
        d["total_roles"] += 1
        title = job.get("title", "")
        pm_terms = ["product manager", "product lead", "product owner", "head of product",
                    "director of product", "vp product", "staff pm", "principal pm", "group pm"]
        if any(t in title.lower() for t in pm_terms):
            d["pm_roles"] += 1
            d["titles"].append(title)
        d["locations"].append(job.get("location", ""))
        d["work_types"].append(job.get("work_type", "unknown"))
        d["sources"].append(job.get("source", ""))

    # Aggregate breakdowns
    all_pm = [j for j in raw_jobs if any(
        t in j.get("title","").lower()
        for t in ["product manager","product lead","product owner","head of product",
                  "director of product","vp product","staff pm","principal pm","group pm"]
    )]

    def seniority(title: str) -> str:
        t = title.lower()
        if any(x in t for x in ["vp ", "vice president"]): return "VP"
        if any(x in t for x in ["director", "head of"]): return "Director/Head"
        if any(x in t for x in ["principal", "staff", "group pm"]): return "Principal/Staff"
        if any(x in t for x in ["senior", "sr.","sr "]): return "Senior"
        if any(x in t for x in ["lead"]): return "Lead"
        return "Mid-level"

    seniority_counts = {}
    for j in all_pm:
        s = seniority(j.get("title",""))
        seniority_counts[s] = seniority_counts.get(s, 0) + 1

    work_type_counts = {}
    for j in all_pm:
        wt = j.get("work_type", "unknown")
        work_type_counts[wt] = work_type_counts.get(wt, 0) + 1

    source_counts = {}
    for j in raw_jobs:
        src = j.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    snapshot = {
        "date": today,
        "total_jobs_scraped": len(raw_jobs),
        "total_pm_roles": len(all_pm),
        "companies_hiring": len(company_data),
        "companies_with_pm_roles": sum(1 for d in company_data.values() if d["pm_roles"] > 0),
        "seniority_breakdown": seniority_counts,
        "work_type_breakdown": work_type_counts,
        "source_breakdown": source_counts,
        "companies": sorted(company_data.values(), key=lambda x: x["pm_roles"], reverse=True),
    }

    # Load existing history, append today's snapshot (replace if same date)
    history = []
    if os.path.exists(stats_path):
        try:
            with open(stats_path) as f:
                history = json.load(f)
        except Exception:
            history = []

    history = [s for s in history if s.get("date") != today]
    history.append(snapshot)
    history.sort(key=lambda s: s["date"])

    with open(stats_path, "w") as f:
        json.dump(history, f, indent=2)
    logger.info(f"  → Market snapshot saved ({len(all_pm)} PM roles across {snapshot['companies_with_pm_roles']} companies)")


def _print_summary(jobs: list[dict], config: dict):
    top_n = config.get("TOP_N_FOR_EMAIL", 10)
    print(f"\n{'='*55}")
    print(f"TOP {min(top_n, len(jobs))} JOBS")
    print(f"{'='*55}")
    for i, j in enumerate(jobs[:top_n], 1):
        rec  = j.get('apply_recommendation', '?')
        tier = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(j.get("company_tier", ""), "")
        work = {"remote": "🌐 Remote", "hybrid": "🔀 Hybrid", "on-site": "🏢 On-site"}.get(j.get("work_type", ""), "❓ Unknown")
        salary = j.get("salary_estimate", "N/A")
        short_desc = j.get("short_description", "")
        print(f"  {i:>2}. [{j['score']:>3}] {tier} {j['title']:<42} @ {j['company']}")
        print(f"       {rec.upper()}  |  {work}  |  {salary}")
        if short_desc:
            print(f"       {short_desc}")
        print(f"       {j.get('match_summary', '')[:100]}")
        print(f"       🔗 {j.get('url', 'No URL')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Agent — daily job scraper and scorer")
    parser.add_argument("--dry-run",    action="store_true", help="Scrape+score only, no Sheet/email")
    parser.add_argument("--score-only", action="store_true", help="Re-score last scrape, skip fetch")
    parser.add_argument("--email-only", action="store_true", help="Resend digest from last results")
    parser.add_argument("--dashboard",  action="store_true", help="Open GUI from cached results, no scraping")
    parser.add_argument("--headless",   action="store_true", help="Cloud/CI mode: no browser, write HTML to public/")
    parser.add_argument("--crm-only",   action="store_true", help="Sync Gmail CRM only — no scraping or scoring")
    args = parser.parse_args()
    run(args)
