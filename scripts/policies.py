"""Separate generation/tampering policies; scores are not fraud probabilities."""
import math

VERSION = "baseline-v0.1-A-B"


def probability(model, raw):
    if not math.isfinite(raw):
        raise ValueError("Non-finite score")
    if model == "bfree":
        if raw >= 0:
            return 1.0 / (1.0 + math.exp(-raw))
        z = math.exp(raw)
        return z / (1.0 + z)
    if model == "trufor" and 0 <= raw <= 1:
        return raw
    raise ValueError("Unknown model or TruFor score outside [0,1]")


def decide(model, raw, policy):
    p = probability(model, raw)
    if policy == "A":
        result = int(raw > 0) if model == "bfree" else int(raw >= 0.5)
    elif policy == "B":
        result = 0 if p < 0.4 else (1 if p > 0.6 else None)
    else:
        raise ValueError("Unknown policy")
    return {"decision": result, "display_score": None if result is None else math.floor(100*p+0.5),
            "normalized_score": p}


def auroc(labels, scores):
    # Rank-sum AUROC with average ranks for ties; no sigmoid saturation.
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(scores, labels))
    rank_sum = 0.0
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        rank_sum += ((i + 1 + j) / 2) * sum(label for _, label in ordered[i:j])
        i = j
    return (rank_sum - positives*(positives+1)/2) / (positives*negatives)


def metrics(rows, policy):
    valid = [r for r in rows if r["status"] == "success"]
    counts = {"positive": 0, "negative": 0, "false_positive": 0,
              "false_negative": 0, "abstain_positive": 0, "abstain_negative": 0}
    for row in valid:
        label = row["label"]
        prediction = decide(row["model"], row["raw_score"], policy)["decision"]
        counts["positive" if label else "negative"] += 1
        if prediction is None:
            counts["abstain_positive" if label else "abstain_negative"] += 1
        elif prediction == 1 and label == 0:
            counts["false_positive"] += 1
        elif prediction == 0 and label == 1:
            counts["false_negative"] += 1
    def rate(n, d):
        return n/d if d else None
    abstain = counts["abstain_positive"] + counts["abstain_negative"]
    return {"policy": policy, "version": VERSION, "requests": len(rows), "valid": len(valid),
            "failed": len(rows)-len(valid), **counts,
            "auroc": auroc([r["label"] for r in valid], [r["raw_score"] for r in valid]),
            "false_positive_rate": rate(counts["false_positive"], counts["negative"]),
            "false_negative_rate": rate(counts["false_negative"], counts["positive"]),
            "abstain_rate": rate(abstain, len(valid)),
            "abstain_positive_rate": rate(counts["abstain_positive"], counts["positive"]),
            "abstain_negative_rate": rate(counts["abstain_negative"], counts["negative"]),
            "decision_rate": rate(len(valid)-abstain, len(valid)),
            "failure_rate": rate(len(rows)-len(valid), len(rows))}
