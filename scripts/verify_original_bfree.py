"""Verify frozen B-Free tune/final metadata, labels, scores and independent AUROC."""
import json
import math
from collections import Counter
from sklearn.metrics import roc_auc_score
from freeze_protocol import verify_freeze
from policies import decide, metrics
from run_inference import ROOT, read_manifest, sha256

BASE = ROOT / "runs/20261002_bfree_raise"


def main():
    manifest = BASE / "preparation/manifest.csv"
    frozen = BASE / "bfree_protocol.json"
    protocol = verify_freeze(manifest, "bfree", frozen)
    rows = read_manifest(manifest, "bfree")
    summaries, all_ids, by_group = {}, set(), {}
    for split in ("tune", "final"):
        run = BASE / ("bfree_" + split)
        predictions = [json.loads(line) for line in (run / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line]
        expected = {r["image_id"]: r for r in rows if r["split"] == split}
        if len(predictions) != 40 or len({r["image_id"] for r in predictions}) != 40 or {r["image_id"] for r in predictions} != set(expected):
            raise ValueError("Incomplete split coverage")
        environment = json.loads((run / "environment.json").read_text(encoding="utf-8"))
        if environment["weights_sha256"] != protocol["weights_sha256"] or environment["code_commit"] != protocol["code_commit"]:
            raise ValueError("Frozen model mismatch")
        if split == "final" and environment["policy_freeze_sha256"] != sha256(frozen):
            raise ValueError("Final run did not use frozen protocol")
        if split == "tune" and sha256(run / "predictions.jsonl") != protocol["tune_predictions_sha256"]:
            raise ValueError("Tuning results changed since freezing")
        valid, cases = [], []
        for row in predictions:
            expected_row = expected[row["image_id"]]
            for key, value in expected_row.items():
                if row[key] != (int(value) if key == "label" else value):
                    raise ValueError("Manifest/prediction mismatch: " + key)
            if row["image_id"] in all_ids:
                raise ValueError("Duplicate image ID across splits")
            all_ids.add(row["image_id"])
            if row["group_id"] in by_group and by_group[row["group_id"]] != split:
                raise ValueError("Scene group crosses splits")
            by_group[row["group_id"]] = split
            if row["status"] == "success":
                if not math.isfinite(row["raw_score"]):
                    raise ValueError("Non-finite logit")
                probability = decide("bfree", row["raw_score"], "A")["normalized_score"]
                if abs(probability - row["normalized_score"]) > 1e-12:
                    raise ValueError("Probability/logit mismatch")
                valid.append(row)
                decisions = {p: decide("bfree", row["raw_score"], p)["decision"] for p in ("A", "B")}
                if any(value is None or value != row["label"] for value in decisions.values()):
                    cases.append({"image_id": row["image_id"], "label": row["label"], "logit": row["raw_score"],
                        "normalized_score": probability, "decisions": decisions})
        independent = float(roc_auc_score([r["label"] for r in valid], [r["raw_score"] for r in valid]))
        evaluation = json.loads((run / "evaluation/summary.json").read_text(encoding="utf-8"))
        for policy in ("A", "B"):
            matching = [r for r in evaluation["policies"] if r["policy"] == policy and r["dataset"] == "all"]
            if len(matching) != 1:
                raise ValueError("Missing split policy summary")
            for key, value in metrics(predictions, policy).items():
                if matching[0][key] != value:
                    raise ValueError("Summary metric differs: " + key)
            if abs(matching[0]["auroc"] - independent) > 1e-12:
                raise ValueError("Independent AUROC mismatch")
        summaries[split] = {"requests": 40, "success": len(valid), "failed": 40-len(valid), "independent_sklearn_auroc": independent,
            "generator_counts": dict(Counter(r["generator"] for r in predictions if r["label"])),
            "distinct_scene_groups": len({r["group_id"] for r in predictions}), "error_or_abstention_cases": cases,
            "predictions_sha256": sha256(run / "predictions.jsonl"), "environment_sha256": sha256(run / "environment.json")}
    record = {"code_sha256": sha256(__file__), "frozen_protocol_verified": True,
        "all_ids_labels_metadata_input_hashes_verified": True, "independent_auroc_verified": True,
        "scene_group_split_leakage": False, "requests": len(all_ids), "splits": summaries}
    with (BASE / "bfree_verification.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Verified B-Free original 80-input scope", json.dumps(summaries))


if __name__ == "__main__":
    main()
