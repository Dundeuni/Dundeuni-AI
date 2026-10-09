"""Construct 80 original-plan requests, preserving prior-exposure boundaries.

Columbia tune: 20 authentic/20 spliced from the recorded exploratory selection.
COVERAGE final: 20 original/tampered pairs selected by official factor strata.
Final scores are never read here. Both datasets remain in separate splits because
Columbia's shared scenes were already exposed in the exploratory experiment.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.io import loadmat
from build_demo_manifest import FIELDS
from run_inference import ROOT, sha256, read_manifest


def convert(path, destination):
    with Image.open(path) as source:
        image=source.convert("RGB")
        before=np.asarray(image)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            with Image.open(destination) as existing:
                if not np.array_equal(np.asarray(existing),before):
                    raise ValueError("Existing input pixels differ")
        else:
            image.save(destination)
    with Image.open(destination) as saved:
        if not np.array_equal(np.asarray(saved),before):
            raise ValueError("Input conversion changed RGB pixels")
    return before


def selected_pairs(labels, eligible=None):
    buckets=defaultdict(list)
    for index, factor in enumerate(labels,1):
        if int(factor) not in range(1,7):
            raise ValueError("Unexpected official factor label")
        if eligible is None or index in eligible:
            buckets[int(factor)].append(index)
    if sum(len(v) for v in buckets.values())<20:
        raise ValueError("Insufficient validated pairs")
    selected=[]
    cursor=0
    while len(selected)<20:
        for factor in sorted(buckets):
            if cursor<len(buckets[factor]) and len(selected)<20:
                selected.append((buckets[factor][cursor],factor))
        cursor+=1
    return selected


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=ROOT/"runs/20261001_original/trufor_preparation")
    parser.add_argument("--visual-review-confirmed",action="store_true")
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    old=ROOT/"runs/20261001_original/columbia_localization/predictions.jsonl"
    cached=[json.loads(l) for l in old.read_text(encoding="utf-8").splitlines() if l]
    if len(cached)!=40:
        raise ValueError("Columbia tuning source must cover 40 requests")
    rows=[]
    for row in cached:
        row["split"]="tune"
        row["group_id"]="columbia_exposed_connected_scenes"
        row["reused_from_predictions"]=str(old.relative_to(ROOT))
        rows.append({k:row[k] for k in FIELDS})
    source=ROOT/"data/coverage/COVERAGE"
    labels=np.asarray(loadmat(source/"label/TFlabel.mat")["TFlabel"]).squeeze()
    if labels.shape!=(100,):
        raise ValueError("Unexpected official factor array shape")
    eligible, excluded=set(),[]
    for index in range(1,101):
        with Image.open(source/"image"/(str(index)+"t.tif")) as image, Image.open(source/"mask"/(str(index)+"forged.tif")) as mask:
            truth=np.asarray(mask)
            if image.size != mask.size:
                excluded.append({"pair_id":index,"reason":"official tampered image/mask size mismatch",
                                 "image_size":list(image.size),"mask_size":list(mask.size)})
            elif truth.ndim!=2 or not np.isin(truth,[0,255]).all() or not (truth>0).any():
                excluded.append({"pair_id":index,"reason":"invalid official binary forged mask"})
            else:
                eligible.add(index)
    selected=selected_pairs(labels,eligible)
    audit,panels=[],[]
    for index,factor in selected:
        images=[]
        for label,suffix in ((0,""),(1,"t")):
            original=source/"image"/(str(index)+suffix+".tif")
            png=ROOT/"data/converted/coverage"/(str(index)+suffix+".png")
            image=convert(original,png)
            images.append(image)
            mask_path=""
            if label:
                official=source/"mask"/(str(index)+"forged.tif")
                with Image.open(official) as mask:
                    truth=np.asarray(mask)
                if truth.ndim!=2 or not np.isin(truth,[0,255]).all() or not (truth>0).any():
                    raise ValueError("Official forged mask is not binary/nonempty")
                if truth.shape!=image.shape[:2]:
                    raise ValueError("Mask/image shape mismatch: pair "+str(index))
                mask_path=str(official.relative_to(ROOT))
            rows.append(dict(image_id="trufor_coverage_"+str(index)+suffix,model="trufor",
                path=str(png.relative_to(ROOT)),dataset="COVERAGE-2017-corrected",
                source="https://github.com/wenbihan/coverage",group_id="coverage_pair_"+str(index),
                label=label,generator="",mask_path=mask_path,split="final",
                variant="official TIFF to RGB PNG, identical RGB pixels",
                label_review="verified" if args.visual_review_confirmed else "pending",
                sha256=sha256(png)))
            audit.append({"original_path":str(original.relative_to(ROOT)),"original_sha256":sha256(original),
                "input_path":str(png.relative_to(ROOT)),"input_sha256":sha256(png),
                "pixel_identity_verified":True,"pair_id":index,"factor":factor,
                "mask_path":mask_path,"mask_sha256":sha256(ROOT/mask_path) if mask_path else None})
        overlay=images[1].copy()
        overlay[truth>0]=(.55*overlay[truth>0]+.45*np.array([255,0,255])).astype(np.uint8)
        panel=Image.new("RGB",(900,260),"white")
        for x,array in ((0,images[0]),(300,images[1]),(600,overlay)):
            preview=Image.fromarray(array)
            preview.thumbnail((295,225))
            panel.paste(preview,(x,30))
        ImageDraw.Draw(panel).text((4,2),"pair %d / factor %d: original | tampered | official forged mask"%(index,factor),fill="black")
        panels.append(panel)
    for start in range(0,len(panels),5):
        sheet=Image.new("RGB",(900,260*min(5,len(panels)-start)),"white")
        for i,panel in enumerate(panels[start:start+5]):
            sheet.paste(panel,(0,260*i))
        sheet.save(args.out/("coverage_review_%d.jpg"%(start//5)))
    manifest=args.out/"manifest.csv"
    with manifest.open("x",encoding="utf-8",newline="") as target:
        writer=csv.DictWriter(target,fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (args.out/"tune_predictions.jsonl").write_text("".join(json.dumps(r)+"\n" for r in cached),encoding="utf-8")
    record={"model":"trufor","selected_pairs":selected,"factor_counts":dict(Counter(f for _,f in selected)),
        "source_validation_exclusions":excluded,
        "selection":"official factor strata round robin, ascending pair ID, before any COVERAGE score",
        "visual_review_confirmed":args.visual_review_confirmed,"samples":80,
        "split":"Columbia 40 tune / COVERAGE 40 final", "final_scores_seen":False,
        "split_reason":"Conservative scene grouping and prior Columbia exposure; preserve all original derivatives in one split",
        "limitations":"dataset distribution differs between splits; service policy remains unselected",
        "coverage_conversion":audit,"cached_tuning_predictions_sha256":sha256(old),
        "manifest_sha256":sha256(manifest)}
    (args.out/"audit.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
    if args.visual_review_confirmed:
        read_manifest(manifest,"trufor")
    print("Prepared 80; final pair factors",record["factor_counts"],"reviewed",args.visual_review_confirmed)


if __name__ == "__main__":
    main()
