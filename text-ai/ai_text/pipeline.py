import os
from pathlib import Path
import re
import time
import json

from .rules import evaluate_rules, normalize

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME', str(ROOT / 'cache' / 'huggingface'))
os.environ.setdefault('PADDLE_PDX_CACHE_HOME', str(ROOT / 'cache' / 'paddlex'))
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
os.environ.setdefault('OMP_NUM_THREADS', '4')
PUBLIC_MODEL = 'donghyun95/smishing-detection-roberta-base'
LOCAL_MODEL = ROOT / 'models' / 'korean-roberta'
DEFAULT_MODEL = str(LOCAL_MODEL) if (LOCAL_MODEL / 'config.json').exists() else PUBLIC_MODEL


class RiskAnalyzer:
    def __init__(self, model_id=DEFAULT_MODEL, phishing_label=1,
                 threshold=None, review_threshold=None):
        config_path = Path(model_id) / 'risk_config.json'
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
        threshold = threshold if threshold is not None else config.get('threshold',60.0)
        review_threshold = review_threshold if review_threshold is not None else min(config.get('review_threshold',30.0), threshold / 2)
        if not 0 <= review_threshold < threshold <= 100:
            raise ValueError('Require 0 <= review_threshold < threshold <= 100')
        self.model_id = model_id
        self.phishing_label = phishing_label
        self.threshold = threshold
        self.review_threshold = review_threshold
        self._ocr = self._model = self._tokenizer = None

    def _load_classifier(self):
        if self._model is None:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            torch.set_num_threads(4)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=False)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_id, trust_remote_code=False, use_safetensors=True).eval()
            if not 0 <= self.phishing_label < self._model.config.num_labels:
                raise ValueError('Invalid phishing class index')

    def model_score(self, text):
        self._load_classifier()
        import torch
        # Follow this model card's training preprocessing. Rules retain URLs separately.
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', normalize(text)).strip()
        if not cleaned:
            return None, 0
        windows = self._tokenizer(cleaned, return_tensors='pt', truncation=True,
                                  max_length=128, stride=32, return_overflowing_tokens=True,
                                  padding=True)
        windows.pop('overflow_to_sample_mapping', None)
        scores = []
        with torch.inference_mode():
            for start in range(0, len(windows['input_ids']), 8):
                inputs = {k: v[start:start + 8] for k, v in windows.items()}
                probs = torch.softmax(self._model(**inputs).logits, dim=-1)
                scores.extend(probs[:, self.phishing_label].tolist())
        return max(scores), len(scores)

    def analyze_text(self, text):
        started = time.perf_counter()
        text = normalize(text)
        rules = evaluate_rules(text)
        if not re.search(r'[가-힣a-zA-Z0-9]', text):
            return dict(text=text, risk_score=None, label='텍스트 확인 필요',
                        rules=rules, model_score=None, model_windows=0,
                        quality=dict(needs_review=True, reasons=['분석 가능한 텍스트 없음']))
        model, windows = self.model_score(text)
        if model is None:
            score, label = None, '텍스트 확인 필요'
        else:
            score = round(0.4 * rules['score'] + 60 * model, 6)
            label = ('사기 의심' if score >= self.threshold else
                     '추가 확인' if score >= self.review_threshold else '위험 신호 적음')
        return dict(text=text, risk_score=score, label=label, rules=rules,
                    model_score=model, model_windows=windows,
                    model_id=self.model_id, phishing_label_index=self.phishing_label,
                    quality=dict(needs_review=model is None, reasons=[]),
                    thresholds=dict(review=self.review_threshold, suspicious=self.threshold),
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    score_meaning='검증 전 휴리스틱 위험 점수. 실제 사기 확률이 아님.')

    def extract(self, image_path):
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(device='cpu',
                                  text_detection_model_name='PP-OCRv5_mobile_det',
                                  text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
                                  use_doc_orientation_classify=False,
                                  use_doc_unwarping=False, use_textline_orientation=False,
                                  enable_mkldnn=False, cpu_threads=4,
                                  text_rec_score_thresh=0.0)
        lines = []
        for page in self._ocr.predict(str(image_path)):
            for text, confidence, box in zip(page['rec_texts'], page['rec_scores'], page['rec_polys']):
                lines.append(dict(text=text, confidence=float(confidence), box=box.tolist()))
        # Suitable for a cropped single message; full conversation speaker attribution is not implemented.
        lines.sort(key=lambda line: (min(p[1] for p in line['box']), min(p[0] for p in line['box'])))
        return lines

    def analyze_image(self, image_path, crop=None):
        import tempfile
        from PIL import Image, ImageOps
        image_path = Path(image_path)
        started = time.perf_counter()
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            if crop:
                x1, y1, x2, y2 = crop
                if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
                    raise ValueError('Crop must lie within the image')
                image = image.crop(crop)
            temp_root = ROOT / 'cache' / 'temp'
            temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
                prepared = Path(tmp) / 'image.png'
                image.save(prepared)
                lines = self.extract(prepared)
        result = self.analyze_ocr_lines(lines)
        result.update(image=str(image_path.resolve()), crop=list(crop) if crop else None,
                      elapsed_seconds=round(time.perf_counter() - started, 3))
        return result

    def analyze_ocr_lines(self, lines):
        result = self.analyze_text('\n'.join(line['text'] for line in lines))
        reasons = result['quality']['reasons']
        if any(line['confidence'] < 0.75 for line in lines):
            reasons.append('OCR 인식 점수가 낮은 줄이 있음')
        if not lines:
            reasons.append('OCR 텍스트를 찾지 못함')
        result['quality']['needs_review'] = bool(reasons)
        # Keep the risk signal; low OCR confidence never downgrades risk to safe.
        if reasons and result['label'] == '위험 신호 적음':
            result['label'] = '텍스트 확인 필요'
        result['ocr_lines'] = lines
        return result
