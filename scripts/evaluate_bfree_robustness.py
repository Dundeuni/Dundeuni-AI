"""Verify and describe B-Free paired robustness without selecting new thresholds."""
import json
import math
from build_robustness_data import VARIANTS
from evaluate_robustness import describe, read_rows
from freeze_protocol import verify_freeze
from policies import decide
from run_inference import ROOT, read_manifest, sha256


def main():
    base = ROOT / "runs/20261002_bfree_raise"
    directory = base / "robustness"
    manifest = base / "preparation/manifest.csv"
    verify_freeze(manifest, "bfree", base / "bfree_protocol.json")
    record = json.loads((directory / "conditions.json").read_text(encoding="utf-8"))
    if sha256(manifest) != record["source_manifest_sha256"]:
        raise ValueError("Parent manifest changed")
    for name, key in (("build_bfree_robustness_data.py", "generator_sha256"), ("build_robustness_data.py", "shared_transform_code_sha256")):
        if sha256(ROOT / "scripts" / name) != record[key]:
            raise ValueError("Input transform code changed")
    originals = read_rows(base / "bfree_tune/predictions.jsonl") + read_rows(base / "bfree_final/predictions.jsonl")
    lookup = {r["image_id"]: r for r in originals}
    if len(originals) != 80 or len(lookup) != 80:
        raise ValueError("Incomplete original references")
    audited = {s["image_id"]: s for s in record["samples"]}
    result = {"study": record["study"], "evaluator_sha256": sha256(__file__), "conditions_sha256": sha256(directory / "conditions.json"),
        "original_parents": 80, "derived_requests": 400, "original": {split: describe([r for r in originals if r["split"] == split]) for split in ("tune", "final")},
        "variants": {}, "failures": []}
    changes = []
    for variant in VARIANTS:
        path = directory / (variant + ".csv")
        if sha256(path) != record["variant_manifest_sha256"][variant]:
            raise ValueError("Variant manifest changed")
        expected = {r["image_id"]: r for r in read_manifest(path, "bfree")}
        rows = read_rows(directory / ("bfree_" + variant) / "predictions.jsonl")
        if len(rows) != 80 or len({r["image_id"] for r in rows}) != 80 or {r["image_id"] for r in rows} != set(expected):
            raise ValueError("Variant result coverage mismatch")
        for row in rows:
            for key, value in expected[row["image_id"]].items():
                if row[key] != (int(value) if key == "label" else value):
                    raise ValueError("Manifest/result metadata mismatch")
            parent = lookup[row["parent_image_id"]]
            for key in ("group_id", "label", "dataset", "code_commit", "weights_sha256", "preprocessing", "policy_version"):
                if row[key] != parent[key]:
                    raise ValueError("Parent/model condition differs")
            if row["parent_split"] != parent["split"] or row["parent_sha256"] != parent["sha256"]:
                raise ValueError("Parent lineage differs")
            if row["sha256"] != audited[row["image_id"]]["input_sha256"]:
                raise ValueError("Recorded input hash differs")
            if row["status"] != "success":
                result["failures"].append(row)
                continue
            if not math.isfinite(row["raw_score"]) or row["imgsize"] != list(reversed(audited[row["image_id"]]["size"])):
                raise ValueError("Score/input size invalid")
            changes.append({"image_id": row["image_id"], "parent_image_id": row["parent_image_id"], "parent_split": row["parent_split"],
                "variant": variant, "label": row["label"], "original_logit": parent["raw_score"], "derived_logit": row["raw_score"],
                "normalized_score_delta": row["normalized_score"] - parent["normalized_score"],
                "policy_transitions": {p: [decide("bfree", parent["raw_score"], p)["decision"], decide("bfree", row["raw_score"], p)["decision"]] for p in ("A", "B")}})
        result["variants"][variant] = {split: describe([r for r in rows if r["parent_split"] == split]) for split in ("tune", "final")}
        result["variants"][variant]["all_operations"] = describe(rows)["operations"]
        print(variant, "final AUROC", result["variants"][variant]["final"]["policies"]["A"]["auroc"], flush=True)
    result["verification"] = {"input_hashes_checked": 400, "metadata_lineage_checked": 400, "frozen_protocol_verified": True,
        "independent_sklearn_auroc_verified": True, "failed_requests": len(result["failures"])}
    out = directory / "evaluation"
    out.mkdir(exist_ok=False)
    with (out / "summary.json").open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2, allow_nan=False)
    with (out / "paired_changes.json").open("x", encoding="utf-8") as target:
        json.dump(changes, target, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
