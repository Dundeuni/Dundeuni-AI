"""Real loopback sockets: owned uvicorn thread, no GPU or existing process access."""

from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace

import httpx
import uvicorn
from conftest import request_headers, request_parts

from image_analysis.adapters import MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.config import Settings


@contextmanager
def live_server(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="critical",
            proxy_headers=False,
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        limit = time.monotonic() + 3
        while not server.started and thread.is_alive() and time.monotonic() < limit:
            time.sleep(0.01)
        assert server.started, "owned localhost test server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=3)
        sock.close()
        assert not thread.is_alive(), "owned test server did not exit cleanly"


def test_real_multipart_success_auth_and_busy():
    entered = threading.Event()

    class SignalingAdapter(MockAdapter):
        async def infer(self, image):
            entered.set()
            return await super().infer(image)

    app = create_app(
        adapters={
            "generation": SignalingAdapter("generation", delay_seconds=0.15),
            "manipulation": MockAdapter("manipulation"),
        }
    )
    with (
        live_server(app) as origin,
        httpx.Client(base_url=origin, trust_env=False) as client,
    ):
        assert client.get("/healthz").json()["mode"] == "MOCK"
        denied = client.post(
            ENDPOINT,
            files=request_parts(),
            headers={
                "X-Request-ID": request_headers()["X-Request-ID"],
            },
        )
        assert denied.status_code == 401
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                client.post, ENDPOINT, files=request_parts(), headers=request_headers()
            )
            assert entered.wait(2)
            busy = client.post(
                ENDPOINT, files=request_parts(), headers=request_headers()
            )
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "AI_BUSY"
            assert busy.headers["Retry-After"] == "1"
            response = first.result(timeout=3)
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
        response = client.post(
            ENDPOINT,
            headers=request_headers(),
            files=request_parts(fields={"models": "MANIPULATION"}),
        )
        assert response.json()["generation"] is None


def test_real_chunked_body_actual_limit_and_slot_recovery():
    settings = replace(Settings(), max_file_bytes=1024, max_body_bytes=1024)
    with live_server(create_app(settings)) as origin:
        with httpx.Client(base_url=origin, trust_env=False) as client:
            response = client.post(
                ENDPOINT,
                content=iter([b"x" * 700, b"y" * 700]),
                headers=request_headers(),
            )
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
            response = client.post(
                ENDPOINT, files=request_parts(), headers=request_headers()
            )
            assert response.status_code == 200


def test_real_model_timeout_partial_result():
    app = create_app(
        replace(Settings(), model_timeout_seconds=0.02),
        {
            "generation": MockAdapter("generation"),
            "manipulation": MockAdapter("manipulation", delay_seconds=0.1),
        },
    )
    with (
        live_server(app) as origin,
        httpx.Client(base_url=origin, trust_env=False) as client,
    ):
        response = client.post(
            ENDPOINT, files=request_parts(), headers=request_headers()
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PARTIAL_FAILED"
    assert payload["generation"]["status"] == "SUCCEEDED"
    assert payload["manipulation"]["errorCode"] == "MODEL_TIMEOUT"
