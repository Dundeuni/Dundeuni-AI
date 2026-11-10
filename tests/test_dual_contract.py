"""Dual-mode contracts with controlled model outputs, not accuracy claims."""

import base64
import io
from dataclasses import replace

from conftest import request_parts
from PIL import Image
from starlette.testclient import TestClient
from test_cure_contract import ControlledCuRe

from image_analysis.adapters import ManipulationOutput, MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.config import FUSED_THRESHOLD
from image_analysis.trufor import dual_settings


def dual_client(failure=None):
    return TestClient(
        create_app(
            dual_settings(),
            {
                "generation": ControlledCuRe(),
                "manipulation": MockAdapter("manipulation", failure=failure),
            },
        ),
        client=("127.0.0.1", 50000),
    )


def test_dual_default_and_real_map_coordinates(headers):
    with dual_client() as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
        assert client.get("/healthz").json()["mode"] == "CURE_TRUFOR"
        assert client.post("/api/analysis").status_code == 404
    body = response.json()
    assert body["requestedModels"] == ["generation", "manipulation"]
    assert body["status"] == "COMPLETED"
    assert body["generation"]["modelName"] == "CuRe"
    manipulation = body["manipulation"]
    assert "TruFor" in manipulation["reasons"][0]
    assert "확정 변조" in manipulation["limitations"][0]
    location = manipulation["localization"]
    assert location["coordinateSpace"] == "ANALYSIS_IMAGE"
    assert location["imageSize"] == {"width": 64, "height": 48}
    with Image.open(io.BytesIO(base64.b64decode(location["data"]))) as image:
        assert image.mode == "L" and image.size == (64, 48)
        assert image.getpixel((0, 0)) == 204


def test_dual_partial_failure_keeps_generation(headers):
    with dual_client("MODEL_TIMEOUT") as client:
        body = client.post(ENDPOINT, files=request_parts(), headers=headers).json()
    assert body["status"] == "PARTIAL_FAILED"
    assert body["generation"]["status"] == "SUCCEEDED"
    assert body["manipulation"]["status"] == "FAILED"
    assert body["manipulation"]["localization"] is None


def test_manipulation_only_retry_does_not_recreate_generation(headers):
    with dual_client() as client:
        body = client.post(
            ENDPOINT,
            files=request_parts(fields={"models": "MANIPULATION"}),
            headers=headers,
        ).json()
    assert body["generation"] is None
    assert body["requestedModels"] == ["manipulation"]
    assert body["manipulation"]["localization"] is not None


def test_fused_uses_existing_request_and_its_own_decision_boundary(headers):
    class ControlledFused(MockAdapter):
        async def infer(self, image):
            return ManipulationOutput(
                score=self.value,
                map=Image.new("F", image.size, 0.8),
                conf=None,
                imgsize=(image.height, image.width),
            )

    for score, expected in (
        (FUSED_THRESHOLD - 1e-8, "NO_CLEAR_MANIPULATION_SIGNAL"),
        (FUSED_THRESHOLD, "MANIPULATION_SUSPECTED"),
    ):
        fused = ControlledFused("manipulation", value=score)
        fused.model_name = "FUSED"
        settings = replace(dual_settings(), mode="CURE_FUSED")
        app = create_app(
            settings,
            {"generation": ControlledCuRe(), "manipulation": fused},
        )
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.post(ENDPOINT, files=request_parts(), headers=headers)
        assert response.status_code == 200
        result = response.json()["manipulation"]
        assert result["modelName"] == "FUSED"
        assert result["decision"] == expected
        assert result["localization"]["coordinateSpace"] == "ANALYSIS_IMAGE"
