"""Offline PB-04 synthetic scenario evaluator, not an approved service policy.

Inputs describe evidence conditions only. No numbers, reports, scores, provider
responses or image contract objects are accepted. No risk classification exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

ProcessingStatus = Literal["COMPLETED", "FAILED"]
Reason = Literal[
    "NO_DATA",
    "INSUFFICIENT_EVIDENCE",
    "CONFLICTING_EVIDENCE",
    "POLICY_UNCONFIRMED",
    "LOOKUP_FAILED",
    "LOOKUP_TIMEOUT",
    "INVALID_RESPONSE",
]

COMPLETED_EVIDENCE: dict[str, Reason] = {
    "risk_candidate": "POLICY_UNCONFIRMED",
    "suspicion_candidate": "POLICY_UNCONFIRMED",
    "absent": "NO_DATA",
    "zero_reports_condition_only": "INSUFFICIENT_EVIDENCE",
    "insufficient": "INSUFFICIENT_EVIDENCE",
    "conflicting": "CONFLICTING_EVIDENCE",
    "unmapped": "POLICY_UNCONFIRMED",
}
FAILED_LOOKUPS: dict[str, tuple[str, Reason]] = {
    "failed": ("unavailable", "LOOKUP_FAILED"),
    "timeout": ("unavailable", "LOOKUP_TIMEOUT"),
    "invalid_response": ("unusable", "INVALID_RESPONSE"),
}


@dataclass(frozen=True)
class ExperimentalResult:
    """Local result only; verdict None means technical failure, not no data."""

    processing_status: ProcessingStatus
    verdict: Optional[Literal["INCONCLUSIVE"]]
    reason: Reason
    lookup: str
    evidence: str
    policy_status: Literal["UNCONFIRMED"] = "UNCONFIRMED"


def evaluate_synthetic_scenario(payload: object) -> ExperimentalResult:
    """Validate an abstract synthetic condition and return uncertainty or failure.

    Exactly synthetic=True, lookup and evidence are required. Invalid caller
    input raises ValueError; a valid scenario describing a broken upstream
    response instead returns FAILED/INVALID_RESPONSE. No external I/O occurs.
    """
    if not isinstance(payload, dict) or set(payload) != {
        "synthetic",
        "lookup",
        "evidence",
    }:
        raise ValueError("expected synthetic, lookup and evidence fields only")
    if payload["synthetic"] is not True:
        raise ValueError("only explicitly synthetic scenarios are supported")
    lookup, evidence = payload["lookup"], payload["evidence"]
    if type(lookup) is not str or type(evidence) is not str:
        raise ValueError("lookup and evidence must be strings")
    if lookup == "completed":
        if evidence not in COMPLETED_EVIDENCE:
            raise ValueError("unsupported evidence for completed lookup")
        return ExperimentalResult(
            processing_status="COMPLETED",
            verdict="INCONCLUSIVE",
            reason=COMPLETED_EVIDENCE[evidence],
            lookup=lookup,
            evidence=evidence,
        )
    if lookup not in FAILED_LOOKUPS:
        raise ValueError("unsupported lookup state")
    required_evidence, reason = FAILED_LOOKUPS[lookup]
    if evidence != required_evidence:
        raise ValueError("evidence contradicts lookup state")
    return ExperimentalResult(
        processing_status="FAILED",
        verdict=None,
        reason=reason,
        lookup=lookup,
        evidence=evidence,
    )
