"""Post-hoc paired input-condition analysis; preserve the frozen final protocol."""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from PIL import Image
from sklearn.metrics import roc_auc_score
from build_robustness_data import VARIANTS
from evaluate import localization, percentile
from freeze_protocol import verify_freeze
from policies import decide, metrics
from run_inference import ROOT, read_manifest, sha256

BASE = ROOT / "runs/20261001_robustness"
ORIGINAL = ROOT / "runs/20261001_original"


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def describe(rows):
    valid = [r for r in rows if r["status"] == "success"]
    policies = {p: metrics(rows, p) for p in ("A", "B")}
    if len({r["label"] for r in valid}) == 2:
        independent = roc_auc_score([r["label"] for r in valid], [r["raw_score"] for r in valid])
        if abs(independent - policies["A"]["auroc"]) > 1e-12:
            raise ValueError("Independent AUROC mismatch")
    locations = [localization(r, .5) for r in valid if r["label"] == 1 and r.get("mask_path")]
    # Independently recompute pixel counts rather than relying on summary output.
    for row, result in zip([r for r in valid if r["label"] == 1 and r.get("mask_path")], locations):
        with np.load(ROOT / row["map_path"], allow_pickle=False) as maps:
            pred = maps["map"] >= .5
        with Image.open(ROOT / row["mask_path"]) as mask:
            truth = np.asarray(mask) > 0
        union = np.count_nonzero(pred | truth)
        intersection = np.count_nonzero(pred & truth)
        f1 = 2 * intersection / (np.count_nonzero(pred) + np.count_nonzero(truth))
        if abs(result["iou"] - intersection / union) > 1e-12 or abs(result["pixel_f1"] - f1) > 1e-12:
            raise ValueError("Independent localization mismatch")
    durations = [r["inference_seconds"] for r in valid]
    warm = [r["inference_seconds"] for r in valid if not r["first_after_load"]]
    memory = [r["gpu_peak_allocated_mib"] for r in valid if r["gpu_peak_allocated_mib"] is not None]
    return {"policies": policies, "localization": {
        "samples": len(locations), "mean_iou": np.mean([r["iou"] for r in locations]).item() if locations else None,
        "mean_pixel_f1": np.mean([r["pixel_f1"] for r in locations]).item() if locations else None, "rows": locations},
        "operations": {"mean_seconds": np.mean(durations).item() if durations else None,
            "p95_seconds": percentile(durations, .95), "after_first_count": len(warm),
            "after_first_mean_seconds": np.mean(warm).item() if warm else None,
            "after_first_p95_seconds": percentile(warm, .95), "peak_allocated_mib": max(memory) if memory else None}}


