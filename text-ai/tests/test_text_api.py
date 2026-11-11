"""API boundary/policy tests use an explicit stub classifier; not model accuracy tests."""
import io
from pathlib import Path
import subprocess
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ai_text.api import API_PATH, create_app
from ai_text.api_service import TextRiskService, validate_image

TOKEN = 'unit-test-token-only'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


class StubClassifier:
    def analyze_text(self, text):
        score = .1 if any(c.isalnum() for c in text) else None
        return {'score': score, 'requires_context_review': False}


class StubService(TextRiskService):
    def __init__(self):
        self.classifier = StubClassifier()
        self.model_version = 'explicit-stub-test-model'
        self.device, self.ocr_available = 'stub', False
        self._gate = threading.Lock()

    def analyze_image(self, data, content_type):
        validate_image(data, content_type)
        return self._infer('테스트용 OCR 대역', {'poor_confidence': True})


@pytest.fixture
def service():
    return StubService()


@pytest.fixture
def client(service):
    with TestClient(create_app(lambda: service, token=TOKEN), raise_server_exceptions=False) as client:
        yield client


def png():
    stream = io.BytesIO()
    Image.new('RGB', (64, 64), 'white').save(stream, 'PNG')
    return stream.getvalue()


def test_missing_and_wrong_auth_do_not_analyze(client):
    for headers in ({}, {'Authorization': 'Bearer wrong'}):
        response = client.post(API_PATH, json={'text': '예약 안내'}, headers=headers)
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'UNAUTHORIZED'


@pytest.mark.parametrize('text', ['', ' \n\t ', '가' * 4001], ids=['empty', 'whitespace', 'too-long'])
def test_invalid_text_rejected(client, text):
    response = client.post(API_PATH, json={'text': text}, headers=AUTH)
    assert response.status_code == 422
    assert 'input' not in response.text


def test_context_ids_score_scale_and_no_invented_evidence(client):
    request_id, analysis_id, element_id = (str(uuid4()) for _ in range(3))
    response = client.post(API_PATH, headers={**AUTH, 'X-Request-ID': request_id},
                           json={'text': '예약 안내', 'analysisId': analysis_id, 'elementId': element_id})
    assert response.status_code == 200
    body = response.json()
    assert body['requestId'] == request_id == response.headers['X-Request-ID']
    assert body['analysisId'] == analysis_id and body['elementId'] == element_id
    assert body['riskScore'] == .1 and body['scoreScale'] == '0..1'
    assert body['decision'] == 'normal' and body['sourceType'] == 'TEXT'
    assert body['evidence'] == []


def test_punctuation_never_becomes_normal(client):
    response = client.post(API_PATH, json={'text': '!!!'}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()['decision'] == 'defer'
    assert response.json()['riskScore'] is None


@pytest.mark.parametrize('score,body,context,expected', [
    (.1, {'poor_confidence': True}, False, 'defer'),
    (.1, {'layout_uncertain': True}, False, 'defer'),
    (.1, None, True, 'defer'),
    (.9, {'poor_confidence': True, 'layout_uncertain': True}, True, 'phishing'),
    (None, {}, False, 'defer'),
    (.4, None, False, 'defer'),
])
def test_current_cli_policy_preserved(service, score, body, context, expected):
    service.classifier.analyze_text = lambda text: {'score': score, 'requires_context_review': context}
    assert service._infer('본문', body)['decision'] == expected


@pytest.mark.parametrize('data,mime,status', [
    (b'bad image', 'image/png', 422),
    (b'GIF89a', 'image/gif', 415),
    (b'x' * (10 * 1024 * 1024 + 1), 'image/png', 413),
], ids=['corrupt', 'unsupported', 'oversized'])
def test_upload_boundaries(client, data, mime, status):
    response = client.post(API_PATH + '/image', headers=AUTH,
                           files={'file': ('ignored-name', data, mime)})
    assert response.status_code == status


def test_uncertain_image_ocr_remains_defer(client):
    response = client.post(API_PATH + '/image', headers=AUTH,
                           data={'sourceType': 'SCREEN_CROP'},
                           files={'file': ('image.png', png(), 'image/png')})
    assert response.status_code == 200
    body = response.json()
    assert body['sourceType'] == 'SCREEN_CROP'
    assert body['decision'] == 'defer' and body['quality']['poorOcrConfidence']


def test_request_body_limit_and_request_id(client):
    request_id = str(uuid4())
    response = client.post(API_PATH, headers={**AUTH, 'X-Request-ID': request_id,
                                             'Content-Type': 'application/json'},
                           content=b'x' * (11 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()['requestId'] == request_id


def test_model_error_is_not_normal_or_sensitive_response(client, service):
    def fail(text):
        raise RuntimeError('secret input and absolute path must not escape')
    service.classifier.analyze_text = fail
    response = client.post(API_PATH, headers=AUTH, json={'text': '본문'})
    assert response.status_code == 503
    assert 'secret input' not in response.text
    assert 'decision' not in response.json()


def test_busy_request_does_not_overlap_inference(client, service):
    service._gate.acquire()
    try:
        response = client.post(API_PATH, headers=AUTH, json={'text': '본문'})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'ANALYZER_BUSY'
    finally:
        service._gate.release()


def test_classifier_constructed_once_per_server_lifespan():
    loaded = []
    def factory():
        loaded.append(True)
        return StubService()
    with TestClient(create_app(factory, token=TOKEN)) as client:
        for _ in range(2):
            assert client.post(API_PATH, headers=AUTH, json={'text': '본문'}).status_code == 200
    assert len(loaded) == 1


def test_ocr_timeout_returns_error_and_cleans_uploaded_file(tmp_path, monkeypatch):
    import ai_text.api_service as module
    service = StubService()
    service.ocr_available = True
    service.ocr_python, service.ocr_worker = Path('python'), Path('worker')
    service.ocr_timeout = 1
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker', 1)
    monkeypatch.setattr(module.subprocess, 'run', timeout)
    app = create_app(lambda: service, token=TOKEN)
    # Use the production image method, replacing only the child process.
    service.analyze_image = lambda data, mime: TextRiskService.analyze_image(service, data, mime)
    with TestClient(app) as client:
        response = client.post(API_PATH + '/image', headers=AUTH,
                               files={'file': ('image.png', png(), 'image/png')})
    assert response.status_code == 504
    assert response.json()['error']['code'] == 'OCR_TIMEOUT'
    assert list((tmp_path / 'cache/api-temp').iterdir()) == []
