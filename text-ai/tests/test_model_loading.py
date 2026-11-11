"""Tiny local checkpoints cover loader precision without production assets."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from safetensors.torch import save_file
import torch
from transformers import AutoConfig, ModernBertConfig

from ai_text.action_encoder import ActionModel

Checkpoint = tuple[Path, dict[str, torch.Tensor]]


@pytest.fixture
def tiny_checkpoint(tmp_path: Path) -> Checkpoint:
    config = ModernBertConfig(
        vocab_size=32,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        max_position_embeddings=32,
        local_attention=8,
        pad_token_id=0,
        bos_token_id=1,
        eos_token_id=2,
        dtype=torch.float32,
    )
    source = ActionModel(config).float()
    weights = {
        name: torch.full_like(value, 0.1234567, dtype=torch.float32)
        if value.is_floating_point()
        else value.detach().clone()
        for name, value in source.state_dict().items()
    }
    # Reproduce the delivered config/weights dtype mismatch using tiny assets.
    config.dtype = torch.bfloat16
    config.save_pretrained(tmp_path)
    save_file(weights, str(tmp_path / "model.safetensors"))
    return tmp_path, weights


@pytest.mark.parametrize("device", ["cpu", torch.device("cpu")])
def test_cpu_loader_preserves_every_fp32_value(
    tiny_checkpoint: Checkpoint, device: str | torch.device
) -> None:
    folder, expected = tiny_checkpoint
    stored_config = AutoConfig.from_pretrained(folder, local_files_only=True)
    assert stored_config.dtype == torch.bfloat16
    saved_value = next(iter(expected.values())).flatten()[0]
    assert saved_value != saved_value.bfloat16().float()

    model = ActionModel.load(folder, device)

    assert model.config.dtype == torch.float32
    assert not model.training
    for name, actual in model.state_dict().items():
        assert torch.equal(actual, expected[name]), name
    for parameter in model.parameters():
        assert parameter.device.type == "cpu"
        if parameter.is_floating_point():
            assert parameter.dtype == torch.float32


def test_cpu_loader_heads_are_fp32_before_loading_with_custom_default(
    tiny_checkpoint: Checkpoint,
) -> None:
    folder, expected = tiny_checkpoint
    previous = torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.bfloat16)
        model = ActionModel.load(folder, "cpu")
    finally:
        torch.set_default_dtype(previous)
    for name, actual in model.state_dict().items():
        assert actual.dtype == expected[name].dtype
        assert torch.equal(actual, expected[name]), name


@pytest.mark.parametrize("mismatch", ["missing", "unexpected"])
def test_loader_keeps_strict_checkpoint_validation(
    tiny_checkpoint: Checkpoint, mismatch: str
) -> None:
    folder, weights = tiny_checkpoint
    if mismatch == "missing":
        weights.pop(next(iter(weights)))
    else:
        weights["unexpected.weight"] = torch.ones(1)
    save_file(weights, str(folder / "model.safetensors"))
    with pytest.raises(RuntimeError, match="state_dict"):
        ActionModel.load(folder, "cpu")


def test_cuda_loader_retains_configured_precision_without_cuda_compute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_text.action_encoder as module

    config = SimpleNamespace(dtype=torch.bfloat16)
    state = {"weight": torch.tensor([0.1234567])}
    recorded = {}
    monkeypatch.setattr(module.AutoConfig, "from_pretrained", lambda *a, **k: config)
    monkeypatch.setattr(module, "load_file", lambda *a, **k: state)

    class RecordingModel:
        def __init__(self, loaded_config: SimpleNamespace) -> None:
            recorded["dtype_at_construction"] = loaded_config.dtype

        def float(self) -> "RecordingModel":
            pytest.fail("The CUDA loader must not apply the CPU FP32 conversion")

        def load_state_dict(
            self, loaded_state: dict[str, torch.Tensor], strict: bool
        ) -> None:
            assert loaded_state is state
            assert strict is True

        def to(self, device: str) -> "RecordingModel":
            recorded["device"] = device
            return self

        def eval(self) -> "RecordingModel":
            return self

    ActionModel.load.__func__(RecordingModel, Path("unused"), "cuda")
    assert recorded == {"dtype_at_construction": torch.bfloat16, "device": "cuda"}
    assert config.dtype == torch.bfloat16
