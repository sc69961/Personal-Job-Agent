"""
conftest.py — shared pytest fixtures for the job-agent test suite.

Autouse fixtures here apply to every test in the suite automatically.
Individual test files don't need to import anything from this file.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolate_scorer_registries():
    """
    Isolate scorer registries (seen_job_ids + first_seen) for every test.

    Without this, score_all_jobs() reads/writes two files under ./output/:
      - seen_job_ids.json: job IDs accumulate across test runs, causing
        subsequent tests to see "(seen) … skipping re-score"
      - first_seen_registry.json: job IDs get a first_seen timestamp on
        first run; later runs return the cached date instead of today, breaking
        assertions like `assert result["first_seen"].startswith(today)`

    We patch the functions (not the path constants) because Python captures
    default argument values at function-definition time, so patching a
    module-level path string has no effect on already-defined function signatures.
    """
    with patch("scripts.scorer._load_seen_ids", return_value=set()), \
         patch("scripts.scorer._save_seen_ids"), \
         patch("scripts.scorer._load_first_seen_registry", return_value={}), \
         patch("scripts.scorer._save_first_seen_registry"):
        yield
