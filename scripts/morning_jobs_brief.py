#!/usr/bin/env python3
"""
morning_jobs_brief.py — Format a morning review of new high-scored job opportunities.

Reads scored_jobs.json (from S3 or local), filters for:
  - Score >= MIN_SCORE (default 65)
  - first_seen within LOOKBACK_DAYS (default 7)
  - Not yet applied / in an active CRM status

Outputs a formatted brief suitable for a Claude chat review session.

Run from ~/Downloads/job-agent:
  python3 scripts/morning_jobs_brief.py
  python3 scripts/morning_jobs_brief.py --min-score 50 --days 3
"""

import json
import sys
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_MIN_SCORE  = 65
DEFAULT_LOOKBACK   = 7   # days
QUICK_APPLY_MIN    = 40  # show separately as "quick apply" queue
QUICK_APPLY_MAX    = 64

SCORED_JOBS_PATH = Path(__file__).parent.parent / "output" / "scored_jobs.json"
CRM_PATH         = Path(__file__).parent.parent / "output" / "crm.json"

ACTIVE_STATUSES = {"applied", "interview_requested", "response_received", "offer"}


def _load_from_s3() -> list | None:
    """Try to load scored_jobs.json from S3. Returns None if not available."""
    try:
        from config.config import (
            AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
            S3_BUCKET_NAME as BUCKET, AWS_REGION,
        )
        import boto3
        s3 = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
        obj = s3.get_object(Bucket=BUCKET, Key="scored_jobs.json")
        return json.loads(obj["Body"].read())
    except Exception:
        return None


def load_jobs() -> list:
    """Load scored jobs from S3 (preferred) or local file."""
    jobs = _load_from_s3()
    if jobs is not None:
        return jobs
    if SCORED_JOBS_PATH.exists():
        with open(SCORED_JOBS_PATH) as f:
            return json.load(f)
    return []


def load_crm_applied_set() -> set[str]:
    """Return set of (company_lower, title_lower_prefix) for active CRM entries."""
    applied = set()
    if not CRM_PATH.exists():
        return applied
    with open(CRM_PATH) as f:
        crm = json.load(f)
    for app in crm.get("applications", []):
        if app.get("status") in ACTIVE_STATUSES:
            co    = (app.get("company") or "").lower().strip()
            title = (app.get("job_title") or "").lower().strip()[:40]
            applied.add((co, title))
            applied.add((co, ""))  # company-only match as fallback
    return applied


def is_applied(job: dict, applied_set: set) -> bool:
    co    = (job.get("company") or "").lower().strip()
    title = (job.get("title") or "").lower().strip()[:40]
    return (co, title) in applied_set or (co, "") in applied_set


def format_brief(
    review_jobs: list,
    quick_jobs: list,
    lookback_days: int,
    min_score: int,
) -> str:
    today = datetime.now().strftime("%A, %B %-d, %Y")
    lines = [
        f"# 🌅 Morning Job Review — {today}",
        f"*New roles scored {min_score}+ in the last {lookback_days} days, not yet applied.*",
        "",
    ]

    if not review_jobs and not quick_jobs:
        lines += [
            "No new high-scored roles since the last brief.",
            "Check the dashboard for the full active queue.",
        ]
        return "\n".join(lines)

    # ── Review roles (65+) ────────────────────────────────────────────────────
    if review_jobs:
        lines += [
            f"## Review Queue ({len(review_jobs)} roles) — discuss with Claude before applying",
            "",
        ]
        for i, job in enumerate(review_jobs, 1):
            title    = job.get("title", "?")
            company  = job.get("company", "?")
            score    = job.get("score", 0)
            rec      = job.get("apply_recommendation") or job.get("recommendation", "")
            summary  = job.get("match_summary", "").strip()
            strengths = job.get("top_strengths", [])[:2]
            gaps      = job.get("top_gaps", [])[:2]
            salary   = job.get("salary_estimate", "") or job.get("salary_text", "")
            work     = job.get("work_type", "")
            url      = job.get("url") or job.get("job_url", "")
            first    = (job.get("first_seen") or "")[:10]
            tier     = job.get("company_tier", "")

            tier_icon = {"climatetech": "⚡", "fintech_ai": "🤖"}.get(tier, "🏢")

            lines += [
                f"### {i}. {tier_icon} {title} — {company}",
                f"**Score: {score}/100** | {rec} | {work} | {salary} | First seen: {first}",
            ]
            if summary:
                lines.append(f"> {summary}")
            if strengths:
                lines.append(f"**Strengths:** {' / '.join(str(s)[:80] for s in strengths)}")
            if gaps:
                lines.append(f"**Gaps:** {' / '.join(str(g)[:80] for g in gaps)}")
            if url:
                lines.append(f"[Apply →]({url})")
            lines.append("")

    # ── Quick Apply queue (40-64) ─────────────────────────────────────────────
    if quick_jobs:
        lines += [
            f"---",
            f"## Quick Apply Queue ({len(quick_jobs)} roles scored {QUICK_APPLY_MIN}–{QUICK_APPLY_MAX})",
            "*Resume auto-generation coming soon. For now: review score + apply link.*",
            "",
        ]
        for job in quick_jobs:
            title   = job.get("title", "?")
            company = job.get("company", "?")
            score   = job.get("score", 0)
            salary  = job.get("salary_estimate", "") or ""
            url     = job.get("url") or job.get("job_url", "")
            tier    = job.get("company_tier", "")
            tier_icon = {"climatetech": "⚡", "fintech_ai": "🤖"}.get(tier, "🏢")
            apply_link = f" — [Apply →]({url})" if url else ""
            lines.append(f"- {tier_icon} **{title}** at {company} | Score: {score} | {salary}{apply_link}")
        lines.append("")

    lines += [
        "---",
        "*To get a full resume + tailored cover note for any role above, share the role name and I'll generate it.*",
    ]
    return "\n".join(lines)


def run(min_score: int = DEFAULT_MIN_SCORE, lookback_days: int = DEFAULT_LOOKBACK) -> str:
    jobs       = load_jobs()
    applied    = load_crm_applied_set()
    cutoff     = (datetime.now() - timedelta(days=lookback_days)).isoformat()

    review_jobs = []
    quick_jobs  = []

    for job in jobs:
        if is_applied(job, applied):
            continue
        first_seen = job.get("first_seen", "")
        if first_seen and first_seen < cutoff:
            continue
        score = job.get("score", 0)
        if score >= min_score:
            review_jobs.append(job)
        elif QUICK_APPLY_MIN <= score <= QUICK_APPLY_MAX:
            quick_jobs.append(job)

    review_jobs.sort(key=lambda j: j.get("score", 0), reverse=True)
    quick_jobs.sort(key=lambda j: j.get("score", 0), reverse=True)

    return format_brief(review_jobs, quick_jobs, lookback_days, min_score)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Morning job review brief")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK)
    args = parser.parse_args()

    brief = run(min_score=args.min_score, lookback_days=args.days)
    print(brief)
