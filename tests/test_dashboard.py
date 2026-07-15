"""
test_dashboard.py — Tests for dashboard HTML generation.

Covers:
  - Action queue / Maybe / Archive section splitting logic
  - Maybe section appears for jobs scoring 40–54, action queue for 55+
  - Stale jobs (>7 days) go to archive regardless of score
  - Applied jobs (CRM match) go to archive
  - _build_performance_tab: stats, filter buttons, table rows, type badges

Run with: pytest tests/test_dashboard.py -v
"""

import sys
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.dashboard import _build_jobs_tab, _build_performance_tab, generate_dashboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scored_job(job_id="job_001", score=75, days_ago=1, **kwargs):
    """Build a scored job dict. days_ago controls first_seen age."""
    first_seen = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "id": job_id,
        "title": "Senior Product Manager",
        "company": "Uplight",
        "location": "Remote",
        "description": "DER platform strategy.",
        "salary_text": "$170,000",
        "url": "https://example.com/job",
        "source": "test",
        "score": score,
        "confidence": 80,
        "title_match": "strong",
        "location_ok": True,
        "salary_ok": True,
        "company_tier": "climatetech",
        "is_target_company": True,
        "seniority_ok": True,
        "top_strengths": ["DER expertise"],
        "top_gaps": [],
        "top_reasons": ["Strong match"],
        "match_summary": "Excellent fit.",
        "apply_recommendation": "yes",
        "work_type": "remote",
        "salary_estimate": "$170K–$210K",
        "short_description": "DER PM role.",
        "first_seen": first_seen,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Action queue / Maybe / Archive splitting
# ---------------------------------------------------------------------------

class TestJobsTabSectionSplitting:

    def test_high_score_recent_job_in_action_queue(self):
        """Score ≥ 55, seen within 7 days → action queue."""
        jobs = [make_scored_job("j1", score=80, days_ago=1)]
        html = _build_jobs_tab(jobs, "test run")
        assert "Action queue" in html
        # The job card should be in the #grid (action queue) section
        assert "j1" not in html.split("Archive")[1] if "Archive" in html else True

    def test_maybe_score_recent_job_in_maybe_section(self):
        """Score 40–54, seen within 7 days → Maybe section."""
        jobs = [make_scored_job("j1", score=48, days_ago=2)]
        html = _build_jobs_tab(jobs, "test run")
        assert "Maybe" in html
        assert "40–54" in html or "40–54" in html

    def test_high_score_stale_job_in_archive(self):
        """Score ≥ 55 but seen >7 days ago → archive, not action queue."""
        jobs = [make_scored_job("j1", score=90, days_ago=10)]
        html = _build_jobs_tab(jobs, "test run")
        assert "Archive" in html

    def test_maybe_score_stale_job_in_archive(self):
        """Score 40–54 but stale → archive (stale takes priority over maybe)."""
        jobs = [make_scored_job("j1", score=45, days_ago=10)]
        html = _build_jobs_tab(jobs, "test run")
        assert "Archive" in html

    def test_no_maybe_section_when_all_jobs_above_threshold(self):
        """If all jobs score 55+, the Maybe section should not appear."""
        jobs = [
            make_scored_job("j1", score=75, days_ago=1),
            make_scored_job("j2", score=82, days_ago=2),
        ]
        html = _build_jobs_tab(jobs, "test run")
        assert "maybeToggleBtn" not in html

    def test_no_archive_section_when_all_jobs_recent_and_unapplied(self):
        """No stale or applied jobs → no archive section."""
        jobs = [make_scored_job("j1", score=70, days_ago=1)]
        html = _build_jobs_tab(jobs, "test run")
        assert "archiveToggleBtn" not in html

    def test_display_threshold_is_55(self):
        """Score 54 → Maybe. Score 55 → Action queue."""
        jobs = [
            make_scored_job("j_54", score=54, days_ago=1),
            make_scored_job("j_55", score=55, days_ago=1),
        ]
        html = _build_jobs_tab(jobs, "test run")
        # Maybe section should exist (for j_54)
        assert "maybeToggleBtn" in html
        # Action queue should have j_55
        assert "Action queue" in html

    def test_applied_job_moves_to_archive(self):
        """A job with a CRM match (applied) should move to archive regardless of score/age."""
        jobs = [make_scored_job("j1", score=85, days_ago=1,
                                company="Uplight", title="Senior Product Manager")]
        crm = {
            "applications": [{
                "company": "Uplight",
                "job_title": "Senior Product Manager",
                "status": "applied",
                "status_label": "Applied",
                "job_url": "https://example.com",
                "applied_date": "2026-07-01",
                "last_activity": "2026-07-01",
                "follow_up_date": "",
                "recommended_action": "",
                "notes": "",
            }]
        }
        html = _build_jobs_tab(jobs, "test run", crm=crm)
        assert "archiveToggleBtn" in html

    def test_empty_jobs_list_shows_empty_state(self):
        """No jobs → empty state message."""
        html = _build_jobs_tab([], "test run")
        assert "No new unapplied jobs" in html

    def test_action_count_badge_reflects_action_queue_size(self):
        """The count badge should show the number of action queue jobs."""
        jobs = [
            make_scored_job("j1", score=75, days_ago=1),
            make_scored_job("j2", score=80, days_ago=1),
            make_scored_job("j3", score=45, days_ago=1),  # maybe
        ]
        html = _build_jobs_tab(jobs, "test run")
        assert "2 jobs in queue" in html


