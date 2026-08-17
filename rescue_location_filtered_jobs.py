#!/usr/bin/env python3
"""
rescue_location_filtered_jobs.py — Rescue all jobs wrongly dropped by the location pre-filter.

The pre-filter drops jobs with a specific non-Denver US city when no remote signal is
found in the description.  This silently blacklists jobs that are actually remote-eligible
when:
  - Description was empty at scrape time (board-scraped jobs: Lynceus, Wellfound, etc.)
  - The company used its HQ city in the ATS location field even for remote roles
  - Remote signal synonyms weren't in our list ("remote-first", "open to remote", etc.)

This script:
  1. Downloads rejected_jobs.json + seen_job_ids.json + first_seen_registry.json from S3
  2. Finds every pre-filter drop with reason containing "on-site, not in Denver metro"
  3. Seeds first_seen_registry with each job's first_analyzed date so re-scoring
     preserves the ORIGINAL first-seen date (not today's date)
  4. Removes those IDs from seen_job_ids so the next run re-scrapes + re-scores them
  5. Re-uploads all three files to S3

IMPORTANT: Run this AFTER deploying the improved pre_filter (scorer.py with Fixes A-D).
Otherwise the same jobs will be dropped again on the next run.

Run from ~/Downloads/job-agent:  python3 rescue_location_filtered_jobs.py
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

try:
    from config.config import (
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
        S3_BUCKET_NAME as BUCKET, AWS_REGION,
    )
except ImportError as e:
    sys.exit(f"Could not load config: {e}")

try:
    import boto3
except ImportError:
    sys.exit("boto3 not installed — run: pip install boto3 --break-system-packages")


def s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


def download(key: str) -> any:
    obj = s3_client().get_object(Bucket=BUCKET, Key=key)
    return json.loads(obj["Body"].read())


def download_safe(key: str, default) -> any:
    """Download from S3; return default if key doesn't exist yet."""
    try:
        return download(key)
    except Exception as e:
        if "NoSuchKey" in str(e) or "404" in str(e):
            return default
        raise


def upload(key: str, data) -> None:
    s3_client().put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json",
    )


# Pre-filter rejection reasons that indicate a location false-drop
_LOCATION_DROP_REASONS = [
    "on-site, not in denver metro",
    "on-site only signal in jd, outside allowed locations",
    "international signals in description",   # may include false positives from bad geo-parsing
]


def is_location_false_drop(reason: str) -> bool:
    reason_lower = reason.lower()
    return any(pattern in reason_lower for pattern in _LOCATION_DROP_REASONS)


if __name__ == "__main__":
    print("=" * 60)
    print("rescue_location_filtered_jobs.py")
    print("Rescues jobs wrongly dropped by the location pre-filter")
    print("=" * 60)

    print("\nDownloading rejected_jobs.json from S3...")
    rejected_raw = download("rejected_jobs.json")
    # Normalize to dict keyed by job id
    if isinstance(rejected_raw, list):
        rejected_dict = {e["id"]: e for e in rejected_raw if e.get("id")}
    else:
        rejected_dict = rejected_raw
    print(f"  {len(rejected_dict)} total rejected entries")

    print("Downloading seen_job_ids.json from S3...")
    seen_raw = download("seen_job_ids.json")
    seen_ids: set = set(seen_raw) if isinstance(seen_raw, list) else set(seen_raw.get("ids", []))
    print(f"  {len(seen_ids)} IDs in seen_job_ids")

    print("Downloading first_seen_registry.json from S3...")
    first_seen_registry: dict = download_safe("first_seen_registry.json", {})
    print(f"  {len(first_seen_registry)} entries in first_seen_registry")

    # Find all location-related false-drops
    rescue_entries = {}
    for jid, entry in rejected_dict.items():
        reason = entry.get("rejection_reason", "") or entry.get("filter_reason", "")
        if reason and is_location_false_drop(reason):
            rescue_entries[jid] = entry

    if not rescue_entries:
        print("\nNo location false-drops found — nothing to do.")
        sys.exit(0)

    # Print breakdown
    print(f"\nFound {len(rescue_entries)} jobs to rescue:\n")
    by_reason: dict = {}
    for jid, entry in rescue_entries.items():
        r = entry.get("rejection_reason", "")
        by_reason.setdefault(r, []).append(entry)

    for reason, entries in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(entries)}] {reason}")
        for e in entries[:5]:  # show up to 5 examples per reason
            loc = e.get("location", "?")
            print(f"       • {e.get('title','?'):45s} | {e.get('company','?'):25s} | loc: {loc}")
        if len(entries) > 5:
            print(f"       ... and {len(entries) - 5} more")

    # ── Step 1: Seed first_seen_registry BEFORE removing from seen_ids ──────────
    # This ensures re-scoring picks up the original date, not today's date.
    # Jobs on the dashboard already have entries in first_seen_registry — setdefault
    # never overwrites them.
    registry_seeded = 0
    for jid, entry in rescue_entries.items():
        if jid not in first_seen_registry:
            original_date = (
                entry.get("first_analyzed")
                or entry.get("last_analyzed")
                or datetime.now().isoformat()
            )
            first_seen_registry[jid] = original_date
            registry_seeded += 1

    print(f"\nSeeded {registry_seeded} original dates into first_seen_registry")
    print(f"  ({len(rescue_entries) - registry_seeded} already had registry entries — left untouched)")

    # ── Step 2: Remove rescued IDs from seen_job_ids ──────────────────────────
    before = len(seen_ids)
    seen_ids -= set(rescue_entries.keys())
    after = len(seen_ids)
    print(f"Removed {before - after} IDs from seen_job_ids ({before} → {after})")

    # ── Step 3: Remove from rejected_jobs so the performance tab is clean ──────
    for jid in rescue_entries:
        rejected_dict.pop(jid, None)
    updated_rejected = list(rejected_dict.values())
    print(f"Removed {len(rescue_entries)} entries from rejected_jobs")

    # ── Step 4: Upload all three files ────────────────────────────────────────
    print("\nUploading updated files to S3...")
    upload("first_seen_registry.json", first_seen_registry)
    print("  ✅ first_seen_registry.json — original dates preserved")
    upload("seen_job_ids.json", list(seen_ids))
    print("  ✅ seen_job_ids.json — rescued IDs cleared")
    upload("rejected_jobs.json", updated_rejected)
    print("  ✅ rejected_jobs.json — false-drops removed from performance log")

    print(f"""
✅ Done — {len(rescue_entries)} jobs rescued.
   Their original first-seen dates are preserved in first_seen_registry.
   Jobs currently on the dashboard are UNAFFECTED (first_seen_registry
   uses setdefault — existing entries are never overwritten).

Next steps:
  1. Make sure scorer.py with the improved pre_filter (Fixes A-D) is
     deployed to GitHub (git push from job-agent-cloud).
  2. Trigger 'Job Agent — Daily Run' in GitHub Actions.
     These jobs will be re-scraped, pass the improved filter, and be
     scored by Claude with their original first-seen dates intact.
""")
