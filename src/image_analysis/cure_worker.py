"""Isolated CuRe worker, executed with the existing CuRe Python environment."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-format", choices=("PNG", "JPEG"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    # These dependencies belong to the isolated CuRe interpreter, not the API venv.
    import albumentations as A  # type: ignore[import-not-found]
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]
    from albumentations.pytorch import ToTensorV2  # type: ignore[import-not-found]
    from PIL import Image

    torch.set_num_threads(4)
    sys.path.insert(0, str(args.root / "third_party/CuRe"))
    from cure.model import load_model  # type: ignore[import-not-found]
    from cure.preprocess import preprocess_image  # type: ignore[import-not-found]

    with Image.open(args.input) as source:
        image = source.convert("RGB")
        image.load()
    # Exactly the existing official CuRe pipeline, preserving the received format.
    if args.source_format == "PNG":
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=96)
        buffer.seek(0)
        with Image.open(buffer) as decoded:
            image = decoded.convert("RGB")
            image.load()
    pipeline = A.Compose(
        [
            A.SmallestMaxSize(max_size=390, interpolation=cv2.INTER_CUBIC, p=1.0),
            A.CenterCrop(height=390, width=390, p=1.0),
            A.Resize(height=336, width=336, interpolation=cv2.INTER_CUBIC, p=1.0),
            A.ImageCompression(quality_range=(70, 70), p=1.0),
            A.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
            ToTensorV2(),
        ]
    )
    tensor = pipeline(image=np.asarray(image))["image"]
    parity = None
    if args.reference:
        reference = preprocess_image(args.reference)
        parity = float((tensor - reference).abs().max())
        if parity != 0.0:
            raise ValueError("Official preprocessing parity failed")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; no silent CPU fallback")
    model = load_model(
        checkpoint=args.root / "third_party/CuRe/weights/cure_adapter.pt",
        base_checkpoint=args.root / "weights/CuRe/PE-Core-L14-336.pt",
        device="cuda",
    )
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode(), torch.amp.autocast("cuda"):
        logits = model(tensor.unsqueeze(0).cuda())
        if logits.shape != (1, 2) or not bool(torch.isfinite(logits).all()):
            raise ValueError("Invalid CuRe logits")
        score = float(logits.softmax(1)[0, 1].float().cpu())
    torch.cuda.synchronize()
    args.output.write_text(
        json.dumps(
            {
                "score": score,
                "preprocessingMaxAbsDifference": parity,
                "peakAllocatedBytes": torch.cuda.max_memory_allocated(),
                "device": "cuda",
            },
            allow_nan=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Parent suppresses paths and stack traces; no source image/token logging.
        code = (
            "MODEL_OUT_OF_MEMORY"
            if "out of memory" in str(error).lower()
            else (
                "MODEL_OUTPUT_INVALID"
                if isinstance(error, ValueError)
                else "MODEL_EXECUTION_FAILED"
            )
        )
        print(code, file=sys.stderr)
        sys.exit(2)
