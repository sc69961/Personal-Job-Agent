"""
test_scorer.py — Tests for pre_filter, scoring prompt, and cache logic.
Run with: pytest tests/test_scorer.py -v
No API keys needed — all Claude calls are mocked.
"""

import json
import sys
import os
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.scorer import pre_filter, build_scoring_prompt, _load_score_cache, score_job, score_all_jobs


# ---------------------------------------------------------------------------
# Shared config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return {
        "SALARY_FLOOR": 130_000,
        "ALLOWED_LOCATIONS": ["Denver", "Boulder", "Colorado", "Remote"],
        "PREFERRED_TITLES": ["Senior Product Manager", "Staff PM", "Director of Product"],
        "HIGH_SIGNAL_KEYWORDS": ["DER", "VPP", "DERMS", "grid", "demand response"],
        "NEGATIVE_KEYWORDS": ["healthcare", "pharma", "mining"],
        "ALL_TARGET_COMPANIES": ["Uplight", "Voltus", "WeaveGrid", "Enode", "Leap Energy"],
        "RESUME_TEXT": "Steve Christian, Senior PM, Denver CO. DER/VPP experience.",
        "ANTHROPIC_API_KEY": "test-key",
        "MIN_SCORE_TO_INCLUDE": 55,
        "TOP_N_FOR_EMAIL": 10,
    }


