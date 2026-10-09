"""Attach independently reviewed masks without changing cached predictions."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np
from audit_columbia import rgb
from run_inference import ROOT, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--review", type=Path, default=ROOT/"runs/20261001_original/columbia_review/review.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--visual-review-confirmed", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    review = json.loads(args.review.read_text(encoding="utf-8"))
    masks = {m["image_id"]: m for m in review["masks"]}
    rows = [json.loads(line) for line in args.predictions.read_text(encoding="utf-8").splitlines() if line]
    selected, panels = [], []
    for row in rows:
        if row["dataset"] != "Columbia" or row["label"] != 1:
            continue
        name = row["image_id"].replace("trufor_columbia_", "")
        mask = masks[name]
        image = rgb(ROOT/row["path"])
        with Image.open(ROOT/mask["positive_mask_path"]) as source:
            positive = np.asarray(source) > 0
        overlay = image.copy()
        overlay[positive] = (.55*image[positive] + .45*np.array([255, 0, 255])).astype(np.uint8)
        panel = Image.new("RGB", (600, 245), "white")
        for x, array in ((0,image), (300,overlay)):
            preview = Image.fromarray(array)
            preview.thumbnail((295,205))
            panel.paste(preview,(x,35))
        ImageDraw.Draw(panel).text((4,2), name+"\nbackground="+mask["background_source"], fill="black")
        panels.append(panel)
        selected.append(mask)
        if args.visual_review_confirmed:
            row["mask_path"] = mask["positive_mask_path"]
    for offset in range(0,len(panels),10):
        subset=panels[offset:offset+10]
        sheet=Image.new("RGB",(1200,245*((len(subset)+1)//2)),"white")
        for i,panel in enumerate(subset):
            sheet.paste(panel,(600*(i%2),245*(i//2)))
        sheet.save(args.out/("selected_%d.jpg" % (offset//10)))
    (args.out/"mask_audit.json").write_text(json.dumps({"original_predictions_sha256":sha256(args.predictions),
        "source_review_sha256":sha256(args.review), "selected_masks":selected,
        "visual_review_confirmed":args.visual_review_confirmed,
        "predictions_recomputed":False, "split_unchanged":True},indent=2),encoding="utf-8")
    if args.visual_review_confirmed:
        (args.out/"predictions.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8")
    print("Mask candidates",len(selected),"confirmed",args.visual_review_confirmed)


if __name__ == "__main__":
    main()
