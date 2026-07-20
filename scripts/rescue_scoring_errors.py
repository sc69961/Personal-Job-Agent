#!/usr/bin/env python3
"""
rescue_scoring_errors.py — Re-queues API-error jobs so they're scored on the
next agent run.

The job descriptions are not stored in rejected_jobs.json, so we can't rescore
directly.  Instead this script:
  1. Downloads seen_job_ids.json + rejected_jobs.json from S3
  2. Finds every entry with rejection_type == "scoring_error"
  3. Removes those IDs from seen_ids  (unblocks them for the next scrape)
  4. Removes those entries from rejected_jobs (clean slate)
  5. Uploads both files back to S3

On the next run (scheduled or manual), the scraper re-fetches those jobs from
the company career pages and passes them to Claude for scoring.  Any job that
has since been taken down simply won't appear — that's expected behaviour.

Usage (local):
    cd ~/Downloads/job-agent
    python3 scripts/rescue_scoring_errors.py

Usage (GitHub Actions — triggered via workflow_dispatch with rescue_errors=true):
    Credentials are read from environment variables set by the workflow.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEEN_IDS_PATH = "./output/seen_job_ids.json"
REJECTED_PATH = "./output/rejected_jobs.json"


def _get_aws_config():
    """Return (bucket, region, key_id, secret) from env vars or config.py."""
    bucket = os.environ.get("S3_BUCKET_NAME", "")
    region = os.environ.get("AWS_REGION", "")
    key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

    if not all([bucket, key_id, secret]):
        try:
            from config.config import (
                S3_BUCKET_NAME, AWS_REGION,
                AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
            )
            bucket = bucket or S3_BUCKET_NAME
            region = region or AWS_REGION
            key_id = key_id or AWS_ACCESS_KEY_ID
            secret = secret or AWS_SECRET_ACCESS_KEY
        except ImportError:
            pass

    return bucket, region or "us-east-2", key_id, secret


def main():
    bucket, region, key_id, secret = _get_aws_config()

    if not all([bucket, key_id, secret]):
        print("❌  S3 credentials not found in env vars or config/config.py")
        print("    Set S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")
        sys.exit(1)

    try:
        import boto3
    except ImportError:
        print("❌  boto3 not installed.  Run: pip install boto3 --break-system-packages")
        sys.exit(1)

    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )

    os.makedirs("output", exist_ok=True)

    # ── Pull latest files from S3 ────────────────────────────────────────────
    for local_path in [SEEN_IDS_PATH, REJECTED_PATH]:
        s3_key = local_path.lstrip("./")
        print(f"  ⬇  s3://{bucket}/{s3_key}")
        try:
            s3.download_file(bucket, s3_key, local_path)
        except Exception as e:
            print(f"     (not in S3 yet — using local file if present: {e})")

    # ── Load files ───────────────────────────────────────────────────────────
    seen_ids: set = set()
    if os.path.exists(SEEN_IDS_PATH):
        with open(SEEN_IDS_PATH) as f:
            seen_ids = set(json.load(f))
    print(f"\n  seen_job_ids.json : {len(seen_ids):,} IDs")

    rejected: list = []
    if os.path.exists(REJECTED_PATH):
        with open(REJECTED_PATH) as f:
            rejected = json.load(f)
    print(f"  rejected_jobs.json: {len(rejected):,} entries")

    # ── Find scoring_error jobs ──────────────────────────────────────────────
    error_jobs = [r for r in rejected if r.get("rejection_type") == "scoring_error"]
    error_ids  = {r["id"] for r in error_jobs if r.get("id")}

    if not error_jobs:
        print("\n✅  No scoring_error entries found — nothing to rescue.")
        return

    print(f"\n  Found {len(error_jobs)} API-error jobs to rescue:")
    for r in error_jobs:
        print(f"    · {r.get('company', '?')} — {r.get('title', '?')}")

    # ── Remove error IDs from seen_ids ───────────────────────────────────────
    before = len(seen_ids)
    seen_ids -= error_ids
    removed_from_seen = before - len(seen_ids)
    print(f"\n  seen_ids: {before:,} → {len(seen_ids):,}  (-{removed_from_seen} IDs unblocked)")

    # ── Remove error entries from rejected_jobs ──────────────────────────────
    clean_rejected = [r for r in rejected if r.get("id") not in error_ids]
    print(f"  rejected_jobs: {len(rejected):,} → {len(clean_rejected):,} entries")

    # ── Write updated local files ────────────────────────────────────────────
    with open(SEEN_IDS_PATH, "w") as f:
        json.dump(sorted(seen_ids), f)
    with open(REJECTED_PATH, "w") as f:
        json.dump(clean_rejected, f, indent=2)

    # ── Upload back to S3 ────────────────────────────────────────────────────
    print()
    for local_path, s3_key in [
        (SEEN_IDS_PATH, "output/seen_job_ids.json"),
        (REJECTED_PATH, "output/rejected_jobs.json"),
    ]:
        print(f"  ⬆  s3://{bucket}/{s3_key}")
        try:
            s3.upload_file(local_path, bucket, s3_key)
            print(f"     ✅  uploaded")
        except Exception as e:
            print(f"     ❌  upload failed: {e}")
            sys.exit(1)

    print(f"""
✅  Rescue complete!
    {len(error_ids)} jobs cleared from seen_ids and removed from rejected_jobs.

    Next step: trigger a GitHub Actions run (Actions → Job Agent → Run workflow).
    The scraper will re-fetch those jobs from the company career pages and score
    them.  Jobs that have since been taken down simply won't appear.
""")


if __name__ == "__main__":
    main()
