"""Real dual-model HTTP and map decoding check on synthetic input."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import socket
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from PIL import Image

from image_analysis.app import ENDPOINT, create_app
from image_analysis.cure import CureAdapter
from image_analysis.schemas import Envelope
from image_analysis.service import timestamp, utc_now
from image_analysis.trufor import TruForAdapter, dual_settings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-prefix", default="dual-overall-result-20261013")
    args = parser.parse_args()
    if Path(args.output_prefix).name != args.output_prefix:
        parser.error("output-prefix must be a filename prefix")
    root = Path(__file__).resolve().parents[1]
    cure = CureAdapter(Path(os.environ["DUNDEUNI_CURE_ROOT"]))
    trufor = TruForAdapter(Path(os.environ["DUNDEUNI_TRUFOR_ROOT"]))
    app = create_app(dual_settings(), {"generation": cure, "manipulation": trufor})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("Server did not start")
            await asyncio.sleep(0.01)
        image_bytes = io.BytesIO()
        with Image.new("RGB", (256, 192), (40, 80, 130)) as image:
            for y in range(48, 144):
                for x in range(64, 192):
                    image.putpixel((x, y), (180, 60, 30))
            image.save(image_bytes, format="PNG")
        async with httpx.AsyncClient(trust_env=False, timeout=250) as client:
            response = await client.post(
                f"http://127.0.0.1:{sock.getsockname()[1]}{ENDPOINT}",
                headers={
                    "Authorization": "Bearer MOCK_ONLY_NOT_A_SECRET",
                    "X-Request-ID": str(uuid4()),
                },
                data={
                    "analysisId": str(uuid4()),
                    "elementId": str(uuid4()),
                    "sourceType": "IMAGE",
                    "models": "ALL",
                    "deadlineAt": timestamp(utc_now() + timedelta(seconds=245)),
                },
                files={"file": ("synthetic.png", image_bytes.getvalue(), "image/png")},
            )
        body = response.json()
        assert response.status_code == 200, body
        Envelope.model_validate(body)
        assert body["status"] == "COMPLETED", body
        assert body["generation"]["modelName"] == "CuRe"
        assert body["manipulation"]["modelName"] == "TruFor"
        location = body["manipulation"]["localization"]
        assert location["imageSize"] == {"width": 256, "height": 192}
        assert location["coordinateSpace"] == "ANALYSIS_IMAGE"
        output = root / "validation"
        output.mkdir(exist_ok=True)
        png = base64.b64decode(location["data"], validate=True)
        with Image.open(io.BytesIO(png)) as image:
            assert image.format == "PNG" and image.mode == "L"
            assert image.size == (256, 192)
            extrema = image.getextrema()
        (output / f"{args.output_prefix}-localization.png").write_bytes(png)
        assert cure.process is None and trufor.process is None
        results = {}
        for kind, low, high, absent, suspected in (
            (
                "generation",
                0.000004,
                0.02,
                "NO_CLEAR_GENERATION_SIGNAL",
                "AI_GENERATED_SUSPECTED",
            ),
            (
                "manipulation",
                0.12,
                0.70,
                "NO_CLEAR_MANIPULATION_SIGNAL",
                "MANIPULATION_SUSPECTED",
            ),
        ):
            result = body[kind]
            value = result["rawScore"]["score"]
            expected = (
                absent
                if value < low
                else suspected
                if value >= high
                else "INCONCLUSIVE"
            )
            assert result["decision"] == expected
            expected_label = {
                "NO_CLEAR_GENERATION_SIGNAL": "뚜렷한 AI 생성 신호 없음",
                "AI_GENERATED_SUSPECTED": "AI 생성 의심",
                "NO_CLEAR_MANIPULATION_SIGNAL": "뚜렷한 변조 신호 없음",
                "MANIPULATION_SUSPECTED": "변조 의심",
                "INCONCLUSIVE": "판단 불가",
            }[expected]
            assert result["decisionLabel"] == expected_label
            assert result["policyVersion"] == dual_settings().policy_version
            assert (result["displayScore"] is None) == (expected == "INCONCLUSIVE")
            results[kind] = {
                key: result[key]
                for key in (
                    "rawScore",
                    "displayScore",
                    "decision",
                    "decisionLabel",
                    "policyVersion",
                    "modelVersion",
                )
            }
        suspected = [
            kind
            for kind, result in results.items()
            if result["decision"]
            in ("AI_GENERATED_SUSPECTED", "MANIPULATION_SUSPECTED")
        ]
        uncertain = [
            kind
            for kind, result in results.items()
            if result["decision"] == "INCONCLUSIVE"
        ]
        expected_overall = (
            ("GENERATION_OR_MANIPULATION_SUSPECTED", "생성·변조 의심")
            if suspected
            else ("INCONCLUSIVE", "판단 불가")
            if uncertain
            else ("NO_CLEAR_SIGNAL", "뚜렷한 신호 없음")
        )
        overall = body["overallResult"]
        assert (overall["decision"], overall["decisionLabel"]) == expected_overall
        assert overall["suspectedKinds"] == suspected
        assert overall["uncertainKinds"] == uncertain
        assert overall["policyVersion"] == "image-overall-v1"
        # No image payloads or private dataset identifiers in the summary.
        report = {
            "passed": True,
            "input": "synthetic PNG 256x192",
            "status": body["status"],
            "localizationSize": location["mapSize"],
            "pixelRange": extrema,
            "workersCleaned": True,
            "purpose": "connection and coordinates, not localization accuracy",
            "modelResults": results,
            "overallResult": overall,
        }
        (output / f"{args.output_prefix}-live.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
        )
        print("CuRe + TruFor real GPU / HTTP / PNG coordinates: passed")
    finally:
        server.should_exit = True
        await task


if __name__ == "__main__":
    asyncio.run(main())
