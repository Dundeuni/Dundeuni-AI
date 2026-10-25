"""BE-callable scam-text API; independent of the CuRe/TruFor contract."""
from contextlib import asynccontextmanager
import hmac
import logging
import os
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator
from starlette.concurrency import run_in_threadpool

from .api_service import MAX_FILE_BYTES, MAX_TEXT_CHARS, ServiceError, TextRiskService

API_PATH = '/internal/v1/text-analyses'
logger = logging.getLogger('ai_text.api')
bearer = HTTPBearer(auto_error=False)


class TextInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    analysisId: UUID | None = None
    elementId: UUID | None = None

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Text must not be blank')
        return value


class Quality(BaseModel):
    needsReview: bool
    reasonCodes: list[str]
    ocrUsed: bool
    poorOcrConfidence: bool
    layoutUncertain: bool
    contextDisagreement: bool


class UrlLookupItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    originalUrl: str
    lookupUrl: str | None
    schemeInferred: bool
    status: Literal['malicious', 'not_found', 'unavailable', 'disabled', 'skipped']
    reasonCode: str | None
    threatTypes: list[Literal['MALWARE', 'SOCIAL_ENGINEERING', 'UNWANTED_SOFTWARE']]
    cacheHit: bool
    lookupCheckedAt: str | None = None
    providerExpireTime: str | None = None


class UrlReputation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['GOOGLE_WEB_RISK_LOOKUP']
    policyVersion: Literal['url-reputation-lookup-v1']
    enabled: bool
    status: Literal['no_urls', 'disabled', 'malicious', 'not_found', 'incomplete']
    checkedAt: str
    urlCount: int = Field(ge=0)
    submittedCount: int = Field(ge=0, le=5)
    targetVisited: Literal[False]
    notFoundMeaning: Literal['NO_KNOWN_THREAT_MATCH_NOT_A_SAFETY_GUARANTEE']
    results: list[UrlLookupItem]


class TextRiskResponse(BaseModel):
    contractVersion: Literal['text-risk-1.0'] = 'text-risk-1.0'
    requestId: UUID4
    analysisId: UUID | None
    elementId: UUID | None
    sourceType: Literal['TEXT', 'IMAGE', 'SCREEN_CROP']
    status: Literal['COMPLETED'] = 'COMPLETED'
    decision: Literal['normal', 'phishing', 'defer']
    textDecision: Literal['normal', 'phishing', 'defer']
    decisionSource: Literal['TEXT_CLASSIFIER', 'KNOWN_MALICIOUS_URL']
    urlReputation: UrlReputation
    riskScore: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    scoreScale: Literal['0..1']
    scoreMeaning: Literal['UNCALIBRATED_CLASSIFIER_SCORE']
    modelName: str
    modelVersion: str
    policyVersion: str
    text: str
    quality: Quality
    evidence: list[str]
    limitations: list[str]
    processingMs: float = Field(ge=0, allow_inf_nan=False)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    requestId: UUID4 = Field(
        description=(
            "Validated or generated request UUID v4. INVALID_REQUEST_ID uses a "
            "new UUID v4 because the supplied header was rejected."
        )
    )


class HealthResponse(BaseModel):
    status: Literal["ready"]
    modelVersion: str
    device: str
    ocrWorkerAvailable: bool


def _request_id_metadata(
    _x_request_id: Annotated[
        str | None,
        Header(
            alias="X-Request-ID",
            description=(
                "Optional UUID v4. The server generates one when omitted or "
                "empty. An invalid nonempty value returns 422 INVALID_REQUEST_ID "
                "with a fresh requestId and no X-Request-ID response header."
            ),
            json_schema_extra={"format": "uuid4"},
        ),
    ] = None,
) -> None:
    """Document the header; existing middleware remains its sole validator."""
    return None


def _request_id_response_header() -> dict:
    return {
        "description": (
            "Echoes the validated UUID v4 or the generated UUID v4 after request "
            "context completes. Absent for INVALID_REQUEST_ID and not guaranteed "
            "for unexpected internal errors."
        ),
        "schema": {"type": "string", "format": "uuid4"},
    }


