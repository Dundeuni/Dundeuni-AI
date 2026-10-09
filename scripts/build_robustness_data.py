"""Generate explicit input transformations; never modify official preprocessing.

All derived inputs are exploratory. Parent tune/final membership is retained as
metadata, since the source final scores were already observed before this study.
"""
import argparse
import csv
import datetime
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, __version__ as PIL_VERSION
from build_demo_manifest import FIELDS
from run_inference import ROOT, read_manifest, sha256

VARIANTS = ("jpeg_q75", "half_png", "messenger_proxy_512_q80", "screen_720x1280", "screen_photo_crop")
EXTRA_FIELDS = ["parent_image_id", "parent_sha256", "parent_split", "condition"]


def resized(image, mask, size):
    rendered=image.resize(size,Image.Resampling.LANCZOS)
    truth=mask.resize(size,Image.Resampling.NEAREST) if mask is not None else None
    return rendered,truth


def screen_images(image, mask):
    scale=min(640/image.width,1000/image.height)
    size=(max(1,round(image.width*scale)),max(1,round(image.height*scale)))
    photo,truth=resized(image,mask,size)
    screen=Image.new("RGB",(720,1280),(242,242,242))
    draw=ImageDraw.Draw(screen)
    draw.rectangle((0,0,719,75),fill=(255,255,255))
    draw.text((24,30),"Image preview",fill=(25,25,25))
    draw.rectangle((0,1190,719,1279),fill=(255,255,255))
    draw.text((32,1225),"Share       Save       Close",fill=(30,30,30))
    left=(720-size[0])//2
    top=110+(1000-size[1])//2
    box=(left,top,left+size[0],top+size[1])
    screen.paste(photo,(left,top))
    screen_mask=None
    if truth is not None:
        screen_mask=Image.new("L",screen.size,0)
        screen_mask.paste(truth,(left,top))
    crop=screen.crop(box)
    crop_mask=screen_mask.crop(box) if screen_mask is not None else None
    if not np.array_equal(np.asarray(crop),np.asarray(photo)):
        raise ValueError("Screen photo crop changed rendered pixels")
    if truth is not None and not np.array_equal(np.asarray(crop_mask),np.asarray(truth)):
        raise ValueError("Screen photo crop changed mask alignment")
    return screen,screen_mask,crop,crop_mask,box


