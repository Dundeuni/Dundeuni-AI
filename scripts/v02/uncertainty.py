"""Conditional source-group bootstrap intervals after frozen validation only."""
import json,collections
import numpy as np
from common import ROOT,RUN,CONDITIONS,SEED,save_json,timestamp
from policy_selection import decision
from evaluate_followup import load_rows,reference_candidates
def percentile(values):
    values=np.asarray(values);values=values[np.isfinite(values)]
    return {"low":float(np.percentile(values,2.5)) if len(values) else None,
      "high":float(np.percentile(values,97.5)) if len(values) else None,"usable_resamples":len(values)}
def main():
    evaluated=json.loads((RUN/"evaluation.json").read_text());results={};paired_boot={};paired_groups={}
    for model in ["bfree","trufor","mesorch","mesorch_p"]:
        rows=load_rows(model,"validation")
        groups=sorted({r["group_id"] for r in rows});lookup={g:i for i,g in enumerate(groups)}
        dataset={r["group_id"]:r["dataset"] for r in rows}
        weights=np.zeros((2000,len(groups)));rng=np.random.RandomState(SEED)
        for ds in sorted(set(dataset.values())):
            ids=[lookup[g] for g in groups if dataset[g]==ds];n=len(ids)
            weights[:,ids]=rng.multinomial(n,[1/n]*n,size=2000)
        paired_boot[model]={};paired_groups[model]=groups
        policies=reference_candidates(model)
        chosen=evaluated["models"][model]["selected"]
        if chosen is not None and chosen not in policies:policies.append(chosen)
        model_result={}
        for condition in CONDITIONS:
            subset=[r for r in rows if r["condition"]==condition]
            condition_result={}
            for candidate in policies:
                # Column counts: negative, positive, FP,FN, abstentions, success.
                values=np.zeros((len(groups),6))
                for row in subset:
                    if row["status"]!="success":continue
                    v=values[lookup[row["group_id"]]];label=row["label"];d=decision(row,candidate)
                    v[label]+=1;v[5]+=1
                    if d is None:v[4]+=1
                    elif d==1 and label==0:v[2]+=1
                    elif d==0 and label==1:v[3]+=1
                boot=weights@values
                with np.errstate(divide="ignore",invalid="ignore"):
                    condition_result[candidate["id"]]={"FPR":percentile(boot[:,2]/boot[:,0]),"FNR":percentile(boot[:,3]/boot[:,1]),
                         "abstain_rate":percentile(boot[:,4]/boot[:,5])}
            if model!="bfree":
                values=np.zeros((len(groups),4))
                for row in subset:
                    if row["status"]!="success":continue
                    loc=row["localization"];v=values[lookup[row["group_id"]]]
                    if row["label"]==1 and loc["F1"] is not None:v[0]+=loc["F1"];v[1]+=1
                    if row["label"]==0:v[2]+=loc["false_positive_area_fraction"];v[3]+=1
                boot=weights@values
                with np.errstate(divide="ignore",invalid="ignore"):
                    paired_boot[model][condition]=boot[:,0]/boot[:,1]
                    condition_result["localization"]={"mean_positive_F1":percentile(boot[:,0]/boot[:,1]),
                        "mean_negative_false_area":percentile(boot[:,2]/boot[:,3])}
            model_result[condition]=condition_result
        results[model]=model_result
    paired_intervals={}
    for model in ["mesorch","mesorch_p"]:
        if paired_groups[model]!=paired_groups["trufor"]:raise ValueError("Paired bootstrap groups differ")
        paired_intervals[model]={c:percentile(paired_boot[model][c]-paired_boot["trufor"][c]) for c in CONDITIONS}
    save_json(RUN/"validation_group_uncertainty.json",{"created_at_utc":timestamp(),"method":"2000 fixed-seed bootstrap resamples of source groups, stratified within each dataset; percentile95%",
       "paired_location_F1_difference_vs_TruFor":paired_intervals,
       "seed":SEED,"resampling_unit":"Source group includes its negative and all4generator results, or its real/edited pair",
       "caution":"Conditional on chosen validation sources and visible group assumptions. Zero-observed-event intervals0..0 do not upper-bound unseen-error risk. Pretraining/event overlap uncertainty is not quantified.",
       "zero_of40_independent_binary_one_sided95_upper":1-.05**(1/40),"models":results})
    print("Source-group uncertainty recorded; no selection changes",flush=True)
if __name__=="__main__":main()
