"""Explicit legacy binary FE compatibility checks; not the default pilot policy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn

from image_analysis.app import ENDPOINT, create_app
from image_analysis.cure import CureAdapter, cure_settings, resolve_cure_root
from image_analysis.service import timestamp, utc_now

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "validation/cure-legacy-binary-live-20261012.json"
)


async def main() -> None:
    asset_root = resolve_cure_root()
    manifest = json.loads(
        (asset_root / "runs/20261012_qwen_p0_pilot/manifest.json").read_text("utf-8")
    )
    old = [
        json.loads(line)
        for line in (asset_root / "runs/20261012_qwen_p0_pilot/cure_fresh.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    cache = {row["id"]: row for row in old}
    selected = []
    for label, kind in [
        (0, "original"),
        (1, "original"),
        (0, "photo_crop"),
        (1, "photo_crop"),
    ]:
        selected.append(
            next(
                row
                for row in manifest["rows"]
                if row["variant"] == "native"
                and row["label"] == label
                and row["input_type"] == kind
            )
        )
    # Include known positive-output paths as functional cases, not accuracy selection.
    for kind in ("original", "photo_crop"):
        selected.append(
            next(
                row
                for row in manifest["rows"]
                if row["variant"] == "native"
                and row["input_type"] == kind
                and row["label"] == 1
                and cache[row["id"]]["score"] >= 0.5
            )
        )
    # The current four-field BE interface cannot carry an inconclusive null score.
    # Pilot defaults are tested by test_signal_policy.py and validate_dual_live.py.
    settings = replace(cure_settings(), hold_enabled=False, fe_compatibility=True)
    adapter = CureAdapter(asset_root)
    app = create_app(settings, {"generation": adapter})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    server_task = asyncio.create_task(server.serve(sockets=[sock]))
    rows = []
    started = time.monotonic()
    try:
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("Server did not start")
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=150
        ) as client:
            health = (await client.get("/healthz")).json()
            assert health["mode"] == "CURE"
            for index, row in enumerate(selected):
                path = Path(row["path"])
                data = path.read_bytes()
                assert hashlib.sha256(data).hexdigest() == row["sha256"]
                mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
                adapter.reference = path
                fields = {
                    "analysisId": str(uuid4()),
                    "elementId": str(uuid4()),
                    "sourceType": "SCREEN_CROP"
                    if row["input_type"] == "photo_crop"
                    else "IMAGE",
                    "deadlineAt": timestamp(utc_now() + timedelta(seconds=145)),
                }
                t = time.monotonic()
                response = await client.post(
                    ENDPOINT,
                    data=fields,
                    files={"file": (path.name, data, mime)},
                    headers={
                        "X-Request-ID": str(uuid4()),
                        "Authorization": "Bearer MOCK_ONLY_NOT_A_SECRET",
                    },
                )
                payload = response.json()
                assert response.status_code == 200, payload
                result = payload["generation"]
                assert result["status"] == "SUCCEEDED", payload
                assert payload["manipulation"] is None
                assert payload["requestedModels"] == ["generation"]
                assert payload["analysisImage"]["inputSha256"] == row["sha256"]
                actual, expected = (
                    result["rawScore"]["score"],
                    cache[row["id"]]["score"],
                )
                assert abs(actual - expected) <= 1e-5, (actual, expected)
                assert adapter.last_metrics["preprocessingMaxAbsDifference"] == 0.0
                assert result["displayScore"] == math.floor(actual * 100 + 0.5)
                assert result["decision"] == (
                    "AI_GENERATED_SUSPECTED"
                    if actual >= 0.5
                    else "NO_CLEAR_GENERATION_SIGNAL"
                )
                assert adapter.process is None
                entry = {
                    "id": row["id"],
                    "label": row["label"],
                    "mime": mime,
                    "sha256": row["sha256"],
                    "seconds": time.monotonic() - t,
                    "cachedScore": expected,
                    "apiScore": actual,
                    "difference": abs(actual - expected),
                    "worker": adapter.last_metrics,
                    "response": payload,
                }
                rows.append(entry)
                print(
                    f"{row['id']}: score={actual:.8f}; "
                    f"parity={entry['difference']:.2g}; {entry['seconds']:.2f}s",
                    flush=True,
                )
                if index == 0:
                    # FE exact request, actual CuRe, current BE-style 202 response.
                    fe = await client.post(
                        "/api/analysis",
                        data={"type": "IMAGE"},
                        files={"file": (path.name, data, mime)},
                    )
                    body = fe.json()
                    assert fe.status_code == 202, body
                    assert body["code"] == "ANALYSIS202" and body["isSuccess"] is True
                    assert body["result"]["status"] == "COMPLETED"
                    assert body["result"]["aiGenerationScore"] == result["displayScore"]
                    assert body["result"]["modelVersion"] == result["modelVersion"]
                    entry["feCompatibilityResponse"] = body
            node = await asyncio.create_subprocess_exec(
                "node",
                str(OUTPUT.parents[1] / "integration/live-provider-check.mjs"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            message = json.dumps(
                {
                    "origin": f"http://127.0.0.1:{port}",
                    "path": str(path),
                    "mime": mime,
                    "expectedScore": result["displayScore"],
                }
            ).encode()
            stdout, stderr = await node.communicate(message)
            assert node.returncode == 0, stderr.decode(errors="replace")
            node_result = json.loads(stdout)
            print("PASS: Node BE-provider client -> actual CuRe HTTP/GPU", flush=True)
            # Exercise actual Windows worker cancellation and reap the owned tree.
            app.state.service.settings = replace(settings, model_timeout_seconds=0.1)
            expired = await client.post(
                ENDPOINT,
                data=fields,
                files={"file": (path.name, data, mime)},
                headers={
                    "X-Request-ID": str(uuid4()),
                    "Authorization": "Bearer MOCK_ONLY_NOT_A_SECRET",
                },
            )
            assert expired.json()["generation"]["errorCode"] == "MODEL_TIMEOUT"
            assert adapter.process is None
            print("PASS: actual worker timeout, child tree reaped", flush=True)
            invalid = await client.post(
                "/api/analysis",
                data={"type": "IMAGE"},
                files={"file": ("bad.png", b"bad", "image/png")},
            )
            assert invalid.status_code == 415 and invalid.json()["result"] is None
    finally:
        server.should_exit = True
        await server_task
        sock.close()
        await adapter.recover()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "passed",
        "finishedAt": timestamp(utc_now()),
        "rows": rows,
        "realGpuCalls": len(selected) + 2,
        "nodeProviderResult": node_result,
        "workerTimeoutReaped": adapter.process is None,
        "selection": (
            "existing JPEG/PNG and known positive-score functional paths; "
            "not an accuracy evaluation"
        ),
        "mode": "CURE",
        "modelVersion": adapter.model_version,
        "manifest": adapter.manifest,
        "seconds": time.monotonic() - started,
        "ownedWorkersReaped": adapter.process is None,
        "realBE": False,
        "androidUI": False,
        "serverStopped": True,
    }
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), "utf-8"
    )
    print(
        f"PASS: {len(rows)} parity cases + FE-shaped HTTP request; server stopped.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
