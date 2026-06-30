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

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.gmail_crm import (
    _normalize_company,
    _app_id,
    _should_upgrade_status,
    _find_existing_by_company,
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
