"""Single-model sequential inference, using pinned official model/preprocessing."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path, model):
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        rows = [r for r in csv.DictReader(source) if r["model"] == model]
    if not rows:
        raise ValueError("No samples for selected model")
    ids, groups, hashes = set(), {}, {}
    for row in rows:
        if row["image_id"] in ids or row["label"] not in ("0", "1"):
            raise ValueError("Duplicate sample ID or invalid label")
        if row["split"] not in ("smoke", "exploratory", "tune", "final") or not row["group_id"]:
            raise ValueError("Invalid split/group")
        if row.get("label_review") != "verified":
            raise ValueError("Only verified labels may enter the experiment")
        image = ROOT / row["path"]
        if not image.is_file():
            raise FileNotFoundError(image)
        digest = sha256(image)
        if row.get("sha256") and row["sha256"] != digest:
            raise ValueError("Input hash mismatch")
        for key, mapping in ((row["group_id"], groups), (digest, hashes)):
            if key in mapping and mapping[key] != row["split"]:
                raise ValueError("Group or exact duplicate crosses splits")
            mapping[key] = row["split"]
        row["sha256"] = digest
        ids.add(row["image_id"])
    return rows


def load_bfree(torch, device):
    source = ROOT / "third_party/B-Free/code"
    sys.path.insert(0, str(source))
    from main_bfree_single import get_config
    from networks import get_network, load_weights
    from utils.normalization import get_list_norm
    from torchvision.transforms import Compose
    from PIL import Image
    _, weight, arch, norm = get_config("BFREE_dino2reg4", str(source / "weights"))
    model = load_weights(get_network(arch), weight).to(device).eval()
    transform = Compose(get_list_norm(norm))
    def predict(path):
        with Image.open(path) as image:
            size = (image.height, image.width)
            tensor = transform(image.convert("RGB")).unsqueeze(0).to(device)
        output = model(tensor).cpu().numpy()
        if output.shape == (1, 1):
            raw = float(output[0, 0])
        elif output.shape == (1, 2):
            raw = float(output[0, 1] - output[0, 0])
        else:
            raise ValueError("Unexpected B-Free output shape")
        return raw, {}, size
    return model, predict, Path(weight), {"architecture": arch, "norm_type": norm,
                                       "region_processing": "official Wrapper5crops (504)"}


def load_trufor(torch, device):
    source = ROOT / "third_party/TruFor/TruFor_train_test"
    os.environ["MPLCONFIGDIR"] = str(ROOT / "runs/.matplotlib")
    sys.path.insert(0, str(source))
    from lib.config import config, update_config
    from lib.utils import get_model
    from dataset.dataset_test import TestDataset
    import numpy as np
    import torch.nn.functional as F
    weight = source / "pretrained_models/weights/trufor.pth.tar"
    # Official config loader resolves lib/config relative to cwd.
    previous = Path.cwd()
    try:
        os.chdir(source)
        update_config(config, argparse.Namespace(experiment="trufor_ph3",
                      opts=["TEST.MODEL_FILE", str(weight)]))
    finally:
        os.chdir(previous)
    if device.startswith("cuda"):
        torch.backends.cudnn.benchmark = config.CUDNN.BENCHMARK
        torch.backends.cudnn.deterministic = config.CUDNN.DETERMINISTIC
        torch.backends.cudnn.enabled = config.CUDNN.ENABLED
    checkpoint = torch.load(str(weight), map_location=torch.device(device))
    model = get_model(config)
    model.load_state_dict(checkpoint["state_dict"])
    model = model.to(device).eval()
    def predict(path):
        rgb, _ = TestDataset(list_img=[str(path)])[0]
        rgb = rgb.unsqueeze(0).to(device)
        pred, conf, det, _ = model(rgb, save_np=False)
        if det is None or conf is None:
            raise ValueError("Missing score or confidence")
        maps = {"map": F.softmax(pred.squeeze(0), dim=0)[1].cpu().numpy(),
                "conf": torch.sigmoid(conf.squeeze(0))[0].cpu().numpy(),
                "imgsize": np.array(tuple(rgb.shape[2:]))}
        raw = float(torch.sigmoid(det).item())
        size = tuple(rgb.shape[2:])
        for name in ("map", "conf"):
            array = maps[name]
            if array.shape != size or not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
                raise ValueError(f"Invalid {name} shape/range")
        return raw, maps, size
    return model, predict, weight, {"config": "trufor_ph3", "RGB_divisor": 256,
                                   "map": "softmax channel 1", "conf": "sigmoid",
                                   "score": "official sigmoid(det), once",
                                   "config_sha256": sha256(source / "lib/config/trufor_ph3.yaml")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("bfree", "trufor"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--split", choices=("smoke", "exploratory", "tune", "final"))
    parser.add_argument("--policy-freeze", type=Path)
    args = parser.parse_args()
    rows = read_manifest(args.manifest, args.model)
    if args.split:
        rows = [r for r in rows if r["split"] == args.split]
    if not rows:
        raise ValueError("No samples for selected split")
    freeze = None
    if any(r["split"] == "final" for r in rows):
        if args.split != "final" or not args.policy_freeze or args.limit is not None:
            raise ValueError("Run the complete final split separately with --policy-freeze")
        from freeze_protocol import verify_freeze
        freeze = verify_freeze(args.manifest, args.model, args.policy_freeze)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("Limit must be positive")
        rows = rows[:args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / "predictions.jsonl"
    if result_path.exists():
        raise FileExistsError("Choose a new run directory; existing results are preserved")
    import torch
    import numpy as np
    from policies import probability, VERSION
    gpu = args.device.startswith("cuda")
    if gpu and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; CPU must be selected explicitly")
    if gpu:
        torch.cuda.set_device(torch.device(args.device))
    started = time.perf_counter()
    model, predict, weight, preprocessing = (load_bfree if args.model == "bfree" else load_trufor)(torch, args.device)
    if gpu:
        torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    sources = json.loads((ROOT / "runs/20261001_baseline" / (args.model + "_sources.json")).read_text())
    metadata = {"experiment_id": args.out.name, "model": args.model, "device": args.device,
                "python": sys.version, "python_executable": sys.executable,
                "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
                "cuda_architectures": torch.cuda.get_arch_list() if gpu else [],
                "gpu": torch.cuda.get_device_name() if gpu else None,
                "code_commit": sources["commit"], "weights_sha256": sha256(weight),
                "manifest_sha256": sha256(args.manifest), "runner_sha256": sha256(__file__),
                "load_seconds": load_seconds, "preprocessing": preprocessing,
                "policy_version": VERSION, "scope": sorted({r["split"] for r in rows}),
                "policy_freeze_sha256": sha256(args.policy_freeze) if freeze else None,
                "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    (args.out / "environment.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    with result_path.open("x", encoding="utf-8") as output, torch.no_grad():
        for index, row in enumerate(rows):
            record = {**row, "label": int(row["label"]), "model": args.model,
                      "experiment_id": args.out.name, "device": args.device,
                      "code_commit": sources["commit"], "weights_sha256": metadata["weights_sha256"],
                      "preprocessing": preprocessing, "policy_version": VERSION,
                      "raw_score": None, "normalized_score": None, "map_path": None,
                      "status": "failed", "error": None,
                      "inference_seconds": None,
                      "gpu_peak_allocated_mib": None, "gpu_peak_reserved_mib": None}
            if gpu:
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
            begin = time.perf_counter()
            try:
                raw, maps, size = predict(ROOT / row["path"])
                if gpu:
                    torch.cuda.synchronize()
                record["inference_seconds"] = time.perf_counter() - begin
                p = probability(args.model, raw)
                if maps:
                    destination = args.out / "maps" / (row["image_id"] + ".npz")
                    destination.parent.mkdir(exist_ok=True)
                    np.savez(destination, **maps, score=raw)
                    record["map_path"] = str(destination.resolve().relative_to(ROOT))
                record.update(raw_score=raw, normalized_score=p, imgsize=list(size), status="success")
            except Exception as error:
                record["error"] = {"type": type(error).__name__, "message": str(error),
                                   "traceback": traceback.format_exc()}
            if gpu:
                torch.cuda.synchronize()
                record["gpu_peak_allocated_mib"] = torch.cuda.max_memory_allocated()/1024**2
                record["gpu_peak_reserved_mib"] = torch.cuda.max_memory_reserved()/1024**2
            record["processing_seconds"] = time.perf_counter() - begin
            record["first_after_load"] = index == 0
            output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            print(row["image_id"], record["status"], record["raw_score"],
                  round(record["processing_seconds"], 3), flush=True)


if __name__ == "__main__":
    main()
