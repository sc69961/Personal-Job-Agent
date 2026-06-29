"""
test_scraper.py — Tests for ATS detection, PM role matching, and URL deduplication.
Run with: pytest tests/test_scraper.py -v
No network calls made.
"""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.scraper import _is_pm_role, _detect_ats


# ---------------------------------------------------------------------------
# _is_pm_role — what counts as a PM role
# ---------------------------------------------------------------------------

class TestIsPmRole:

    # Should match
    def test_senior_product_manager(self):
        assert _is_pm_role("Senior Product Manager") is True

    def test_staff_product_manager(self):
        assert _is_pm_role("Staff Product Manager") is True

    def test_principal_pm(self):
        assert _is_pm_role("Principal PM") is True

    def test_group_product_manager(self):
        assert _is_pm_role("Group Product Manager") is True

    def test_director_of_product(self):
        assert _is_pm_role("Director of Product Management") is True

    def test_head_of_product(self):
        assert _is_pm_role("Head of Product") is True

    def test_vp_of_product(self):
        assert _is_pm_role("VP of Product") is True

    def test_product_lead(self):
        assert _is_pm_role("Product Lead") is True

    def test_product_owner(self):
        assert _is_pm_role("Product Owner") is True

    def test_case_insensitive(self):
        assert _is_pm_role("SENIOR PRODUCT MANAGER") is True
        assert _is_pm_role("senior product manager") is True

    # Should NOT match
    def test_program_manager_excluded(self):
        """Program Manager ≠ Product Manager — critical distinction."""
        assert _is_pm_role("Program Manager") is False

    def test_project_manager_excluded(self):
        assert _is_pm_role("Project Manager") is False

    def test_product_marketing_manager_excluded(self):
        """PMM is not a PM role."""
        assert _is_pm_role("Product Marketing Manager") is False

    def test_product_analyst_excluded(self):
        assert _is_pm_role("Product Analyst") is False

    def test_product_designer_excluded(self):
        assert _is_pm_role("Product Designer") is False

    def test_software_engineer_excluded(self):
        assert _is_pm_role("Software Engineer") is False

    def test_data_scientist_excluded(self):
        assert _is_pm_role("Data Scientist") is False

    def test_empty_string_excluded(self):
        assert _is_pm_role("") is False


# ---------------------------------------------------------------------------
# _detect_ats — URL → (ats_type, slug)
# ---------------------------------------------------------------------------

class TestDetectAts:

    def test_greenhouse_boards_url(self):
        ats, slug = _detect_ats("https://boards.greenhouse.io/acmecorp")
        assert ats == "greenhouse"
        assert slug == "acmecorp"

    def test_greenhouse_job_boards_url(self):
        ats, slug = _detect_ats("https://job-boards.greenhouse.io/uplight")
        assert ats == "greenhouse"
        assert slug == "uplight"

    def test_lever_url(self):
        ats, slug = _detect_ats("https://jobs.lever.co/omnidian")
        assert ats == "lever"
        assert slug == "omnidian"

    def test_workable_url(self):
        ats, slug = _detect_ats("https://apply.workable.com/leapfrog-power-inc/")
        assert ats == "workable"
        assert slug == "leapfrog-power-inc"

    def test_bamboohr_url(self):
        ats, slug = _detect_ats("https://boxpower.bamboohr.com/careers")
        assert ats == "bamboohr"
        assert slug == "boxpower"

    def test_workday_url(self):
        ats, slug = _detect_ats("https://bloomenergy.wd1.myworkdayjobs.com/BloomEnergyCareers")
        assert ats == "workday"
        assert "bloomenergy" in slug.lower()

    def test_ashby_url(self):
        ats, slug = _detect_ats("https://jobs.ashbyhq.com/davidenergy")
        assert ats == "ashby"
        assert slug == "davidenergy"

    def test_rippling_url(self):
        ats, slug = _detect_ats("https://ats.rippling.com/rhythm-energy/jobs")
        assert ats == "rippling"
        assert slug == "rhythm-energy"

    def test_plain_html_url(self):
        ats, slug = _detect_ats("https://www.weavegrid.com/careers/job-openings")
        assert ats == "html"
        assert "weavegrid" in slug

    def test_returns_tuple(self):
        result = _detect_ats("https://boards.greenhouse.io/test")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# URL deduplication (logic extracted from main.py)
# ---------------------------------------------------------------------------

class TestUrlDeduplication:

    def _dedup(self, jobs: list) -> list:
        """Replicate the URL dedup logic from main.py."""
        seen_urls = set()
        deduped = []
        for job in jobs:
            url = job.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            deduped.append(job)
        return deduped

    def test_removes_duplicate_urls(self):
        jobs = [
            {"id": "a", "url": "https://hopper.com/pm-flight", "title": "PM"},
            {"id": "b", "url": "https://hopper.com/pm-flight", "title": "PM"},
            {"id": "c", "url": "https://hopper.com/pm-flight", "title": "PM"},
        ]
        result = self._dedup(jobs)
        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_keeps_unique_urls(self):
        jobs = [
            {"id": "a", "url": "https://uplight.com/job/1", "title": "PM"},
            {"id": "b", "url": "https://voltus.com/job/2", "title": "PM"},
            {"id": "c", "url": "https://enode.com/job/3", "title": "PM"},
        ]
        result = self._dedup(jobs)
        assert len(result) == 3

    def test_keeps_jobs_without_url(self):
        """Jobs with no URL should pass through (can't dedup what we can't identify)."""
        jobs = [
            {"id": "a", "url": "", "title": "PM"},
            {"id": "b", "url": "", "title": "PM"},
        ]
        result = self._dedup(jobs)
        assert len(result) == 2

    def test_hopper_seven_duplicates_collapse_to_one(self):
        """Regression test for the 7x Hopper duplicate seen in production."""
        url = "https://hopper.com/careers/pm-flight-connectivity"
        jobs = [{"id": f"hop_{i}", "url": url, "title": "Senior PM - Flight"} for i in range(7)]
        result = self._dedup(jobs)
        assert len(result) == 1

    def test_mixed_duplicates_and_uniques(self):
        jobs = [
            {"id": "a", "url": "https://uplight.com/job/1", "title": "PM"},
            {"id": "b", "url": "https://hopper.com/job/dup", "title": "PM"},
            {"id": "c", "url": "https://hopper.com/job/dup", "title": "PM"},
            {"id": "d", "url": "https://voltus.com/job/2", "title": "PM"},
        ]
        result = self._dedup(jobs)
        assert len(result) == 3
        ids = [j["id"] for j in result]
        assert "c" not in ids
