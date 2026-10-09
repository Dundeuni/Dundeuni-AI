"""Policy and fixed-direction localization evaluation with explicit denominators."""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from policies import metrics
from run_inference import ROOT


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(values) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position-lo)


def localization(row, threshold):
    import numpy as np
    from PIL import Image
    with np.load(ROOT / row["map_path"], allow_pickle=False) as maps:
        prediction = maps["map"] >= threshold
    with Image.open(ROOT / row["mask_path"]) as mask:
        truth = np.asarray(mask)
    if truth.ndim != 2 or not np.isin(truth, [0, 1, 255]).all():
        raise ValueError("Provide a reviewed binary mask (0/1 or 0/255)")
    truth = truth > 0
    if truth.shape != prediction.shape or not truth.any():
        raise ValueError("Mask shape mismatch or empty positive mask")
    tp = int((truth & prediction).sum())
    fp = int((~truth & prediction).sum())
    fn = int((truth & ~prediction).sum())
    return {"image_id": row["image_id"], "model": row["model"], "split": row["split"],
            "dataset": row["dataset"], "tp": tp, "fp": fp, "fn": fn,
            "iou": tp/(tp+fp+fn), "pixel_f1": 2*tp/(2*tp+fp+fn)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map-threshold", type=float, default=0.5)
    args = parser.parse_args()
    if not 0 <= args.map_threshold <= 1:
        raise ValueError("Invalid map threshold")
    rows = [json.loads(line) for line in args.predictions.read_text(encoding="utf-8").splitlines() if line]
    buckets, identities = defaultdict(list), set()
    group_splits = {}
    for row in rows:
        if row["label"] not in (0, 1) or row["status"] not in ("success", "failed"):
            raise ValueError("Invalid label/status")
        key = (row["model"], row["image_id"])
        if key in identities:
            raise ValueError("Duplicate prediction")
        identities.add(key)
        group = (row["model"], row["group_id"])
        if group in group_splits and group_splits[group] != row["split"]:
            raise ValueError("Group crosses splits")
        group_splits[group] = row["split"]
        buckets[(row["model"], row["split"], "all")].append(row)
        buckets[(row["model"], row["split"], row["dataset"])].append(row)
    policy_rows, operations, location_rows, location_errors = [], [], [], []
    for (model, split, dataset), subset in buckets.items():
        for policy in ("A", "B"):
            policy_rows.append({"model": model, "split": split, "dataset": dataset, **metrics(subset, policy)})
        success = [r for r in subset if r["status"] == "success"]
        warm = [r["inference_seconds"] for r in success if not r["first_after_load"]]
        durations = [r["inference_seconds"] for r in success]
        memory = [r["gpu_peak_allocated_mib"] for r in success if r["gpu_peak_allocated_mib"] is not None]
        operations.append({"model": model, "split": split, "dataset": dataset,
                           "inference_mean_seconds": sum(durations)/len(durations) if durations else None,
                           "inference_p95_seconds": percentile(durations, .95),
                           "after_first_count": len(warm),
                           "after_first_mean_seconds": sum(warm)/len(warm) if warm else None,
                           "after_first_p95_seconds": percentile(warm, .95),
                           "peak_allocated_mib": max(memory) if memory else None})
    for row in rows:
        if row["model"] == "trufor" and row["label"] == 1 and row["status"] == "success" and row.get("mask_path"):
            try:
                location_rows.append(localization(row, args.map_threshold))
            except Exception as error:
                location_errors.append({"image_id": row["image_id"], "error": str(error)})
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, values in (("policy_metrics.csv", policy_rows), ("operations.csv", operations)):
        with (args.out / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    location = {"threshold": args.map_threshold, "direction": "official map, no inversion",
                "boundary": "all pixels, no border exclusion", "aggregation": "macro per image",
                "samples": len(location_rows), "rows": location_rows, "errors": location_errors,
                "mean_iou": sum(r["iou"] for r in location_rows)/len(location_rows) if location_rows else None,
                "mean_pixel_f1": sum(r["pixel_f1"] for r in location_rows)/len(location_rows) if location_rows else None}
    location_groups = defaultdict(list)
    for row in location_rows:
        location_groups[(row["model"], row["split"], row["dataset"])].append(row)
    location["by_dataset_and_split"] = [{"model":model,"split":split,"dataset":dataset,
        "samples":len(items),"mean_iou":sum(r["iou"] for r in items)/len(items),
        "mean_pixel_f1":sum(r["pixel_f1"] for r in items)/len(items)}
        for (model,split,dataset),items in location_groups.items()]
    (args.out / "summary.json").write_text(json.dumps({"policies": policy_rows, "operations": operations,
        "localization": location, "failures": [r for r in rows if r["status"] == "failed"]}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(policy_rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
