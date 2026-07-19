"""V4 blocker 4: dependency provenance is mandatory and verified."""
from pathlib import Path

import pytest

from eagle_eye.provenance import (
    dependency_lock_digest,
    parse_lock,
    verify_dependency_lock,
)

ROOT = Path(__file__).resolve().parents[1]


def test_lock_exists_and_digest_is_stable():
    digest = dependency_lock_digest(ROOT)
    assert len(digest) == 64
    assert digest == dependency_lock_digest(ROOT)
    assert digest != "NOT_AVAILABLE"


def test_missing_lock_raises_never_not_available(tmp_path):
    with pytest.raises(FileNotFoundError, match="provenance is mandatory"):
        dependency_lock_digest(tmp_path)


def test_lock_refuses_non_pinned_lines(tmp_path):
    lock = tmp_path / "environment" / "requirements-lock.txt"
    lock.parent.mkdir(parents=True)
    lock.write_text("cryptography>=46\n")
    with pytest.raises(ValueError, match="exact pins only"):
        parse_lock(tmp_path)


def test_running_environment_matches_audited_lock():
    report = verify_dependency_lock(ROOT)
    mismatches = [r for r in report["packages"] if not r["match"]]
    assert report["all_match"], f"environment drifted from audited lock: {mismatches}"
    assert {r["package"] for r in report["packages"]} >= {"cryptography", "pytest"}
