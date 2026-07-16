"""
conftest.py — shared pytest fixtures for the job-agent test suite.

Autouse fixtures here apply to every test in the suite automatically.
Individual test files don't need to import anything from this file.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolate_seen_ids():
    """
    Isolate the seen_job_ids registry for every test.

    Without this, score_all_jobs() reads/writes ./output/seen_job_ids.json.
    Job IDs accumulate across test runs, causing tests that expect a fresh
    scoring pass to see "(seen) … skipping re-score" instead.

    We patch the functions (not the path constant) because Python captures
    default argument values at function-definition time, so patching the
    module-level _SEEN_IDS_PATH string has no effect on already-defined
    function signatures.
    """
    with patch("scripts.scorer._load_seen_ids", return_value=set()), \
         patch("scripts.scorer._save_seen_ids"):
        yield
