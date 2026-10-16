from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass
from typing import Protocol, Union

from PIL import Image

from image_analysis.errors import ModelFailure
from image_analysis.schemas import ModelKind


@dataclass
class GenerationOutput:
    logit: float | None = None
    score: float | None = None


@dataclass
class ManipulationOutput:
    """Adapter-restored F maps in EXIF-normalized analysis coordinates, [H,W]."""

    score: float
    map: Image.Image
    conf: Image.Image
    imgsize: tuple[int, int]  # (height, width), AFTER official padding/resize removal


RawOutput = Union[GenerationOutput, ManipulationOutput]


class ModelAdapter(Protocol):
    kind: ModelKind
    model_name: str
    model_version: str
    ready: bool

    async def infer(self, image: Image.Image) -> RawOutput:
        """Consume normalized RGB; apply official preprocessing inside adapter."""
        ...

    async def recover(self) -> bool:
        """Return only after owned work stopped; false marks shared runtime unsafe."""
        ...


class Authenticator(Protocol):
    def authenticate(self, authorization: str) -> str:
        """Return ALLOWED, DENIED (authenticated), or INVALID."""
        ...


class MockAuthenticator:
    """Public placeholders, deliberately unsuitable as real service credentials."""

    def authenticate(self, authorization: str) -> str:
        if authorization == "Bearer MOCK_ONLY_NOT_A_SECRET":
            return "ALLOWED"
        if authorization == "Bearer MOCK_DENIED_NOT_A_SECRET":
            return "DENIED"
        return "INVALID"


class MockAdapter:
    def __init__(
        self,
        kind: ModelKind,
        *,
        value: float = 0.8,
        failure: str | None = None,
        delay_seconds: float = 0.0,
        ready: bool = True,
        recovery_safe: bool = True,
    ) -> None:
        self.kind = kind
        self.model_name = "B-Free" if kind == "generation" else "TruFor"
        self.model_version = f"MOCK-{kind}-constant-v1-{value}"
        self.value = value
        self.failure = failure
        self.delay_seconds = delay_seconds
        self.ready = ready
        self.recovery_safe = recovery_safe
        self.calls = 0

    async def infer(self, image: Image.Image) -> RawOutput:
        self.calls += 1
        await asyncio.sleep(self.delay_seconds)
        if self.failure:
            raise ModelFailure(self.failure)
        if self.kind == "generation":
            return GenerationOutput(logit=self.value)
        return ManipulationOutput(
            score=self.value,
            map=Image.new("F", image.size, self.value),
            conf=Image.new("F", image.size, 1.0),
            imgsize=(image.height, image.width),
        )

    async def recover(self) -> bool:
        return self.recovery_safe


class ServiceAuthenticator:
    """Use a caller-supplied token without generating or persisting secrets."""

    def __init__(self, token: str) -> None:
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Invalid service token")
        self.expected = "Bearer " + token

    def authenticate(self, authorization: str) -> str:
        return (
            "ALLOWED"
            if hmac.compare_digest(authorization, self.expected)
            else "INVALID"
        )
