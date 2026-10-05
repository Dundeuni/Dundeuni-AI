"""Independent checks of the frozen final experiment and its archived maps."""
import json
from collections import defaultdict
import numpy as np
from PIL import Image
from sklearn.metrics import roc_auc_score, jaccard_score, f1_score
from freeze_protocol import verify_freeze
from policies import decide, metrics
from run_inference import ROOT, read_manifest, sha256


def main():
    base=ROOT/"runs/20261001_original"
    manifest=base/"trufor_preparation/manifest.csv"
    frozen=base/"trufor_protocol.json"
    protocol=verify_freeze(manifest,"trufor",frozen)
    final=[json.loads(l) for l in (base/"trufor_final/predictions.jsonl").read_text(encoding="utf-8").splitlines() if l]
    expected={r["image_id"]:r for r in read_manifest(manifest,"trufor") if r["split"]=="final"}
    assert len(final)==40 and set(expected)=={r["image_id"] for r in final}
    environment=json.loads((base/"trufor_final/environment.json").read_text(encoding="utf-8"))
    assert environment["policy_freeze_sha256"]==sha256(frozen)
    assert environment["weights_sha256"]==protocol["weights_sha256"]
    assert environment["code_commit"]==protocol["code_commit"]
    valid=[r for r in final if r["status"]=="success"]
    assert len(valid)==40
    labels=[r["label"] for r in valid]
    scores=[r["raw_score"] for r in valid]
    independent_auroc=float(roc_auc_score(labels,scores))
    assert abs(independent_auroc-metrics(final,"A")["auroc"])<1e-12
    locations=[]
    factors=json.loads((base/"trufor_preparation/audit.json").read_text())["selected_pairs"]
    factor_lookup=dict(factors)
    by_factor=defaultdict(list)
    cases=[]
    for row in final:
        item=expected[row["image_id"]]
        for key in ("path","sha256","mask_path","group_id","split"):
            assert row[key]==item[key],(row["image_id"],key)
        assert row["label"]==int(item["label"])
        with np.load(ROOT/row["map_path"],allow_pickle=False) as saved:
            assert saved["score"].item()==row["raw_score"]
            assert saved["imgsize"].tolist()==row["imgsize"]
            for key in ("map","conf"):
                assert list(saved[key].shape)==row["imgsize"]
                assert np.isfinite(saved[key]).all() and saved[key].min()>=0 and saved[key].max()<=1
            prediction=saved["map"]>=protocol["location_threshold"]
        if row["label"]:
            with Image.open(ROOT/row["mask_path"]) as image:
                truth=np.asarray(image)>0
            assert prediction.shape==truth.shape
            locations.append({"image_id":row["image_id"],
                "iou":float(jaccard_score(truth.flatten(),prediction.flatten())),
                "pixel_f1":float(f1_score(truth.flatten(),prediction.flatten()))})
        pair_id=int(row["group_id"].replace("coverage_pair_",""))
        by_factor[factor_lookup[pair_id]].append(row)
        decisions={p:decide("trufor",row["raw_score"],p)["decision"] for p in ("A","B")}
        if any(value is None or value!=row["label"] for value in decisions.values()):
            cases.append({"image_id":row["image_id"],"pair_id":pair_id,"factor":factor_lookup[pair_id],
                          "label":row["label"],"score":row["raw_score"],"decisions":decisions})
    summary=json.loads((base/"trufor_final/evaluation/summary.json").read_text())
    independent_iou=sum(r["iou"] for r in locations)/len(locations)
    independent_f1=sum(r["pixel_f1"] for r in locations)/len(locations)
    assert abs(summary["localization"]["mean_iou"]-independent_iou)<1e-12
    assert abs(summary["localization"]["mean_pixel_f1"]-independent_f1)<1e-12
    record={"frozen_protocol_verified":True,"all_final_ids_labels_hashes_maps_verified":True,
        "requests":40,"success":40,"independent_sklearn_auroc":independent_auroc,
        "independent_sklearn_mean_iou":independent_iou,"independent_sklearn_mean_pixel_f1":independent_f1,
        "by_factor":[{"factor":factor,"policy":policy,**metrics(items,policy)}
                     for factor,items in sorted(by_factor.items()) for policy in ("A","B")],
        "error_or_abstention_cases":cases}
    with (base/"trufor_verification.json").open("x",encoding="utf-8") as target:
        json.dump(record,target,indent=2)
    print("Verified official weight/source freeze; 40/40 maps; independent AUROC/IoU/F1",independent_auroc,independent_iou,independent_f1)


if __name__ == "__main__":
    main()
