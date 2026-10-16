from dataclasses import replace

from conftest import image_bytes, request_parts
from starlette.testclient import TestClient
from test_cure_contract import ControlledCuRe

from image_analysis.adapters import ServiceAuthenticator
from image_analysis.app import ENDPOINT, create_app
from image_analysis.cure import cure_settings


def test_compatibility_disabled_by_default():
    app = create_app(cure_settings(), {"generation": ControlledCuRe()})
    with TestClient(app) as client:
        response = client.post("/api/analysis")
    assert response.status_code == 404


def test_service_token_is_required_when_configured(headers):
    app = create_app(
        cure_settings(),
        {"generation": ControlledCuRe()},
        ServiceAuthenticator("TEST_NOT_A_SECRET"),
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert (
            client.post(ENDPOINT, files=request_parts(), headers=headers).status_code
            == 401
        )
        headers["Authorization"] = "Bearer TEST_NOT_A_SECRET"
        assert (
            client.post(ENDPOINT, files=request_parts(), headers=headers).status_code
            == 200
        )


def test_compatibility_rejects_remote_client():
    app = create_app(
        replace(cure_settings(), fe_compatibility=True),
        {"generation": ControlledCuRe()},
    )
    with TestClient(app, client=("192.0.2.1", 50000)) as client:
        response = client.post(
            "/api/analysis",
            data={"type": "IMAGE"},
            files={"file": ("p.png", image_bytes(), "image/png")},
        )
    assert response.status_code == 403 and response.json()["result"] is None
