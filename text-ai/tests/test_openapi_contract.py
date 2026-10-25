"""Compare the declared contract with HTTP responses without loading a model."""

from collections.abc import Iterator
import json
from pathlib import Path
import threading
from typing import Any
from uuid import UUID, uuid1, uuid4

from fastapi.testclient import TestClient
from httpx import Response
import pytest

from ai_text.api import API_PATH, ErrorResponse, HealthResponse, create_app
from ai_text.api_service import ServiceError, TextRiskService

TOKEN = "openapi-contract-test-only"
AUTH = {"Authorization": "Bearer " + TOKEN}


class ContractService(TextRiskService):
    """Use the production admission gate while forbidding model inference."""

    def __init__(self) -> None:
        self.model_version = "contract-test-model"
        self.device = "cpu"
        self.ocr_available = False
        self._gate = threading.Lock()

    def _infer(
        self, text: str, body: dict[str, Any] | None, started: float | None = None
    ) -> dict[str, Any]:
        raise AssertionError("Contract error tests must not run inference")


@pytest.fixture
def service() -> ContractService:
    return ContractService()


@pytest.fixture
def client(service: ContractService) -> Iterator[TestClient]:
    app = create_app(lambda: service, token=TOKEN)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _assert_error(response: Response, status: int, code: str) -> ErrorResponse:
    assert response.status_code == status
    parsed = ErrorResponse.model_validate(response.json())
    assert parsed.error.code == code
    assert parsed.error.message
    assert set(response.json()) == {"error", "requestId"}
    assert set(response.json()["error"]) == {"code", "message"}
    return parsed


def test_validation_error_uses_declared_error_envelope(client: TestClient) -> None:
    identifier = str(uuid4())
    response = client.post(
        API_PATH, headers={**AUTH, "X-Request-ID": identifier}, json={}
    )
    error = _assert_error(response, 422, "INVALID_REQUEST")
    assert str(error.requestId) == identifier == response.headers["X-Request-ID"]


@pytest.mark.parametrize("credentials", [None, "Bearer wrong"])
def test_unauthorized_body_and_headers_match_schema(
    client: TestClient, credentials: str | None
) -> None:
    headers = {"Authorization": credentials} if credentials else {}
    response = client.post(API_PATH, headers=headers, json={"text": "예약 안내"})
    error = _assert_error(response, 401, "UNAUTHORIZED")
    assert str(error.requestId) == response.headers["X-Request-ID"]
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "Retry-After" not in response.headers


def test_busy_503_has_retry_after_only_for_busy(
    client: TestClient, service: ContractService
) -> None:
    service._gate.acquire()
    try:
        response = client.post(API_PATH, headers=AUTH, json={"text": "예약 안내"})
    finally:
        service._gate.release()
    error = _assert_error(response, 503, "ANALYZER_BUSY")
    assert str(error.requestId) == response.headers["X-Request-ID"]
    assert response.headers["Retry-After"] == "2"


def test_unexpected_503_does_not_guarantee_request_or_retry_headers(
    client: TestClient, service: ContractService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_text: str) -> None:
        raise RuntimeError("internal failure")

    monkeypatch.setattr(service, "analyze_text", fail)
    identifier = str(uuid4())
    response = client.post(
        API_PATH,
        headers={**AUTH, "X-Request-ID": identifier},
        json={"text": "예약 안내"},
    )
    error = _assert_error(response, 503, "ANALYSIS_FAILED")
    assert str(error.requestId) == identifier
    assert "X-Request-ID" not in response.headers
    assert "Retry-After" not in response.headers