def transform(image,mask,variant):
    if variant=="jpeg_q75":
        return image.copy(),mask.copy() if mask is not None else None,{"format":"JPEG","quality":75,"subsampling":2,"geometry":"identity"}
    if variant=="half_png":
        size=(max(1,image.width//2),max(1,image.height//2))
        output,truth=resized(image,mask,size)
        return output,truth,{"format":"PNG","size":list(size),"image_filter":"LANCZOS","mask_filter":"NEAREST"}
    if variant=="messenger_proxy_512_q80":
        scale=min(1,512/max(image.size))
        size=(max(1,round(image.width*scale)),max(1,round(image.height*scale)))
        output,truth=resized(image,mask,size)
        return output,truth,{"format":"JPEG","quality":80,"subsampling":2,"size":list(size),
                             "max_long_side":512,"real_app_measured":False,"image_filter":"LANCZOS","mask_filter":"NEAREST"}
    screen,screen_mask,crop,crop_mask,box=screen_images(image,mask)
    condition={"format":"PNG","canvas":[720,1280],"photo_box":list(box),"image_filter":"LANCZOS",
               "mask_filter":"NEAREST","synthetic_screen":True,"photo_region_selection":"known rendering box, no automatic detector"}
    if variant=="screen_720x1280":
        return screen,screen_mask,condition
    if variant=="screen_photo_crop":
        return crop,crop_mask,condition
    raise ValueError("Unknown variant")


def write_manifest(path,rows):
    with path.open("x",encoding="utf-8",newline="") as target:
        writer=csv.DictWriter(target,fieldnames=FIELDS+EXTRA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,default=ROOT/"runs/20261001_original/trufor_preparation/manifest.csv")
    parser.add_argument("--out",type=Path,default=ROOT/"runs/20261001_robustness")
    args=parser.parse_args()
    parents=read_manifest(args.source,"trufor")
    if len(parents)!=80:
        raise ValueError("Expected original 80-parent TruFor manifest")
    args.out.mkdir(parents=True,exist_ok=False)
    by_variant={v:[] for v in VARIANTS}
    audit=[]
    for row in parents:
        with Image.open(ROOT/row["path"]) as source:
            image=source.convert("RGB")
        mask=None
        if row["mask_path"]:
            with Image.open(ROOT/row["mask_path"]) as source:
                mask=source.convert("L")
            if mask.size!=image.size or not np.isin(np.asarray(mask),[0,255]).all():
                raise ValueError("Reviewed parent mask changed")
        for variant in VARIANTS:
            output,truth,condition=transform(image,mask,variant)
            suffix=".jpg" if condition["format"]=="JPEG" else ".png"
            destination=ROOT/"data/robustness"/variant/(row["image_id"]+suffix)
            destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                raise FileExistsError("Preserve previous derived input: "+str(destination))
            save_options={k:condition[k] for k in ("quality","subsampling") if k in condition}
            output.save(destination,format=condition["format"],**save_options)
            mask_path=""
            if truth is not None:
                if truth.size!=output.size or not np.isin(np.asarray(truth),[0,255]).all() or not np.any(np.asarray(truth)>0):
                    raise ValueError("Derived binary mask is invalid")
                path=ROOT/"data/robustness_masks"/variant/(row["image_id"]+".png")
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    raise FileExistsError(path)
                truth.save(path,format="PNG")
                mask_path=str(path.relative_to(ROOT))
            item={**row,"image_id":row["image_id"]+"__"+variant,"path":str(destination.relative_to(ROOT)),
                  "sha256":sha256(destination),"mask_path":mask_path,"split":"exploratory","variant":variant,
                  "parent_image_id":row["image_id"],"parent_sha256":row["sha256"],"parent_split":row["split"],
                  "condition":json.dumps(condition,sort_keys=True)}
            by_variant[variant].append(item)
            audit.append({"image_id":item["image_id"],"parent_image_id":row["image_id"],"parent_group_id":row["group_id"],
                          "parent_split":row["split"],"input_sha256":item["sha256"],"size":list(output.size),
                          "mask_sha256":sha256(ROOT/mask_path) if mask_path else None,"condition":condition})
    hashes={}
    for variant,rows in by_variant.items():
        manifest=args.out/(variant+".csv")
        write_manifest(manifest,rows)
        read_manifest(manifest,"trufor")
        hashes[variant]=sha256(manifest)
    # CPU probes are already-observed original inputs, isolated from derivatives.
    cpu_rows=[]
    for row in [r for r in parents if r["dataset"].startswith("COVERAGE")][:4]:
        cpu_rows.append({**row,"split":"exploratory","parent_image_id":row["image_id"],
                         "parent_sha256":row["sha256"],"parent_split":row["split"],"condition":"CPU original-input probe"})
    write_manifest(args.out/"cpu_trufor.csv",cpu_rows)
    conditions={"created_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "study":"post-hoc robustness exploration, no new independent final validation",
        "source_manifest_sha256":sha256(args.source),"generator_sha256":sha256(__file__),"Pillow":PIL_VERSION,
        "official_preprocessing_modified":False,"new_thresholds_selected":False,"policies":["A","B"],
        "map_threshold":.5,"map_direction":"official, no inversion","boundary":"all pixels",
        "original_parents":80,"derived_requests":400,"variant_manifest_sha256":hashes,"samples":audit,
        "limitations":"messenger proxy and synthetic screen are controlled conditions; no actual app or device screenshot acquisition"}
    (args.out/"conditions.json").write_text(json.dumps(conditions,indent=2),encoding="utf-8")
    print("Prepared 80 parents x 5 variants = 400 derived requests; reviewed masks 200; CPU probe 4")


if __name__ == "__main__":
    main()
