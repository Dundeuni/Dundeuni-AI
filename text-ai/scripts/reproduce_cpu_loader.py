"""New equivalent of the review's missing CPU-loader diagnostic, using tiny assets.

Creates only temporary ModernBERT config/weights. No tokenizer, trained weights,
downloads, training, inference, OCR, or CUDA computation are used.
"""

import argparse
from importlib import import_module
import json
from pathlib import Path
import sys
import tempfile

from safetensors.torch import save_file
import torch
from transformers import ModernBertConfig


def diagnose(repo: Path) -> dict[str, object]:
    """Compare exact stored/loaded FP32 tensors with a saved BF16 config."""
    text_root = repo / "text-ai" if (repo / "text-ai").is_dir() else repo
    if not (text_root / "ai_text" / "action_encoder.py").is_file():
        raise ValueError("--repo must point to the repository root or text-ai folder")
    sys.path.insert(0, str(text_root))
    action_model = import_module("ai_text.action_encoder").ActionModel
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
    source = action_model(config).float()
    stored = {
        name: torch.full_like(value, 0.1234567, dtype=torch.float32)
        if value.is_floating_point()
        else value.detach().clone()
        for name, value in source.state_dict().items()
    }
    config.dtype = torch.bfloat16
    with tempfile.TemporaryDirectory(prefix="text-ai-tiny-cpu-loader-") as temporary:
        folder = Path(temporary)
        config.save_pretrained(folder)
        save_file(stored, str(folder / "model.safetensors"))
        loaded = action_model.load(folder, "cpu")
    actual = loaded.state_dict()
    name = next(key for key, value in stored.items() if value.is_floating_point())
    saved_value = stored[name].flatten()[0].item()
    loaded_value = actual[name].flatten()[0].item()
    return {
        "saved_config_dtype": "bfloat16",
        "saved_weights_dtype": "float32",
        "loaded_device": "cpu",
        "saved_value": saved_value,
        "loaded_value": loaded_value,
        "absolute_difference": abs(saved_value - loaded_value),
        "all_tensors_exact": all(
            torch.equal(actual[key], value) for key, value in stored.items()
        ),
        "all_floating_parameters_fp32": all(
            not value.is_floating_point() or value.dtype == torch.float32
            for value in loaded.parameters()
        ),
    }


def main() -> int:
    """Print reproducible values; optionally require an exact FP32 round trip."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--require-exact", action="store_true")
    args = parser.parse_args()
    result = diagnose(args.repo.resolve())
    print(json.dumps(result, indent=2))
    exact = result["all_tensors_exact"] and result["all_floating_parameters_fp32"]
    return 1 if args.require_exact and not exact else 0


if __name__ == "__main__":
    raise SystemExit(main())
