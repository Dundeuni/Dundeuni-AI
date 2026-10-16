from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image
from starlette.testclient import TestClient

from image_analysis.adapters import MockAdapter, ModelAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.schemas import Envelope, ModelKind
from image_analysis.service import timestamp, utc_now


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "examples"
    output_dir.mkdir(exist_ok=True)
    buffer = io.BytesIO()
    with Image.new("RGB", (64, 48), "gray") as image:
        image.save(buffer, format="PNG")
    suspected = "GENERATION_OR_MANIPULATION_SUSPECTED"
    scenarios: dict[str, tuple[float, float, str | None, str | None, str, str]] = {
        "completed": (2.197224577, 0.8, None, None, "ALL", suspected),
        "inconclusive": (0, 0.8, None, None, "ALL", suspected),
        "both_inconclusive": (0, 0.5, None, None, "ALL", "INCONCLUSIVE"),
        "no_clear_signal": (-10, 0.1, None, None, "ALL", "NO_CLEAR_SIGNAL"),
        "partial_failed": (2.197224577, 0.8, None, "MODEL_TIMEOUT", "ALL", suspected),
        "failed": (
            0,
            0.8,
            "MODEL_OUT_OF_MEMORY",
            "MODEL_EXECUTION_FAILED",
            "ALL",
            "INCONCLUSIVE",
        ),
        "manipulation_only": (0, 0.8, None, None, "MANIPULATION", suspected),
    }
    for name, (
        value,
        manipulation_value,
        first_error,
        second_error,
        models,
        expected_overall,
    ) in scenarios.items():
        adapters: dict[ModelKind, ModelAdapter] = {
            "generation": MockAdapter("generation", value=value, failure=first_error),
            "manipulation": MockAdapter(
                "manipulation", value=manipulation_value, failure=second_error
            ),
        }
        headers = {
            "Authorization": "Bearer MOCK_ONLY_NOT_A_SECRET",
            "X-Request-ID": str(uuid4()),
        }
        fields = {
            "analysisId": "8c1b24c0-3186-4ee5-a679-74acb055b001",
            "elementId": "a65d2da5-8ec3-4f89-b066-0f24ce940001",
            "sourceType": "SCREEN_CROP",
            "models": models,
            "deadlineAt": timestamp(utc_now() + timedelta(seconds=30)),
        }
        with TestClient(
            create_app(adapters=adapters), client=("127.0.0.1", 50000)
        ) as client:
            response = client.post(
                ENDPOINT,
                data=fields,
                headers=headers,
                files={"file": ("synthetic.png", buffer.getvalue(), "image/png")},
            )
        response.raise_for_status()
        envelope = Envelope.model_validate(response.json())
        assert response.headers["X-AI-Mode"] == "MOCK"
        assert envelope.overallResult.decision == expected_overall
        (output_dir / f"{name}.json").write_text(
            json.dumps(response.json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if name == "completed":
            request_example = {
                "method": "POST",
                "path": ENDPOINT,
                "contentType": "multipart/form-data (boundary는 클라이언트 생성)",
                "headers": headers,
                "textFields": fields,
                "filePart": {
                    "field": "file",
                    "mimeType": "image/png",
                    "note": "64x48 합성 회색 이미지의 바이너리 파일 part",
                },
            }
            (output_dir / "request-description.json").write_text(
                json.dumps(request_example, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
