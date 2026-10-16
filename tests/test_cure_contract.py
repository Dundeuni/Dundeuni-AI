"""Controlled CuRe doubles test contracts, not model performance."""

import asyncio
import io
from dataclasses import replace

import pytest
from conftest import image_bytes, request_parts
from PIL import Image
from starlette.testclient import TestClient

from image_analysis.adapters import GenerationOutput
from image_analysis.app import ENDPOINT, create_app
from image_analysis.compat import provider_result
from image_analysis.cure import cure_settings
from image_analysis.errors import ModelFailure, TransportError
from image_analysis.images import normalize_image
from image_analysis.policy import make_success
from image_analysis.schemas import Envelope


class ControlledCuRe:
    kind = "generation"
    model_name = "CuRe"
    model_version = "TEST-CuRe-contract-double"
    ready = True

    def __init__(self, score=0.8, error=None, delay=0):
        self.score, self.error, self.delay = score, error, delay
        self.formats = []
        self.cleaned = False

    async def infer(self, image):
        self.formats.append(image.info.get("analysis_source_format"))
        try:
            await asyncio.sleep(self.delay)
            if self.error:
                raise ModelFailure(self.error)
            return GenerationOutput(score=self.score)
        finally:
            self.cleaned = True

    async def recover(self):
        return self.cleaned


def client_for(adapter=None, settings=None):
    return TestClient(
        create_app(
            replace(settings or cure_settings(), fe_compatibility=True),
            {"generation": adapter or ControlledCuRe()},
        ),
        client=("127.0.0.1", 50000),
    )


@pytest.mark.parametrize(
    "score,decision,display",
    [
        (0.000003, "NO_CLEAR_GENERATION_SIGNAL", 0),
        (0.000004, "INCONCLUSIVE", None),
        (0.019999, "INCONCLUSIVE", None),
        (0.02, "AI_GENERATED_SUSPECTED", 2),
        (0.5, "AI_GENERATED_SUSPECTED", 50),
        (0.8, "AI_GENERATED_SUSPECTED", 80),
        (0.0, "NO_CLEAR_GENERATION_SIGNAL", 0),
        (1.0, "AI_GENERATED_SUSPECTED", 100),
    ],
)
def test_single_cure_direct_score(headers, score, decision, display):
    with client_for(ControlledCuRe(score)) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    result = response.json()
    assert response.status_code == 200
    assert result["requestedModels"] == ["generation"]
    assert result["manipulation"] is None and result["status"] == "COMPLETED"
    generation = result["generation"]
    assert generation["rawScore"] == {"score": score}
    assert generation["displayScore"] == display
    assert generation["decision"] == decision
    assert generation["localization"] is None
    assert response.headers["X-AI-Mode"] == "CURE"
    assert all(
        "mock" not in text.lower()
        for text in generation["reasons"] + generation["limitations"]
    )


@pytest.mark.parametrize("selection", ["ALL", "MANIPULATION"])
def test_cure_rejects_other_models(headers, selection):
    with client_for() as client:
        response = client.post(
            ENDPOINT, headers=headers, files=request_parts(fields={"models": selection})
        )
    assert response.status_code == 400


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_outputs(headers, score):
    with client_for(ControlledCuRe(score)) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    result = response.json()
    assert result["status"] == "FAILED" and result["manipulation"] is None
    assert result["generation"]["errorCode"] == "MODEL_OUTPUT_INVALID"
    assert result["generation"]["displayScore"] is None


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_original_format_reaches_adapter(headers, fmt, mime):
    adapter = ControlledCuRe()
    with client_for(adapter) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(image_bytes(format=fmt), mime=mime),
        )
    assert response.status_code == 200 and adapter.formats == [fmt]


def test_exif_alpha_normalization():
    settings = cure_settings()
    with Image.new("RGB", (40, 80), "red") as image:
        exif = Image.Exif()
        exif[274] = 6
        data = io.BytesIO()
        image.save(data, format="JPEG", exif=exif)
    result = normalize_image(data.getvalue(), "image/jpeg", settings)
    assert result.image.size == (80, 40)
    assert result.image.info["analysis_source_format"] == "JPEG"
    result.image.close()
    result = normalize_image(
        image_bytes(mode="RGBA", color=(255, 0, 0, 0)), "image/png", settings
    )
    assert result.alpha_composited
    assert result.image.getpixel((0, 0)) == (255, 255, 255)
    result.image.close()


def upload_fe(client, kind="IMAGE"):
    return client.post(
        "/api/analysis",
        data={"type": kind},
        files={"file": ("photo.png", image_bytes(), "image/png")},
    )


def test_fe_be_provider_compatibility():
    with client_for() as client:
        response = upload_fe(client)
    body = response.json()
    assert response.status_code == 202 and body["code"] == "ANALYSIS202"
    assert body["isSuccess"] is True
    assert body["message"] == "분석 요청 생성에 성공했습니다."
    result = body["result"]
    assert result["status"] == "COMPLETED" and result["type"] == "IMAGE"
    assert result["aiGenerationScore"] == 80
    assert result["aiRiskLevel"] == "AI_GENERATED_SUSPECTED"
    assert result["errorCode"] is None
    assert all(set(reason) == {"description"} for reason in result["reasons"])
    assert not {"fraudScore", "manipulation", "riskLevel"}.intersection(result)
    assert response.headers["X-Compatibility-Only"] == "true"


@pytest.mark.parametrize("kind", ["SCREEN", "TEXT", ""])
def test_fe_only_image(kind):
    with client_for() as client:
        response = upload_fe(client, kind)
    assert response.status_code == 400 and response.json()["result"] is None


def test_fe_failure_matches_be():
    with client_for(ControlledCuRe(error="MODEL_OUT_OF_MEMORY")) as client:
        response = upload_fe(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ANALYSIS503"
    assert response.json()["result"] is None


def test_be_mock_fixture_too_small_for_real_cure():
    adapter = ControlledCuRe()
    with client_for(adapter) as client:
        response = client.post(
            "/api/analysis",
            data={"type": "IMAGE"},
            files={"file": ("tiny.png", image_bytes(size=(1, 1)), "image/png")},
        )
    assert response.status_code == 422
    assert response.json()["result"] is None
    assert adapter.formats == []


def test_hold_not_converted_to_zero(headers):
    with client_for(ControlledCuRe(0.01), cure_settings()) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    envelope = Envelope.model_validate(response.json())
    assert envelope.generation.decision == "INCONCLUSIVE"
    assert envelope.generation.displayScore is None
    with pytest.raises(TransportError):
        provider_result(envelope)


def test_cure_rejects_bfree_logit():
    with pytest.raises(ModelFailure):
        make_success(
            "generation",
            "CuRe",
            "test",
            GenerationOutput(logit=1),
            (64, 48),
            False,
            cure_settings(),
        )


def test_timeout_cleanup(headers):
    adapter = ControlledCuRe(delay=0.1)
    with client_for(
        adapter, replace(cure_settings(), model_timeout_seconds=0.02)
    ) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
        assert response.json()["generation"]["errorCode"] == "MODEL_TIMEOUT"
        assert adapter.cleaned
        adapter.delay = 0
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
        assert response.json()["status"] == "COMPLETED"
