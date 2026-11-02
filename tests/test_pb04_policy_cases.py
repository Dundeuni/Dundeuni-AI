"""Review artifact checks only; no phone policy or provider is exercised."""

import json
from pathlib import Path

import pytest

CASES_PATH = Path(__file__).parent / "fixtures" / "pb04_policy_cases.json"
ARTIFACT = json.loads(CASES_PATH.read_text(encoding="utf-8"))
CASES = ARTIFACT["cases"]
REQUIRED_CASES = {
    "risk_evidence",
    "suspicious_evidence",
    "no_data",
    "zero_reports",
    "insufficient",
    "conflicting",
    "lookup_failure",
    "timeout",
    "malformed",
    "policy_pending",
}


def test_review_artifact_is_synthetic_and_covers_required_scenarios():
    assert ARTIFACT["synthetic"] is True
    assert ARTIFACT["purpose"] == "POLICY_REVIEW_ONLY_NOT_PROVIDER_DATA"
    identifiers = [case["id"] for case in CASES]
    assert len(identifiers) == len(set(identifiers))
    assert set(identifiers) == REQUIRED_CASES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_review_case_has_no_invented_verdict_or_report_data(case):
    # Exact whitelist excludes phone numbers, scores and report histories.
    assert set(case) == {
        "id",
        "lookup",
        "evidence",
        "expectedVerdict",
        "reviewRequirement",
    }
    assert case["expectedVerdict"] is None
    assert all(
        isinstance(case[field], str) and case[field]
        for field in ("id", "lookup", "evidence", "reviewRequirement")
    )


def test_no_data_and_technical_failures_remain_distinct_review_cases():
    by_id = {case["id"]: case for case in CASES}
    assert by_id["no_data"]["lookup"] == "completed"
    assert by_id["no_data"]["evidence"] == "absent"
    for case_id, state in (
        ("lookup_failure", "failed"),
        ("timeout", "timeout"),
        ("malformed", "invalid_response"),
    ):
        assert by_id[case_id]["lookup"] == state
        assert by_id[case_id]["evidence"] != "absent"
