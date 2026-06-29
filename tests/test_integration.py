"""
test_integration.py — End-to-end pipeline tests with all external calls mocked.
Tests the full flow: score → filter → email cap → dashboard render.
Run with: pytest tests/test_integration.py -v
"""

import json
import sys
import os
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_job(id="job_001", title="Senior Product Manager", company="Uplight",
             score=None, first_seen=None, **kwargs):
    job = {
        "id": id, "title": title, "company": company,
        "location": "Remote", "url": f"https://example.com/{id}",
        "description": "Lead DER platform product strategy.",
        "salary_text": "$170,000 - $200,000",
        "source": "company_site",
        "work_type": "remote",
        "company_tier": "climatetech",
    }
    if score is not None:
        job.update({
            "score": score, "confidence": 80, "title_match": "strong",
            "location_ok": True, "salary_ok": True, "is_target_company": True,
            "seniority_ok": True, "top_strengths": ["DER expertise"],
            "top_gaps": [], "top_reasons": ["Strong fit"],
            "match_summary": "Great fit.", "apply_recommendation": "yes",
            "salary_estimate": "$185K", "short_description": "DER PM role.",
        })
    if first_seen:
        job["first_seen"] = first_seen
    job.update(kwargs)
    return job


MOCK_CLAUDE_SCORE = {
    "score": 78, "confidence": 85, "title_match": "strong",
    "location_ok": True, "salary_ok": True, "company_tier": "climatetech",
    "is_target_company": True, "seniority_ok": True,
    "top_strengths": ["DER platform experience", "0->1 ownership"],
    "top_gaps": [], "top_reasons": ["Energy software match"],
    "match_summary": "Strong fit for this DER platform PM role.",
    "apply_recommendation": "yes", "work_type": "remote",
    "salary_estimate": "$185K-$210K", "short_description": "DER PM role at Uplight."
}


# ---------------------------------------------------------------------------
# Scorer integration — mocked Claude API
# ---------------------------------------------------------------------------

class TestScorerIntegration:

    def test_full_score_pipeline_with_mock_claude(self, tmp_path):
        """Raw job → score_all_jobs → scored output with correct fields."""
        from scripts.scorer import score_all_jobs

        config = {
            "SALARY_FLOOR": 130_000, "ALLOWED_LOCATIONS": ["Remote", "Denver"],
            "PREFERRED_TITLES": ["Senior Product Manager"],
            "HIGH_SIGNAL_KEYWORDS": ["DER"], "NEGATIVE_KEYWORDS": ["healthcare"],
            "ALL_TARGET_COMPANIES": ["Uplight"], "RESUME_TEXT": "Steve Christian, DER PM.",
            "ANTHROPIC_API_KEY": "test-key", "MIN_SCORE_TO_INCLUDE": 55,
        }

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(MOCK_CLAUDE_SCORE))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        jobs = [make_job(id="new_job")]
        cache_file = tmp_path / "scored.json"

        with patch("scripts.scorer.Anthropic", return_value=mock_client):
            results = score_all_jobs(jobs, config, min_score=55, cache_path=str(cache_file))

        assert len(results) == 1
        assert results[0]["score"] == 78
        assert results[0]["apply_recommendation"] == "yes"
        assert results[0]["first_seen"] == datetime.now().strftime("%Y-%m-%d")

    def test_malformed_claude_response_does_not_crash(self, tmp_path):
        """If Claude returns garbage JSON, pipeline continues gracefully."""
        from scripts.scorer import score_all_jobs

        config = {
            "SALARY_FLOOR": 130_000, "ALLOWED_LOCATIONS": ["Remote"],
            "PREFERRED_TITLES": [], "HIGH_SIGNAL_KEYWORDS": [],
            "NEGATIVE_KEYWORDS": [], "ALL_TARGET_COMPANIES": [],
            "RESUME_TEXT": "Steve.", "ANTHROPIC_API_KEY": "test-key",
            "MIN_SCORE_TO_INCLUDE": 55,
        }

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="I cannot score this role at this time.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        jobs = [make_job(id="bad_job")]
        cache_file = tmp_path / "scored.json"

        with patch("scripts.scorer.Anthropic", return_value=mock_client):
            results = score_all_jobs(jobs, config, min_score=55, cache_path=str(cache_file))

        # Malformed response → score=0 → filtered below min_score=55
        assert len(results) == 0

    def test_api_exception_does_not_crash_pipeline(self, tmp_path):
        """If Claude API raises an exception mid-run, other jobs still get scored."""
        from scripts.scorer import score_all_jobs

        config = {
            "SALARY_FLOOR": 130_000, "ALLOWED_LOCATIONS": ["Remote"],
            "PREFERRED_TITLES": [], "HIGH_SIGNAL_KEYWORDS": [],
            "NEGATIVE_KEYWORDS": [], "ALL_TARGET_COMPANIES": [],
            "RESUME_TEXT": "Steve.", "ANTHROPIC_API_KEY": "test-key",
            "MIN_SCORE_TO_INCLUDE": 55,
        }

        # First call fails, second succeeds
        good_response = MagicMock()
        good_response.content = [MagicMock(text=json.dumps(MOCK_CLAUDE_SCORE))]
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception("Rate limit"),
            Exception("Rate limit"),  # both attempts for job_1 fail
            good_response,            # job_2 succeeds
        ]

        jobs = [make_job(id="job_1"), make_job(id="job_2")]
        cache_file = tmp_path / "scored.json"

        with patch("scripts.scorer.Anthropic", return_value=mock_client):
            results = score_all_jobs(jobs, config, min_score=55, cache_path=str(cache_file))

        # job_1 failed → score=0 → filtered; job_2 passed
        assert len(results) == 1
        assert results[0]["id"] == "job_2"


