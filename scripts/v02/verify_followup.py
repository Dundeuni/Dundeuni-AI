"""Verify completed results, all native maps, frozen sources, and preserved v0.1."""
import json,sys,math,collections
from pathlib import Path
import numpy as np
from common import ROOT,RUN,sha256,save_json,timestamp
from inference import verify_validation_guard,location_metrics
def main():
    from PIL import Image
    sys.path.insert(0,str(ROOT/"scripts"))
    from freeze_protocol import verify_freeze
    old_checks={}
    for model,manifest,protocol in [
       ("bfree","runs/20261002_bfree_raise/preparation/manifest.csv","runs/20261002_bfree_raise/bfree_protocol.json"),
       ("trufor","runs/20261001_original/trufor_preparation/manifest.csv","runs/20261001_original/trufor_protocol.json")]:
        verify_freeze(ROOT/manifest,model,ROOT/protocol);old_checks[model]=True
    inventory=json.loads((ROOT/"runs/20261004_relocation/copy_manifest.json").read_text())
    protected={}
    names={"scripts/run_inference.py","scripts/policies.py","scripts/evaluate.py","scripts/freeze_protocol.py",
       "reports/BFREE_ORIGINAL_RESULTS_20261002.md","reports/ROBUSTNESS_AND_CPU_RESULTS_20261001.md"}
    for item in inventory["files"]:
        name=item["path"].replace("\\","/")
        if name in names:
            actual=sha256(ROOT/item["path"])
            if actual!=item["sha256"]:raise ValueError("Protected v0.1 artifact changed: "+name)
            protected[name]=actual
    if len(protected)!=len(names):raise ValueError("Missing protected artifact inventory")
    total=failed=map_count=0;cohorts={}
    for model in ["bfree","trufor","mesorch","mesorch_p"]:
        task="bfree" if model=="bfree" else "tampering";manifest=RUN/(task+"_manifest.json")
        freeze=RUN/(model+"_policy_freeze.json")
        verify_validation_guard(manifest,model,freeze)
        plan=json.loads(manifest.read_text())
        for role in ["setting","validation"]+([] if model=="bfree" else ["comparison"]):
            folder=RUN/"inference"/model/role
            rows=[json.loads(l) for l in (folder/"predictions.jsonl").read_text().splitlines() if l]
            expected=[r for r in plan["rows"] if r["role"]==role]
            if len(rows)!=len(expected) or {r["image_id"] for r in rows}!={r["image_id"] for r in expected}:raise ValueError("Incomplete or duplicated requests")
            completion=json.loads((folder/"completion.json").read_text())
            if sha256(folder/"predictions.jsonl")!=completion["prediction_sha256"]:raise ValueError("Score file hash mismatch")
            metadata=json.loads((folder/"metadata.json").read_text())
            if metadata["manifest_sha256"]!=sha256(manifest):raise ValueError("Manifest metadata differs")
            if role=="validation" and metadata["freeze_sha256"]!=sha256(freeze):raise ValueError("Wrong validation freeze")
            for row in rows:
                total+=1
                if row["status"]!="success":failed+=1;continue
                if not all(math.isfinite(v) and 0<=v<=1 for v in row["scores"].values()):raise ValueError("Invalid image score")
                if row["raw_score"] is not None and not math.isfinite(row["raw_score"]):raise ValueError("Nonfinite raw score")
                if row.get("maps_path"):
                    p=ROOT/row["maps_path"]
                    if sha256(p)!=row["maps_sha256"]:raise ValueError("Map bytes changed")
                    with np.load(p) as saved:
                        predicted=saved["map"]
                        if row.get("mask_path"):
                            with Image.open(ROOT/row["mask_path"]) as im:truth=np.asarray(im)>0
                        else:truth=np.zeros(predicted.shape,dtype=bool)
                        checked=location_metrics(predicted,truth,row["label"])
                        if checked!=row["localization"]:raise ValueError("Saved map/localization metric mismatch")
                        if model in ["mesorch","mesorch_p"]:
                            native=saved["native_map"]
                            if native.shape!=(512,512):raise ValueError("Native map shape changed")
                            k=max(1,int(np.ceil(native.size*.01)));values=native.reshape(-1)
                            scores={"mean":float(values.mean()),"max":float(values.max()),"top1":float(np.partition(values,len(values)-k)[-k:].mean())}
                            if scores!=row["scores"]:raise ValueError("Adapter score/native map mismatch")
                    map_count+=1
            cohorts[model+":"+role]={"requests":len(rows),"failed":sum(r["status"]!="success" for r in rows),"prediction_sha256":sha256(folder/"predictions.jsonl")}
    if total!=6720:raise ValueError("Unexpected total scope")
    for name in ["approved_protocol.json","scope_adjustment.json","bfree_manifest.json","tampering_manifest.json","evaluation.json","validation_group_uncertainty.json"]:
        if not (RUN/name).is_file():raise FileNotFoundError(name)
    artifacts=json.loads((RUN/"report_artifacts.json").read_text())
    if sha256(ROOT/artifacts["report_path"])!=artifacts["report_sha256"]:raise ValueError("Report bytes changed")
    for p,digest in artifacts["artifacts"].items():
        if sha256(ROOT/p)!=digest:raise ValueError("Figure changed")
    save_json(RUN/"final_verification.json",{"verified_at_utc":timestamp(),"requests":total,"failures":failed,"maps_revalidated":map_count,
       "cohorts":cohorts,"frozen_v01_verified":old_checks,"protected_artifacts_sha256":protected,"manifest_freeze_and_native_map_checks":True,
       "artifacts_verified":True,"report_sha256":artifacts["report_sha256"],"scope":"400 generation originals,240tampering originals,6conditions,4model executions;Columbia reference-only"})
    print("Final verification passed",total,"requests",map_count,"maps",failed,"failures; v0.1 preserved",flush=True)
if __name__=="__main__":main()
