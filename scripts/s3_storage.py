"""
s3_storage.py — Persistent data storage via Amazon S3.

Downloads key output files at run start to warm the local cache after a
GitHub Actions cache expiry. Uploads after each run so S3 is always the
permanent source of truth (never expires, unlike the 7-day Actions cache).

Files managed:
  output/scored_jobs.json         — scoring cache (primary, not in git)
  output/first_seen_registry.json — first-seen timestamps
  output/rejected_jobs.json       — pipeline / performance log
  output/market_stats.json        — historical PM role trends
"""

import os
import logging

logger = logging.getLogger(__name__)

S3_FILES = [
    "output/scored_jobs.json",
    "output/first_seen_registry.json",
    "output/rejected_jobs.json",
    "output/market_stats.json",
]


def _bucket(config: dict) -> str:
    return config.get("S3_BUCKET_NAME") or os.environ.get("S3_BUCKET_NAME", "")


def _is_configured(config: dict) -> bool:
    return bool(
        _bucket(config)
        and (config.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID", ""))
        and (config.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
    )


def _client(config: dict):
    import boto3
    return boto3.client(
        "s3",
        region_name=config.get("AWS_REGION", "us-east-2"),
        aws_access_key_id=config.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=config.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    )


def restore(config: dict) -> None:
    """
    Download files from S3 that are missing locally.
    Called at run start — recovers the scoring cache after a cache expiry.

    Files already present on disk (from the GitHub Actions cache) are left
    alone; S3 only fills in the gaps.
    """
    if not _is_configured(config):
        logger.info("S3: not configured — skipping restore (set S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)")
        return

    bucket = _bucket(config)
    try:
        s3 = _client(config)
    except Exception as e:
        logger.warning(f"S3: could not initialise client — {e}")
        return

    downloaded, skipped = 0, 0
    for local_path in S3_FILES:
        key = os.path.basename(local_path)
        if os.path.exists(local_path):
            logger.info(f"S3 restore: {key} already local — skipping")
            skipped += 1
            continue
        # Ensure parent directory exists before downloading
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        try:
            s3.download_file(bucket, key, local_path)
            size_kb = os.path.getsize(local_path) // 1024 if os.path.exists(local_path) else 0
            logger.info(f"S3 restore: downloaded {key} ({size_kb} KB)")
            downloaded += 1
        except Exception as e:
            err = str(e)
            if "NoSuchKey" in err or "404" in err or "does not exist" in err.lower():
                logger.info(f"S3 restore: {key} not in bucket yet — will be created after this run")
            else:
                logger.info(f"S3 restore: {key} not found — {e}")

    logger.info(f"S3 restore complete — {downloaded} downloaded, {skipped} already local from s3://{bucket}/")


def backup(config: dict) -> None:
    """
    Upload all managed output files to S3 after a run.
    Called at run end — S3 becomes the permanent, always-current source of truth.
    """
    if not _is_configured(config):
        return

    bucket = _bucket(config)
    try:
        s3 = _client(config)
    except Exception as e:
        logger.warning(f"S3: could not initialise client — {e}")
        return

    uploaded, missing = 0, 0
    for local_path in S3_FILES:
        if not os.path.exists(local_path):
            missing += 1
            continue
        key = os.path.basename(local_path)
        try:
            s3.upload_file(local_path, bucket, key)
            size_kb = os.path.getsize(local_path) // 1024
            logger.info(f"S3 backup: uploaded {key} ({size_kb} KB)")
            uploaded += 1
        except Exception as e:
            logger.warning(f"S3 backup: upload failed for {key} — {e}")

    logger.info(f"S3 backup complete — {uploaded} uploaded, {missing} not found — s3://{bucket}/")
