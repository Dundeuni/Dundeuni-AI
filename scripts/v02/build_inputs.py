"""Derive the five inputs with fixed v0.1 geometry and audited masks."""
import json,sys,collections
from pathlib import Path
import numpy as np
from PIL import Image
from common import ROOT,RUN,DATA,CONDITIONS,sha256,save_json,timestamp
sys.path.insert(0,str(ROOT/"scripts"))
from build_robustness_data import transform
def verify_rows(rows):
    ids=set();groups={};hashes={};group_folds={}
    for r in rows:
        if r["image_id"] in ids:raise ValueError("Repeated image ID")
        ids.add(r["image_id"])
        if r["role"] not in ["setting","validation","comparison"] or r["label"] not in [0,1] or r["label_review"]!="verified":raise ValueError("Unreviewed/invalid input")
        if sha256(ROOT/r["path"])!=r["sha256"]:raise ValueError("Image hash mismatch")
        if r.get("mask_path") and sha256(ROOT/r["mask_path"])!=r["mask_sha256"]:raise ValueError("Truth hash mismatch")
        for key,mapping in [(r["group_id"],groups),(r["sha256"],hashes)]:
            if key in mapping and mapping[key]!=r["role"]:raise ValueError("Group or identical input crosses roles")
            mapping[key]=r["role"]
        if r["role"]=="setting":
            if r["fold"] not in range(5):raise ValueError("Missing setting CV fold")
            if r["group_id"] in group_folds and group_folds[r["group_id"]]!=r["fold"]:raise ValueError("Source group crosses CV folds")
            group_folds[r["group_id"]]=r["fold"]
def derive(originals):
    rows=[]
    for i,r in enumerate(originals,1):
        r=dict(r);r["parent_image_id"]=r["image_id"];r["parent_sha256"]=r["sha256"]
        rows.append(r)
        with Image.open(ROOT/r["path"]) as im:image=im.convert("RGB")
        mask=None
        if r.get("mask_path"):
            with Image.open(ROOT/r["mask_path"]) as m:mask=m.convert("L")
            if mask.size!=image.size or not np.isin(np.asarray(mask),[0,255]).all():raise ValueError("Original mask geometry invalid")
        for condition in CONDITIONS[1:]:
            output,truth,geometry=transform(image,mask,condition)
            suffix=".jpg" if geometry["format"]=="JPEG" else ".png"
            dest=DATA/"variants"/condition/(r["image_id"]+suffix);dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():raise FileExistsError(dest)
            output.save(dest,format=geometry["format"],**{k:geometry[k] for k in ["quality","subsampling"] if k in geometry})
            row={**r,"image_id":r["image_id"]+"__"+condition,"path":str(dest.relative_to(ROOT)),
              "sha256":sha256(dest),"condition":condition,"geometry":geometry,"size":list(output.size)}
            if truth is not None:
                path=DATA/"variant_masks"/condition/(r["image_id"]+".png");path.parent.mkdir(parents=True,exist_ok=True)
                truth.save(path)
                row.update(mask_path=str(path.relative_to(ROOT)),mask_sha256=sha256(path),
                           mask_fraction=float(np.mean(np.asarray(truth)>0)),empty_positive_mask=not bool(np.any(np.asarray(truth)>0)))
            rows.append(row)
        if i%40==0:print("Derived",i,"/",len(originals),"originals",flush=True)
    verify_rows(rows)
    return sorted(rows,key=lambda r:(CONDITIONS.index(r["condition"]),r["role"],r["dataset"],r["image_id"]))
def main():
    task=sys.argv[1]
    if task=="tampering":
        fresh=json.loads((RUN/"tampering_fresh_review_confirmed.json").read_text())
        reference=json.loads((RUN/"columbia_comparison_review_confirmed.json").read_text())
        originals=fresh["originals"]+reference["originals"]
        if len(originals)!=240:raise ValueError("Expected240originals")
    elif task=="bfree":
        review=json.loads((RUN/"bfree_source_review_confirmed.json").read_text())
        if not review["visual_review_completed"]:raise ValueError("Source scene review incomplete")
        source=json.loads((RUN/"bfree_images_provenance_v3.json").read_text())
        originals=[]
        for item in source["images"]:
            originals.append({"image_id":item["dataset"]+"_"+item["source"]+"_"+item["image_id"],"source_id":item["image_id"],
             "dataset":item["dataset"],"generator":item["source"] if item["label"] else "","label":item["label"],"path":item["path"],
             "sha256":item["sha256"],"group_id":review.get("group_overrides",{}).get(item["group_id"],item["group_id"]),
             "role":item["role"],"fold":review.get("fold_overrides",{}).get(item["group_id"],item["fold"]),"condition":"original","mask_path":"","mask_sha256":"",
             "label_review":"verified","upstream_revision":item["upstream_revision"],"upstream_file":item["upstream_file"],
             "row_group":item["row_group"],"row_in_group":item["row_in_group"],"source_path_in_parquet":item["image"]["path"]})
        if len(originals)!=400:raise ValueError("Expected400originals")
    else:raise ValueError(task)
    verify_rows(originals)
    rows=derive(originals)
    record={"task":task,"created_at_utc":timestamp(),"original_count":len(originals),"request_count":len(rows),"conditions":list(CONDITIONS),
      "condition_counts":dict(collections.Counter(r["condition"] for r in rows)),"role_counts":dict(collections.Counter(r["role"] for r in rows)),
      "transform_code_sha256":sha256(ROOT/"scripts/build_robustness_data.py"),"transform_scope":"Input proxies, not measured device/app captures",
      "rows":rows}
    save_json(RUN/(task+"_manifest.json"),record)
    print(task,"manifest frozen",len(rows),"input requests",flush=True)
if __name__=="__main__":main()
