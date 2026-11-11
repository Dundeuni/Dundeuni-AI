"""HyperCLOVAX adapter for the existing text-risk HTTP contract."""

import os
from pathlib import Path
from threading import Lock
from time import perf_counter

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from .api import create_app
from .api_service import MAX_TEXT_CHARS, ServiceError
from .url_reputation import UrlReputationLookup, apply_reputation


class HyperClovaTextService:
    ocr_available = False

    def __init__(self):
        folder = Path(os.environ["AI_TEXT_MODEL_DIR"]).resolve(strict=True)
        self.model_version = folder.name
        self.device = os.environ.get("AI_TEXT_DEVICE", "cuda")
        if self.device not in {"cuda", "cpu"}:
            raise ValueError("AI_TEXT_DEVICE must be cuda or cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            folder, local_files_only=True, torch_dtype=torch.float32,
            low_cpu_mem_usage=True, attn_implementation="sdpa",
        ).eval().to(self.device)
        self.instruction = (folder / "instruction.txt").read_text(encoding="utf-8").strip()
        labels = [self.tokenizer.encode(label, add_special_tokens=False) for label in ("0", "1")]
        if any(len(ids) != 1 for ids in labels):
            raise RuntimeError("Expected one token for each class label")
        self.label_ids = [ids[0] for ids in labels]
        self.gate = Lock()
        self.reputation = UrlReputationLookup.from_env()
        self.analyze_text("요청하신 예약 안내입니다.")

    @torch.inference_mode()
    def _classify(self, text):
        # Same prompt, first label token, and comparison rule as the SMS evaluation.
        prompt = f"{self.instruction}\n문자:{text}\n"
        tokens = self.tokenizer(prompt, return_tensors="pt", truncation=False).input_ids
        if tokens.shape[1] > 1024:
            return "defer", None, ["TEXT_TOKEN_LIMIT_EXCEEDED"]
        if not any(character.isalnum() for character in text):
            return "defer", None, ["NO_ANALYZABLE_TEXT"]
        hidden = self.model.model(input_ids=tokens.to(self.device), use_cache=False).last_hidden_state
        logits = torch.nn.functional.linear(hidden[0, -1], self.model.lm_head.weight[self.label_ids])
        if not torch.isfinite(logits).all():
            raise RuntimeError("Non-finite classification logits")
        return ("phishing" if logits[1] > logits[0] else "normal",
                logits.softmax(dim=0)[1].item(), [])

    def analyze_text(self, text):
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise ServiceError(422, "INVALID_TEXT", "본문은 공백을 제외하고 1자 이상, 전체 4000자 이하여야 합니다.")
        if not self.gate.acquire(blocking=False):
            raise ServiceError(503, "ANALYZER_BUSY", "분석 중입니다. 잠시 후 다시 요청해주세요.")
        try:
            started = perf_counter()
            decision, score, reasons = self._classify(text)
            result = apply_reputation({
                "decision": decision, "riskScore": score, "scoreScale": "0..1",
                "scoreMeaning": "UNCALIBRATED_CLASSIFIER_SCORE",
                "modelName": "naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B",
                "modelVersion": self.model_version, "policyVersion": "hyperclovax-first-label-v1",
                "text": text,
                "quality": {
                    "needsReview": bool(reasons), "reasonCodes": reasons, "ocrUsed": False,
                    "poorOcrConfidence": False, "layoutUncertain": False, "contextDisagreement": False,
                },
                "evidence": [],
                "limitations": ["위험 점수는 실제 사기 확률이 아닙니다."],
            }, self.reputation.assess(text))
            result["processingMs"] = round((perf_counter() - started) * 1000, 2)
            return result
        finally:
            self.gate.release()

    def analyze_image(self, data, content_type):
        raise ServiceError(503, "OCR_UNAVAILABLE", "이 모델 서비스는 직접 입력한 문자 분석을 지원합니다.")


app = create_app(service_factory=HyperClovaTextService)
app.title = "HyperCLOVAX 문자 위험 분석 API"
