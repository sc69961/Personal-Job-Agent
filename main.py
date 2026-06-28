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
        GMAIL_SENDER, DIGEST_EMAIL_TO, RESUME_TEXT, SALARY_FLOOR,
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
        with open(raw_jobs_path, "w") as f:
            json.dump(raw_jobs, f, indent=2)
        logger.info(f"  → {len(raw_jobs)} raw jobs saved")

    # ── 2. SCORE ──────────────────────────────────────────────────────────
    scored_path = "./output/scored_jobs.json"

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
    if not new_jobs and not args.email_only:
        logger.info("  → No new jobs this run — skipping email to avoid noise")
    else:
        try:
            from scripts.gmail_sender import send_digest
            ok = send_digest(
                scored_jobs,
                config=config,
                total_scraped=len(raw_jobs),
                credentials_path=config["GOOGLE_CREDENTIALS_PATH"],
            )
            logger.info(f"  → Email {'sent ✓' if ok else 'failed ✗'} ({len(new_jobs)} new jobs)")
        except Exception as e:
            logger.warning(f"  Email send failed: {e}")

    _print_summary(scored_jobs, config)

    if not args.headless:
        from scripts.dashboard import open_dashboard
        open_dashboard(scored_jobs, crm=crm)

    logger.info("Job Agent run complete.")


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
    args = parser.parse_args()
    run(args)
