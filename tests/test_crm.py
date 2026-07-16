"""
test_crm.py — Tests for CRM logic: normalization, status priority, ghosting, dedup.
Run with: pytest tests/test_crm.py -v
No API keys or Gmail access needed.
"""

import sys
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.gmail_crm import (
    _normalize_company,
    _app_id,
    _should_upgrade_status,
    _find_existing_by_company,
    _extract_sender_domains,
    _build_domain_map,
    _find_existing_by_domain,
    _analyze_thread,
    _GENERIC_DOMAINS,
    STATUS_PRIORITY,
    GHOST_AFTER_DAYS,
)


# ---------------------------------------------------------------------------
# _normalize_company
# ---------------------------------------------------------------------------

class TestNormalizeCompany:

    def test_strips_inc(self):
        assert _normalize_company("Voltus Inc.") == "voltus"
        assert _normalize_company("Voltus Inc") == "voltus"

    def test_strips_llc(self):
        assert _normalize_company("BoxPower LLC") == "boxpower"

    def test_strips_corp(self):
        assert _normalize_company("Acme Corp.") == "acme"

    def test_strips_ltd(self):
        assert _normalize_company("GridX Ltd") == "gridx"

    def test_strips_co(self):
        assert _normalize_company("Amperon Co.") == "amperon"

    def test_handles_plain_name(self):
        assert _normalize_company("WeaveGrid") == "weavegrid"

    def test_lowercases(self):
        assert _normalize_company("EnergyHub") == "energyhub"

    def test_handles_punctuation(self):
        assert _normalize_company("Landis+Gyr") == "landis gyr"

    def test_handles_empty_string(self):
        assert _normalize_company("") == ""

    def test_voltus_variants_match(self):
        """Core dedup requirement: Voltus and Voltus Inc. must normalize to the same thing."""
        assert _normalize_company("Voltus") == _normalize_company("Voltus Inc.")
        assert _normalize_company("Voltus") == _normalize_company("Voltus, Inc.")

    def test_weavegrid_variants_match(self):
        assert _normalize_company("WeaveGrid") == _normalize_company("WeaveGrid Inc.")

    def test_boxpower_with_suffix_matches(self):
        # "BoxPower LLC" should normalize to same as "BoxPower" — suffix stripping works.
        # Note: "Box Power" (two words) vs "BoxPower" (one word) are genuinely different
        # strings; the normalizer can't reconcile camelCase splitting without a whitelist.
        assert _normalize_company("BoxPower LLC") == _normalize_company("BoxPower")


# ---------------------------------------------------------------------------
# _app_id — stable, normalized ID generation
# ---------------------------------------------------------------------------

class TestAppId:

    def test_same_company_same_title_same_id(self):
        assert _app_id("Voltus", "Product Manager") == _app_id("Voltus", "Product Manager")

    def test_normalized_company_same_id(self):
        """Voltus and Voltus Inc. must produce the same ID for the same role."""
        assert _app_id("Voltus", "Product Manager") == _app_id("Voltus Inc.", "Product Manager")

    def test_different_company_different_id(self):
        assert _app_id("Voltus", "Product Manager") != _app_id("Uplight", "Product Manager")

    def test_different_title_different_id(self):
        assert _app_id("Voltus", "Product Manager") != _app_id("Voltus", "Senior Product Manager")

    def test_id_is_deterministic(self):
        id1 = _app_id("WeaveGrid Inc.", "Senior Product Manager")
        id2 = _app_id("WeaveGrid Inc.", "Senior Product Manager")
        assert id1 == id2

    def test_id_length(self):
        """ID should be 10 hex chars."""
        result = _app_id("Uplight", "Staff PM")
        assert len(result) == 10


# ---------------------------------------------------------------------------
# _should_upgrade_status
# ---------------------------------------------------------------------------