# ---------------------------------------------------------------------------
# Daily email cap logic
# ---------------------------------------------------------------------------

class TestDailyEmailCap:

    def _run_email_cap_check(self, flag_content: str, today: str, email_only: bool = False) -> bool:
        """Replicate the email cap check from main.py."""
        already_sent = False
        if flag_content and not email_only:
            already_sent = flag_content.strip() == today
        return already_sent

    def test_blocks_second_email_same_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        already_sent = self._run_email_cap_check(today, today)
        assert already_sent is True

    def test_allows_email_on_new_day(self):
        yesterday = "2026-06-28"
        today = "2026-06-29"
        already_sent = self._run_email_cap_check(yesterday, today)
        assert already_sent is False

    def test_allows_email_on_first_run(self):
        already_sent = self._run_email_cap_check("", datetime.now().strftime("%Y-%m-%d"))
        assert already_sent is False

    def test_email_only_flag_bypasses_cap(self):
        today = datetime.now().strftime("%Y-%m-%d")
        # email_only=True should bypass the cap
        already_sent = self._run_email_cap_check(today, today, email_only=True)
        assert already_sent is False


# ---------------------------------------------------------------------------
# Dashboard rendering with mock data
# ---------------------------------------------------------------------------

class TestDashboardRendering:

    def test_renders_without_crashing(self, tmp_path):
        """Dashboard should generate valid HTML from scored jobs + CRM data."""
        from scripts.dashboard import generate_dashboard

        jobs = [
            make_job("j1", score=85, first_seen=datetime.now().strftime("%Y-%m-%d")),
            make_job("j2", company="Voltus", score=72, first_seen="2026-06-01"),
        ]
        crm = {
            "applications": [
                {"id": "a1", "company": "Voltus", "status": "interview_requested",
                 "status_label": "Interview Requested", "job_title": "PM",
                 "job_url": "", "applied_date": "", "last_activity": "2026-06-22",
                 "follow_up_date": "", "recommended_action": "", "notes": "", "thread_ids": []}
            ],
            "last_synced": "2026-06-29T00:00:00"
        }

        output_path = str(tmp_path / "dashboard.html")
        result = generate_dashboard(jobs, crm=crm, output_path=output_path)

        assert os.path.exists(output_path)
        html = open(output_path).read()
        assert "Job Agent" in html
        assert "Uplight" in html
        assert "Voltus" in html

    def test_new_badge_appears_for_today_job(self, tmp_path):
        """Jobs with first_seen == today should show NEW badge."""
        from scripts.dashboard import generate_dashboard

        today = datetime.now().strftime("%Y-%m-%d")
        jobs = [make_job("j1", score=80, first_seen=today)]

        output_path = str(tmp_path / "dashboard.html")
        generate_dashboard(jobs, crm={}, output_path=output_path)
        html = open(output_path).read()
        assert "NEW" in html

    def test_new_badge_absent_for_old_job(self, tmp_path):
        """Jobs with first_seen in the past should NOT show NEW badge."""
        from scripts.dashboard import generate_dashboard

        jobs = [make_job("j1", score=80, first_seen="2026-06-01")]

        output_path = str(tmp_path / "dashboard.html")
        generate_dashboard(jobs, crm={}, output_path=output_path)
        html = open(output_path).read()

        # The NEW badge should not appear for old jobs
        # Check that the specific NEW badge style isn't tied to this job
        # (the word NEW might appear elsewhere, so check for badge style context)
        import re
        new_badges = re.findall(r'background:#1e2a0f.*?NEW', html, re.DOTALL)
        assert len(new_badges) == 0

    def test_applied_badge_appears_for_crm_company(self, tmp_path):
        """Jobs at companies with a CRM entry should show the CRM status badge."""
        from scripts.dashboard import generate_dashboard

        jobs = [make_job("j1", company="Uplight", score=80, first_seen="2026-06-01")]
        crm = {
            "applications": [
                {"id": "a1", "company": "Uplight", "status": "interview_requested",
                 "status_label": "Interview Requested", "job_title": "PM",
                 "job_url": "", "applied_date": "", "last_activity": "2026-06-22",
                 "follow_up_date": "", "recommended_action": "", "notes": "", "thread_ids": []}
            ]
        }

        output_path = str(tmp_path / "dashboard.html")
        generate_dashboard(jobs, crm=crm, output_path=output_path)
        html = open(output_path).read()
        assert "Interviewing" in html

    def test_renders_with_empty_jobs_list(self, tmp_path):
        """Empty job list should render without crashing."""
        from scripts.dashboard import generate_dashboard

        output_path = str(tmp_path / "dashboard.html")
        generate_dashboard([], crm={}, output_path=output_path)
        assert os.path.exists(output_path)

    def test_renders_market_tab_with_no_stats(self, tmp_path):
        """Market tab should show placeholder, not crash, when no stats file exists."""
        from scripts.dashboard import _build_market_tab

        html = _build_market_tab(stats_path=str(tmp_path / "nonexistent.json"))
        assert "No market data" in html


