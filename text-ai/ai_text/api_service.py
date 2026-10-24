"""Persistent A.X classifier plus an isolated, bounded PaddleOCR worker."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import warnings

from PIL import Image, UnidentifiedImageError

from .url_reputation import UrlReputationLookup, apply_reputation

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_CHARS = 4000
MAX_FILE_BYTES = 10 * 1024 * 1024


class ServiceError(Exception):
    def __init__(self, status, code, message):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def validate_image(data, content_type):
    if not data:
        raise ServiceError(422, 'EMPTY_IMAGE', '이미지 파일이 비어 있습니다.')
    if len(data) > MAX_FILE_BYTES:
        raise ServiceError(413, 'IMAGE_TOO_LARGE', '이미지는 최대 10 MiB입니다.')
    formats = {'image/png': 'PNG', 'image/jpeg': 'JPEG'}
    if content_type not in formats:
        raise ServiceError(415, 'UNSUPPORTED_IMAGE', 'PNG 또는 JPEG 파일을 보내주세요.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != formats[content_type]:
                    raise ServiceError(415, 'IMAGE_TYPE_MISMATCH', '파일 내용과 MIME 형식이 다릅니다.')
                width, height = image.size
                if not (32 <= width <= 8192 and 32 <= height <= 8192) or width * height > 16_000_000:
                    raise ServiceError(422, 'IMAGE_DIMENSIONS', '가로·세로 32~8192px, 총 1600만 픽셀 이하가 필요합니다.')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ServiceError(415, 'ANIMATED_IMAGE', '단일 프레임 이미지를 보내주세요.')
                image.load()
    except ServiceError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ServiceError(422, 'INVALID_IMAGE', '이미지 파일을 읽을 수 없습니다.') from None


class TextRiskService:
    def __init__(self):
        from .action_encoder import ActionEncoder
        configured = os.environ.get('AI_TEXT_MODEL_DIR')
        self.folder = Path(configured) if configured else ROOT / 'models/ax_text_actions-20261016'
        self.model_version = self.folder.name
        self.classifier = ActionEncoder(self.folder)
        self.device = self.classifier.device
        self.ocr_python = ROOT / '.venv/Scripts/python.exe'
        self.ocr_worker = ROOT / 'ai_text/api_ocr_worker.py'
        self.ocr_available = self.ocr_python.is_file() and self.ocr_worker.is_file()
        self.ocr_timeout = int(os.environ.get('AI_OCR_TIMEOUT_SECONDS', '90'))
        if not 1 <= self.ocr_timeout <= 600:
            raise ValueError('AI_OCR_TIMEOUT_SECONDS must be between 1 and 600')
        # Optional external lookup is off by default. Reuse the client to keep
        # provider-expiry cache; analysis retains the existing single-request gate.
        self.url_reputation = UrlReputationLookup.from_env()
        self._gate = threading.Lock()
        # Warm up before the lifespan reports readiness; reuse these weights.
        self.classifier.analyze_text('요청하신 예약 안내입니다.')

    def _acquire(self):
        if not self._gate.acquire(blocking=False):
            raise ServiceError(503, 'ANALYZER_BUSY', '분석 중입니다. 잠시 후 다시 요청해주세요.')

    def analyze_text(self, text):
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise ServiceError(422, 'INVALID_TEXT', '본문은 공백을 제외하고 1자 이상, 전체 4000자 이하여야 합니다.')
        self._acquire()
        try:
            return self._infer(text, None)
        finally:
            self._gate.release()

    def analyze_image(self, data, content_type):
        validate_image(data, content_type)
        if not self.ocr_available:
            raise ServiceError(503, 'OCR_UNAVAILABLE', 'OCR 실행 환경이 준비되지 않았습니다.')
        self._acquire()
        try:
            started = time.perf_counter()
            temp_root = ROOT / 'cache/api-temp'
            temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
                folder = Path(temporary)
                source = folder / ('input.png' if content_type == 'image/png' else 'input.jpg')
                source.write_bytes(data)
                target = folder / 'ocr.json'
                try:
                    process = subprocess.run(
                        [str(self.ocr_python), '-X', 'utf8', str(self.ocr_worker),
                         '--image', str(source), '--output', str(target)],
                        cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                        timeout=self.ocr_timeout,
                    )
                except subprocess.TimeoutExpired:
                    raise ServiceError(504, 'OCR_TIMEOUT', '이미지 문자 인식 제한 시간을 초과했습니다.') from None
                if process.returncode or not target.is_file():
                    raise ServiceError(502, 'OCR_FAILED', '이미지 문자 인식을 완료하지 못했습니다.')
                try:
                    body = json.loads(target.read_text(encoding='utf-8'))
                    text = body['text']
                    if not isinstance(text, str):
                        raise ValueError('Invalid OCR body')
                except (ValueError, KeyError, OSError):
                    raise ServiceError(502, 'OCR_FAILED', '문자 인식 결과 형식이 올바르지 않습니다.') from None
            if len(text) > MAX_TEXT_CHARS:
                raise ServiceError(422, 'OCR_TEXT_TOO_LONG', '본문이 4000자를 초과합니다. 문자 영역을 잘라 다시 보내주세요.')
            return self._infer(text, body, started)
        finally:
            self._gate.release()

    def _infer(self, text, body, started=None):
        from .action_encoder import decide_action
        started = time.perf_counter() if started is None else started
        result = self.classifier.analyze_text(text)
        final = decide_action(result, body)
        flags = body or {}
        reasons = []
        if result['score'] is None:
            reasons.append('NO_ANALYZABLE_TEXT')
        if flags.get('poor_confidence', False):
            reasons.append('LOW_OCR_CONFIDENCE')
        if flags.get('layout_uncertain', False):
            reasons.append('UNCERTAIN_MESSAGE_LAYOUT')
        if result.get('requires_context_review', False):
            reasons.append('CONTEXT_DISAGREEMENT')
        if final['decision'] == 'defer' and not reasons:
            reasons.append('SCORE_IN_REVIEW_INTERVAL')
        text_result = {
            'decision': final['decision'], 'riskScore': result['score'],
            'scoreScale': '0..1', 'scoreMeaning': 'UNCALIBRATED_CLASSIFIER_SCORE',
            'modelName': 'skt/A.X-Encoder-base', 'modelVersion': self.model_version,
            'policyVersion': 'action-decision-v1', 'text': text,
            'quality': {
                'needsReview': bool(reasons), 'reasonCodes': reasons,
                'ocrUsed': body is not None,
                'poorOcrConfidence': bool(flags.get('poor_confidence', False)),
                'layoutUncertain': bool(flags.get('layout_uncertain', False)),
                'contextDisagreement': bool(result.get('requires_context_review', False)),
            },
            # Highest-scoring text and weak auxiliary topics are not proof.
            'evidence': [],
            'limitations': ['위험 점수는 실제 사기 확률이 아닙니다.',
                            '화자·발신자·URL의 진위는 확인하지 않습니다.',
                            '본문 분류 모델의 개별 사기 근거는 검증하지 않았습니다.',
                            'URL 위험 목록 미등록은 안전 보장이 아닙니다.'],
            'processingMs': round((time.perf_counter() - started) * 1000, 2),
        }
        # Compatibility for test/custom subclasses that omit the production
        # constructor: absent configuration never enables an external request.
        lookup = getattr(self, 'url_reputation', None)
        lookup = lookup if lookup is not None else UrlReputationLookup()
        combined = apply_reputation(text_result, lookup.assess(text))
        # Include lookup time in both text and OCR processing measurements.
        combined['processingMs'] = round((time.perf_counter() - started) * 1000, 2)
        return combined