class TestShouldUpgradeStatus:

    def test_applied_to_interview_upgrades(self):
        assert _should_upgrade_status("applied", "interview_requested") is True

    def test_applied_to_offer_upgrades(self):
        assert _should_upgrade_status("applied", "offer") is True

    def test_interview_to_offer_upgrades(self):
        assert _should_upgrade_status("interview_requested", "offer") is True

    def test_offer_to_applied_does_not_downgrade(self):
        """This is the critical regression: a new "applied" thread must not wipe an offer."""
        assert _should_upgrade_status("offer", "applied") is False

    def test_interview_to_applied_does_not_downgrade(self):
        assert _should_upgrade_status("interview_requested", "applied") is False

    def test_offer_to_response_received_does_not_downgrade(self):
        assert _should_upgrade_status("offer", "response_received") is False

    def test_same_status_does_not_upgrade(self):
        assert _should_upgrade_status("applied", "applied") is False
        assert _should_upgrade_status("interview_requested", "interview_requested") is False

    def test_applied_to_rejected_upgrades(self):
        """Rejected has higher priority than applied — status should update."""
        assert _should_upgrade_status("applied", "rejected") is True

    def test_applied_to_ghosted_upgrades(self):
        assert _should_upgrade_status("applied", "ghosted") is True


# ---------------------------------------------------------------------------
# STATUS_PRIORITY ordering
# ---------------------------------------------------------------------------

class TestStatusPriority:

    def test_applied_is_lowest(self):
        assert STATUS_PRIORITY.index("applied") == 0

    def test_interview_above_response(self):
        assert STATUS_PRIORITY.index("interview_requested") > STATUS_PRIORITY.index("response_received")

    def test_offer_above_interview(self):
        assert STATUS_PRIORITY.index("offer") > STATUS_PRIORITY.index("interview_requested")

    def test_ghosted_is_terminal(self):
        """Ghosted should be at the end — a ghost shouldn't be overwritten by a new applied."""
        assert STATUS_PRIORITY.index("ghosted") > STATUS_PRIORITY.index("applied")

    def test_all_expected_statuses_present(self):
        expected = {"applied", "response_received", "interview_requested", "offer", "withdrawn", "rejected", "ghosted"}
        assert expected.issubset(set(STATUS_PRIORITY))


# ---------------------------------------------------------------------------
# _find_existing_by_company — cross-thread matching
# ---------------------------------------------------------------------------

class TestFindExistingByCompany:

    def _make_app_by_id(self, apps: list) -> dict:
        return {a["id"]: a for a in apps}

    def test_finds_exact_match(self):
        apps = [{"id": "abc", "company": "Uplight", "status": "applied"}]
        result = _find_existing_by_company("Uplight", self._make_app_by_id(apps))
        assert result is not None
        assert result["id"] == "abc"

    def test_finds_normalized_match(self):
        """'Voltus Inc.' in DB should match incoming 'Voltus'."""
        apps = [{"id": "volt1", "company": "Voltus Inc.", "status": "interview_requested"}]
        result = _find_existing_by_company("Voltus", self._make_app_by_id(apps))
        assert result is not None
        assert result["id"] == "volt1"

    def test_returns_none_for_no_match(self):
        apps = [{"id": "abc", "company": "Uplight", "status": "applied"}]
        result = _find_existing_by_company("WeaveGrid", self._make_app_by_id(apps))
        assert result is None

    def test_returns_highest_priority_status_when_multiple(self):
        """If same company has two entries (shouldn't happen but defensive), prefer highest status."""
        apps = [
            {"id": "v1", "company": "Voltus", "status": "applied"},
            {"id": "v2", "company": "Voltus Inc.", "status": "interview_requested"},
        ]
        result = _find_existing_by_company("Voltus", self._make_app_by_id(apps))
        assert result is not None
        assert result["status"] == "interview_requested"

    def test_returns_none_for_empty_company(self):
        apps = [{"id": "abc", "company": "Uplight", "status": "applied"}]
        result = _find_existing_by_company("", self._make_app_by_id(apps))
        assert result is None


# ---------------------------------------------------------------------------
# Ghost detection logic
# (Tests the auto-ghost pass logic from sync_gmail_crm inline)
# ---------------------------------------------------------------------------