@pytest.mark.parametrize("path", ["/healthz", API_PATH, API_PATH + "/image"])
@pytest.mark.parametrize("invalid_id", ["invalid", str(uuid1())])
def test_invalid_request_id_uses_new_uuid_without_echo(
    client: TestClient, path: str, invalid_id: str
) -> None:
    headers = {**AUTH, "X-Request-ID": invalid_id}
    if path == "/healthz":
        response = client.get(path, headers=headers)
    else:
        response = client.post(path, headers=headers, json={})
    error = _assert_error(response, 422, "INVALID_REQUEST_ID")
    assert str(error.requestId) != invalid_id
    assert UUID(str(error.requestId)).version == 4
    assert "X-Request-ID" not in response.headers


@pytest.mark.parametrize(
    "status,code",
    [
        (413, "IMAGE_TOO_LARGE"),
        (415, "UNSUPPORTED_IMAGE"),
        (422, "INVALID_IMAGE"),
        (502, "OCR_FAILED"),
        (503, "OCR_UNAVAILABLE"),
        (504, "OCR_TIMEOUT"),
    ],
)
def test_image_service_errors_use_envelope_and_conditional_headers(
    client: TestClient,
    service: ContractService,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
) -> None:
    def reject(_data: bytes, _content_type: str) -> None:
        raise ServiceError(status, code, "Contract test service error")

    monkeypatch.setattr(service, "analyze_image", reject)
    response = client.post(
        API_PATH + "/image",
        headers=AUTH,
        files={"file": ("test.png", b"stub", "image/png")},
    )
    error = _assert_error(response, status, code)
    assert str(error.requestId) == response.headers["X-Request-ID"]
    assert "Retry-After" not in response.headers


def test_health_response_has_the_four_declared_fields(
    client: TestClient, service: ContractService
) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    health = HealthResponse.model_validate(response.json())
    assert response.json() == {
        "status": "ready",
        "modelVersion": service.model_version,
        "device": "cpu",
        "ocrWorkerAvailable": False,
    }
    assert health.status == "ready"
    assert UUID(response.headers["X-Request-ID"]).version == 4


def test_openapi_generated_without_startup_matches_saved_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_factory() -> None:
        raise AssertionError("OpenAPI generation must not initialize a service")

    monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
    schema = create_app(service_factory=forbidden_factory).openapi()
    saved = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    assert schema == json.loads(saved.read_text(encoding="utf-8"))

    components = schema["components"]["schemas"]
    assert "HTTPValidationError" not in components
    assert "ValidationError" not in components
    assert set(components["ErrorResponse"]["required"]) == {"error", "requestId"}
    assert set(components["ErrorDetail"]["required"]) == {"code", "message"}
    assert components["ErrorResponse"]["properties"]["requestId"]["format"] == (
        "uuid4"
    )
    assert set(components["HealthResponse"]["required"]) == {
        "status", "modelVersion", "device", "ocrWorkerAvailable"
    }

    expected_statuses = {
        "/healthz": {"200", "422", "503"},
        API_PATH: {"200", "401", "413", "422", "503"},
        API_PATH + "/image": {
            "200", "401", "413", "415", "422", "502", "503", "504"
        },
    }
    for path, expected in expected_statuses.items():
        operation = schema["paths"][path]["get" if path == "/healthz" else "post"]
        assert set(operation["responses"]) == expected
        request_id = next(
            item for item in operation["parameters"]
            if item["name"] == "X-Request-ID"
        )
        assert request_id["in"] == "header"
        assert request_id["required"] is False
        assert request_id["schema"]["format"] == "uuid4"
        for status, response in operation["responses"].items():
            headers = response["headers"]
            assert headers["X-Request-ID"]["schema"]["format"] == "uuid4"
            if status != "200":
                assert response["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/ErrorResponse"
                }
            if status == "401":
                assert headers["WWW-Authenticate"]["schema"]["const"] == "Bearer"
            if status == "503" and path != "/healthz":
                assert headers["Retry-After"]["schema"]["const"] == "2"
                assert "only for ANALYZER_BUSY" in (
                    headers["Retry-After"]["description"]
                )
            else:
                assert "Retry-After" not in headers

    health = schema["paths"]["/healthz"]["get"]["responses"]["200"]
    assert health["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