def make_job(**kwargs):
    """Build a minimal job dict for testing."""
    defaults = {
        "id": "test_001",
        "title": "Senior Product Manager",
        "company": "Uplight",
        "location": "Remote",
        "description": "Lead product strategy for our DER platform.",
        "salary_text": "$170,000 - $210,000",
        "url": "https://example.com/job",
        "source": "company_site",
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# pre_filter — junior/APM signals
# ---------------------------------------------------------------------------

class TestPreFilterJunior:

    def test_filters_junior_title(self, config):
        job = make_job(title="Junior Product Manager")
        ok, reason = pre_filter(job, config)
        assert not ok
        assert "junior" in reason.lower()

    def test_filters_apm_title(self, config):
        job = make_job(title="Associate Product Manager")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_intern_title(self, config):
        job = make_job(title="Product Manager Intern")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_entry_level(self, config):
        job = make_job(title="Entry-Level Product Manager")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_passes_senior_pm(self, config):
        job = make_job(title="Senior Product Manager")
        ok, reason = pre_filter(job, config)
        assert ok, f"Should pass but got: {reason}"

    def test_passes_staff_pm(self, config):
        job = make_job(title="Staff Product Manager")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_director(self, config):
        job = make_job(title="Director of Product Management")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_head_of_product(self, config):
        job = make_job(title="Head of Product")
        ok, reason = pre_filter(job, config)
        assert ok


# ---------------------------------------------------------------------------
# pre_filter — location / onsite signals
# ---------------------------------------------------------------------------

class TestPreFilterLocation:

    # --- International filter ---

    def test_filters_madrid_spain(self, config):
        job = make_job(title="Senior Product Manager", description="", location="Madrid, Spain")
        ok, reason = pre_filter(job, config)
        assert not ok
        assert "international" in reason

    def test_filters_london_uk(self, config):
        job = make_job(title="Senior Product Manager", description="", location="London, UK")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_toronto_canada(self, config):
        job = make_job(title="Senior Product Manager", description="", location="Toronto, Canada")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_india(self, config):
        job = make_job(title="Senior Product Manager", description="", location="Bangalore, India")
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_emea(self, config):
        job = make_job(title="Senior Product Manager", description="", location="EMEA")
        ok, reason = pre_filter(job, config)
        assert not ok

    # --- On-site non-Denver US filter ---

    def test_filters_onsite_new_york(self, config):
        job = make_job(
            title="Senior Product Manager",
            description="In-office only.",
            location="New York, NY",
        )
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_filters_onsite_san_francisco(self, config):
        job = make_job(
            title="Senior Product Manager",
            description="Join our SF team.",
            location="San Francisco, CA",
        )
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_passes_onsite_denver(self, config):
        job = make_job(
            title="Senior Product Manager",
            description="Must be located in Denver.",
            location="Denver, CO",
        )
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_onsite_boulder(self, config):
        job = make_job(title="Senior Product Manager", description="", location="Boulder, CO")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_onsite_colorado_generic(self, config):
        job = make_job(title="Senior Product Manager", description="", location="Colorado")
        ok, reason = pre_filter(job, config)
        assert ok

    # --- Remote passes regardless of listed city ---

    def test_passes_remote(self, config):
        job = make_job(
            title="Senior Product Manager",
            description="Fully remote position.",
            location="Remote",
        )
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_hybrid_non_denver_city(self, config):
        """Hybrid role listing a non-Denver city should still pass — it's location-flexible."""
        job = make_job(
            title="Senior Product Manager",
            description="Hybrid — 2 days/week in office.",
            location="Chicago, IL",
        )
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_usa_generic_location(self, config):
        """'United States' with no city → nationwide role, pass through."""
        job = make_job(title="Senior Product Manager", description="", location="United States")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_blank_location(self, config):
        """No location info at all → can't filter, pass through."""
        job = make_job(title="Senior Product Manager", description="Great DER PM role.", location="")
        ok, reason = pre_filter(job, config)
        assert ok

    # --- Regression: international-remote jobs that slipped through ---

    def test_filters_remote_madrid_in_description(self, config):
        """Regression: Ashby returns isRemote=True for a Madrid role → location='Remote'.
        The description reveals it's Spain-based; should be filtered."""
        job = make_job(
            title="Senior Product Manager",
            location="Remote",
            description="This is a remote role based out of our Madrid, Spain office.",
        )
        ok, reason = pre_filter(job, config)
        assert not ok, "Madrid remote role should be filtered"

    def test_filters_remote_london_in_description(self, config):
        """Remote (London) should be caught via description scan."""
        job = make_job(
            title="Senior Product Manager",
            location="Remote",
            description="Remote role — must be based in London, UK.",
        )
        ok, reason = pre_filter(job, config)
        assert not ok

    def test_passes_remote_us_even_if_description_mentions_europe(self, config):
        """A US remote role that mentions European partners should NOT be filtered."""
        job = make_job(
            title="Senior Product Manager",
            location="Remote",
            description="Remote anywhere in the US. We work with clients in London and Spain.",
        )
        ok, reason = pre_filter(job, config)
        assert ok, "US remote role mentioning European clients should pass"

    def test_passes_blank_location_no_international_in_desc(self, config):
        """Blank location + no international signals in description → pass through."""
        job = make_job(
            title="Senior Product Manager",
            location="",
            description="Lead our DER platform team. We are based in Colorado.",
        )
        ok, reason = pre_filter(job, config)
        assert ok


# ---------------------------------------------------------------------------
# pre_filter — salary floor
# ---------------------------------------------------------------------------

class TestPreFilterSalary:

    def test_filters_clearly_below_floor(self, config):
        # Floor is $130K, 70% of that is $91K — $80K clearly below
        job = make_job(salary_text="$70,000 - $80,000")
        ok, reason = pre_filter(job, config)
        assert not ok
        assert "salary" in reason.lower()

    def test_passes_above_floor(self, config):
        job = make_job(salary_text="$160,000 - $200,000")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_no_salary_listed(self, config):
        job = make_job(salary_text="")
        ok, reason = pre_filter(job, config)
        assert ok

    def test_passes_borderline_salary(self, config):
        # $100K is above 70% of $130K floor ($91K), so should pass
        job = make_job(salary_text="$95,000 - $110,000")
        ok, reason = pre_filter(job, config)
        assert ok


# ---------------------------------------------------------------------------
# build_scoring_prompt — structure and content
# ---------------------------------------------------------------------------

class TestBuildScoringPrompt:

    def test_contains_resume(self, config):
        # scorer uses CONDENSED_RESUME (a hardcoded constant), not the passed resume arg.
        # Verify the candidate's name and key details appear in the prompt.
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Steve Christian" in prompt
        assert "DER" in prompt

    def test_contains_job_title(self, config):
        job = make_job(title="Staff Product Manager")
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Staff Product Manager" in prompt

    def test_contains_company_name(self, config):
        job = make_job(company="WeaveGrid")
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "WeaveGrid" in prompt

    def test_contains_positive_signals(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "POSITIVE SIGNALS" in prompt

    def test_contains_negative_signals(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "NEGATIVE SIGNALS" in prompt

    def test_contains_wrong_function_penalty(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Wrong function in energy" in prompt

    def test_contains_scientific_domain_penalty(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "scientific" in prompt.lower() or "domain expertise" in prompt.lower()

    def test_contains_json_schema(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert '"score"' in prompt
        assert '"apply_recommendation"' in prompt

    def test_crm_signal_included_when_provided(self, config):
        job = make_job(company="Uplight")
        prompt = build_scoring_prompt(
            job, config["RESUME_TEXT"], config,
            positive_outcome_companies=["Uplight", "WeaveGrid"]
        )
        assert "Uplight" in prompt
        assert "WeaveGrid" in prompt

    def test_crm_signal_empty_when_none(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "no interview/offer outcomes" in prompt.lower() or "CRM FEEDBACK" in prompt

    def test_target_company_list_included(self, config):
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        # At least one target company should appear in the prompt
        assert any(co in prompt for co in config["ALL_TARGET_COMPANIES"])

    def test_salary_prompt_uses_structured_field(self, config):
        """Salary is now extracted into salary_text by the scraper and echoed by Claude
        from the structured 'Salary info' field — not fished from raw description text."""
        job = make_job(salary_text="$120,000–$135,000 / year")
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        # The structured salary value must appear in the prompt
        assert "$120,000" in prompt or "120,000" in prompt

    def test_salary_prompt_says_use_structured_field(self, config):
        """The salary prompt must direct Claude to use the structured salary info field."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Salary info" in prompt  # the structured field label must be referenced


# ---------------------------------------------------------------------------
# Score cache loading
# ---------------------------------------------------------------------------

class TestLoadScoreCache:

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = _load_score_cache(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_loads_and_keys_by_id(self, tmp_path):
        jobs = [
            {"id": "abc123", "score": 75, "title": "Senior PM", "company": "Uplight"},
            {"id": "def456", "score": 60, "title": "Staff PM", "company": "Voltus"},
        ]
        cache_file = tmp_path / "scored.json"
        cache_file.write_text(json.dumps(jobs))

        result = _load_score_cache(str(cache_file))
        assert "abc123" in result
        assert "def456" in result
        assert result["abc123"]["score"] == 75

    def test_excludes_jobs_with_null_score(self, tmp_path):
        jobs = [
            {"id": "abc123", "score": 75, "title": "Senior PM", "company": "Uplight"},
            {"id": "no_score", "score": None, "title": "PM", "company": "Other"},
        ]
        cache_file = tmp_path / "scored.json"
        cache_file.write_text(json.dumps(jobs))

        result = _load_score_cache(str(cache_file))
        assert "abc123" in result
        assert "no_score" not in result

    def test_returns_empty_on_corrupt_file(self, tmp_path):
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("{ this is not valid json }")
        result = _load_score_cache(str(cache_file))
        assert result == {}


# ---------------------------------------------------------------------------
# score_job — with mocked Claude client
# ---------------------------------------------------------------------------

class TestScoreJob:

    def _mock_client(self, response_json: dict):
        """Build a mock Anthropic client that returns the given dict as JSON."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_json))]
        client = MagicMock()
        client.messages.create.return_value = mock_response
        return client

    def test_scores_job_correctly(self, config):
        claude_response = {
            "score": 82, "confidence": 85, "title_match": "strong",
            "location_ok": True, "salary_ok": True,
            "company_tier": "climatetech", "is_target_company": True,
            "seniority_ok": True, "top_strengths": ["DER expertise", "0->1 experience"],
            "top_gaps": [], "top_reasons": ["Strong energy background"],
            "match_summary": "Excellent fit for this DER platform role.",
            "apply_recommendation": "strong yes", "work_type": "remote",
            "salary_estimate": "$170K-$210K", "short_description": "DER platform PM role."
        }
        client = self._mock_client(claude_response)
        job = make_job()
        result = score_job(job, config, client)

        assert result["score"] == 82
        assert result["apply_recommendation"] == "strong yes"
        assert result["company_tier"] == "climatetech"

    def test_stamps_first_seen_on_new_job(self, config):
        claude_response = {
            "score": 70, "confidence": 75, "title_match": "good",
            "location_ok": True, "salary_ok": True,
            "company_tier": "climatetech", "is_target_company": True,
            "seniority_ok": True, "top_strengths": [], "top_gaps": [],
            "top_reasons": [], "match_summary": "Good fit.",
            "apply_recommendation": "yes", "work_type": "remote",
            "salary_estimate": "$180K", "short_description": "PM role."
        }
        client = self._mock_client(claude_response)
        job = make_job()
        assert "first_seen" not in job or job.get("first_seen") is None

        result = score_job(job, config, client)
        # first_seen is now a full ISO timestamp — check it starts with today's date
        today = datetime.now().strftime("%Y-%m-%d")
        assert result["first_seen"].startswith(today), f"first_seen={result['first_seen']!r} should start with {today}"

    def test_preserves_existing_first_seen(self, config):
        claude_response = {
            "score": 70, "confidence": 75, "title_match": "good",
            "location_ok": True, "salary_ok": True,
            "company_tier": "climatetech", "is_target_company": True,
            "seniority_ok": True, "top_strengths": [], "top_gaps": [],
            "top_reasons": [], "match_summary": "Good fit.",
            "apply_recommendation": "yes", "work_type": "remote",
            "salary_estimate": "$180K", "short_description": "PM role."
        }
        client = self._mock_client(claude_response)
        job = make_job(first_seen="2026-06-01")
        result = score_job(job, config, client)
        assert result["first_seen"] == "2026-06-01"

    def test_falls_back_gracefully_on_malformed_json(self, config):
        """If Claude returns garbage, job should get score=0 not crash."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="sorry, I can't score that right now")]
        client = MagicMock()
        client.messages.create.return_value = mock_response

        job = make_job()
        result = score_job(job, config, client)
        assert result["score"] == 0
        assert result["apply_recommendation"] == "maybe"

    def test_falls_back_gracefully_on_api_exception(self, config):
        """If Claude API raises an exception, job should get score=0 not crash."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("API timeout")

        job = make_job()
        result = score_job(job, config, client)
        assert result["score"] == 0

    def test_scoring_error_flag_set_on_bad_json(self, config):
        """Malformed JSON response → scoring_error=True so it's not confused with a real 0."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="sorry, cannot score")]
        client = MagicMock()
        client.messages.create.return_value = mock_response

        result = score_job(make_job(), config, client)
        assert result.get("scoring_error") is True

    def test_scoring_error_flag_set_on_api_exception(self, config):
        """API exception → scoring_error=True."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("connection reset")

        result = score_job(make_job(), config, client)
        assert result.get("scoring_error") is True

    def test_scoring_error_detail_contains_error_message(self, config):
        """scoring_error_detail should capture the actual error string for the performance log."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("API timeout after 30s")

        result = score_job(make_job(), config, client)
        assert "API timeout after 30s" in result.get("scoring_error_detail", "")

    def test_no_scoring_error_flag_on_success(self, config):
        """A successful score must NOT have scoring_error set."""
        claude_response = {
            "score": 75, "confidence": 80, "title_match": "strong",
            "location_ok": True, "salary_ok": True,
            "company_tier": "climatetech", "is_target_company": True,
            "seniority_ok": True, "top_strengths": [], "top_gaps": [],
            "top_reasons": [], "match_summary": "Good fit.",
            "apply_recommendation": "yes", "work_type": "remote",
            "salary_estimate": "$170K", "short_description": "PM role.",
        }
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(claude_response))]
        client = MagicMock()
        client.messages.create.return_value = mock_response

        result = score_job(make_job(), config, client)
        assert not result.get("scoring_error")


# ---------------------------------------------------------------------------
# score_all_jobs — scoring_error routing
# ---------------------------------------------------------------------------

class TestScoringErrorRouting:

    def test_scoring_error_job_excluded_from_results(self, config, tmp_path):
        """A job that errors should not appear in score_all_jobs results."""
        cache_file    = tmp_path / "scored.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        client = MagicMock()
        client.messages.create.side_effect = Exception("timeout")

        with patch("scripts.scorer.Anthropic", return_value=client):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    results = score_all_jobs(
                        [make_job(id="j1")], config, min_score=40,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        assert len(results) == 0

    def test_scoring_error_written_to_rejected_file(self, config, tmp_path):
        """A scoring error should appear in rejected_jobs.json with type='scoring_error'."""
        cache_file    = tmp_path / "scored.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        client = MagicMock()
        client.messages.create.side_effect = Exception("rate limit")

        with patch("scripts.scorer.Anthropic", return_value=client):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(
                        [make_job(id="j1")], config, min_score=40,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        rejected = json.loads(rejected_file.read_text())
        assert len(rejected) == 1
        entry = rejected[0]
        assert entry["rejection_type"] == "scoring_error"
        assert "rate limit" in entry["rejection_reason"]

    def test_scoring_error_not_in_low_score_bucket(self, config, tmp_path):
        """Scoring errors must not be double-counted as low_score entries."""
        cache_file    = tmp_path / "scored.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        client = MagicMock()
        client.messages.create.side_effect = Exception("timeout")

        with patch("scripts.scorer.Anthropic", return_value=client):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(
                        [make_job(id="j1")], config, min_score=40,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        rejected = json.loads(rejected_file.read_text())
        assert all(r["rejection_type"] != "low_score" for r in rejected)

    def test_scoring_error_score_is_none_in_rejected_log(self, config, tmp_path):
        """Scoring errors have no meaningful score — it should be stored as None."""
        cache_file    = tmp_path / "scored.json"
        rejected_file = tmp_path / "rejected_jobs.json"

        client = MagicMock()
        client.messages.create.side_effect = Exception("503")

        with patch("scripts.scorer.Anthropic", return_value=client):
            with patch("scripts.scorer._load_first_seen_registry", return_value={}):
                with patch("scripts.scorer._save_first_seen_registry"):
                    score_all_jobs(
                        [make_job(id="j1")], config, min_score=40,
                        cache_path=str(cache_file),
                        rejected_path=str(rejected_file),
                    )

        rejected = json.loads(rejected_file.read_text())
        assert rejected[0]["score"] is None


# ---------------------------------------------------------------------------
# score_all_jobs — caching and deduplication
# ---------------------------------------------------------------------------

class TestScoreAllJobs:

    def test_uses_cache_for_already_scored_jobs(self, config, tmp_path):
        """Jobs already in the cache should not trigger a new Claude call."""
        cached_job = {
            "id": "job_001", "score": 78, "title": "Senior PM",
            "company": "Uplight", "first_seen": "2026-06-01"
        }
        cache_file = tmp_path / "scored.json"
        cache_file.write_text(json.dumps([cached_job]))

        jobs = [make_job(id="job_001")]
        config["MIN_SCORE_TO_INCLUDE"] = 55

        mock_client = MagicMock()
        with patch("scripts.scorer.Anthropic", return_value=mock_client):
            results = score_all_jobs(
                jobs, config, min_score=55, cache_path=str(cache_file)
            )

        # Claude should never have been called
        mock_client.messages.create.assert_not_called()
        assert len(results) == 1
        assert results[0]["score"] == 78

    def test_filters_below_min_score(self, config, tmp_path):
        """Jobs scoring below min_score should be excluded from results."""
        cache_file = tmp_path / "scored.json"

        claude_response = {
            "score": 40, "confidence": 60, "title_match": "weak",
            "location_ok": True, "salary_ok": True,
            "company_tier": "other", "is_target_company": False,
            "seniority_ok": True, "top_strengths": [], "top_gaps": ["Poor fit"],
            "top_reasons": [], "match_summary": "Not a great match.",
            "apply_recommendation": "no", "work_type": "remote",
            "salary_estimate": "$120K", "short_description": "Unrelated role."
        }
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(claude_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        jobs = [make_job(id="new_job")]
        with patch("scripts.scorer.Anthropic", return_value=mock_client):
            results = score_all_jobs(
                jobs, config, min_score=55, cache_path=str(cache_file)
            )

        assert len(results) == 0

    def test_results_sorted_by_score_descending(self, config, tmp_path):
        """Results should come back sorted highest score first."""
        cached_jobs = [
            {"id": "job_a", "score": 65, "title": "PM A", "company": "Co A", "first_seen": "2026-06-01"},
            {"id": "job_b", "score": 88, "title": "PM B", "company": "Co B", "first_seen": "2026-06-01"},
            {"id": "job_c", "score": 72, "title": "PM C", "company": "Co C", "first_seen": "2026-06-01"},
        ]
        cache_file = tmp_path / "scored.json"
        cache_file.write_text(json.dumps(cached_jobs))

        jobs = [make_job(id=j["id"]) for j in cached_jobs]
        with patch("scripts.scorer.Anthropic", return_value=MagicMock()):
            results = score_all_jobs(
                jobs, config, min_score=55, cache_path=str(cache_file)
            )

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 88


# ---------------------------------------------------------------------------
# Scoring prompt — new signals added in recent sprint
# ---------------------------------------------------------------------------

class TestScoringPromptNewSignals:
    """Verify that scoring prompt changes from the recent sprint are present:
    - ESG / sustainability software signal (+8 pts) added
    - Large PM org penalty (-5 pts) removed
    - Adjacent domain (SaaS, data, IoT) explicitly gets 0 pts penalty
    - Expanded title list includes CPO, Head of Digital Products, Director of Innovation
    """

    def test_esg_signal_present_with_plus_8(self, config):
        """ESG / sustainability software should be a +8 positive signal."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "ESG" in prompt
        assert "sustainability software" in prompt
        assert "+8 pts" in prompt

    def test_esg_signal_mentions_carbon_accounting(self, config):
        """The ESG signal should name carbon accounting as an example."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "carbon accounting" in prompt

    def test_no_large_pm_org_penalty_in_prompt(self, config):
        """The large PM org / highly matrixed penalty (-5 pts) should be removed."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        # Should not contain any reference to the old penalty
        assert "Large PM organization" not in prompt
        assert "highly matrixed" not in prompt
        assert "limited strategic scope per PM" not in prompt

    def test_adjacent_domain_gets_zero_penalty(self, config):
        """Adjacent industries (enterprise SaaS, data platforms, IoT) should explicitly
        get 0 pts — not be grouped with penalised domains."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Adjacent domain" in prompt
        assert "0 pts" in prompt
        # Key adjacent industries should be listed
        assert "enterprise SaaS" in prompt
        assert "IoT" in prompt or "IoT/smart building" in prompt

    def test_domain_mismatch_still_penalises_healthcare_pharma(self, config):
        """Healthcare, pharma, telecom, mining, defense should still carry the domain penalty."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "healthcare" in prompt or "pharma" in prompt
        assert "Domain mismatch" in prompt or "domain mismatch" in prompt.lower()

    def test_title_list_includes_cpo(self, config):
        """Chief Product Officer should be in the title match list."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Chief Product Officer" in prompt

    def test_title_list_includes_head_of_digital_products(self, config):
        """Head of Digital Products should be in the title match list."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Head of Digital Products" in prompt

    def test_title_list_includes_director_of_innovation(self, config):
        """Director of Innovation should be in the title match list."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "Director of Innovation" in prompt

    def test_iot_smart_building_positive_signal_present(self, config):
        """IoT / smart building software should appear as a positive signal."""
        job = make_job()
        prompt = build_scoring_prompt(job, config["RESUME_TEXT"], config)
        assert "IoT" in prompt
        assert "smart building" in prompt