class TestGhostDetection:

    def _run_ghost_pass(self, apps: list) -> list:
        """Replicate the auto-ghost pass from sync_gmail_crm."""
        cutoff = (datetime.now() - timedelta(days=GHOST_AFTER_DAYS)).strftime("%Y-%m-%d")
        for app in apps:
            if app.get("status") == "applied":
                last = app.get("last_activity", "")
                if last and last < cutoff:
                    app["status"] = "ghosted"
                    app["status_label"] = "Ghosted"
        return apps

    def test_ghosts_stale_applied_entry(self):
        stale_date = (datetime.now() - timedelta(days=GHOST_AFTER_DAYS + 5)).strftime("%Y-%m-%d")
        apps = [{"id": "a1", "company": "Acme", "status": "applied", "last_activity": stale_date}]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "ghosted"

    def test_does_not_ghost_recent_applied(self):
        recent_date = (datetime.now() - timedelta(days=GHOST_AFTER_DAYS - 5)).strftime("%Y-%m-%d")
        apps = [{"id": "a1", "company": "Acme", "status": "applied", "last_activity": recent_date}]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "applied"

    def test_does_not_ghost_interview_entry(self):
        """Only 'applied' status should auto-ghost — not interviews in flight."""
        stale_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        apps = [{"id": "a1", "company": "Uplight", "status": "interview_requested", "last_activity": stale_date}]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "interview_requested"

    def test_does_not_ghost_offer(self):
        stale_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        apps = [{"id": "a1", "company": "Omnidian", "status": "offer", "last_activity": stale_date}]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "offer"

    def test_does_not_ghost_rejected(self):
        stale_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        apps = [{"id": "a1", "company": "Acme", "status": "rejected", "last_activity": stale_date}]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "rejected"

    def test_ghost_after_days_constant_is_sane(self):
        """Sanity check: the ghost threshold should be between 14 and 60 days."""
        assert 14 <= GHOST_AFTER_DAYS <= 60

    def test_ghosts_multiple_stale_entries(self):
        stale_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        apps = [
            {"id": "a1", "company": "Co A", "status": "applied", "last_activity": stale_date},
            {"id": "a2", "company": "Co B", "status": "applied", "last_activity": stale_date},
            {"id": "a3", "company": "Co C", "status": "interview_requested", "last_activity": stale_date},
        ]
        result = self._run_ghost_pass(apps)
        assert result[0]["status"] == "ghosted"
        assert result[1]["status"] == "ghosted"
        assert result[2]["status"] == "interview_requested"  # untouched


# ---------------------------------------------------------------------------
# _extract_sender_domains
# ---------------------------------------------------------------------------

def _make_msg(from_addr: str) -> dict:
    """Build a minimal Gmail message dict with a From header."""
    return {"payload": {"headers": [{"name": "From", "value": from_addr}]}}


class TestExtractSenderDomains:

    def test_extracts_domain_from_angle_bracket_format(self):
        msgs = [_make_msg("Alice Recruiter <alice@uplight.com>")]
        assert _extract_sender_domains(msgs) == {"uplight.com"}

    def test_extracts_domain_from_bare_email(self):
        msgs = [_make_msg("recruiter@voltus.co")]
        assert _extract_sender_domains(msgs) == {"voltus.co"}

    def test_excludes_gmail_domain(self):
        msgs = [_make_msg("steve@gmail.com")]
        assert _extract_sender_domains(msgs) == set()

    def test_excludes_greenhouse_ats_domain(self):
        msgs = [_make_msg("no-reply@greenhouse.io")]
        assert _extract_sender_domains(msgs) == set()

    def test_excludes_lever_ats_domain(self):
        msgs = [_make_msg("jobs@lever.co")]
        assert _extract_sender_domains(msgs) == set()

    def test_excludes_ashby_ats_domain(self):
        msgs = [_make_msg("recruiting@ashbyhq.com")]
        assert _extract_sender_domains(msgs) == set()

    def test_returns_empty_set_for_no_from_header(self):
        msgs = [{"payload": {"headers": [{"name": "Subject", "value": "Hi"}]}}]
        assert _extract_sender_domains(msgs) == set()

    def test_returns_empty_set_for_empty_messages(self):
        assert _extract_sender_domains([]) == set()

    def test_collects_multiple_domains_from_multiple_messages(self):
        msgs = [
            _make_msg("alice@uplight.com"),
            _make_msg("bob@weavegrid.com"),
        ]
        result = _extract_sender_domains(msgs)
        assert result == {"uplight.com", "weavegrid.com"}

    def test_deduplicates_same_domain_multiple_messages(self):
        msgs = [
            _make_msg("alice@uplight.com"),
            _make_msg("bob@uplight.com"),
        ]
        result = _extract_sender_domains(msgs)
        assert result == {"uplight.com"}

    def test_handles_malformed_from_header_gracefully(self):
        msgs = [_make_msg("not-an-email")]
        assert _extract_sender_domains(msgs) == set()

    def test_all_generic_domains_excluded(self):
        """Spot-check a handful of generic domains are in the exclusion set."""
        for domain in ("gmail.com", "yahoo.com", "hotmail.com", "linkedin.com", "workday.com"):
            assert domain in _GENERIC_DOMAINS


