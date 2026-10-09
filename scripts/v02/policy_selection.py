"""Prespecified candidates, group-CV selection, and explicit selection failure."""
import math,json,statistics
from common import CONDITIONS
def candidates(model):
    result=[]
    aggregations=["official"] if model in ["bfree","trufor"] else ["mean","max","top1"]
    for aggregation in aggregations:
        if model=="bfree":
            result.append({"id":"A","aggregation":aggregation,"kind":"raw_gt","threshold":0.0})
        elif model=="trufor":
            result.append({"id":"A","aggregation":aggregation,"kind":"ge","threshold":.5})
        result.append({"id":("B" if aggregation=="official" else aggregation+"_B"),"aggregation":aggregation,"kind":"abstain","lower":.4,"upper":.6})
        for t in [.3,.4,.5,.6,.7]:
            result.append({"id":aggregation+"_binary_"+str(t),"aggregation":aggregation,"kind":"gt","threshold":t})
        for low in [.2,.3,.4]:
            for high in [.6,.7,.8]:
                result.append({"id":aggregation+"_abstain_"+str(low)+"_"+str(high),"aggregation":aggregation,"kind":"abstain","lower":low,"upper":high})
    return result
def decision(row,candidate):
    if row["status"]!="success":raise ValueError("No decision for failed inference")
    score=row["scores"][candidate["aggregation"]]
    if not math.isfinite(score) or not 0<=score<=1:raise ValueError("Invalid probability-like score")
    kind=candidate["kind"]
    if kind=="raw_gt":return int(row["raw_score"]>candidate["threshold"])
    if kind=="gt":return int(score>candidate["threshold"])
    if kind=="ge":return int(score>=candidate["threshold"])
    if kind=="abstain":return 0 if score<candidate["lower"] else 1 if score>candidate["upper"] else None
    raise ValueError("Unknown policy")
def metrics(rows,candidate):
    valid=[r for r in rows if r["status"]=="success"]
    n0=sum(r["label"]==0 for r in valid);n1=len(valid)-n0
    fp=fn=a0=a1=0
    for row in valid:
        d=decision(row,candidate)
        if d is None:
            if row["label"]:a1+=1
            else:a0+=1
        elif d==1 and row["label"]==0:fp+=1
        elif d==0 and row["label"]==1:fn+=1
    return {"requests":len(rows),"success":len(valid),"failed":len(rows)-len(valid),"negative":n0,"positive":n1,
      "FP":fp,"FN":fn,"abstain_negative":a0,"abstain_positive":a1,
      "FPR":fp/n0 if n0 else None,"FNR":fn/n1 if n1 else None,"abstain_rate":(a0+a1)/len(valid) if valid else None,
      "effective_positive_unresolved_rate":(fn+a1)/n1 if n1 else None,
      "denominator":"All successfully inferred truth-class requests; abstentions reported separately; repeated conditions are not independent observations"}
def select(rows,model,targets):
    if not rows or any(r["role"]!="setting" for r in rows):raise ValueError("Policy selection permits setting data only")
    evaluated=[];eligible=[]
    for order,candidate in enumerate(candidates(model)):
        bycondition={c:metrics([r for r in rows if r["condition"]==c],candidate) for c in CONDITIONS}
        qualifies=all(m["requests"] and not m["failed"] and m["positive"] and m["negative"] and
          m["FPR"]<=targets["false_positive_rate"] and m["FNR"]<=targets["false_negative_rate"] and
          m["abstain_rate"]<=targets["abstain_rate"] for m in bycondition.values())
        row={"candidate":candidate,"eligible":qualifies,"by_condition":bycondition}
        evaluated.append(row)
        if qualifies:
            values=list(bycondition.values())
            rank=(max(m["FNR"] for m in values),statistics.mean(m["FNR"] for m in values),
                  statistics.mean(m["abstain_rate"] for m in values),statistics.mean(m["FPR"] for m in values),order)
            eligible.append((rank,candidate))
    return {"status":"selected" if eligible else "selection_failed","selected":min(eligible,key=lambda x:x[0])[1] if eligible else None,
            "eligible_count":len(eligible),"evaluated":evaluated}
def cross_validate(rows,model,targets):
    if any(r["role"]!="setting" for r in rows):raise ValueError("CV permits setting only")
    groups={}
    for r in rows:
        if r["group_id"] in groups and groups[r["group_id"]]!=r["fold"]:raise ValueError("Source group crosses CV folds")
        groups[r["group_id"]]=r["fold"]
    if set(groups.values())!=set(range(5)):raise ValueError("Exactly five source-group folds required")
    results=[]
    for fold in range(5):
        fit=[r for r in rows if r["fold"]!=fold];held=[r for r in rows if r["fold"]==fold]
        chosen=select(fit,model,targets)
        result={"held_fold":fold,"fit_groups":len({r["group_id"] for r in fit}),"held_groups":len({r["group_id"] for r in held}),
                "selection_status":chosen["status"],"candidate":chosen["selected"]}
        if chosen["selected"] is not None:
            result["held_metrics"]={c:metrics([r for r in held if r["condition"]==c],chosen["selected"]) for c in CONDITIONS}
        results.append(result)
    return {"source":"Setting-only group five-fold CV; no independent validation scores used","folds":results}
