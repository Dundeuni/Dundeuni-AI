from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from image_analysis.errors import ErrorInfo

ModelKind = Literal["generation", "manipulation"]
Decision = Literal[
    "AI_GENERATED_SUSPECTED",
    "NO_CLEAR_GENERATION_SIGNAL",
    "MANIPULATION_SUSPECTED",
    "NO_CLEAR_MANIPULATION_SIGNAL",
    "INCONCLUSIVE",
]
DecisionLabel = Literal[
    "AI 생성 의심",
    "뚜렷한 AI 생성 신호 없음",
    "변조 의심",
    "뚜렷한 변조 신호 없음",
    "판단 불가",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Size(ContractModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class AnalysisImage(Size):
    inputSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalizationVersion: str = Field(min_length=1, max_length=128)


class Localization(ContractModel):
    format: Literal["PNG_BASE64"] = "PNG_BASE64"
    kind: Literal["MANIPULATION_HEATMAP"] = "MANIPULATION_HEATMAP"
    mimeType: Literal["image/png"] = "image/png"
    data: str = Field(max_length=1_398_104)
    imageSize: Size
    mapSize: Size
    coordinateSpace: Literal["ANALYSIS_IMAGE"] = "ANALYSIS_IMAGE"


class ModelResult(ContractModel):
    status: Literal["SUCCEEDED", "FAILED"]
    modelName: str = Field(min_length=1, max_length=64)
    modelVersion: str = Field(min_length=1, max_length=128)
    policyVersion: str = Field(min_length=1, max_length=128)
    rawScore: Optional[dict[str, float]] = None
    displayScore: Optional[int] = Field(default=None, ge=0, le=100)
    decision: Optional[Decision] = None
    decisionLabel: Optional[DecisionLabel] = None
    reasons: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    localization: Optional[Localization] = None
    errorCode: Optional[str] = None
    error: Optional[ErrorInfo] = None


class OverallResult(ContractModel):
    decision: Literal[
        "GENERATION_OR_MANIPULATION_SUSPECTED", "INCONCLUSIVE", "NO_CLEAR_SIGNAL"
    ]
    decisionLabel: Literal["생성·변조 의심", "판단 불가", "뚜렷한 신호 없음"]
    policyVersion: Literal["image-overall-v1"] = "image-overall-v1"
    suspectedKinds: list[ModelKind] = Field(max_length=2)
    uncertainKinds: list[ModelKind] = Field(max_length=2)


class Envelope(ContractModel):
    contractVersion: str = "1.0"
    requestId: str
    analysisId: str
    elementId: str
    sourceType: Literal["IMAGE", "SCREEN_CROP"]
    requestedModels: list[ModelKind]
    status: Literal["COMPLETED", "PARTIAL_FAILED", "FAILED"]
    analysisImage: AnalysisImage
    generation: Optional[ModelResult] = None
    manipulation: Optional[ModelResult] = None
    overallResult: OverallResult
    completedAt: str
