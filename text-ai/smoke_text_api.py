"""Real local HTTP checks for the text-risk API. Never sends requests to BE."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

import httpx


ROOT = Path(__file__).resolve().parent
ENDPOINT = "/internal/v1/text-analyses"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_error(response: httpx.Response, status: int, request_id: str) -> dict:
    require(response.status_code == status, f"Expected HTTP {status}; got {response.status_code}")
    body = response.json()
    require(isinstance(body, dict), "Error response must be an object")
    require(body.get("requestId") == request_id, "Error requestId must match the request")
    error = body.get("error")
    require(isinstance(error, dict), "Error object missing")
    require(isinstance(error.get("code"), str) and bool(error["code"]), "Error code missing")
    require(isinstance(error.get("message"), str) and bool(error["message"]), "Error message missing")
    return {"statusCode": status, "errorCode": error["code"]}


def validate_result(response: httpx.Response, request_id: str, source: str,
                    analysis_id: str, element_id: str, punctuation: bool = False) -> dict:
    require(response.status_code == 200, f"Expected HTTP 200; got {response.status_code}")
    body = response.json()
    require(isinstance(body, dict), "Analysis response must be an object")
    require(body.get("contractVersion") == "text-risk-1.0", "Unexpected contract version")
    require(body.get("requestId") == request_id, "requestId must match the request")
    require(UUID(body["requestId"]).version == 4, "requestId must be UUID4")
    require(body.get("analysisId") == analysis_id, "analysisId was not preserved")
    require(body.get("elementId") == element_id, "elementId was not preserved")
    require(body.get("sourceType") == source, "Unexpected sourceType")
    require(body.get("status") == "COMPLETED", "Unexpected processing status")
    require(body.get("decision") in ("normal", "phishing", "defer"), "Unknown decision")
    score = body.get("riskScore")
    require(score is None or (type(score) in (int, float) and math.isfinite(score)
                             and 0 <= score <= 1), "riskScore must be null or finite in 0..1")
    require(body.get("scoreScale") == "0..1", "Unexpected score scale")
    require(body.get("scoreMeaning") == "UNCALIBRATED_CLASSIFIER_SCORE", "Score meaning missing")
    require(body.get("modelName") == "skt/A.X-Encoder-base", "Unexpected model name")
    require(body.get("modelVersion") == "ax_text_actions-20261016", "Unexpected model version")
    require(body.get("policyVersion") == "action-decision-v1", "Unexpected policy version")
    require(isinstance(body.get("text"), str), "Text field missing")
    require(body.get("evidence") == [], "Baseline must not invent verified evidence")
    limitations = body.get("limitations")
    require(isinstance(limitations, list) and all(isinstance(x, str) for x in limitations),
            "limitations must be a string array")
    elapsed = body.get("processingMs")
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
            "processingMs must be finite and non-negative")
    quality = body.get("quality")
    require(isinstance(quality, dict), "Quality object missing")
    for name in ("needsReview", "ocrUsed", "poorOcrConfidence", "layoutUncertain", "contextDisagreement"):
        require(type(quality.get(name)) is bool, f"Quality flag {name} must be boolean")
    reasons = quality.get("reasonCodes")
    require(isinstance(reasons, list) and all(isinstance(x, str) for x in reasons),
            "Quality reasonCodes must be a string array")
    require(quality["ocrUsed"] == (source != "TEXT"), "Unexpected OCR use flag")
    if any(quality[name] for name in ("poorOcrConfidence", "layoutUncertain", "contextDisagreement")):
        require(body["decision"] != "normal", "Uncertain inputs must not pass as normal")
    if score is None:
        require(body["decision"] == "defer", "Null score must defer")
    if punctuation:
        require(score is None and body["decision"] == "defer", "Punctuation-only input must defer")
    return {"statusCode": 200, "decision": body["decision"], "riskScore": score,
            "modelVersion": body["modelVersion"], "processingMs": elapsed,
            "reasonCodes": reasons}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--image", type=Path, help="Optional PNG/JPEG image for a real OCR request")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results/api-baseline-20261016/http-smoke.json")
    args = parser.parse_args()
    token = os.environ.get("AI_SERVICE_TOKEN", "").strip()
    if not token:
        parser.error("Set AI_SERVICE_TOKEN to the token used by the running AI API.")
    if args.image is not None and not args.image.is_file():
        parser.error("--image must be an existing local PNG/JPEG file.")
    if args.image is not None and args.image.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        parser.error("--image must have a PNG/JPEG extension.")

    checks: list[dict] = []
    timeout = httpx.Timeout(180.0, connect=5.0)
    # Ignore proxy environment variables: the default target is the local AI server.
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=timeout,
                      trust_env=False, follow_redirects=False) as client:
        def check(name, action):
            started = time.perf_counter()
            item = {"check": name}
            try:
                item.update(action())
                item["passed"] = True
            except AssertionError as exc:
                item.update(passed=False, failure=str(exc))
            except Exception as exc:
                # Do not print response bodies, OCR text, tokens, or original inputs.
                item.update(passed=False, failureType=type(exc).__name__)
            item["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
            checks.append(item)
            print(f"{'PASS' if item['passed'] else 'FAIL'} {name}")

        def health():
            response = client.get("/healthz")
            require(response.status_code == 200, f"Expected health HTTP 200; got {response.status_code}")
            require(isinstance(response.json(), dict), "Health response must be an object")
            return {"statusCode": 200}

        def error_case(status, text, authorized):
            request_id = str(uuid4())
            headers = {"X-Request-ID": request_id}
            if authorized:
                headers["Authorization"] = f"Bearer {token}"
            response = client.post(ENDPOINT, json={"text": text}, headers=headers)
            return validate_error(response, status, request_id)

        def text_case(text, punctuation=False):
            request_id, analysis_id, element_id = (str(uuid4()) for _ in range(3))
            response = client.post(ENDPOINT,
                headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id},
                json={"text": text, "analysisId": analysis_id, "elementId": element_id})
            return validate_result(response, request_id, "TEXT", analysis_id, element_id, punctuation)

        def image_case():
            request_id, analysis_id, element_id = (str(uuid4()) for _ in range(3))
            content_type = "image/png" if args.image.suffix.lower() == ".png" else "image/jpeg"
            with args.image.open("rb") as image:
                response = client.post(ENDPOINT + "/image",
                    headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id},
                    data={"analysisId": analysis_id, "elementId": element_id, "sourceType": "IMAGE"},
                    files={"file": ("sample" + args.image.suffix.lower(), image, content_type)})
            return validate_result(response, request_id, "IMAGE", analysis_id, element_id)

        check("health", health)
        check("missing_token_401", lambda: error_case(401, "예약 안내입니다.", False))
        check("whitespace_text_422", lambda: error_case(422, " \n\t ", True))
        check("punctuation_defers", lambda: text_case("!!! ??? …", True))
        check("ordinary_text_schema", lambda: text_case("내일 오후 3시 예약이 완료되었습니다."))
        check("risk_text_schema", lambda: text_case("인증번호를 저에게 알려주세요."))
        if args.image is not None:
            check("uploaded_image_real_ocr", image_case)

    report = {"createdAt": datetime.now(timezone.utc).isoformat(),
              "testType": "REAL_AI_HTTP_CLIENT_SMOKE",
              "actualBeIntegrationTested": False,
              "imageTestIncluded": args.image is not None,
              "modelAccuracyEvaluated": False,
              "originalTextsLogged": False,
              "checks": checks,
              "passed": all(item["passed"] for item in checks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Result: {sum(item['passed'] for item in checks)}/{len(checks)} passed")
    print(f"Report: {args.output.resolve()}")
    print("This checks the AI HTTP API; actual BE integration is not tested.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
