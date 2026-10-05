"""Compare actual inference against official examples and independent AUROC."""
import csv
import json
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score
from policies import decide
from run_inference import ROOT


def main():
    base = ROOT / "runs/20261001_baseline"
    reference_path = ROOT / "third_party/B-Free/code/demo_images/results.csv"
    with reference_path.open(encoding="utf-8", newline="") as source:
        reference = {r["filename"]: float(r["BFREE_dino2reg4"]) for r in csv.DictReader(source)}
    demo_rows = [json.loads(l) for l in (base / "bfree_demo/predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    delta = max(abs(r["raw_score"] - reference[Path(r["path"]).name]) for r in demo_rows)
    if delta > 1e-4:
        raise AssertionError("B-Free official example mismatch")
    trufor_row = json.loads((base / "trufor_one/predictions.jsonl").read_text(encoding="utf-8"))
    with np.load(base / "trufor_official_single/pristine1.npz", allow_pickle=False) as official:
        with np.load(ROOT / trufor_row["map_path"], allow_pickle=False) as adapted:
            map_delta = float(np.max(np.abs(official["map"] - adapted["map"])))
            conf_delta = float(np.max(np.abs(official["conf"] - adapted["conf"])))
            score_delta = abs(float(official["score"]) - trufor_row["raw_score"])
    if max(map_delta, conf_delta, score_delta) > 1e-6:
        raise AssertionError("TruFor official preprocessing/output mismatch")
    audit = {"official_comparison": {"bfree_max_abs_logit_delta": delta,
                "trufor_map_max_abs_delta": map_delta, "trufor_conf_max_abs_delta": conf_delta,
                "trufor_score_abs_delta": score_delta}}
    for model in ("bfree", "trufor"):
        rows = [json.loads(l) for l in (base / (model + "_available") / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        valid = [r for r in rows if r["status"] == "success"]
        summary = json.loads((base / (model + "_available") / "evaluation/summary.json").read_text(encoding="utf-8"))
        auc = roc_auc_score([r["label"] for r in valid], [r["raw_score"] for r in valid])
        if abs(auc - summary["policies"][0]["auroc"]) > 1e-12:
            raise AssertionError("Independent AUROC mismatch")
        audit[model] = {"requests": len(rows), "valid": len(valid), "sklearn_auroc": auc,
                       "errors_and_abstentions": []}
        for row in valid:
            a = decide(model, row["raw_score"], "A")["decision"]
            b = decide(model, row["raw_score"], "B")["decision"]
            if a != row["label"] or b != row["label"]:
                audit[model]["errors_and_abstentions"].append({"id": row["image_id"], "label": row["label"],
                    "raw_score": row["raw_score"], "A": a, "B": b})
    (base / "verification.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
