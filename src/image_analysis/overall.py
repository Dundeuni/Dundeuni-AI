"""Representative image signal verdict; no score fusion or fraud assessment."""

from __future__ import annotations

from typing import Optional

from image_analysis.schemas import ModelKind, ModelResult, OverallResult


def make_overall_result(
    generation: Optional[ModelResult], manipulation: Optional[ModelResult]
) -> OverallResult:
    """Use both current results, including null/unrequested as uncertainty.

    A retry envelope describes this call only. BE must merge preserved results
    for the same image before recalculating its session-level representative.
    """
    suspected: list[ModelKind] = []
    uncertain: list[ModelKind] = []
    comparisons: tuple[tuple[ModelKind, Optional[ModelResult], str, str], ...] = (
        (
            "generation",
            generation,
            "AI_GENERATED_SUSPECTED",
            "NO_CLEAR_GENERATION_SIGNAL",
        ),
        (
            "manipulation",
            manipulation,
            "MANIPULATION_SUSPECTED",
            "NO_CLEAR_MANIPULATION_SIGNAL",
        ),
    )
    for kind, result, suspicion, absent in comparisons:
        if result is None or result.status != "SUCCEEDED":
            uncertain.append(kind)
        elif result.decision == suspicion:
            suspected.append(kind)
        elif result.decision != absent:
            uncertain.append(kind)
    if suspected:
        return OverallResult(
            decision="GENERATION_OR_MANIPULATION_SUSPECTED",
            decisionLabel="생성·변조 의심",
            suspectedKinds=suspected,
            uncertainKinds=uncertain,
        )
    if uncertain:
        return OverallResult(
            decision="INCONCLUSIVE",
            decisionLabel="판단 불가",
            suspectedKinds=[],
            uncertainKinds=uncertain,
        )
    return OverallResult(
        decision="NO_CLEAR_SIGNAL",
        decisionLabel="뚜렷한 신호 없음",
        suspectedKinds=[],
        uncertainKinds=[],
    )
