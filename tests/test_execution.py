from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from conftest import request_headers, request_parts
from PIL import Image
from starlette.testclient import TestClient

from image_analysis.adapters import GenerationOutput, MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.config import Settings
from image_analysis.service import timestamp, utc_now


@pytest.mark.parametrize(
    "fault",
    [
        "map_nan",
        "conf_range",
        "map_size",
        "imgsize",
        "missing",
        "wrong_type",
        "map_missing",
        "conf_missing",
    ],
)
def test_invalid_maps_and_missing_outputs(fault):
    class InvalidAdapter(MockAdapter):
        async def infer(self, image):
            raw = await super().infer(image)
            if fault == "wrong_type":
                raw.map.close()
                raw.conf.close()
                return GenerationOutput(0.5)
            if fault == "map_nan":
                raw.map.putpixel((0, 0), float("nan"))
            if fault == "conf_range":
                raw.conf.putpixel((0, 0), 1.1)
            if fault == "map_size":
                raw.map.close()
                raw.map = Image.new("F", (3, 3), 0.5)
            if fault == "imgsize":
                raw.imgsize = (3, 3)
            if fault == "missing":
                raw.map.close()
                raw.conf.close()
                return None
            if fault == "map_missing":
                raw.map.close()
                raw.map = None
            if fault == "conf_missing":
                raw.conf.close()
                raw.conf = None
            return raw

    with TestClient(
        create_app(
            adapters={
                "manipulation": InvalidAdapter("manipulation"),
            }
        ),
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.post(
            ENDPOINT,
            files=request_parts(
                fields={
                    "models": "MANIPULATION",
                }
            ),
            headers=request_headers(),
        )
    assert response.status_code == 200
    assert response.json()["manipulation"]["errorCode"] == "MODEL_OUTPUT_INVALID"


def test_timeout_waits_for_cleanup_before_slot_release():
    async def scenario():
        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        class SlowAdapter(MockAdapter):
            async def infer(self, image):
                started.set()
                try:
                    await asyncio.sleep(10)
                finally:
                    cleanup_started.set()
                    await cleanup_release.wait()

        app = create_app(
            replace(Settings(), model_timeout_seconds=0.02),
            {
                "generation": SlowAdapter("generation"),
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            request = asyncio.create_task(
                client.post(
                    ENDPOINT,
                    files=request_parts(fields={"models": "GENERATION"}),
                    headers=request_headers(),
                )
            )
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.wait_for(cleanup_started.wait(), 2)
            busy = await client.post(
                ENDPOINT, files=request_parts(), headers=request_headers()
            )
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "AI_BUSY"
            assert not request.done()
            cleanup_release.set()
            response = await asyncio.wait_for(request, 2)
            assert response.json()["generation"]["errorCode"] == "MODEL_TIMEOUT"
            app.state.service.adapters["generation"] = MockAdapter("generation")
            response = await client.post(
                ENDPOINT,
                files=request_parts(fields={"models": "GENERATION"}),
                headers=request_headers(),
            )
            assert response.json()["status"] == "COMPLETED"

    asyncio.run(scenario())


def test_deadline_after_acceptance_keeps_completed_first_model():
    now = utc_now()

    class AdvancingAdapter(MockAdapter):
        async def infer(self, image):
            nonlocal now
            raw = await super().infer(image)
            # First result has budget; next clock read exhausts it.
            return raw

    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return now + (timedelta(seconds=2) if calls >= 5 else timedelta())

    manipulation = MockAdapter("manipulation")
    app = create_app(
        adapters={
            "generation": AdvancingAdapter("generation"),
            "manipulation": manipulation,
        },
        clock=clock,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            ENDPOINT,
            headers=request_headers(),
            files=request_parts(
                fields={
                    "deadlineAt": timestamp(now + timedelta(seconds=1)),
                }
            ),
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PARTIAL_FAILED"
    assert payload["generation"]["status"] == "SUCCEEDED"
    assert payload["manipulation"]["errorCode"] == "REQUEST_DEADLINE_EXCEEDED"
    assert manipulation.calls == 0


def test_unsafe_recovery_blocks_next_model_and_future_requests():
    second = MockAdapter("manipulation")
    app = create_app(
        adapters={
            "generation": MockAdapter(
                "generation", failure="MODEL_OUT_OF_MEMORY", recovery_safe=False
            ),
            "manipulation": second,
        }
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            ENDPOINT, files=request_parts(), headers=request_headers()
        )
        assert response.status_code == 200
        assert (
            response.json()["manipulation"]["errorCode"] == "MODEL_RUNTIME_UNAVAILABLE"
        )
        assert second.calls == 0
        response = client.post(
            ENDPOINT, files=request_parts(), headers=request_headers()
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_unclassified_exception_is_sanitized():
    class ExplodingAdapter(MockAdapter):
        async def infer(self, image):
            raise RuntimeError("private filename token path image content")

    with TestClient(
        create_app(
            adapters={
                "generation": ExplodingAdapter("generation"),
            }
        ),
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.post(
            ENDPOINT,
            headers=request_headers(),
            files=request_parts(fields={"models": "GENERATION"}),
        )
    assert response.status_code == 200
    assert "private filename" not in response.text
    assert response.json()["generation"]["errorCode"] == "MODEL_EXECUTION_FAILED"


def test_response_size_transport_failure():
    with TestClient(
        create_app(replace(Settings(), max_response_bytes=10)),
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.post(
            ENDPOINT, files=request_parts(), headers=request_headers()
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