# ---------------------------------------------------------------------------
# _build_domain_map
# ---------------------------------------------------------------------------

class TestBuildDomainMap:

    def test_empty_when_no_sender_domains(self):
        app_by_id = {"abc": {"id": "abc", "company": "Acme"}}
        assert _build_domain_map(app_by_id) == {}

    def test_maps_single_domain_to_app_id(self):
        app_by_id = {
            "abc": {"id": "abc", "company": "Uplight", "sender_domains": ["uplight.com"]},
        }
        result = _build_domain_map(app_by_id)
        assert result == {"uplight.com": ["abc"]}

    def test_maps_multiple_domains_from_one_app(self):
        app_by_id = {
            "abc": {"id": "abc", "company": "Uplight",
                    "sender_domains": ["uplight.com", "mail.uplight.com"]},
        }
        result = _build_domain_map(app_by_id)
        assert "uplight.com" in result
        assert "mail.uplight.com" in result
        assert result["uplight.com"] == ["abc"]

    def test_multiple_apps_different_domains(self):
        app_by_id = {
            "a1": {"id": "a1", "sender_domains": ["uplight.com"]},
            "a2": {"id": "a2", "sender_domains": ["voltus.co"]},
        }
        result = _build_domain_map(app_by_id)
        assert result["uplight.com"] == ["a1"]
        assert result["voltus.co"] == ["a2"]

    def test_empty_app_dict_returns_empty(self):
        assert _build_domain_map({}) == {}


# ---------------------------------------------------------------------------
# _find_existing_by_domain
# ---------------------------------------------------------------------------

class TestFindExistingByDomain:

    def _make_app_by_id(self, apps):
        return {a["id"]: a for a in apps}

    def test_returns_none_when_sender_domains_empty(self):
        app_by_id = {"a1": {"id": "a1", "status": "applied"}}
        domain_map = {"uplight.com": ["a1"]}
        result = _find_existing_by_domain(set(), domain_map, app_by_id)
        assert result is None

    def test_returns_none_when_domain_map_empty(self):
        app_by_id = {"a1": {"id": "a1", "status": "applied"}}
        result = _find_existing_by_domain({"uplight.com"}, {}, app_by_id)
        assert result is None

    def test_returns_none_when_no_intersection(self):
        app_by_id = {"a1": {"id": "a1", "status": "applied"}}
        domain_map = {"voltus.co": ["a1"]}
        result = _find_existing_by_domain({"uplight.com"}, domain_map, app_by_id)
        assert result is None

    def test_returns_matching_app(self):
        app = {"id": "a1", "company": "Uplight", "status": "applied"}
        app_by_id = {"a1": app}
        domain_map = {"uplight.com": ["a1"]}
        result = _find_existing_by_domain({"uplight.com"}, domain_map, app_by_id)
        assert result is not None
        assert result["id"] == "a1"

    def test_returns_highest_priority_when_multiple_match(self):
        """Two apps share a domain (edge case); prefer the higher-status one."""
        app1 = {"id": "a1", "company": "Uplight", "status": "applied"}
        app2 = {"id": "a2", "company": "Uplight", "status": "interview_requested"}
        app_by_id = {"a1": app1, "a2": app2}
        domain_map = {"uplight.com": ["a1", "a2"]}
        result = _find_existing_by_domain({"uplight.com"}, domain_map, app_by_id)
        assert result["status"] == "interview_requested"

    def test_partial_domain_overlap_still_matches(self):
        """Thread has two domains; only one is in the map — should still find the app."""
        app = {"id": "a1", "company": "Acme", "status": "applied"}
        app_by_id = {"a1": app}
        domain_map = {"acmecorp.com": ["a1"]}
        # Thread also came from noreply@greenhouse.io (excluded) but real address is acmecorp.com
        result = _find_existing_by_domain({"acmecorp.com", "greenhouse.io"}, domain_map, app_by_id)
        assert result is not None
        assert result["id"] == "a1"


