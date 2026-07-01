#!/usr/bin/env python3
"""
sync_crm.py — Run ONLY the Gmail CRM sync, then open the dashboard from cache.

Usage:
    python sync_crm.py

Does NOT scrape jobs or call Claude for scoring — just re-reads your Gmail,
updates crm.json, and refreshes the dashboard with the existing scored_jobs.json.
Costs only a few Haiku tokens (per email thread analyzed).
"""

import json
import logging
import os
import sys
import webbrowser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from config.config import (
    ANTHROPIC_API_KEY,
    GOOGLE_CREDENTIALS_PATH,
)
from scripts.gmail_crm import sync_gmail_crm
from scripts.dashboard import generate_dashboard

def main():
    config = {
        "ANTHROPIC_API_KEY":      ANTHROPIC_API_KEY,
        "GOOGLE_CREDENTIALS_PATH": GOOGLE_CREDENTIALS_PATH,
    }

    # --- Sync CRM ---
    logger.info("Syncing Gmail CRM...")
    crm = sync_gmail_crm(config)
    apps = crm.get("applications", [])
    logger.info(f"  → {len(apps)} applications tracked")

    # Print a quick summary
    from collections import Counter
    counts = Counter(a.get("status", "unknown") for a in apps)
    for status, n in sorted(counts.items()):
        logger.info(f"     {status}: {n}")

    # --- Load existing scored jobs (no re-scrape) ---
    scored_path = "./output/scored_jobs.json"
    scored_jobs = []
    if os.path.exists(scored_path):
        with open(scored_path) as f:
            scored_jobs = json.load(f)
        logger.info(f"  Loaded {len(scored_jobs)} scored jobs from cache")
    else:
        logger.info("  No scored_jobs.json found — dashboard will show CRM only")

    # --- Rebuild dashboard ---
    dashboard_path = "./output/dashboard.html"
    generate_dashboard(scored_jobs, crm=crm, output_path=dashboard_path)
    logger.info(f"  Dashboard written to {dashboard_path}")

    webbrowser.open(f"file://{os.path.abspath(dashboard_path)}")
    logger.info("Done.")

if __name__ == "__main__":
    main()