# ---------------------------------------------------------------------------
# Regression tests — known past bugs
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_offer_status_not_overwritten_by_new_applied_thread(self):
        """
        Regression: Omnidian offer was lost when a new thread arrived with status=applied.
        The CRM should never downgrade from offer → applied.
        """
        from scripts.gmail_crm import _should_upgrade_status
        assert _should_upgrade_status("offer", "applied") is False

    def test_company_normalization_prevents_duplicate_crm_entries(self):
        """
        Regression: Voltus and Voltus Inc. created two separate CRM entries.
        After normalization fix, they must hash to the same ID.
        """
        from scripts.gmail_crm import _app_id
        id_plain = _app_id("Voltus", "Product Manager")
        id_with_inc = _app_id("Voltus Inc.", "Product Manager")
        assert id_plain == id_with_inc

    def test_pre_filter_catches_junior_before_claude_called(self):
        """
        Regression: Junior roles were being sent to Claude for scoring (wasting tokens).
        pre_filter must catch them first.
        """
        from scripts.scorer import pre_filter
        config = {
            "SALARY_FLOOR": 130_000, "ALLOWED_LOCATIONS": ["Remote"],
            "NEGATIVE_KEYWORDS": [],
        }
        job = {"title": "Junior Product Manager", "description": "", "location": "Remote", "salary_text": ""}
        ok, reason = pre_filter(job, config)
        assert not ok, "Junior PM should be caught by pre_filter before Claude"

    def test_url_dedup_collapses_hopper_duplicates(self):
        """
        Regression: 7 identical Hopper job URLs appeared as separate jobs.
        URL dedup must collapse them to 1.
        """
        url = "https://hopper.com/careers/pm-flight-connectivity"
        jobs = [{"id": f"hop_{i}", "url": url, "title": "Senior PM"} for i in range(7)]

        seen_urls = set()
        deduped = []
        for job in jobs:
            u = job.get("url", "")
            if u and u in seen_urls:
                continue
            if u:
                seen_urls.add(u)
            deduped.append(job)

        assert len(deduped) == 1
