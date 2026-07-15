"""
test_rejection_tracking.py — Tests for the rejection tracking pipeline.

Verifies that pre_filter rejections (no Claude tokens spent) and low_score
rejections (scored by Claude but below threshold) are correctly persisted to
rejected_jobs.json, with first_analyzed timestamps preserved across runs.

Run with: pytest tests/test_rejection_tracking.py -v
No API keys needed — all Claude calls are mocked.
"""

import json
import sys
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.scorer import score_all_jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return {
        "SALARY_FLOOR": 130_000,
        "ALLOWED_LOCATIONS": ["Remote", "Denver", "Colorado"],
        "PREFERRED_TITLES": ["Senior Product Manager"],
        "HIGH_SIGNAL_KEYWORDS": ["DER"],
        "NEGATIVE_KEYWORDS": [],
        "ALL_TARGET_COMPANIES": [],
        "RESUME_TEXT": "Steve Christian, Senior PM.",
        "ANTHROPIC_API_KEY": "test-key",
        "MIN_SCORE_TO_INCLUDE": 55,
    }


def make_job(job_id="job_001", **kwargs):
    return {
        "id": job_id,
        "title": "Senior Product Manager",
        "company": "Uplight",
        "location": "Remote",
        "description": "Lead DER platform strategy.",
        "salary_text": "$170,000",
        "url": "https://example.com/job",
        "source": "test",
        **kwargs,
    }


def mock_client_with_score(score: int):
    resp = {
        "score": score, "confidence": 70, "title_match": "good",
        "location_ok": True, "salary_ok": True,
        "company_tier": "other", "is_target_company": False,
        "seniority_ok": True, "top_strengths": [], "top_gaps": [],
        "top_reasons": [], "match_summary": "Fit summary.",
        "apply_recommendation": "maybe", "work_type": "remote",
        "salary_estimate": "$130K", "short_description": "PM role.",
    }
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps(resp))]
    client = MagicMock()
    client.messages.create.return_value = mock_resp
    return client


# ---------------------------------------------------------------------------
# Pre-filter rejection tracking
# ---------------------------------------------------------------------------

class TestPreFilterRejectionTracking:

    def test_pre_filter_rejection_written_to_file(self, config, tmp_path):
        """A job that fails pre_filter should appear in rejected_jobs.json."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        # Junior title → pre_filter will reject this
        jobs = [make_job("j1", title="Junior Product Manager")]

        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(
                        jobs, config, min_score=55,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        assert rejected_file.exists(), "rejected_jobs.json should be created"
        rejected = json.loads(rejected_file.read_text())
        assert len(rejected) == 1
        entry = rejected[0]
        assert entry["id"] == "j1"
        assert entry["rejection_type"] == "pre_filter"
        assert "junior" in entry["rejection_reason"].lower()

    def test_pre_filter_rejection_no_score(self, config, tmp_path):
        """Pre-filtered jobs never get scored, so score field should be None."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1", title="Junior Product Manager")]
        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        rejected = json.loads(rejected_file.read_text())
        assert rejected[0]["score"] is None

    def test_pre_filter_rejection_has_first_analyzed(self, config, tmp_path):
        """Each rejection entry should have a first_analyzed timestamp."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1", title="Junior PM")]
        today = datetime.now().strftime("%Y-%m-%d")
        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        rejected = json.loads(rejected_file.read_text())
        assert rejected[0]["first_analyzed"].startswith(today)

    def test_pre_filter_international_rejection(self, config, tmp_path):
        """International jobs should be pre-filtered with an international reason."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1", location="London, UK", description="")]
        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        rejected = json.loads(rejected_file.read_text())
        assert rejected[0]["rejection_type"] == "pre_filter"
        assert "international" in rejected[0]["rejection_reason"].lower()


# ---------------------------------------------------------------------------
# Low-score rejection tracking
# ---------------------------------------------------------------------------

class TestLowScoreRejectionTracking:

    def test_low_score_job_written_to_rejected_file(self, config, tmp_path):
        """A job scoring below min_score should appear in rejected_jobs.json."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1")]
        with patch("scripts.scorer.Anthropic", return_value=mock_client_with_score(30)):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    results = score_all_jobs(
                        jobs, config, min_score=55,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        assert len(results) == 0, "Low-score job should not appear in results"
        rejected = json.loads(rejected_file.read_text())
        assert len(rejected) == 1
        entry = rejected[0]
        assert entry["rejection_type"] == "low_score"
        assert entry["score"] == 30

    def test_low_score_reason_mentions_threshold(self, config, tmp_path):
        """Rejection reason should reference the score and threshold."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1")]
        with patch("scripts.scorer.Anthropic", return_value=mock_client_with_score(42)):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        rejected = json.loads(rejected_file.read_text())
        reason = rejected[0]["rejection_reason"]
        assert "42" in reason
        assert "55" in reason

    def test_qualifying_job_not_in_rejected_file(self, config, tmp_path):
        """A job scoring above threshold should NOT appear in rejected_jobs.json."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [make_job("j1")]
        with patch("scripts.scorer.Anthropic", return_value=mock_client_with_score(80)):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    results = score_all_jobs(
                        jobs, config, min_score=55,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        assert len(results) == 1
        if rejected_file.exists():
            rejected = json.loads(rejected_file.read_text())
            assert not any(r["id"] == "j1" for r in rejected)


# ---------------------------------------------------------------------------
# first_analyzed preservation across runs
# ---------------------------------------------------------------------------

class TestFirstAnalyzedPreservation:

    def test_first_analyzed_preserved_on_second_run(self, config, tmp_path):
        """
        If a job was rejected in a previous run, re-running should preserve
        the original first_analyzed date (not overwrite with today's date).
        """
        old_date = "2026-05-01T09:00:00"
        existing_rejected = [
            {
                "id": "j1", "title": "Junior PM", "company": "Uplight",
                "url": "https://example.com",
                "rejection_type": "pre_filter",
                "rejection_reason": "junior signal in title",
                "score": None,
                "first_analyzed": old_date,
                "last_analyzed": old_date,
                "location": "Remote", "salary_text": "", "source": "test",
            }
        ]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(existing_rejected))
        cache_file = tmp_path / "scored_jobs.json"

        # Same job appears again
        jobs = [make_job("j1", title="Junior Product Manager")]
        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        updated = json.loads(rejected_file.read_text())
        entry = next(r for r in updated if r["id"] == "j1")
        assert entry["first_analyzed"] == old_date, (
            f"first_analyzed should be preserved as {old_date!r}, got {entry['first_analyzed']!r}"
        )
        # last_analyzed should be updated
        today = datetime.now().strftime("%Y-%m-%d")
        assert entry["last_analyzed"].startswith(today)

    def test_multiple_rejections_all_tracked(self, config, tmp_path):
        """Both a pre-filter and a low-score rejection in the same run are both saved."""
        cache_file    = tmp_path / "scored_jobs.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        jobs = [
            make_job("j_junior", title="Junior Product Manager"),  # pre_filter
            make_job("j_lowscore"),                                # will score low
        ]

        with patch("scripts.scorer.Anthropic", return_value=mock_client_with_score(25)):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(jobs, config, min_score=55,
                                   cache_path=str(cache_file),
                                   rejected_path=str(rejected_file))

        rejected = json.loads(rejected_file.read_text())
        ids = {r["id"] for r in rejected}
        assert "j_junior" in ids
        assert "j_lowscore" in ids
        types = {r["id"]: r["rejection_type"] for r in rejected}
        assert types["j_junior"] == "pre_filter"
        assert types["j_lowscore"] == "low_score"
