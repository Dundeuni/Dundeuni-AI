"""Pure mappings for the current BE provider and FE POST /api/analysis DTO."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from image_analysis.errors import TransportError
from image_analysis.schemas import Envelope
from image_analysis.service import timestamp


def provider_result(envelope: Envelope) -> dict[str, Any]:
    result = envelope.generation
    if (
        envelope.requestedModels != ["generation"]
        or result is None
        or result.status != "SUCCEEDED"
        or result.displayScore is None
    ):
        # Current BE provider rejects null scores. Never convert a hold/failure to 0.
        raise TransportError(503, "MODEL_UNAVAILABLE")
    return {
        "aiGenerationScore": result.displayScore,
        # Provider string, not SAFE/CAUTION/DANGER or a fraud verdict.
        "aiRiskLevel": result.decision,
        "reasons": [
            {"description": reason} for reason in result.reasons + result.limitations
        ],
        "modelVersion": result.modelVersion,
    }


def fe_response(envelope: Envelope, created_at: datetime) -> dict[str, Any]:
    return {
        "isSuccess": True,
        "code": "ANALYSIS202",
        "message": "분석 요청 생성에 성공했습니다.",
        "result": {
            "analysisId": envelope.analysisId,
            "type": "IMAGE",
            "status": "COMPLETED",
            **provider_result(envelope),
            "errorCode": None,
            "createdAt": timestamp(created_at),
            "completedAt": envelope.completedAt,
            # Local compatibility response only; no persisted record or deletion job.
            "expiresAt": timestamp(created_at + timedelta(days=1)),
        },
    }
