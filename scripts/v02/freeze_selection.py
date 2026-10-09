"""Freeze setting-only selection and CV before validation process starts."""
import argparse,json
from pathlib import Path
from common import ROOT,RUN,sha256,save_json,timestamp
from policy_selection import select,cross_validate
def main():
    parser=argparse.ArgumentParser();parser.add_argument("model",choices=["bfree","trufor","mesorch","mesorch_p"]);args=parser.parse_args()
    folder=RUN/"inference"/args.model/"setting";predictions=folder/"predictions.jsonl"
    done=json.loads((folder/"completion.json").read_text());metadata=json.loads((folder/"metadata.json").read_text())
    rows=[json.loads(line) for line in predictions.read_text().splitlines() if line]
    task="bfree" if args.model=="bfree" else "tampering";manifest=RUN/(task+"_manifest.json")
    originals=json.loads(manifest.read_text())
    expected=[r for r in originals["rows"] if r["role"]=="setting"]
    if {r["image_id"] for r in rows}!={r["image_id"] for r in expected} or len(rows)!=len(expected):raise ValueError("Incomplete/duplicate setting predictions")
    if done["prediction_sha256"]!=sha256(predictions) or done["recorded"]!=len(rows):raise ValueError("Setting completion mismatch")
    for name,digest in metadata["code_sha256"].items():
        if sha256(ROOT/name)!=digest:raise ValueError("Implementation differs from setting run")
    protocol=json.loads((RUN/"approved_protocol.json").read_text());targets=protocol["targets"]
    cv=cross_validate(rows,args.model,targets);choice=select(rows,args.model,targets)
    code_paths=["scripts/v02/inference.py","scripts/v02/policy_selection.py","scripts/v02/mesorch_adapter.py","scripts/v02/build_inputs.py","scripts/v02/common.py","scripts/run_inference.py","scripts/policies.py"]
    official_root=ROOT/("third_party/B-Free/code" if args.model=="bfree" else "third_party/TruFor/TruFor_train_test" if args.model=="trufor" else "third_party/Mesorch")
    code_paths.extend(str(p.relative_to(ROOT)) for p in sorted(official_root.rglob("*")) if p.is_file() and p.suffix in [".py",".yaml",".yml",".cfg"] and "__pycache__" not in p.parts)
    freeze={"version":"baseline-v0.2-20261004","model":args.model,"frozen_at_utc":timestamp(),
      "manifest_sha256":sha256(manifest),"setting_predictions_sha256":sha256(predictions),"approved_protocol_sha256":sha256(RUN/"approved_protocol.json"),
      "weights_path":metadata["weights_path"],"weights_sha256":metadata["weights_sha256"],
      "code_sha256":{p:sha256(ROOT/p) for p in code_paths},"targets":targets,
      "selection":choice,"cross_validation":cv,"validation_scores_seen":False,
      "selection_failure_behavior":"Only prespecified reference candidates are evaluated on validation; no invented improved service policy",
      "strata":"Overall gates separately for all six conditions; dataset/generator strata descriptive",
      "scope_adjustment_sha256":sha256(RUN/"scope_adjustment.json")}
    path=RUN/(args.model+"_policy_freeze.json")
    save_json(path,freeze)
    print(args.model,"policy frozen",choice["status"],"eligible",choice["eligible_count"],"candidate",choice["selected"],flush=True)
if __name__=="__main__":main()
