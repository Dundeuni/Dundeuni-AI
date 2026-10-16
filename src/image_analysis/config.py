from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Proposal input limits and mock-only time budgets; no production SLA."""

    max_file_bytes: int = 10 * 1024 * 1024
    max_body_bytes: int = 11 * 1024 * 1024
    min_side: int = 32
    max_side: int = 8192
    max_pixels: int = 16_000_000
    max_active_requests: int = 1
    model_timeout_seconds: float = 5.0
    response_reserve_seconds: float = 0.05
    retry_after_seconds: int = 1
    hold_low: float = 0.4
    hold_high: float = 0.6
    generation_hold_low: float = 0.000004
    generation_hold_high: float = 0.02
    manipulation_hold_low: float = 0.12
    manipulation_hold_high: float = 0.70
    localization_max_side: int = 1024
    localization_max_bytes: int = 1024 * 1024
    max_response_bytes: int = 2 * 1024 * 1024
    mode: str = "MOCK"
    generation_only: bool = False
    hold_enabled: bool = True
    generation_threshold: float = 0.5
    fe_compatibility: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("MOCK", "CURE", "CURE_TRUFOR"):
            raise ValueError("invalid execution mode")
        if (
            type(self.hold_enabled) is not bool
            or type(self.generation_only) is not bool
            or type(self.fe_compatibility) is not bool
        ):
            raise ValueError("invalid model policy flags")
        if (
            not math.isfinite(self.generation_threshold)
            or not 0 <= self.generation_threshold <= 1
        ):
            raise ValueError("invalid generation threshold")
        integer_fields = (
            "max_file_bytes",
            "max_body_bytes",
            "min_side",
            "max_side",
            "max_pixels",
            "max_active_requests",
            "retry_after_seconds",
            "localization_max_side",
            "localization_max_bytes",
            "max_response_bytes",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "model_timeout_seconds",
            "response_reserve_seconds",
            "hold_low",
            "hold_high",
            "generation_hold_low",
            "generation_hold_high",
            "manipulation_hold_low",
            "manipulation_hold_high",
        ):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.model_timeout_seconds <= 0 or self.response_reserve_seconds < 0:
            raise ValueError("invalid mock time budget")
        if not 0 <= self.hold_low <= self.hold_high <= 1:
            raise ValueError("invalid hold interval")
        for kind in ("generation", "manipulation"):
            low = getattr(self, f"{kind}_hold_low")
            high = getattr(self, f"{kind}_hold_high")
            if not 0 <= low < high <= 1:
                raise ValueError(f"invalid {kind} signal interval")
        if self.min_side > self.max_side:
            raise ValueError("invalid side limits")
        if self.max_file_bytes > self.max_body_bytes:
            raise ValueError("file limit exceeds body limit")
        if self.localization_max_side > 1024:
            raise ValueError("localization side exceeds proposed contract")

    @property
    def policy_version(self) -> str:
        manifest = json.dumps(asdict(self), sort_keys=True).encode()
        return self.mode + "-policy-v2-" + hashlib.sha256(manifest).hexdigest()[:16]

    @classmethod
    def from_file(cls, path: Path) -> Settings:
        return cls(**json.loads(path.read_text(encoding="utf-8")))
