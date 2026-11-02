"""Synthetic uncertainty/failure behavior, not risk accuracy evaluation."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from phone_policy_experiment import evaluate_synthetic_scenario

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "pb04_policy_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]
EXPECTED = {
    "risk_evidence": ("COMPLETED", "INCONCLUSIVE", "POLICY_UNCONFIRMED"),
    "suspicious_evidence": ("COMPLETED", "INCONCLUSIVE", "POLICY_UNCONFIRMED"),
    "no_data": ("COMPLETED", "INCONCLUSIVE", "NO_DATA"),
    "zero_reports": ("COMPLETED", "INCONCLUSIVE", "INSUFFICIENT_EVIDENCE"),
    "insufficient": ("COMPLETED", "INCONCLUSIVE", "INSUFFICIENT_EVIDENCE"),
    "conflicting": ("COMPLETED", "INCONCLUSIVE", "CONFLICTING_EVIDENCE"),
    "lookup_failure": ("FAILED", None, "LOOKUP_FAILED"),
    "timeout": ("FAILED", None, "LOOKUP_TIMEOUT"),
    "malformed": ("FAILED", None, "INVALID_RESPONSE"),
    "policy_pending": ("COMPLETED", "INCONCLUSIVE", "POLICY_UNCONFIRMED"),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_synthetic_cases_preserve_uncertainty_and_failure(case):
    payload = {
        "synthetic": True,
        "lookup": case["lookup"],
        "evidence": case["evidence"],
    }
    result = evaluate_synthetic_scenario(payload)
    assert (result.processing_status, result.verdict, result.reason) == EXPECTED[
        case["id"]
    ]
    assert result.lookup == case["lookup"]
    assert result.evidence == case["evidence"]
    assert result.policy_status == "UNCONFIRMED"
    # No invented report data, score, or image API fields in the entire result.
    assert set(asdict(result)) == {
        "processing_status",
        "verdict",
        "reason",
        "lookup",
        "evidence",
        "policy_status",
    }
    assert payload == {
        "synthetic": True,
        "lookup": case["lookup"],
        "evidence": case["evidence"],
    }


@pytest.mark.parametrize("payload", [None, [], "synthetic", 0, True, {}])
def test_invalid_payload_is_rejected(payload):
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(payload)


@pytest.mark.parametrize("field", ["synthetic", "lookup", "evidence"])
@pytest.mark.parametrize("mode", ["missing", "null"])
def test_required_fields_do_not_default(field, mode):
    payload = {"synthetic": True, "lookup": "completed", "evidence": "absent"}
    if mode == "missing":
        del payload[field]
    else:
        payload[field] = None
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(payload)


@pytest.mark.parametrize("field", ["lookup", "evidence"])
@pytest.mark.parametrize("value", [False, 0, -1, 0.5, float("nan"), [], {}, ""])
def test_no_type_coercion_or_unrecognized_values(field, value):
    payload = {"synthetic": True, "lookup": "completed", "evidence": "absent"}
    payload[field] = value
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(payload)


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_synthetic_marker_must_be_literal_true(value):
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(
            {"synthetic": value, "lookup": "completed", "evidence": "absent"}
        )


@pytest.mark.parametrize(
    "lookup,evidence",
    [
        ("completed", "unavailable"),
        ("failed", "absent"),
        ("timeout", "risk_candidate"),
        ("invalid_response", "unavailable"),
        ("unknown", "unmapped"),
    ],
)
def test_contradictory_or_unknown_states_are_rejected(lookup, evidence):
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(
            {"synthetic": True, "lookup": lookup, "evidence": evidence}
        )


@pytest.mark.parametrize(
    "extra", ["phoneNumber", "reports", "reportCount", "rawScore", "displayScore"]
)
def test_real_data_and_score_fields_are_not_accepted(extra):
    with pytest.raises(ValueError):
        evaluate_synthetic_scenario(
            {
                "synthetic": True,
                "lookup": "completed",
                "evidence": "absent",
                extra: None,
            }
        )
