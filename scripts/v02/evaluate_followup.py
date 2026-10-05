"""Evaluate only frozen policies; keep setting, validation and comparison separate."""
import json,collections,statistics,sys
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score,average_precision_score
from common import ROOT,RUN,CONDITIONS,sha256,save_json,timestamp
from policy_selection import candidates,metrics
from inference import verify_validation_guard
def load_rows(model,role):
    path=RUN/"inference"/model/role/"predictions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
def score_summary(rows,aggregation,model):
    valid=[r for r in rows if r["status"]=="success"]
    labels=[r["label"] for r in valid]
    # Use original logits for B-Free AUROC/AP, avoiding sigmoid saturation.
    values=[r["raw_score"] if model=="bfree" else r["scores"][aggregation] for r in valid]
    return {"aggregation":aggregation,"AUROC":float(roc_auc_score(labels,values)) if len(set(labels))==2 else None,
       "AP":float(average_precision_score(labels,values)) if len(set(labels))==2 else None,
       "positive_prevalence":sum(labels)/len(labels) if labels else None,"success":len(valid),
       "score_semantics":"Uncalibrated model/adapter score, not an image-fraud probability"}
def location_summary(rows):
    positive=[r["localization"] for r in rows if r["status"]=="success" and r["label"]==1 and r.get("localization",{}).get("F1") is not None]
    negative=[r["localization"] for r in rows if r["status"]=="success" and r["label"]==0 and r.get("localization")]
    def mean(key,items):return float(np.mean([r[key] for r in items])) if items else None
    return {"positive_evaluated":len(positive),"positive_empty_gt":sum(r["status"]=="success" and r["label"]==1 and r.get("localization",{}).get("location_status")=="empty_positive_mask_after_geometry" for r in rows),
       "mean_positive_F1":mean("F1",positive),"mean_positive_IoU":mean("IoU",positive),
       "mean_negative_false_area":mean("false_positive_area_fraction",negative),
       "negative_evaluated":len(negative),"direction":"Official positive forgery; >=.5, never inverted; original input coordinates",
       "averaging":"Per-positive-image means, excludes normal images; normal false area reported separately"}
def reference_candidates(model):
    grid=candidates(model)
    if model in ["bfree","trufor"]:return [next(c for c in grid if c["id"]==id) for id in ["A","B"]]
    return [c for c in grid if c["id"] in [a+"_binary_0.5" for a in ["mean","max","top1"]]+[a+"_B" for a in ["mean","max","top1"]]]
def summarize(rows,model,selected):
    policies=reference_candidates(model)
    if selected is not None and all(selected!=p for p in policies):policies.append(selected)
    output={"requests":len(rows),"success":sum(r["status"]=="success" for r in rows),
       "failures":sum(r["status"]!="success" for r in rows),"original_parent_count":len({r["parent_image_id"] for r in rows}),
       "source_group_count":len({r["group_id"] for r in rows}),"policies":{p["id"]:metrics(rows,p) for p in policies},
       "scores":[score_summary(rows,a,model) for a in (["official"] if model in ["bfree","trufor"] else ["mean","max","top1"])],
       "localization":location_summary(rows) if model!="bfree" else None,
       "latency_p50":float(np.median([r["latency_seconds"] for r in rows if r["status"]=="success"])) if any(r["status"]=="success" for r in rows) else None,
       "latency_p95":float(np.percentile([r["latency_seconds"] for r in rows if r["status"]=="success"],95)) if any(r["status"]=="success" for r in rows) else None,
       "peak_gpu_GiB":max([r["peak_gpu_allocated_bytes"] for r in rows if r["status"]=="success"],default=0)/1024**3}
    for metric in output["policies"].values():
        n0,n1=metric["negative"],metric["positive"]
        metric["balanced_accuracy_with_abstentions_in_denominator"]=(
            .5*((n0-metric["FP"]-metric["abstain_negative"])/n0+
                (n1-metric["FN"]-metric["abstain_positive"])/n1)) if n0 and n1 else None
    return output
