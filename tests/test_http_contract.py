from __future__ import annotations

import base64
import hashlib
import io
import math
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from conftest import image_bytes, request_parts
from PIL import Image
from starlette.testclient import TestClient

from image_analysis.adapters import MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.config import Settings
from image_analysis.schemas import Envelope
from image_analysis.service import timestamp, utc_now


def client_for(settings=None, adapters=None):
    return TestClient(create_app(settings, adapters), client=("127.0.0.1", 50000))


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {"requestId", "analysisId", "elementId", "error"}
    assert payload["error"]["code"] == code
    assert response.headers["X-Request-ID"] == payload["requestId"]
    assert response.headers["X-AI-Mode"] == "MOCK"
    assert set(payload["error"]) == {"code", "message", "retryable"}
    return payload


def test_success_envelope_and_grayscale_map(headers):
    data = image_bytes()
    with client_for() as client:
        response = client.post(ENDPOINT, files=request_parts(data), headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    Envelope.model_validate(payload)
    assert payload["requestedModels"] == ["generation", "manipulation"]
    assert payload["status"] == "COMPLETED"
    assert payload["generation"]["displayScore"] == 90
    assert payload["manipulation"]["displayScore"] == 80
    assert payload["generation"]["localization"] is None
    assert payload["analysisImage"]["inputSha256"] == hashlib.sha256(data).hexdigest()
    assert response.headers["X-Request-ID"] == headers["X-Request-ID"]
    assert payload["completedAt"].endswith("Z")
    for kind in payload["requestedModels"]:
        result = payload[kind]
        assert result["modelVersion"].startswith("MOCK-")
        assert result["policyVersion"].startswith("MOCK-")
        assert result["error"] is None and result["errorCode"] is None
        assert "MOCK" in result["limitations"][0]
    loc = payload["manipulation"]["localization"]
    with Image.open(io.BytesIO(base64.b64decode(loc["data"], validate=True))) as png:
        assert png.mode == "L" and png.size == (64, 48)
        assert png.getpixel((0, 0)) == 204
    assert loc["imageSize"] == loc["mapSize"] == {"width": 64, "height": 48}


@pytest.mark.parametrize(
    "kind,value,decision,score",
    [
        ("generation", 0, "INCONCLUSIVE", None),
        ("generation", -1000, "NO_CLEAR_GENERATION_SIGNAL", 0),
        ("generation", 1000, "AI_GENERATED_SUSPECTED", 100),
        ("manipulation", 0.4, "INCONCLUSIVE", None),
        ("manipulation", 0.6, "INCONCLUSIVE", None),
        ("manipulation", 0.3999, "NO_CLEAR_MANIPULATION_SIGNAL", 40),
        ("manipulation", 0.6001, "MANIPULATION_SUSPECTED", 60),
    ],
)
def test_hold_boundary_and_rounding(headers, kind, value, decision, score):
    adapter = MockAdapter(kind, value=value)
    with client_for(adapters={kind: adapter}) as client:
        response = client.post(
            ENDPOINT,
            files=request_parts(fields={"models": kind.upper()}),
            headers=headers,
        )
    payload = response.json()
    assert response.status_code == 200 and payload["status"] == "COMPLETED"
    result = payload[kind]
    assert result["status"] == "SUCCEEDED" and result["decision"] == decision
    assert result["displayScore"] == score and result["rawScore"] is not None
    assert result["error"] is None
    assert payload["manipulation" if kind == "generation" else "generation"] is None
    if kind == "manipulation":
        assert result["localization"] is not None  # Holds still carry internal map.


@pytest.mark.parametrize(
    "generation_failure,manipulation_failure,status",
    [
        (None, "MODEL_TIMEOUT", "PARTIAL_FAILED"),
        ("MODEL_OUT_OF_MEMORY", None, "PARTIAL_FAILED"),
        ("MODEL_OUT_OF_MEMORY", "MODEL_EXECUTION_FAILED", "FAILED"),
    ],
)
def test_failures_preserve_other_result(
    headers, generation_failure, manipulation_failure, status
):
    adapters = {
        "generation": MockAdapter("generation", failure=generation_failure),
        "manipulation": MockAdapter("manipulation", failure=manipulation_failure),
    }
    with client_for(adapters=adapters) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    payload = response.json()
    assert response.status_code == 200 and payload["status"] == status
    for kind, failure in (
        ("generation", generation_failure),
        ("manipulation", manipulation_failure),
    ):
        result = payload[kind]
        if failure:
            assert result["status"] == "FAILED"
            assert result["errorCode"] == result["error"]["code"] == failure
            assert result["rawScore"] is result["displayScore"] is None
            assert result["decision"] is result["localization"] is None
            assert result["reasons"] == result["limitations"] == []
        else:
            assert result["status"] == "SUCCEEDED"


@pytest.mark.parametrize(
    "kind,value",
    [
        ("generation", float("nan")),
        ("generation", float("inf")),
        ("manipulation", float("nan")),
        ("manipulation", -0.1),
        ("manipulation", 1.1),
    ],
)
def test_invalid_raw_outputs_are_model_failure(headers, kind, value):
    with client_for(adapters={kind: MockAdapter(kind, value=value)}) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(fields={"models": kind.upper()}),
        )
    assert response.status_code == 200
    assert response.json()[kind]["errorCode"] == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize(
    "authorization,status,code",
    [
        (None, 401, "AUTHENTICATION_FAILED"),
        ("Bearer wrong", 401, "AUTHENTICATION_FAILED"),
        ("Bearer MOCK_DENIED_NOT_A_SECRET", 403, "FORBIDDEN_CALLER"),
    ],
)
def test_auth_before_invalid_body(headers, authorization, status, code):
    headers.pop("Authorization")
    if authorization:
        headers["Authorization"] = authorization
    with client_for() as client:
        response = client.post(ENDPOINT, content=b"malformed", headers=headers)
    payload = assert_error(response, status, code)
    assert payload["analysisId"] is payload["elementId"] is None