def _error_response(
    description: str, *, authenticate: bool = False, busy: bool = False
) -> dict:
    headers = {"X-Request-ID": _request_id_response_header()}
    if authenticate:
        headers["WWW-Authenticate"] = {
            "description": "Always returned for 401 UNAUTHORIZED.",
            "schema": {"type": "string", "const": "Bearer"},
        }
    if busy:
        headers["Retry-After"] = {
            "description": (
                "Returned with value 2 only for ANALYZER_BUSY; absent for "
                "OCR_UNAVAILABLE and unexpected ANALYSIS_FAILED errors."
            ),
            "schema": {"type": "string", "const": "2"},
        }
    return {
        "model": ErrorResponse,
        "description": description,
        "headers": headers,
    }


class RequestBodyLimit:
    """Bound multipart/JSON before parsing; this baseline buffers <=11 MiB."""
    def __init__(self, app, limit=11 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            total += len(message.get('body', b''))
            if total > self.limit:
                value = {'error': {'code': 'REQUEST_TOO_LARGE', 'message': '요청 본문은 최대 11 MiB입니다.'},
                         'requestId': scope.get('state', {}).get('request_id', str(uuid4()))}
                return await JSONResponse(value, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get('more_body', False):
                break
        iterator = iter(chunks)

        async def replay():
            return next(iterator, {'type': 'http.request', 'body': b'', 'more_body': False})

        await self.app(scope, replay, send)


def create_app(service_factory=None, token=None):
    @asynccontextmanager
    async def lifespan(app):
        secret = token if token is not None else os.environ.get('AI_SERVICE_TOKEN', '')
        if not secret or any(character.isspace() for character in secret):
            raise RuntimeError('Set a nonempty AI_SERVICE_TOKEN without whitespace')
        app.state.secret = secret
        app.state.service = await run_in_threadpool(service_factory or TextRiskService)
        try:
            yield
        finally:
            del app.state.service
            app.state.secret = ''

    app = FastAPI(
        title="A.X 문자 사기 위험 분석 API", version="1.0.0", lifespan=lifespan,
        dependencies=[Depends(_request_id_metadata)],
        description="문자 사기 분석 전용. CuRe/TruFor 이미지 생성·변조 API와 별도입니다.",
    )
    app.add_middleware(RequestBodyLimit)

    validation_error = _error_response(
        "INVALID_REQUEST for invalid fields or formats; INVALID_REQUEST_ID for "
        "a non-UUID-v4 X-Request-ID header."
    )
    success_response = {
        200: {
            "description": (
                "Completed analysis. A defer decision also returns HTTP 200 "
                "with status COMPLETED."
            ),
            "headers": {"X-Request-ID": _request_id_response_header()},
        }
    }
    text_responses = {
        **success_response,
        401: _error_response(
            "UNAUTHORIZED: missing or invalid Bearer service credentials.",
            authenticate=True,
        ),
        413: _error_response("REQUEST_TOO_LARGE: request body exceeds 11 MiB."),
        422: _error_response(
            validation_error["description"] + " INVALID_TEXT for invalid text."
        ),
        503: _error_response(
            "ANALYZER_BUSY when another analysis is running; ANALYSIS_FAILED "
            "for an unexpected internal error.",
            busy=True,
        ),
    }
    image_responses = {
        **text_responses,
        413: _error_response(
            "REQUEST_TOO_LARGE for a request body over 11 MiB; IMAGE_TOO_LARGE "
            "for an image file over 10 MiB."
        ),
        415: _error_response(
            "UNSUPPORTED_IMAGE, IMAGE_TYPE_MISMATCH, or ANIMATED_IMAGE for "
            "unsupported MIME types, mismatched formats, or multiple frames."
        ),
        422: _error_response(
            validation_error["description"] + " EMPTY_IMAGE, IMAGE_DIMENSIONS, "
            "INVALID_IMAGE, or OCR_TEXT_TOO_LONG for invalid image/OCR input."
        ),
        502: _error_response("OCR_FAILED: OCR worker or its result failed."),
        503: _error_response(
            "OCR_UNAVAILABLE when the OCR worker is not prepared; ANALYZER_BUSY "
            "when another analysis is running; ANALYSIS_FAILED for an "
            "unexpected internal error.",
            busy=True,
        ),
        504: _error_response("OCR_TIMEOUT: OCR worker exceeded its time limit."),
    }

    @app.middleware('http')
    async def request_context(request, call_next):
        incoming = request.headers.get('x-request-id')
        try:
            identifier = UUID(incoming) if incoming else uuid4()
            if identifier.version != 4:
                raise ValueError('Expected UUID v4')
        except ValueError:
            return JSONResponse({'error': {'code': 'INVALID_REQUEST_ID', 'message': 'X-Request-ID는 UUID v4여야 합니다.'},
                                 'requestId': str(uuid4())}, status_code=422)
        request.state.request_id = str(identifier)
        response = await call_next(request)
        response.headers['X-Request-ID'] = str(identifier)
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        headers = {'WWW-Authenticate': 'Bearer'} if error.status == 401 else {}
        if error.code == 'ANALYZER_BUSY':
            headers['Retry-After'] = '2'
        return JSONResponse({'error': {'code': error.code, 'message': error.message},
                             'requestId': request.state.request_id}, status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Do not echo message bodies or tokens in validation diagnostics.
        return JSONResponse({'error': {'code': 'INVALID_REQUEST', 'message': '요청 필드와 형식을 확인해주세요.'},
                             'requestId': request.state.request_id}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        request_id = getattr(request.state, 'request_id', str(uuid4()))
        logger.error('analysis_failed request_id=%s type=%s', request_id, type(error).__name__)
        return JSONResponse({'error': {'code': 'ANALYSIS_FAILED', 'message': '분석을 완료하지 못했습니다.'},
                             'requestId': request_id}, status_code=503)

    def authorize(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), request.app.state.secret.encode()):
            raise ServiceError(401, 'UNAUTHORIZED', '유효한 서비스 인증이 필요합니다.')

    def envelope(request, result, source_type, analysis_id, element_id):
        return {**result, 'contractVersion': 'text-risk-1.0', 'requestId': request.state.request_id,
                'analysisId': str(analysis_id) if analysis_id else None,
                'elementId': str(element_id) if element_id else None,
                'sourceType': source_type, 'status': 'COMPLETED'}

    @app.get('/health', include_in_schema=False)
    @app.get(
        "/healthz", response_model=HealthResponse, summary="기동 및 분류기 준비 상태",
        responses={
            200: {
                "description": "Classifier ready; reports the selected device.",
                "headers": {"X-Request-ID": _request_id_response_header()},
            },
            422: _error_response("INVALID_REQUEST_ID: invalid UUID v4 header."),
            503: _error_response("ANALYSIS_FAILED: unexpected internal error."),
        },
    )
    def health(request: Request):
        service = request.app.state.service
        return {'status': 'ready', 'modelVersion': service.model_version, 'device': service.device,
                'ocrWorkerAvailable': service.ocr_available}

    @app.post(
        API_PATH, response_model=TextRiskResponse, dependencies=[Depends(authorize)],
        responses=text_responses, summary="문자 본문 분석 (JSON)",
    )
    async def analyze_text(request: Request, body: TextInput):
        result = await run_in_threadpool(request.app.state.service.analyze_text, body.text)
        return envelope(request, result, 'TEXT', body.analysisId, body.elementId)

    @app.post(
        API_PATH + "/image", response_model=TextRiskResponse,
        dependencies=[Depends(authorize)], responses=image_responses,
        summary="이미지 OCR 후 문자 사기 위험 분석 (multipart)",
    )
    async def analyze_image(request: Request, file: Annotated[UploadFile, File()],
                            analysisId: Annotated[UUID | None, Form()] = None,
                            elementId: Annotated[UUID | None, Form()] = None,
                            sourceType: Annotated[Literal['IMAGE', 'SCREEN_CROP'], Form()] = 'IMAGE'):
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
            result = await run_in_threadpool(request.app.state.service.analyze_image, data, file.content_type)
            return envelope(request, result, sourceType, analysisId, elementId)
        finally:
            await file.close()

    return app


app = create_app()
