"""Device detection is mocked; these tests do not execute GPU operations."""

from pathlib import Path

import pytest

from ai_text.action_encoder import ActionEncoder
from ai_text.device_policy import select_device


@pytest.fixture(autouse=True)
def isolated_device_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_TEXT_DEVICE", raising=False)


def mock_cuda(
    monkeypatch: pytest.MonkeyPatch, *, available: bool, bf16: bool
) -> list[bool]:
    import ai_text.device_policy as module

    calls: list[bool] = []
    monkeypatch.setattr(module.torch.cuda, "is_available", lambda: available)

    def supports_bf16(*, including_emulation: bool) -> bool:
        calls.append(including_emulation)
        return bf16

    monkeypatch.setattr(module.torch.cuda, "is_bf16_supported", supports_bf16)
    return calls


def test_explicit_cpu_skips_cuda_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    import ai_text.device_policy as module

    def unexpected_detection() -> bool:
        pytest.fail("Explicit CPU must not query CUDA")

    monkeypatch.setattr(module.torch.cuda, "is_available", unexpected_detection)
    monkeypatch.setenv("AI_TEXT_DEVICE", "cuda_bf16")
    assert select_device("cpu") == "cpu"
    monkeypatch.setenv("AI_TEXT_DEVICE", "cpu")
    assert select_device() == "cpu"


def test_default_auto_without_cuda_selects_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = mock_cuda(monkeypatch, available=False, bf16=False)
    assert select_device() == "cpu"
    assert calls == []


def test_explicit_cuda_without_cuda_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = mock_cuda(monkeypatch, available=False, bf16=False)
    with pytest.raises(RuntimeError, match="requires an available CUDA device"):
        select_device("cuda_bf16")
    assert calls == []


@pytest.mark.parametrize("selection", ["auto", "cuda_bf16"])
def test_cuda_without_native_bf16_fails_without_fallback(
    monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    calls = mock_cuda(monkeypatch, available=True, bf16=False)
    with pytest.raises(RuntimeError, match="does not support native BF16"):
        select_device(selection)
    assert calls == [False]


@pytest.mark.parametrize("selection", ["auto", "cuda_bf16"])
def test_supported_cuda_selection_keeps_compatible_device_string(
    monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    calls = mock_cuda(monkeypatch, available=True, bf16=True)
    assert select_device(selection) == "cuda"
    assert calls == [False]


@pytest.mark.parametrize("selection", ["", "cuda", "fp16", "CPU", "invalid"])
def test_invalid_selection_fails_before_cuda_detection(
    monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    import ai_text.device_policy as module

    monkeypatch.setattr(
        module.torch.cuda, "is_available", lambda: pytest.fail("Unexpected CUDA query")
    )
    monkeypatch.setenv("AI_TEXT_DEVICE", selection)
    with pytest.raises(ValueError, match="auto, cpu, cuda_bf16"):
        select_device()


@pytest.mark.parametrize("selection", ["auto", "cuda_bf16", "invalid"])
def test_invalid_or_unsupported_selection_precedes_all_model_loading(
    monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    import ai_text.action_encoder as module

    mock_cuda(monkeypatch, available=True, bf16=False)
    monkeypatch.setattr(
        module.ActionModel,
        "load",
        lambda *a, **k: pytest.fail("Model loading preceded device validation"),
    )
    monkeypatch.setattr(
        module.AutoTokenizer,
        "from_pretrained",
        lambda *a, **k: pytest.fail("Tokenizer loading preceded device validation"),
    )
    with pytest.raises((ValueError, RuntimeError)):
        ActionEncoder("unused", device=selection)


def test_environment_choice_is_reflected_in_encoder_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_text.action_encoder as module

    monkeypatch.setenv("AI_TEXT_DEVICE", "cpu")
    loaded = []
    model, tokenizer = object(), object()

    def load_model(folder: str | Path, device: str) -> object:
        loaded.append((folder, device))
        return model

    monkeypatch.setattr(module.ActionModel, "load", load_model)
    monkeypatch.setattr(
        module.AutoTokenizer, "from_pretrained", lambda *a, **k: tokenizer
    )
    encoder = ActionEncoder("unused")
    assert encoder.device == "cpu"
    assert loaded == [("unused", "cpu")]
    assert encoder.model is model and encoder.tokenizer is tokenizer