@pytest.mark.parametrize(
    "trace",
    [
        None,
        "bad",
        "D5B72AC9-4F31-4A17-8EA0-5D4A53A42B01",
        "8c1b24c0-3186-1ee5-a679-74acb055b001",
    ],
)
def test_invalid_trace_is_replaced(headers, trace):
    headers.pop("X-Request-ID")
    if trace:
        headers["X-Request-ID"] = trace
    with client_for() as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    payload = assert_error(response, 400, "INVALID_REQUEST")
    assert UUID(payload["requestId"]).version == 4


@pytest.mark.parametrize(
    "fields",
    [
        {"analysisId": None},
        {"analysisId": "null"},
        {"analysisId": "BAD"},
        {"elementId": "a65D2da5-8ec3-4f89-b066-0f24ce940001"},
        {"sourceType": "SCREEN"},
        {"sourceType": "null"},
        {"models": "NONE"},
        {"models": "null"},
        {"deadlineAt": "2026-10-09T10:00:00+00:00"},
        {"deadlineAt": "2026-99-99T10:00:00Z"},
        {"deadlineAt": "null"},
        {"sourceType": "가" * 43},
    ],
)
def test_invalid_fields(headers, fields):
    with client_for() as client:
        response = client.post(
            ENDPOINT, files=request_parts(fields=fields), headers=headers
        )
    assert_error(response, 400, "INVALID_REQUEST")


@pytest.mark.parametrize(
    "extra",
    [
        ("fileUrl", (None, "https://example.invalid/image.png")),
        ("analysisId", (None, "8c1b24c0-3186-4ee5-a679-74acb055b001")),
        ("file", ("second.png", image_bytes(), "image/png")),
        ("models", ("not-text.txt", b"ALL", "text/plain")),
    ],
)
def test_unknown_duplicate_and_multiple_files(headers, extra):
    with client_for() as client:
        response = client.post(
            ENDPOINT, files=request_parts() + [extra], headers=headers
        )
    assert_error(response, 400, "INVALID_REQUEST")


