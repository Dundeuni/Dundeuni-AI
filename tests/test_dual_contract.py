"""Dual-mode contracts with controlled model outputs, not accuracy claims."""

import base64
import io

from conftest import request_parts
from PIL import Image
from starlette.testclient import TestClient
from test_cure_contract import ControlledCuRe

from image_analysis.adapters import MockAdapter
from image_analysis.app import ENDPOINT, create_app
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
