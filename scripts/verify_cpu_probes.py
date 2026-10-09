"""Compare identical CPU/GPU inputs, fixed policies, scores, and map numerics."""
import json
import numpy as np
from evaluate import percentile
from evaluate_robustness import read_rows
from freeze_protocol import verify_freeze
from policies import decide
from run_inference import ROOT, sha256


def main():
    base = ROOT / "runs/20261001_robustness"
    original = ROOT / "runs/20261001_original"
    verify_freeze(original / "trufor_preparation/manifest.csv", "trufor", original / "trufor_protocol.json")
    summary = {"verifier_sha256": sha256(__file__), "scope": "four previously observed inputs per model; CPU functional probe, not performance validation",
        "official_preprocessing_modified": False, "models": {}}
    references = {"bfree": ROOT / "runs/20261001_baseline/bfree_demo", "trufor": original / "trufor_final"}
    for model, reference in references.items():
        current = base / (model + "_cpu")
        rows = read_rows(current / "predictions.jsonl")
        gpu = {r["image_id"]: r for r in read_rows(reference / "predictions.jsonl")}
        env = json.loads((current / "environment.json").read_text(encoding="utf-8"))
        threads = json.loads((current / "cpu_probe.json").read_text(encoding="utf-8"))
        if len(rows) != 4 or len({r["image_id"] for r in rows}) != 4 or env["device"] != "cpu":
            raise ValueError("Incomplete CPU probe")
        comparisons, failures = [], []
        for row in rows:
            reference_row = gpu[row["image_id"]]
            for key in ("sha256", "label", "group_id", "path", "code_commit", "weights_sha256", "preprocessing", "policy_version"):
                if row[key] != reference_row[key]:
                    raise ValueError("CPU/GPU comparison changed condition: " + key)
            if sha256(ROOT / row["path"]) != row["sha256"]:
                raise ValueError("CPU input changed")
            if row["device"] != "cpu" or row["gpu_peak_allocated_mib"] is not None:
                raise ValueError("Probe did not use CPU")
            if row["status"] != "success":
                failures.append(row)
                continue
            if reference_row["status"] != "success":
                raise ValueError("GPU reference unavailable")
            item = {"image_id": row["image_id"], "label": row["label"], "size": row["imgsize"],
                "cpu_raw_score": row["raw_score"], "gpu_raw_score": reference_row["raw_score"],
                "absolute_raw_score_delta": abs(row["raw_score"] - reference_row["raw_score"]),
                "absolute_normalized_score_delta": abs(row["normalized_score"] - reference_row["normalized_score"]),
                "policies": {p: {"cpu": decide(model, row["raw_score"], p)["decision"],
                    "gpu": decide(model, reference_row["raw_score"], p)["decision"]} for p in ("A", "B")},
                "cpu_seconds": row["inference_seconds"], "gpu_reference_seconds": reference_row["inference_seconds"]}
            if model == "trufor":
                item["maps"] = {}
                with np.load(ROOT / row["map_path"], allow_pickle=False) as cpu_map, np.load(ROOT / reference_row["map_path"], allow_pickle=False) as gpu_map:
                    if float(cpu_map["score"]) != row["raw_score"]:
                        raise ValueError("CPU saved score mismatch")
                    for key in ("map", "conf"):
                        left, right = cpu_map[key], gpu_map[key]
                        if left.shape != right.shape or list(left.shape) != row["imgsize"] or not np.isfinite(left).all() or left.min() < 0 or left.max() > 1:
                            raise ValueError("Invalid CPU/GPU map shape/range")
                        delta = np.abs(left.astype(np.float64) - right.astype(np.float64))
                        item["maps"][key] = {"max_absolute_delta": float(delta.max()), "mean_absolute_delta": float(delta.mean()),
                            "pixels_crossing_0_5": int(np.count_nonzero((left >= .5) != (right >= .5)))}
            comparisons.append(item)
        valid = [r for r in rows if r["status"] == "success"]
        durations = [r["inference_seconds"] for r in valid]
        warm = [r["inference_seconds"] for r in valid if not r["first_after_load"]]
        summary["models"][model] = {"requests": len(rows), "success": len(valid), "failures": failures,
            "load_seconds": env["load_seconds"], "thread_settings": threads,
            "mean_seconds": float(np.mean(durations)) if durations else None, "p95_seconds": percentile(durations, .95),
            "after_first_count": len(warm), "after_first_mean_seconds": float(np.mean(warm)) if warm else None,
            "max_absolute_raw_score_delta": max((r["absolute_raw_score_delta"] for r in comparisons), default=None),
            "max_absolute_normalized_score_delta": max((r["absolute_normalized_score_delta"] for r in comparisons), default=None),
            "policy_matches": {p: sum(r["policies"][p]["cpu"] == r["policies"][p]["gpu"] for r in comparisons) for p in ("A", "B")},
            "comparisons": comparisons, "environment_sha256": sha256(current / "environment.json")}
        print(model, "success", len(valid), "mean seconds", summary["models"][model]["mean_seconds"], "policy matches", summary["models"][model]["policy_matches"])
    (base / "cpu_verification.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