def test_query_and_non_multipart_rejected(headers):
    with client_for() as client:
        assert_error(
            client.post(
                ENDPOINT + "?models=ALL", files=request_parts(), headers=headers
            ),
            400,
            "INVALID_REQUEST",
        )
        assert_error(
            client.post(ENDPOINT, json={}, headers=headers), 400, "INVALID_REQUEST"
        )
        assert_error(
            client.post(
                ENDPOINT,
                content=b"bad",
                headers={
                    **headers,
                    "Content-Type": "multipart/form-data",
                },
            ),
            400,
            "INVALID_REQUEST",
        )


def test_expired_deadline_no_model_run(headers):
    adapter = MockAdapter("generation")
    with client_for(adapters={"generation": adapter}) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(
                fields={
                    "models": "GENERATION",
                    "deadlineAt": timestamp(utc_now() - timedelta(seconds=1)),
                }
            ),
        )
    assert_error(response, 422, "DEADLINE_EXPIRED")
    assert adapter.calls == 0


@pytest.mark.parametrize(
    "data,mime,status,code",
    [
        (b"\x89PNG\r\n\x1a\ncorrupt", "image/png", 422, "INVALID_IMAGE"),
        (b"GIF89a" + b"x" * 60, "image/png", 415, "UNSUPPORTED_IMAGE_FORMAT"),
        (image_bytes(), "image/jpeg", 415, "UNSUPPORTED_IMAGE_FORMAT"),
        (image_bytes(size=(31, 32)), "image/png", 422, "IMAGE_TOO_SMALL"),
        (
            image_bytes(size=(32, 32)),
            "application/octet-stream",
            415,
            "UNSUPPORTED_IMAGE_FORMAT",
        ),
    ],
)
def test_image_failures(headers, data, mime, status, code):
    with client_for() as client:
        response = client.post(
            ENDPOINT, files=request_parts(data, mime), headers=headers
        )
    assert_error(response, status, code)


@pytest.mark.parametrize(
    "settings",
    [
        replace(Settings(), max_file_bytes=10),
        replace(Settings(), max_body_bytes=10, max_file_bytes=10),
        replace(Settings(), max_side=40),
        replace(Settings(), max_pixels=1000),
    ],
)
def test_configurable_limits(headers, settings):
    with client_for(settings) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    code = (
        "PAYLOAD_TOO_LARGE" if settings.max_file_bytes == 10 else "IMAGE_LIMIT_EXCEEDED"
    )
    assert_error(response, 413, code)


def test_animated_png_rejected(headers):
    with Image.new("RGB", (64, 48), "red") as first:
        with Image.new("RGB", (64, 48), "blue") as second:
            buffer = io.BytesIO()
            first.save(buffer, format="PNG", save_all=True, append_images=[second])
    with client_for() as client:
        response = client.post(
            ENDPOINT, files=request_parts(buffer.getvalue()), headers=headers
        )
    assert_error(response, 415, "UNSUPPORTED_IMAGE_FORMAT")


def test_exif_rgb_and_white_alpha_shared(headers):
    class RecordingAdapter(MockAdapter):
        async def infer(self, image):
            self.record = (image.mode, image.size, image.getpixel((0, 0)))
            return await super().infer(image)

    adapters = {kind: RecordingAdapter(kind) for kind in ("generation", "manipulation")}
    exif = Image.Exif()
    exif[274] = 6
    data = image_bytes(mode="L", format="JPEG", size=(64, 48), color=120, exif=exif)
    with client_for(adapters=adapters) as client:
        response = client.post(
            ENDPOINT, files=request_parts(data, "image/jpeg"), headers=headers
        )
        assert response.status_code == 200
        assert response.json()["analysisImage"]["width"] == 48
        assert response.json()["analysisImage"]["height"] == 64
        assert adapters["generation"].record == adapters["manipulation"].record
        assert adapters["generation"].record[:2] == ("RGB", (48, 64))
        alpha = image_bytes(mode="RGBA", color=(255, 0, 0, 0))
        response = client.post(ENDPOINT, files=request_parts(alpha), headers=headers)
    assert adapters["generation"].record == ("RGB", (64, 48), (255, 255, 255))
    assert any("알파" in text for text in response.json()["generation"]["limitations"])


