from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from PIL import Image

from image_analysis.adapters import ManipulationOutput, ModelAdapter
from image_analysis.config import Settings
from image_analysis.errors import ModelFailure, TransportError, error_info
from image_analysis.images import NormalizedImage
from image_analysis.overall import make_overall_result
from image_analysis.policy import make_success
from image_analysis.schemas import Envelope, ModelKind, ModelResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        adapters: dict[ModelKind, ModelAdapter],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self.adapters = adapters
        self.clock = clock
        # A failed cleanup quarantines future requests, as well as this envelope.
        self.runtime_safe = True

    def ensure_ready(self, selected: list[ModelKind]) -> None:
        if not self.runtime_safe:
            raise TransportError(503, "MODEL_UNAVAILABLE")
        for kind in selected:
            adapter = self.adapters.get(kind)
            if (
                adapter is None
                or not adapter.ready
                or adapter.kind != kind
                or not 1 <= len(adapter.model_name) <= 64
                or not 1 <= len(adapter.model_version) <= 128
            ):
                raise TransportError(503, "MODEL_UNAVAILABLE")

    def failed(self, kind: ModelKind, code: str) -> ModelResult:
        adapter = self.adapters[kind]
        return ModelResult(
            status="FAILED",
            modelName=adapter.model_name,
            modelVersion=adapter.model_version,
            policyVersion=self.settings.policy_version,
            errorCode=code,
            error=error_info(code),
        )

    async def run_model(
        self,
        kind: ModelKind,
        image: NormalizedImage,
        deadline: datetime,
    ) -> ModelResult:
        remaining = (deadline - self.clock()).total_seconds()
        remaining -= self.settings.response_reserve_seconds
        if remaining <= 0:
            return self.failed(kind, "REQUEST_DEADLINE_EXCEEDED")
        if not self.runtime_safe:
            return self.failed(kind, "MODEL_RUNTIME_UNAVAILABLE")
        adapter = self.adapters[kind]
        budget = min(remaining, self.settings.model_timeout_seconds)
        code = "MODEL_EXECUTION_FAILED"
        raw = None
        started = time.monotonic()
        try:
            # wait_for waits for cancellation cleanup. No thread executor with
            # continuing hidden work is used. The slot remains owned throughout.
            with image.image.copy() as model_image:
                raw = await asyncio.wait_for(adapter.infer(model_image), budget)
            if (deadline - self.clock()).total_seconds() <= (
                self.settings.response_reserve_seconds
            ):
                raise ModelFailure("REQUEST_DEADLINE_EXCEEDED")
            if time.monotonic() - started >= budget:
                raise ModelFailure("MODEL_TIMEOUT")
            result = make_success(
                kind,
                adapter.model_name,
                adapter.model_version,
                raw,
                image.image.size,
                image.alpha_composited,
                self.settings,
            )
            if (deadline - self.clock()).total_seconds() <= (
                self.settings.response_reserve_seconds
            ):
                raise ModelFailure("REQUEST_DEADLINE_EXCEEDED")
            return result
        except asyncio.TimeoutError:
            code = (
                "REQUEST_DEADLINE_EXCEEDED" if remaining <= budget else "MODEL_TIMEOUT"
            )
        except MemoryError:
            code = "MODEL_OUT_OF_MEMORY"
        except ModelFailure as exc:
            code = exc.code
        except Exception:
            code = "MODEL_EXECUTION_FAILED"
        finally:
            if isinstance(raw, ManipulationOutput):
                for output_image in (raw.map, raw.conf):
                    if isinstance(output_image, Image.Image):
                        output_image.close()
        try:
            self.runtime_safe = await adapter.recover()
        except Exception:
            self.runtime_safe = False
        return self.failed(kind, code)

    async def analyze(
        self,
        request_id: str,
        fields: dict[str, str],
        selected: list[ModelKind],
        deadline: datetime,
        image: NormalizedImage,
    ) -> Envelope:
        results: dict[ModelKind, ModelResult] = {}
        for kind in selected:
            results[kind] = await self.run_model(kind, image, deadline)
        failures = sum(r.status == "FAILED" for r in results.values())
        status: Literal["COMPLETED", "PARTIAL_FAILED", "FAILED"] = "COMPLETED"
        if failures:
            status = "FAILED" if failures == len(selected) else "PARTIAL_FAILED"
        source_type: Literal["IMAGE", "SCREEN_CROP"] = (
            "IMAGE" if fields["sourceType"] == "IMAGE" else "SCREEN_CROP"
        )
        envelope = Envelope(
            requestId=request_id,
            analysisId=fields["analysisId"],
            elementId=fields["elementId"],
            sourceType=source_type,
            requestedModels=selected,
            status=status,
            analysisImage=image.metadata,
            generation=results.get("generation"),
            manipulation=results.get("manipulation"),
            overallResult=make_overall_result(
                results.get("generation"), results.get("manipulation")
            ),
            completedAt=timestamp(self.clock()),
        )
        encoded = json.dumps(envelope.model_dump(), ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.settings.max_response_bytes:
            raise TransportError(500, "INTERNAL_ERROR")
        return envelope
