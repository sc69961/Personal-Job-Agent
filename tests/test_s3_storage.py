"""
test_s3_storage.py — Tests for S3 persistent storage module.

All AWS calls are mocked — no real S3 bucket or credentials needed.
Tests cover: configuration detection, restore (download) logic,
backup (upload) logic, and graceful failure handling.

Run with: pytest tests/test_s3_storage.py -v
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.s3_storage import restore, backup, _is_configured, S3_FILES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def full_config():
    return {
        "S3_BUCKET_NAME":       "stevechristian-job-agent",
        "AWS_REGION":           "us-east-2",
        "AWS_ACCESS_KEY_ID":    "AKIATEST123",
        "AWS_SECRET_ACCESS_KEY": "supersecret",
    }


def empty_config():
    return {
        "S3_BUCKET_NAME": "",
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
    }


# ---------------------------------------------------------------------------
# _is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:

    def test_returns_true_when_all_fields_set(self):
        assert _is_configured(full_config()) is True

    def test_returns_false_when_bucket_missing(self):
        cfg = full_config()
        cfg["S3_BUCKET_NAME"] = ""
        assert _is_configured(cfg) is False

    def test_returns_false_when_key_id_missing(self):
        cfg = full_config()
        cfg["AWS_ACCESS_KEY_ID"] = ""
        assert _is_configured(cfg) is False

    def test_returns_false_when_secret_missing(self):
        cfg = full_config()
        cfg["AWS_SECRET_ACCESS_KEY"] = ""
        assert _is_configured(cfg) is False

    def test_returns_false_for_empty_config(self):
        assert _is_configured(empty_config()) is False

    def test_reads_bucket_from_env(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_NAME", "my-bucket")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        assert _is_configured({}) is True

    def test_returns_false_when_env_also_empty(self, monkeypatch):
        monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        assert _is_configured({}) is False


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

class TestRestore:

    def test_skips_when_not_configured(self, caplog):
        """restore() should log and return early if S3 isn't configured."""
        import logging
        with caplog.at_level(logging.INFO, logger="scripts.s3_storage"):
            restore(empty_config())
        assert "not configured" in caplog.text.lower()

    def test_skips_download_for_existing_files(self, tmp_path):
        """Files already present on disk should not trigger a download."""
        cfg = full_config()
        existing = tmp_path / "scored_jobs.json"
        existing.write_text(json.dumps([{"id": "j1"}]))

        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [str(existing)]):
                restore(cfg)

        mock_s3.download_file.assert_not_called()

    def test_downloads_missing_files(self, tmp_path):
        """Files missing locally should be downloaded from S3."""
        cfg = full_config()
        missing_path = str(tmp_path / "scored_jobs.json")
        # File does not exist yet

        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [missing_path]):
                restore(cfg)

        mock_s3.download_file.assert_called_once_with(
            "stevechristian-job-agent",
            "scored_jobs.json",
            missing_path,
        )

    def test_handles_missing_s3_key_gracefully(self, tmp_path, caplog):
        """If the file doesn't exist in S3 yet, restore should log info (not error) and continue."""
        import logging
        cfg = full_config()
        missing_path = str(tmp_path / "scored_jobs.json")

        mock_s3 = MagicMock()
        mock_s3.download_file.side_effect = Exception("NoSuchKey")
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [missing_path]):
                with caplog.at_level(logging.INFO, logger="scripts.s3_storage"):
                    restore(cfg)  # should not raise

        # Should log info about missing key, not raise exception
        assert any("not in bucket" in r.message or "not found" in r.message
                   for r in caplog.records)

    def test_handles_client_init_failure_gracefully(self, caplog):
        """If boto3 client can't be created, restore should warn and return."""
        import logging
        cfg = full_config()
        with patch("scripts.s3_storage._client", side_effect=Exception("No module named boto3")):
            with caplog.at_level(logging.WARNING, logger="scripts.s3_storage"):
                restore(cfg)  # should not raise

    def test_creates_output_dir(self, tmp_path):
        """restore() should create the output/ directory if it doesn't exist."""
        cfg = full_config()
        output_dir = tmp_path / "output"
        assert not output_dir.exists()

        missing_path = str(output_dir / "scored_jobs.json")
        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [missing_path]):
                restore(cfg)

        assert output_dir.exists()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

class TestBackup:

    def test_skips_when_not_configured(self):
        """backup() should return early and not call boto3 if unconfigured."""
        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            backup(empty_config())
        mock_s3.upload_file.assert_not_called()

    def test_uploads_existing_files(self, tmp_path):
        """Existing files should be uploaded to S3 with the correct key."""
        cfg = full_config()
        file_path = tmp_path / "scored_jobs.json"
        file_path.write_text(json.dumps([{"id": "j1"}]))

        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [str(file_path)]):
                backup(cfg)

        mock_s3.upload_file.assert_called_once_with(
            str(file_path),
            "stevechristian-job-agent",
            "scored_jobs.json",
        )

    def test_skips_missing_files(self, tmp_path):
        """Files that don't exist locally should be skipped (not cause an error)."""
        cfg = full_config()
        missing = str(tmp_path / "nonexistent.json")

        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [missing]):
                backup(cfg)

        mock_s3.upload_file.assert_not_called()

    def test_handles_upload_failure_gracefully(self, tmp_path, caplog):
        """An upload failure should be logged as a warning, not crash the run."""
        import logging
        cfg = full_config()
        file_path = tmp_path / "scored_jobs.json"
        file_path.write_text("{}")

        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = Exception("S3 connection timeout")

        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", [str(file_path)]):
                with caplog.at_level(logging.WARNING, logger="scripts.s3_storage"):
                    backup(cfg)  # should not raise

        assert any("upload failed" in r.message.lower() for r in caplog.records)

    def test_uploads_all_managed_files(self, tmp_path):
        """All S3_FILES should be uploaded when they all exist locally."""
        cfg = full_config()
        # Create one temp file per S3_FILES entry
        created = []
        for path in S3_FILES:
            f = tmp_path / Path(path).name
            f.write_text("{}")
            created.append(str(f))

        mock_s3 = MagicMock()
        with patch("scripts.s3_storage._client", return_value=mock_s3):
            with patch("scripts.s3_storage.S3_FILES", created):
                backup(cfg)

        assert mock_s3.upload_file.call_count == len(S3_FILES)

    def test_s3_files_constant_has_expected_entries(self):
        """S3_FILES must include all six persistence files."""
        names = [Path(p).name for p in S3_FILES]
        assert "scored_jobs.json" in names
        assert "first_seen_registry.json" in names
        assert "rejected_jobs.json" in names
        assert "market_stats.json" in names
        assert "crm.json" in names
        assert "seen_job_ids.json" in names