def test_localization_resize_and_encoding_failure_preserve_score(headers):
    with client_for() as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(image_bytes(size=(1280, 720))),
        )
    loc = response.json()["manipulation"]["localization"]
    assert loc["mapSize"] == {"width": 1024, "height": 576}
    with client_for(replace(Settings(), localization_max_bytes=1)) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    result = response.json()["manipulation"]
    assert result["status"] == "SUCCEEDED" and result["displayScore"] == 80
    assert result["localization"] is None
    assert any("PNG" in text for text in result["limitations"])
    overall = response.json()["overallResult"]
    assert overall["decision"] == "GENERATION_OR_MANIPULATION_SUSPECTED"
    assert overall["suspectedKinds"] == ["generation", "manipulation"]
    assert overall["uncertainKinds"] == []


def test_model_unavailable_is_pre_execution(headers):
    first = MockAdapter("generation")
    with client_for(
        adapters={
            "generation": first,
            "manipulation": MockAdapter("manipulation", ready=False),
        }
    ) as client:
        response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    assert_error(response, 503, "MODEL_UNAVAILABLE")
    assert response.headers["Retry-After"] == "1" and first.calls == 0


def test_decode_bomb_warning(headers):
    with patch(
        "image_analysis.images.Image.open", side_effect=Image.DecompressionBombWarning
    ):
        with client_for() as client:
            response = client.post(ENDPOINT, files=request_parts(), headers=headers)
    assert_error(response, 413, "IMAGE_LIMIT_EXCEEDED")


def test_version_changes_with_configuration():
    assert Settings().policy_version != replace(Settings(), hold_low=0.3).policy_version
    assert math.isfinite(Settings().model_timeout_seconds)


def test_empty_file_is_invalid_image(headers):
    with client_for() as client:
        response = client.post(ENDPOINT, files=request_parts(b""), headers=headers)
    assert_error(response, 422, "INVALID_IMAGE")


def test_exact_file_limit_and_one_byte_over(headers):
    data = image_bytes()
    settings = replace(Settings(), max_file_bytes=len(data))
    with client_for(settings) as client:
        response = client.post(ENDPOINT, files=request_parts(data), headers=headers)
        assert response.status_code == 200
        response = client.post(
            ENDPOINT, files=request_parts(data + b"x"), headers=headers
        )
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")


def test_screen_crop_and_arbitrary_filename(headers):
    parts = request_parts(fields={"sourceType": "SCREEN_CROP"})
    parts[-1] = ("file", ("ignored.exe", image_bytes(), "image/png"))
    with client_for() as client:
        response = client.post(ENDPOINT, files=parts, headers=headers)
    assert response.status_code == 200
    assert response.json()["sourceType"] == "SCREEN_CROP"


def test_auth_duplicate_headers_rejected(headers):
    with client_for() as client:
        response = client.post(
            ENDPOINT,
            files=request_parts(),
            headers=[
                ("X-Request-ID", headers["X-Request-ID"]),
                ("Authorization", headers["Authorization"]),
                ("Authorization", headers["Authorization"]),
            ],
        )
    assert_error(response, 401, "AUTHENTICATION_FAILED")


def test_palette_transparency_white_composition(headers):
    data = image_bytes(mode="P", color=0, transparency=0)
    with client_for() as client:
        response = client.post(ENDPOINT, files=request_parts(data), headers=headers)
    assert response.status_code == 200
    assert any(
        "알파" in value for value in response.json()["manipulation"]["limitations"]
    )


def test_failed_alpha_model_has_empty_limitations(headers):
    with client_for(
        adapters={
            "generation": MockAdapter(
                "generation",
                failure="MODEL_TIMEOUT",
            )
        }
    ) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(
                image_bytes(mode="RGBA"),
                fields={"models": "GENERATION"},
            ),
        )
    assert response.status_code == 200
    assert response.json()["generation"]["limitations"] == []
