"""One official TruFor GPU inference in the existing isolated environment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.root / "third_party/TruFor/TruFor_train_test"
    os.environ["MPLCONFIGDIR"] = str(args.output.parent / "matplotlib")
    sys.path.insert(0, str(source))
    import numpy as np  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as functional  # type: ignore[import-not-found]
    from dataset.dataset_test import TestDataset  # type: ignore[import-not-found]
    from lib.config import config, update_config  # type: ignore[import-not-found]
    from lib.utils import get_model  # type: ignore[import-not-found]
    from PIL import Image

    if not torch.cuda.is_available():
        raise RuntimeError("GPU unavailable")
    weight = source / "pretrained_models/weights/trufor.pth.tar"
    os.chdir(source)
    update_config(
        config,
        argparse.Namespace(
            experiment="trufor_ph3", opts=["TEST.MODEL_FILE", str(weight)]
        ),
    )
    torch.backends.cudnn.benchmark = config.CUDNN.BENCHMARK
    torch.backends.cudnn.deterministic = config.CUDNN.DETERMINISTIC
    torch.backends.cudnn.enabled = config.CUDNN.ENABLED
    checkpoint = torch.load(str(weight), map_location="cuda:0")
    model = get_model(config)
    model.load_state_dict(checkpoint["state_dict"])
    model = model.to("cuda:0").eval()
    rgb, _ = TestDataset(list_img=[str(args.input)])[0]
    rgb = rgb.unsqueeze(0).to("cuda:0")
    with torch.no_grad():
        pred, conf, det, _ = model(rgb, save_np=False)
        if conf is None or det is None:
            raise ValueError("MODEL_OUTPUT_INVALID")
        maps = {
            "map": functional.softmax(pred.squeeze(0), dim=0)[1].cpu().numpy(),
            "conf": torch.sigmoid(conf.squeeze(0))[0].cpu().numpy(),
        }
        score = float(torch.sigmoid(det).item())
    size = tuple(rgb.shape[2:])
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("MODEL_OUTPUT_INVALID")
    for key, value in maps.items():
        if (
            value.shape != size
            or not np.isfinite(value).all()
            or value.min() < 0
            or value.max() > 1
        ):
            raise ValueError("MODEL_OUTPUT_INVALID")
        with Image.fromarray(value.astype(np.float32), mode="F") as image:
            image.save(args.output.parent / (key + ".tiff"))
    args.output.write_text(json.dumps({"score": score, "imgsize": size}), "utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if "out of memory" in str(exc).lower():
            print("MODEL_OUT_OF_MEMORY", file=sys.stderr)
        elif "MODEL_OUTPUT_INVALID" in str(exc):
            print("MODEL_OUTPUT_INVALID", file=sys.stderr)
        else:
            print("MODEL_EXECUTION_FAILED", file=sys.stderr)
        sys.exit(1)
