"""Resolve CPU FP32 or validated CUDA BF16 before model initialization."""

import os

import torch

DEVICE_CHOICES = ("auto", "cpu", "cuda_bf16")


def select_device(requested: str | None = None) -> str:
    """Return ``cpu``/``cuda`` for the explicit option or AI_TEXT_DEVICE.

    Auto uses CPU only when CUDA is absent. An available CUDA device must
    support native BF16; selecting CPU on such a host requires an explicit
    choice. No FP16 or CPU fallback occurs after CUDA has been selected.
    """
    selection = (
        os.environ.get("AI_TEXT_DEVICE", "auto") if requested is None else requested
    )
    if selection not in DEVICE_CHOICES:
        raise ValueError("AI_TEXT_DEVICE must be one of: auto, cpu, cuda_bf16")
    if selection == "cpu":
        return "cpu"
    if not torch.cuda.is_available():
        if selection == "auto":
            return "cpu"
        raise RuntimeError(
            "AI_TEXT_DEVICE=cuda_bf16 requires an available CUDA device. "
            "Set AI_TEXT_DEVICE=cpu to select CPU explicitly."
        )
    # Exclude BF16 emulation and avoid a probe tensor allocation on older GPUs.
    if not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError(
            f"AI_TEXT_DEVICE={selection} selected CUDA, but the current CUDA "
            "device does not support native BF16. "
            "Set AI_TEXT_DEVICE=cpu to select CPU explicitly."
        )
    return "cuda"