def main():
    manifest = ORIGINAL / "trufor_preparation/manifest.csv"
    verify_freeze(manifest, "trufor", ORIGINAL / "trufor_protocol.json")
    conditions = json.loads((BASE / "conditions.json").read_text(encoding="utf-8"))
    if sha256(manifest) != conditions["source_manifest_sha256"]:
        raise ValueError("Parent manifest changed")
    if sha256(ROOT / "scripts/build_robustness_data.py") != conditions["generator_sha256"]:
        raise ValueError("Input generator changed")
    parents = {r["image_id"]: r for r in read_manifest(manifest, "trufor")}
    for row in parents.values():
        row["label"] = int(row["label"])
    original_rows = read_rows(ORIGINAL / "trufor_preparation/tune_predictions.jsonl") + read_rows(ORIGINAL / "trufor_final/predictions.jsonl")
    originals = {r["image_id"]: r for r in original_rows}
    if set(originals) != set(parents) or len(original_rows) != 80:
        raise ValueError("Original reference coverage mismatch")
    audits = {s["image_id"]: s for s in conditions["samples"]}
    all_rows, changes = [], []
    result = {"study": conditions["study"], "conditions_sha256": sha256(BASE / "conditions.json"),
        "evaluator_sha256": sha256(__file__), "distinct_original_parents": 80, "derived_requests": 400,
        "map_threshold": .5, "direction": "official, no inversion", "boundary": "all pixels",
        "aggregation": "macro per positive image", "original": {}, "variants": {}, "comparisons": {}}
    for split in ("tune", "final"):
        result["original"][split] = describe([r for r in original_rows if r["split"] == split])
    for variant in VARIANTS:
        current_manifest = BASE / (variant + ".csv")
        if sha256(current_manifest) != conditions["variant_manifest_sha256"][variant]:
            raise ValueError("Variant manifest changed")
        expected = {r["image_id"]: r for r in read_manifest(current_manifest, "trufor")}
        for row in expected.values():
            row["label"] = int(row["label"])
        rows = read_rows(BASE / ("trufor_" + variant) / "predictions.jsonl")
        if len(rows) != 80 or len({r["image_id"] for r in rows}) != 80 or {r["image_id"] for r in rows} != set(expected):
            raise ValueError("Variant result coverage mismatch")
        for row in rows:
            parent = parents[row["parent_image_id"]]
            origin = originals[row["parent_image_id"]]
            audit = audits[row["image_id"]]
            for key in expected[row["image_id"]]:
                if row[key] != expected[row["image_id"]][key]:
                    raise ValueError("Prediction metadata mismatch: " + key)
            if row["parent_sha256"] != parent["sha256"] or row["parent_split"] != parent["split"]:
                raise ValueError("Parent metadata mismatch")
            for key in ("label", "group_id", "dataset"):
                if row[key] != parent[key]:
                    raise ValueError("Parent label/group/dataset changed")
            for key in ("weights_sha256", "code_commit", "preprocessing", "policy_version"):
                if row[key] != origin[key]:
                    raise ValueError("Frozen model processing changed")
            if sha256(ROOT / row["path"]) != audit["input_sha256"]:
                raise ValueError("Derived input changed")
            if row["mask_path"] and sha256(ROOT / row["mask_path"]) != audit["mask_sha256"]:
                raise ValueError("Derived mask changed")
            if row["status"] == "success":
                with np.load(ROOT / row["map_path"], allow_pickle=False) as maps:
                    with Image.open(ROOT / row["path"]) as image:
                        shape = (image.height, image.width)
                    for key in ("map", "conf"):
                        array = maps[key]
                        if array.shape != shape or not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
                            raise ValueError("Invalid map geometry/range")
                    if float(maps["score"]) != row["raw_score"]:
                        raise ValueError("Saved score differs")
                if origin["status"] == "success":
                    changes.append({"image_id": row["image_id"], "parent_image_id": row["parent_image_id"],
                        "variant": variant, "parent_split": row["parent_split"], "label": row["label"],
                        "original_score": origin["raw_score"], "derived_score": row["raw_score"],
                        "score_delta": row["raw_score"] - origin["raw_score"],
                        "policy_transitions": {p: [decide("trufor", origin["raw_score"], p)["decision"],
                            decide("trufor", row["raw_score"], p)["decision"]] for p in ("A", "B")}})
        result["variants"][variant] = {split: describe([r for r in rows if r["parent_split"] == split]) for split in ("tune", "final")}
        result["variants"][variant]["all_operations"] = describe(rows)["operations"]
        all_rows.extend(rows)
    for variant in VARIANTS:
        result["comparisons"][variant] = {}
        for split in ("tune", "final"):
            subset = [r for r in changes if r["variant"] == variant and r["parent_split"] == split]
            transitions = {}
            for policy in ("A", "B"):
                counts = defaultdict(int)
                for row in subset:
                    before, after = row["policy_transitions"][policy]
                    counts[str(before) + " -> " + str(after)] += 1
                transitions[policy] = dict(counts)
            result["comparisons"][variant][split] = {"pairs": len(subset),
                "mean_score_delta": np.mean([r["score_delta"] for r in subset]).item(),
                "mean_absolute_score_delta": np.mean([abs(r["score_delta"]) for r in subset]).item(),
                "policy_transitions": transitions}
    result["failures"] = [r for r in all_rows if r["status"] != "success"]
    result["verification"] = {"checked_inputs": len(all_rows), "checked_maps": sum(r["status"] == "success" for r in all_rows),
        "checked_masks": sum(bool(r["mask_path"]) for r in all_rows), "frozen_original_protocol_verified": True,
        "independent_auroc_and_pixel_counts_verified": True}
    destination = BASE / "evaluation"
    destination.mkdir(exist_ok=False)
    (destination / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    (destination / "paired_changes.json").write_text(json.dumps(changes, indent=2, allow_nan=False), encoding="utf-8")
    print("Verified 400 paired derived requests; failures", len(result["failures"]))
    for variant in VARIANTS:
        entry = result["variants"][variant]["final"]
        print(variant, "COVERAGE AUROC", entry["policies"]["A"]["auroc"], "IoU", entry["localization"]["mean_iou"])


if __name__ == "__main__":
    main()
