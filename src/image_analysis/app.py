from __future__ import annotations

import ipaddress
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from image_analysis.adapters import (
    Authenticator,
    MockAdapter,
    MockAuthenticator,
    ModelAdapter,
)
from image_analysis.compat import fe_response
from image_analysis.config import Settings
from image_analysis.errors import TransportError, error_info
from image_analysis.images import normalize_image
from image_analysis.schemas import ModelKind
from image_analysis.service import AnalysisService, utc_now
from image_analysis.validation import valid_uuid, validate_form

ENDPOINT = "/internal/v1/image-analyses"


def transport_response(
    scope: Scope,
    error: TransportError,
    settings: Settings,
) -> JSONResponse:
    state = scope["state"]
    headers = {
        "X-Request-ID": state["request_id"],
        "X-AI-Mode": settings.mode,
        "Cache-Control": "no-store",
    }
    if error.status_code == 503:
        headers["Retry-After"] = str(settings.retry_after_seconds)
    if error.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if scope.get("path") == "/api/analysis":
        codes = {
            400: "COMMON400",
            413: "COMMON413",
            415: "COMMON415",
            422: "COMMON400",
            503: "ANALYSIS503",
            500: "COMMON500",
            403: "AUTH403",
        }
        return JSONResponse(
            status_code=error.status_code,
            headers=headers,
            content={
                "isSuccess": False,
                "code": codes.get(error.status_code, "COMMON500"),
                "message": error_info(error.code).message,
                "result": None,
            },
        )
    return JSONResponse(
        status_code=error.status_code,
        headers=headers,
        content={
            "requestId": state["request_id"],
            "analysisId": state.get("analysis_id"),
            "elementId": state.get("element_id"),
            "error": error_info(error.code).model_dump(),
        },
    )


class AdmissionMiddleware:
    """Immediate slot admission before bounded body read; no pending body queue."""

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        authenticator: Authenticator,
    ) -> None:
        self.app = app
        self.settings = settings
        self.authenticator = authenticator
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        compatibility = (
            self.settings.mode == "CURE"
            and self.settings.fe_compatibility
            and scope.get("path") == "/api/analysis"
        )
        if scope["type"] != "http" or (scope["path"] != ENDPOINT and not compatibility):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_ids = headers.getlist("x-request-id")
        request_id = request_ids[0] if len(request_ids) == 1 else ""
        trace_valid = valid_uuid(request_id, v4=True)
        scope.setdefault("state", {})["request_id"] = (
            request_id if trace_valid else str(uuid4())
        )
        acquired = False
        response_started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            authorization = headers.getlist("authorization")
            verdict = (
                "ALLOWED"
                if compatibility
                else self.authenticator.authenticate(
                    authorization[0] if len(authorization) == 1 else ""
                )
            )
            if verdict != "ALLOWED":
                raise TransportError(
                    403 if verdict == "DENIED" else 401,
                    "FORBIDDEN_CALLER"
                    if verdict == "DENIED"
                    else "AUTHENTICATION_FAILED",
                )
            client = scope.get("client")
            if client and not ipaddress.ip_address(client[0]).is_loopback:
                raise TransportError(403, "FORBIDDEN_CALLER")
            if (not trace_valid and not compatibility) or scope["query_string"]:
                raise TransportError(400, "INVALID_REQUEST")
            if self.active >= self.settings.max_active_requests:
                raise TransportError(503, "AI_BUSY")
            self.active += 1
            acquired = True
            lengths = headers.getlist("content-length")
            if lengths:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise TransportError(400, "INVALID_REQUEST")
                if int(lengths[0]) > self.settings.max_body_bytes:
                    raise TransportError(413, "PAYLOAD_TOO_LARGE")
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    raise ClientDisconnect()
                if message["type"] != "http.request":
                    continue
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.settings.max_body_bytes:
                    raise TransportError(413, "PAYLOAD_TOO_LARGE")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            if lengths and int(lengths[0]) != len(body):
                raise TransportError(400, "INVALID_REQUEST")
            delivered = False

            async def buffered_receive() -> Message:
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, buffered_receive, wrapped_send)
        except ClientDisconnect:
            return
        except TransportError as exc:
            if not response_started:
                await transport_response(scope, exc, self.settings)(
                    scope, receive, send
                )
        except Exception:
            if not response_started:
                await transport_response(
                    scope,
                    TransportError(500, "INTERNAL_ERROR"),
                    self.settings,
                )(scope, receive, send)
        finally:
            if acquired:
                self.active -= 1


