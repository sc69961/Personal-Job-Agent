#!/usr/bin/env python3
"""
rescue_see_listing_jobs.py — Remove incorrectly filtered job-board jobs from seen_ids.

Jobs from ClimatePeople, ClimateDraft, Terra.do (and now Wellfound, Built In CO)
all use 'See listing' as their location placeholder.  The pre-filter was treating
that as a specific non-Denver city and dropping them permanently.

This script:
  1. Downloads rejected_jobs.json + seen_job_ids.json + first_seen_registry.json from S3
  2. Finds every job dropped for "on-site, not in Denver metro: see listing"
  3. Seeds first_seen_registry with each job's first_analyzed date so re-scoring
     preserves the original first-seen date (not today's date)
  4. Removes those IDs from seen_job_ids so the next run re-scrapes + re-scores them
  5. Re-uploads all three files to S3

Run from ~/Downloads/job-agent:  python3 rescue_see_listing_jobs.py
"""

import json
import sys
import os

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


if __name__ == "__main__":
    print("Downloading rejected_jobs.json from S3...")
    rejected = download("rejected_jobs.json")
    print(f"  {len(rejected)} total rejected entries")

    print("Downloading seen_job_ids.json from S3...")
    seen = download("seen_job_ids.json")
    seen_ids: set = set(seen) if isinstance(seen, list) else set(seen.get("ids", []))
    print(f"  {len(seen_ids)} IDs in seen_job_ids")

    print("Downloading first_seen_registry.json from S3...")
    first_seen_registry: dict = download_safe("first_seen_registry.json", {})
    print(f"  {len(first_seen_registry)} entries in first_seen_registry")

    # Normalize rejected to a dict keyed by job id
    if isinstance(rejected, list):
        rejected_dict = {e["id"]: e for e in rejected if e.get("id")}
    else:
        rejected_dict = rejected

    # Find all jobs dropped because location was "See listing"
    rescue_ids = []
    print("\nJobs incorrectly filtered (location = 'See listing'):")
    for jid, entry in rejected_dict.items():
        reason = entry.get("rejection_reason", "") or entry.get("filter_reason", "")
        if "see listing" in reason.lower():
            rescue_ids.append(jid)
            print(f"  {entry.get('title','?'):50s} | {entry.get('company','?'):25s} | {entry.get('source','?')}")

    if not rescue_ids:
        print("  None found — nothing to do.")
        sys.exit(0)

    print(f"\nTotal to rescue: {len(rescue_ids)}")

    # Seed first_seen_registry with original scrape dates BEFORE clearing seen_ids.
    # This ensures re-scoring uses the original first-seen date, not today.
    registry_seeded = 0
    for jid in rescue_ids:
        if jid not in first_seen_registry:
            entry = rejected_dict[jid]
            original_date = entry.get("first_analyzed") or entry.get("last_analyzed")
            if original_date:
                first_seen_registry[jid] = original_date
                registry_seeded += 1
    print(f"Seeded {registry_seeded} entries into first_seen_registry (preserves original dates)")

    # Remove rescued IDs from seen_ids so next run re-processes them
    before = len(seen_ids)
    seen_ids -= set(rescue_ids)
    after = len(seen_ids)
    print(f"Removed {before - after} IDs from seen_job_ids ({before} → {after})")

    # Remove from rejected_jobs too so the performance tab doesn't keep showing them
    for jid in rescue_ids:
        rejected_dict.pop(jid, None)
    updated_rejected = list(rejected_dict.values())

    print("\nUploading updated files to S3...")
    upload("first_seen_registry.json", first_seen_registry)
    upload("seen_job_ids.json", list(seen_ids))
    upload("rejected_jobs.json", updated_rejected)
    print("✅ Done — these jobs will be re-scraped and re-scored on the next run.")
    print("   Their original first-seen dates are preserved in first_seen_registry.")
    print("   Trigger 'Job Agent — Daily Run' in GitHub Actions to process them now.")