def main():
    output={}
    for model in ["bfree","trufor","mesorch","mesorch_p"]:
        freeze_path=RUN/(model+"_policy_freeze.json");freeze=json.loads(freeze_path.read_text())
        task="bfree" if model=="bfree" else "tampering"
        verify_validation_guard(RUN/(task+"_manifest.json"),model,freeze_path)
        selected=freeze["selection"]["selected"]
        summary={"selection_status":freeze["selection"]["status"],"selected":selected,"cv":freeze["cross_validation"],
             "freeze_sha256":sha256(freeze_path),"roles":{}}
        for role in ["setting","validation"]+([] if model=="bfree" else ["comparison"]):
            folder=RUN/"inference"/model/role
            completion=json.loads((folder/"completion.json").read_text())
            rows=[json.loads(line) for line in (folder/"predictions.jsonl").read_text().splitlines() if line]
            if sha256(folder/"predictions.jsonl")!=completion["prediction_sha256"]:raise ValueError("Predictions changed")
            if role=="validation":
                meta=json.loads((folder/"metadata.json").read_text())
                if meta["freeze_sha256"]!=sha256(freeze_path):raise ValueError("Validation ran with wrong freeze")
            manifest=json.loads((RUN/(task+"_manifest.json")).read_text())
            expected={r["image_id"] for r in manifest["rows"] if r["role"]==role}
            if {r["image_id"] for r in rows}!=expected or len(rows)!=len(expected):raise ValueError("Incomplete result alignment")
            bycondition={};strata={}
            for condition in CONDITIONS:
                subset=[r for r in rows if r["condition"]==condition]
                bycondition[condition]=summarize(subset,model,selected)
                for ds in sorted({r["dataset"] for r in subset}):
                    dsrows=[r for r in subset if r["dataset"]==ds]
                    strata[condition+":"+ds]=summarize(dsrows,model,selected)
                if model=="bfree":
                    real=[r for r in subset if r["label"]==0]
                    for generator in sorted({r["generator"] for r in subset if r["label"]}):
                        genrows=[r for r in subset if r["label"]==1 and r["generator"]==generator]
                        strata[condition+":generator:"+generator]=summarize(real+genrows,model,selected)
                elif any(r["label"] for r in subset):
                    for name,low,high in [("small_mask",0,.1),("medium_mask",.1,.3),("large_mask",.3,1.00001)]:
                        stratum=[r for r in subset if r["label"]==1 and low<=r["mask_fraction"]<high]
                        strata[condition+":"+name]={"positive_count":len(stratum),"localization":location_summary(stratum)}
            summary["roles"][role]={"by_condition":bycondition,"strata":strata,
               "prediction_sha256":sha256(folder/"predictions.jsonl"),"non_independent":role=="comparison"}
        output[model]=summary
    paired={}
    for role in ["setting","validation","comparison"]:
        indexed={}
        for model in ["trufor","mesorch","mesorch_p"]:
            p=RUN/"inference"/model/role/"predictions.jsonl"
            indexed[model]={r["image_id"]:r for r in [json.loads(line) for line in p.read_text().splitlines() if line]}
        if any(set(x)!=set(indexed["trufor"]) for x in indexed.values()):raise ValueError("Models were not evaluated on identical requests")
        for condition in CONDITIONS:
            ids=[id for id,r in indexed["trufor"].items() if r["condition"]==condition and r["label"]==1 and all(indexed[m][id]["status"]=="success" and indexed[m][id]["localization"]["F1"] is not None for m in indexed)]
            paired[role+":"+condition]={"joint_successful_positive_images":len(ids),
               "mean_F1_by_model":{m:float(np.mean([indexed[m][id]["localization"]["F1"] for id in ids])) if ids else None for m in indexed},
               "Mesorch_F1_higher_count":sum(indexed["mesorch"][id]["localization"]["F1"]>indexed["trufor"][id]["localization"]["F1"] for id in ids),
               "MesorchP_F1_higher_count":sum(indexed["mesorch_p"][id]["localization"]["F1"]>indexed["trufor"][id]["localization"]["F1"] for id in ids)}
    save_json(RUN/"evaluation.json",{"created_at_utc":timestamp(),"models":output,"paired_location":paired,
        "scope_adjustment":json.loads((RUN/"scope_adjustment.json").read_text()),"sample_units":"Conditions, generators and same-source negatives/positives are correlated; do not treat6720requests as independent photos",
        "validation_not_reused_for_selection":True,"holdout_limitations":"Selected source/photo review does not prove zero shared events or absent model pretraining overlap"})
    print("Frozen evaluation complete",flush=True)
if __name__=="__main__":main()