def create_app(
    settings: Settings | None = None,
    adapters: dict[ModelKind, ModelAdapter] | None = None,
    authenticator: Authenticator | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    config = settings or Settings()
    configured_adapters = (
        adapters
        if adapters is not None
        else {
            "generation": MockAdapter("generation", value=2.197224577),
            "manipulation": MockAdapter("manipulation", value=0.8),
        }
    )
    service = AnalysisService(config, configured_adapters, clock)
    app = FastAPI(title=config.mode + " image analysis", docs_url=None, redoc_url=None)
    app.state.service = service
    app.add_middleware(
        AdmissionMiddleware,
        settings=config,
        authenticator=authenticator or MockAuthenticator(),
    )

    @app.post(ENDPOINT)
    async def analyze(request: Request) -> JSONResponse:
        try:
            content_type = request.headers.get("content-type", "")
            if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
                raise TransportError(400, "INVALID_REQUEST")
            async with request.form(
                max_files=1, max_fields=5, max_part_size=128
            ) as form:
                # Echo only canonical IDs, even when another field is invalid.
                for field, state_name in (
                    ("analysisId", "analysis_id"),
                    ("elementId", "element_id"),
                ):
                    values = form.getlist(field)
                    if len(values) == 1 and isinstance(values[0], str):
                        if valid_uuid(values[0]):
                            request.scope["state"][state_name] = values[0]
                fields, upload, selected, deadline = validate_form(
                    form, clock(), config.generation_only
                )
                service.ensure_ready(selected)
                data = await upload.read(config.max_file_bytes + 1)
                image = normalize_image(data, upload.content_type or "", config)
                try:
                    envelope = await service.analyze(
                        request.state.request_id,
                        fields,
                        selected,
                        deadline,
                        image,
                    )
                finally:
                    image.image.close()
            return JSONResponse(
                content=envelope.model_dump(),
                headers={
                    "X-Request-ID": envelope.requestId,
                    "X-AI-Mode": config.mode,
                    "Cache-Control": "no-store",
                },
            )
        except TransportError as exc:
            return transport_response(request.scope, exc, config)
        except HTTPException:
            return transport_response(
                request.scope,
                TransportError(400, "INVALID_REQUEST"),
                config,
            )
        except Exception:
            return transport_response(
                request.scope,
                TransportError(500, "INTERNAL_ERROR"),
                config,
            )

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        if config.mode == "MOCK":
            return {"mode": "MOCK", "gpuUsed": False, "contractVersion": "1.0"}
        return {
            "mode": config.mode,
            "contractVersion": "1.0",
            "selectedModels": list(configured_adapters),
            "ready": all(adapter.ready for adapter in configured_adapters.values()),
            "compatibilityEndpoint": "/api/analysis (local test only)"
            if config.fe_compatibility
            else None,
            "device": "cuda",
        }

    if config.mode == "CURE" and config.fe_compatibility:

        @app.post("/api/analysis")
        async def fe_compatibility(request: Request) -> JSONResponse:
            # Local test gateway matching BE PR#4 and FE main, NOT a BE replacement.
            created = clock()
            try:
                if (
                    request.headers.get("content-type", "").split(";", 1)[0]
                    != "multipart/form-data"
                ):
                    raise TransportError(400, "INVALID_REQUEST")
                async with request.form(
                    max_files=1, max_fields=1, max_part_size=128
                ) as form:
                    items = form.multi_items()
                    if (
                        len(items) != 2
                        or set(form.keys()) != {"type", "file"}
                        or form.get("type") != "IMAGE"
                    ):
                        raise TransportError(400, "INVALID_REQUEST")
                    from starlette.datastructures import UploadFile

                    upload = form.get("file")
                    if not isinstance(upload, UploadFile):
                        raise TransportError(400, "INVALID_REQUEST")
                    service.ensure_ready(["generation"])
                    data = await upload.read(config.max_file_bytes + 1)
                    image = normalize_image(data, upload.content_type or "", config)
                    fields = {
                        "analysisId": str(uuid4()),
                        "elementId": str(uuid4()),
                        "sourceType": "IMAGE",
                    }
                    deadline = created + timedelta(
                        seconds=config.model_timeout_seconds
                        + config.response_reserve_seconds
                    )
                    try:
                        result = await service.analyze(
                            request.state.request_id,
                            fields,
                            ["generation"],
                            deadline,
                            image,
                        )
                    finally:
                        image.image.close()
                return JSONResponse(
                    status_code=202,
                    content=fe_response(result, created),
                    headers={
                        "X-AI-Mode": "CURE",
                        "X-Request-ID": result.requestId,
                        "X-Compatibility-Only": "true",
                        "Cache-Control": "no-store",
                    },
                )
            except TransportError as error:
                return transport_response(request.scope, error, config)
            except HTTPException:
                return transport_response(
                    request.scope, TransportError(400, "INVALID_REQUEST"), config
                )
            except Exception:
                return transport_response(
                    request.scope, TransportError(500, "INTERNAL_ERROR"), config
                )

    return app
