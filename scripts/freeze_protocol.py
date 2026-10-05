"""Freeze a reproducible protocol before opening final model predictions."""
import argparse
import csv
import datetime
import json
from pathlib import Path
from policies import VERSION
from run_inference import ROOT, read_manifest, sha256


def protocol_files():
    return {name: sha256(ROOT/"scripts"/name) for name in
            ("run_inference.py", "policies.py", "evaluate.py", "freeze_protocol.py")}


def verify_freeze(manifest, model, freeze):
    record = json.loads(Path(freeze).read_text(encoding="utf-8"))
    if record["model"] != model or record["manifest_sha256"] != sha256(manifest):
        raise ValueError("Frozen model/manifest changed")
    if record["protocol_files"] != protocol_files() or record["policy_version"] != VERSION:
        raise ValueError("Frozen protocol code changed")
    for relative, digest in record["model_files"].items():
        if sha256(ROOT/relative) != digest:
            raise ValueError("Frozen model source/weight changed: " + relative)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", choices=("bfree", "trufor"), required=True)
    parser.add_argument("--tune-predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Frozen protocols are immutable; use a new experiment")
    rows = read_manifest(args.manifest, args.model)
    for split in ("tune", "final"):
        subset = [r for r in rows if r["split"] == split]
        if len(subset) != 40 or sum(r["label"] == "1" for r in subset) != 20:
            raise ValueError("Original protocol requires 40 inputs and 20 positives per split")
    if len(rows) != 80:
        raise ValueError("Unexpected original sample count")
    predictions = [json.loads(line) for line in args.tune_predictions.read_text(encoding="utf-8").splitlines() if line]
    expected = {r["image_id"]: r for r in rows if r["split"] == "tune"}
    if len(predictions) != 40 or {r["image_id"] for r in predictions} != set(expected):
        raise ValueError("Tuning predictions do not cover the tuning manifest exactly")
    for row in predictions:
        item = expected[row["image_id"]]
        if row["model"] != args.model or row["split"] != "tune" or int(item["label"]) != row["label"]:
            raise ValueError("Invalid tuning prediction scope")
        if any(row[k] != item[k] for k in ("sha256", "path", "group_id", "mask_path")):
            raise ValueError("Tuning prediction metadata mismatch")
    source = json.loads((ROOT/"runs/20261001_baseline"/(args.model+"_sources.json")).read_text())
    model_files = {}
    source_root = ROOT/"third_party"/("B-Free" if args.model == "bfree" else "TruFor")
    for item in source["files"]:
        local = source_root/item["path"]
        if sha256(local) != item["sha256"]:
            raise ValueError("Pinned source differs from acquisition record: " + item["path"])
        model_files[str(local.relative_to(ROOT))] = item["sha256"]
    if args.model == "trufor":
        weights = ROOT/"third_party/TruFor/TruFor_train_test/pretrained_models/weights/trufor.pth.tar"
    else:
        weights = ROOT/"third_party/B-Free/code/weights/BFREE_dino2reg4/model_epoch_best.pth"
    model_files[str(weights.relative_to(ROOT))] = sha256(weights)
    record = {"frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "model": args.model, "policy_version": VERSION, "primary_policy": "A",
              "secondary_prespecified_policy": "B", "service_policy_selected": False,
              "selection_reason": "Official reference A retained; no agreed service error/abstention targets. B is a fixed secondary comparison.",
              "location_threshold": .5, "location_direction": "official, no inversion",
              "location_boundary": "all pixels", "location_aggregation": "macro per image",
              "manifest_sha256": sha256(args.manifest), "tune_predictions_sha256": sha256(args.tune_predictions),
              "protocol_files": protocol_files(), "model_files": model_files,
              "code_commit": source["commit"], "weights_sha256": sha256(weights),
              "final_predictions_read": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x",encoding="utf-8") as target:
        json.dump(record,target,indent=2)
    print("Frozen",args.model,"A primary / B secondary / localization 0.5",sha256(args.out))


if __name__ == "__main__":
    main()
