"""One encoder classifier; no rule overrides or classifier ensemble."""
from contextlib import nullcontext
import math
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from v2_core import preprocess

def decide(score, low, high, poor_ocr=False):
    if score is None:
        return {'decision': 'defer', 'basis': 'empty_message_body'}
    if not 0 <= low < high <= 1:
        raise ValueError('Invalid classifier interval')
    outcome = 'phishing' if score >= high else 'normal' if score < low else 'defer'
    basis = 'single_classifier_interval'
    if poor_ocr and outcome == 'normal':
        outcome, basis = 'defer', 'message_body_ocr_quality'
    return {'decision': outcome, 'basis': basis}

def metrics(rows):
    normal = [row for row in rows if row['label'] == 0]
    phishing = [row for row in rows if row['label'] == 1]
    fp = sum(row['decision'] == 'phishing' for row in normal)
    fn = sum(row['decision'] == 'normal' for row in phishing)
    alerts = sum(row['decision'] == 'phishing' for row in phishing)
    deferred = sum(row['decision'] == 'defer' for row in rows)
    return {'samples': len(rows), 'normal': len(normal), 'source_phishing': len(phishing),
            'fp': fp, 'fn': fn, 'true_alerts': alerts,
            'deferred': deferred, 'warnings': fp + alerts,
            'normal_passes': sum(row['decision'] == 'normal' for row in rows),
            'deferred_normal': sum(row['decision'] == 'defer' for row in normal),
            'deferred_phishing': sum(row['decision'] == 'defer' for row in phishing),
            'fpr': fp / len(normal) if normal else None,
            'fnr_normal_pass': fn / len(phishing) if phishing else None,
            'deferral_rate': deferred / len(rows) if rows else None,
            'phishing_not_alerted': (len(phishing)-alerts) / len(phishing) if phishing else None}

def select_interval(validation):
    candidates = []
    for low in (.01, .03, .05, .1, .15, .2, .3):
        for high in (.5, .6, .7, .8, .9, .95, .98, .99):
            values = [{'label': row['label'], **decide(row['score'], low, high)} for row in validation]
            stats = metrics(values)
            candidates.append({'low': low, 'high': high, 'metrics': stats})
    # An abstention does not count as successful fraud detection.
    eligible = [row for row in candidates if row['metrics']['fpr'] <= .05 and row['metrics']['phishing_not_alerted'] <= .1]
    if eligible:
        chosen = min(eligible, key=lambda row: (row['metrics']['deferral_rate'],
                     row['metrics']['phishing_not_alerted'], row['metrics']['fpr'], row['high'], -row['low']))
    else:
        chosen = min(candidates, key=lambda row: (row['metrics']['fpr'] + row['metrics']['phishing_not_alerted'],
                     row['metrics']['deferral_rate'], row['high'], -row['low']))
    return {'low': chosen['low'], 'high': chosen['high'], 'validation_metrics': chosen['metrics'],
            'selected_on': 'existing validation only; no capture scores', 'candidate_count': len(candidates),
            'objective': 'FPR<=5%, fraud-not-alerted<=10%; minimize deferrals when feasible',
            'feasible': bool(eligible), 'rule_overrides': False, 'max_length': 384, 'stride': 64,
            'score_meaning': 'uncalibrated classifier score, not real fraud probability'}

class SingleEncoder:
    def __init__(self, folder, config):
        self.folder, self.config = Path(folder), config
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForSequenceClassification.from_pretrained(folder, local_files_only=True,
                        trust_remote_code=False, use_safetensors=True, attn_implementation='sdpa').to(self.device).eval()
        self.score('안녕하세요. 요청하신 예약 안내입니다.')

    def score(self, text):
        text = preprocess(text)
        if not text:
            return None, 0
        batch = self.tokenizer(text, return_tensors='pt', padding=True, truncation=True,
                              max_length=384, stride=64, return_overflowing_tokens=True)
        batch.pop('overflow_to_sample_mapping', None)
        batch = {key: value.to(self.device) for key, value in batch.items()}
        with torch.inference_mode(), (torch.autocast('cuda', dtype=torch.bfloat16) if self.device == 'cuda' else nullcontext()):
            values = self.model(**batch).logits.float().softmax(-1)[:, 1]
        result = float(values.max().cpu())
        assert math.isfinite(result) and 0 <= result <= 1
        return result, len(values)

    def analyze(self, text, poor_ocr=False):
        score, windows = self.score(text)
        return {'score': score, 'windows': windows, **decide(score, self.config['low'], self.config['high'], poor_ocr),
                'model': str(self.folder), 'score_meaning': '분류 점수이며 실제 사기 확률이 아님'}
