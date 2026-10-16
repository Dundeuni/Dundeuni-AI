from __future__ import annotations

import argparse
import io
import json
import os
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from PIL import Image

from image_analysis.app import ENDPOINT
from image_analysis.service import timestamp, utc_now


def main() -> None:
    parser = argparse.ArgumentParser(
        description="합성 이미지로 localhost API 기능 확인"
    )
    parser.add_argument("--origin", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--models", choices=["ALL", "GENERATION", "MANIPULATION"], default="GENERATION"
    )
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != "http" or origin.hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        parser.error("HTTP localhost origin만 허용합니다.")
    if origin.username or origin.password or origin.query or origin.fragment:
        parser.error("인증·query·fragment를 포함할 수 없습니다.")
    with Image.new("RGB", (64, 48), "gray") as synthetic:
        buffer = io.BytesIO()
        synthetic.save(buffer, format="PNG")
    fields = {
        "analysisId": "8c1b24c0-3186-4ee5-a679-74acb055b001",
        "elementId": "a65d2da5-8ec3-4f89-b066-0f24ce940001",
        "sourceType": "IMAGE",
        "models": args.models,
        "deadlineAt": timestamp(utc_now() + timedelta(seconds=125)),
    }
    with httpx.Client(trust_env=False) as client:
        response = client.post(
            args.origin + ENDPOINT,
            data=fields,
            files={"file": ("synthetic.png", buffer.getvalue(), "image/png")},
            headers={
                "Authorization": "Bearer "
                + os.environ.get("DUNDEUNI_AI_SERVICE_TOKEN", "MOCK_ONLY_NOT_A_SECRET"),
                "X-Request-ID": str(uuid4()),
            },
            timeout=130,
        )
    print(
        f"HTTP {response.status_code} / X-AI-Mode={response.headers.get('X-AI-Mode')}"
    )
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    response.raise_for_status()


if __name__ == "__main__":
    main()