# ---------------------------------------------------------------------------
# Performance tab
# ---------------------------------------------------------------------------

class TestPerformanceTab:

    def make_rejected(self, job_id, rtype, score=None, company="Acme", title="PM"):
        return {
            "id": job_id,
            "title": title,
            "company": company,
            "url": f"https://example.com/{job_id}",
            "location": "Remote",
            "salary_text": "",
            "source": "test",
            "rejection_type": rtype,
            "rejection_reason": f"Test reason for {rtype}",
            "score": score,
            "first_analyzed": "2026-07-01T09:00:00",
            "last_analyzed": "2026-07-01T09:00:00",
        }

    def test_empty_state_when_no_data(self, tmp_path):
        """No rejected_jobs.json → show empty state message."""
        html = _build_performance_tab(str(tmp_path / "nonexistent.json"))
        assert "No pipeline data yet" in html

    def test_shows_total_stat(self, tmp_path):
        rejected = [
            self.make_rejected("j1", "pre_filter"),
            self.make_rejected("j2", "low_score", score=40),
            self.make_rejected("j3", "pre_filter"),
        ]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "3" in html   # total count appears

    def test_shows_pre_filter_count(self, tmp_path):
        rejected = [
            self.make_rejected("j1", "pre_filter"),
            self.make_rejected("j2", "pre_filter"),
            self.make_rejected("j3", "low_score", score=35),
        ]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "Pre-filter (2)" in html
        assert "Low Score (1)" in html

    def test_pre_filter_badge_present(self, tmp_path):
        rejected = [self.make_rejected("j1", "pre_filter")]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "Pre-filter" in html

    def test_low_score_badge_present(self, tmp_path):
        rejected = [self.make_rejected("j1", "low_score", score=42)]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "Low score" in html

    def test_score_displayed_for_low_score_entry(self, tmp_path):
        rejected = [self.make_rejected("j1", "low_score", score=38)]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "38" in html

    def test_score_dash_for_pre_filter_entry(self, tmp_path):
        """Pre-filter jobs never got scored, score cell should show '—'."""
        rejected = [self.make_rejected("j1", "pre_filter")]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "—" in html

    def test_unique_companies_count(self, tmp_path):
        rejected = [
            self.make_rejected("j1", "pre_filter", company="Acme"),
            self.make_rejected("j2", "pre_filter", company="Acme"),
            self.make_rejected("j3", "low_score", score=30, company="Beta"),
        ]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        # 2 unique companies
        assert "2" in html

    def test_filter_buttons_present(self, tmp_path):
        rejected = [self.make_rejected("j1", "pre_filter")]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "filterPerf" in html
        assert "perfSearch" in html

    def test_company_name_in_table(self, tmp_path):
        rejected = [self.make_rejected("j1", "pre_filter", company="SuperGrid Inc")]
        rejected_file = tmp_path / "rejected_jobs.json"
        rejected_file.write_text(json.dumps(rejected))

        html = _build_performance_tab(str(rejected_file))
        assert "SuperGrid Inc" in html


# ---------------------------------------------------------------------------
# generate_dashboard — smoke test with all sections
# ---------------------------------------------------------------------------

class TestGenerateDashboard:

    def test_generates_without_error(self, tmp_path):
        jobs = [
            make_scored_job("j1", score=80, days_ago=1),
            make_scored_job("j2", score=48, days_ago=2),  # maybe
            make_scored_job("j3", score=70, days_ago=10), # archive
        ]
        output = tmp_path / "dashboard.html"
        result = generate_dashboard(jobs, crm={}, output_path=str(output))
        assert output.exists()
        content = output.read_text()
        assert "Job Agent" in content
        assert "Action queue" in content
        assert "Maybe" in content
        assert "Archive" in content

    def test_tab_buttons_present(self, tmp_path):
        jobs = [make_scored_job("j1", score=75, days_ago=1)]
        output = tmp_path / "dashboard.html"
        generate_dashboard(jobs, crm={}, output_path=str(output))
        content = output.read_text()
        assert "Job Results" in content
        assert "Application CRM" in content
        assert "Market Intel" in content
        assert "Performance" in content

    def test_job_count_in_tab_label(self, tmp_path):
        jobs = [
            make_scored_job("j1", score=75, days_ago=1),
            make_scored_job("j2", score=80, days_ago=1),
        ]
        output = tmp_path / "dashboard.html"
        generate_dashboard(jobs, crm={}, output_path=str(output))
        content = output.read_text()
        assert "Job Results (2)" in content
