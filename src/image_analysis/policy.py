from __future__ import annotations

import base64
import io
import math

from PIL import Image

from image_analysis.adapters import GenerationOutput, ManipulationOutput, RawOutput
from image_analysis.config import Settings
from image_analysis.errors import ModelFailure
from image_analysis.schemas import (
    Decision,
    DecisionLabel,
    Localization,
    ModelKind,
    ModelResult,
    Size,
)

MOCK_LIMITATION = "MOCK 응답입니다. 실제 모델 추론이나 이미지 판정 결과가 아닙니다."
DECISION_LABELS: dict[Decision, DecisionLabel] = {
    "AI_GENERATED_SUSPECTED": "AI 생성 의심",
    "NO_CLEAR_GENERATION_SIGNAL": "뚜렷한 AI 생성 신호 없음",
    "MANIPULATION_SUSPECTED": "변조 의심",
    "NO_CLEAR_MANIPULATION_SIGNAL": "뚜렷한 변조 신호 없음",
    "INCONCLUSIVE": "판단 불가",
}


def sigmoid(logit: float) -> float:
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    value = math.exp(logit)
    return value / (1 + value)


def finite_scalar(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_map(image: Image.Image, size: tuple[int, int]) -> None:
    if not isinstance(image, Image.Image) or image.mode != "F" or image.size != size:
        raise ModelFailure("MODEL_OUTPUT_INVALID")
    for pixel in image.getdata():
        value = float(pixel)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ModelFailure("MODEL_OUTPUT_INVALID")


def encode_localization(
    raw: ManipulationOutput,
    size: tuple[int, int],
    settings: Settings,
) -> Localization:
    """Bilinear float resampling before half-up 8-bit grayscale quantization."""
    width, height = size
    ratio = min(1.0, settings.localization_max_side / max(size))
    display_size = (
        max(1, math.floor(width * ratio + 0.5)),
        max(1, math.floor(height * ratio + 0.5)),
    )
    with raw.map.resize(display_size, Image.Resampling.BILINEAR) as sampled:
        with Image.new("L", display_size) as gray:
            gray.putdata([math.floor(255 * float(p) + 0.5) for p in sampled.getdata()])
            output = io.BytesIO()
            gray.save(output, format="PNG")
    png = output.getvalue()
    if len(png) > settings.localization_max_bytes:
        raise ValueError("localization PNG too large")
    encoded = base64.b64encode(png).decode("ascii")
    if len(encoded) > 1_398_104:
        raise ValueError("localization base64 too large")
    return Localization(
        data=encoded,
        imageSize=Size(width=width, height=height),
        mapSize=Size(width=display_size[0], height=display_size[1]),
    )


def make_success(
    kind: ModelKind,
    model_name: str,
    model_version: str,
    raw: RawOutput,
    size: tuple[int, int],
    alpha_composited: bool,
    settings: Settings,
) -> ModelResult:
    if kind == "generation" and isinstance(raw, GenerationOutput):
        if raw.score is not None:
            if not finite_scalar(raw.score) or not 0 <= raw.score <= 1:
                raise ModelFailure("MODEL_OUTPUT_INVALID")
            value = raw.score
            raw_score = {"score": raw.score}
        else:
            if settings.mode != "MOCK" or not finite_scalar(raw.logit):
                raise ModelFailure("MODEL_OUTPUT_INVALID")
            assert raw.logit is not None
            value = sigmoid(raw.logit)
            raw_score = {"logit": raw.logit}
    elif kind == "manipulation" and isinstance(raw, ManipulationOutput):
        if not finite_scalar(raw.score) or not 0 <= raw.score <= 1:
            raise ModelFailure("MODEL_OUTPUT_INVALID")
        if raw.imgsize != (size[1], size[0]):
            raise ModelFailure("MODEL_OUTPUT_INVALID")
        validate_map(raw.map, size)
        validate_map(raw.conf, size)
        value = raw.score
        raw_score = {"score": raw.score}
    else:
        raise ModelFailure("MODEL_OUTPUT_INVALID")
    result = ModelResult(
        status="SUCCEEDED",
        modelName=model_name,
        modelVersion=model_version,
        policyVersion=settings.policy_version,
        rawScore=raw_score,
        limitations=[
            MOCK_LIMITATION
            if settings.mode == "MOCK"
            else (
                "CuRe의 AI 생성 탐지 결과입니다. "
                "일반 변조나 의심 위치는 분석하지 않습니다."
                if kind == "generation"
                else "TruFor의 편집·합성 의심 신호입니다. "
                "위치 지도는 확정 변조 영역이나 AI 사용의 증거가 아닙니다."
            ),
            "표시 점수는 보정 확률이나 사기 확률이 아닙니다.",
        ],
    )
    if alpha_composited:
        result.limitations.append("입력 알파 채널을 흰 배경에 합성했습니다.")
    if settings.mode == "MOCK":
        low, upper = settings.hold_low, settings.hold_high
        # Preserve the original mock's inclusive upper boundary.
        hold = settings.hold_enabled and low <= value <= upper
    else:
        low = getattr(settings, f"{kind}_hold_low")
        upper = getattr(settings, f"{kind}_hold_high")
        hold = settings.hold_enabled and low <= value < upper
        result.limitations.append(
            "임시 파일럿 판정 기준이며 최종 서비스 성능이 확정된 것은 아닙니다."
        )
    if hold:
        result.decision = "INCONCLUSIVE"
        result.limitations.append(
            "모델 점수가 임시 판단 불가 구간에 포함되어 판별을 보류합니다."
        )
    else:
        high = (
            (value > upper if settings.mode == "MOCK" else value >= upper)
            if settings.hold_enabled
            else value >= settings.generation_threshold
        )
        if kind == "generation":
            result.decision = (
                "AI_GENERATED_SUSPECTED" if high else "NO_CLEAR_GENERATION_SIGNAL"
            )
        else:
            result.decision = (
                "MANIPULATION_SUSPECTED" if high else "NO_CLEAR_MANIPULATION_SIGNAL"
            )
        result.displayScore = math.floor(100 * value + 0.5)
        if settings.mode == "MOCK":
            result.reasons = [
                "고정 mock 점수가 잠정 의심 기준보다 높습니다."
                if high
                else "고정 mock 점수가 잠정 신호 없음 기준보다 낮습니다."
            ]
        else:
            name = "CuRe 생성 탐지" if kind == "generation" else "TruFor 변조 탐지"
            result.reasons = [
                f"{name} 점수가 임시 의심 기준 이상입니다."
                if high
                else f"{name} 점수에서 뚜렷한 신호를 확인하지 못했습니다."
            ]
    assert result.decision is not None
    result.decisionLabel = DECISION_LABELS[result.decision]
    if isinstance(raw, ManipulationOutput):
        try:
            result.localization = encode_localization(raw, size, settings)
        except (OSError, ValueError):
            result.limitations.append(
                "표시용 위치 PNG를 생성하거나 전달할 수 없습니다."
            )
    return result