# ---------------------------------------------------------------------------
# _analyze_thread — confidence, needs_review, matched_company/title
# ---------------------------------------------------------------------------

def _mock_client(response_text: str):
    """Build a mock Anthropic client that returns the given text."""
    mock = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    mock.messages.create.return_value = msg
    return mock


class TestAnalyzeThreadConfidence:

    def _high_conf_response(self, **overrides):
        base = {
            "job_title": "Senior Product Manager",
            "company": "Uplight",
            "applied_date": "2026-07-01",
            "status": "applied",
            "status_label": "Applied",
            "last_activity": "2026-07-01",
            "follow_up_date": "2026-07-10",
            "recommended_action": "Follow up next week.",
            "confidence": 92,
            "needs_review": False,
            "match_reasoning": "Subject line names the role explicitly.",
            "matched_company": "",
            "matched_title": "",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_high_confidence_returns_result_unchanged(self):
        client = _mock_client(self._high_conf_response())
        result = _analyze_thread("some thread text", client)
        assert result is not None
        assert result["confidence"] == 92
        assert result["needs_review"] is False

    def test_low_confidence_sets_needs_review_true(self):
        """confidence < 70 should force needs_review=True even if Claude said False."""
        client = _mock_client(self._high_conf_response(confidence=65, needs_review=False))
        result = _analyze_thread("some thread text", client)
        assert result["needs_review"] is True

    def test_empty_job_title_sets_needs_review_true(self):
        """job_title='' should force needs_review=True regardless of confidence."""
        client = _mock_client(self._high_conf_response(confidence=85, job_title=""))
        result = _analyze_thread("some thread text", client)
        assert result["needs_review"] is True

    def test_returns_none_for_null_response(self):
        client = _mock_client("null")
        result = _analyze_thread("unrelated email", client)
        assert result is None

    def test_returns_none_for_null_with_whitespace(self):
        client = _mock_client("  null  ")
        result = _analyze_thread("unrelated email", client)
        assert result is None

    def test_strips_markdown_fences(self):
        """Claude sometimes wraps JSON in ```json ... ```."""
        raw = "```json\n" + self._high_conf_response() + "\n```"
        client = _mock_client(raw)
        result = _analyze_thread("some thread text", client)
        assert result is not None
        assert result["company"] == "Uplight"

    def test_includes_matched_company_and_title(self):
        payload = self._high_conf_response(
            matched_company="Uplight",
            matched_title="Senior Product Manager",
        )
        client = _mock_client(payload)
        result = _analyze_thread("some thread text", client)
        assert result["matched_company"] == "Uplight"
        assert result["matched_title"] == "Senior Product Manager"

    def test_returns_none_on_api_exception(self):
        mock = MagicMock()
        mock.messages.create.side_effect = Exception("API error")
        result = _analyze_thread("some thread text", mock)
        assert result is None

    def test_active_applications_included_in_prompt(self):
        """When active_applications is provided, Claude's prompt should include them."""
        client = _mock_client(self._high_conf_response())
        active = [{"company": "Uplight", "job_title": "PM", "applied_date": "2026-07-01", "status": "applied"}]
        _analyze_thread("some thread text", client, active_applications=active)
        call_args = client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Uplight" in prompt
        assert "ACTIVE APPLICATIONS" in prompt

    def test_no_active_applications_prompt_has_no_context_block(self):
        client = _mock_client(self._high_conf_response())
        _analyze_thread("some thread text", client, active_applications=None)
        call_args = client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "ACTIVE APPLICATIONS" not in prompt

    def test_confidence_exactly_70_does_not_trigger_review(self):
        """Boundary: confidence == 70 should NOT set needs_review (threshold is < 70)."""
        client = _mock_client(self._high_conf_response(confidence=70, needs_review=False))
        result = _analyze_thread("some thread text", client)
        assert result["needs_review"] is False

    def test_confidence_69_triggers_review(self):
        """Boundary: confidence == 69 SHOULD set needs_review=True."""
        client = _mock_client(self._high_conf_response(confidence=69, needs_review=False))
        result = _analyze_thread("some thread text", client)
        assert result["needs_review"] is True
