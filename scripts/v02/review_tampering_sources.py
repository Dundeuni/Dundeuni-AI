"""Apply content-only scene audit and prepare Columbia comparison sources."""
import json,csv,re,collections
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from common import ROOT,RUN,DATA,stable_key,sha256,save_json
def panel_rows(items,dest,columns=3):
    for start in range(0,len(items),8):
        sheet=Image.new("RGB",(960,170*8),"white");draw=ImageDraw.Draw(sheet)
        for index,item in enumerate(items[start:start+8]):
            y=index*170;draw.text((4,y+1),item["image_id"]+" "+item["role"],fill="black")
            with Image.open(ROOT/item["path"]) as im:
                image=im.convert("RGB");images=[image]
                if item.get("mask_path"):
                    with Image.open(ROOT/item["mask_path"]) as m:truth=np.asarray(m)>0
                    overlay=np.asarray(image).copy();overlay[truth]=(.55*overlay[truth]+.45*np.array([255,0,255])).astype(np.uint8)
                    images.append(Image.fromarray(overlay))
                for col,preview in enumerate(images):
                    preview.thumbnail((470,145));sheet.paste(preview,(col*480,y+20))
        sheet.save(dest/("sources_"+str(start//8)+".jpg"))
def main():
    pending=RUN/"tampering_source_review_pending_v2.json"
    review=json.loads(pending.read_text());rows=review["originals"]
    removed=[row for row in rows if row["dataset"]=="COVERAGE" and row["source_id"]=="83"]
    if len(removed)!=2:raise ValueError("Expected ambiguous pair83")
    rows=[row for row in rows if row not in removed]
    for old in removed:
        row=dict(old);row.update(image_id="COVERAGE_80"+("_fake" if row["label"] else "_real"),source_id="80",group_id="COVERAGE:80")
        source=ROOT/"data/coverage/COVERAGE/image"/("80t.tif" if row["label"] else "80.tif")
        dest=DATA/"tampering/COVERAGE"/("80_fake.png" if row["label"] else "80_real.png")
        with Image.open(source) as im:
            image=im.convert("RGB");dest.parent.mkdir(parents=True,exist_ok=True);image.save(dest)
            with Image.open(dest) as saved:
                if not np.array_equal(np.asarray(image),np.asarray(saved)):raise ValueError("Pixel mismatch")
        row.update(path=str(dest.relative_to(ROOT)),sha256=sha256(dest),source_path=str(source.relative_to(ROOT)),source_sha256=sha256(source))
        if row["label"]:
            mask=ROOT/"data/coverage/COVERAGE/mask/80forged.tif"
            with Image.open(mask) as m:
                truth=np.asarray(m)
                if m.size!=image.size or not np.isin(truth,[0,255]).all() or not np.any(truth):raise ValueError("Replacement mask invalid")
            row.update(mask_path=str(mask.relative_to(ROOT)),mask_sha256=sha256(mask),mask_fraction=float(np.mean(truth>0)))
        rows.append(row)
    review.update(originals=rows,visual_review_completed=False,content_only_replacement={"removed":"COVERAGE:83","retained":"COVERAGE:96","replacement":"COVERAGE:80","reason":"Possible shared cupcake objects/location across settings and validation; conservative exclusion, no scores used","replacement_rule":"First unused valid factor4 source in original seeded order"})
    save_json(RUN/"tampering_fresh_review_after_scene_audit.json",review)
    out=RUN/"tampering_replacement_review";out.mkdir(exist_ok=False)
    panel_rows([row for row in rows if row["source_id"]=="80" and row["dataset"]=="COVERAGE"],out)
    columbia_review=json.loads((ROOT/"runs/20261001_original/columbia_review/review.json").read_text())
    exposed=set(json.loads((RUN/"columbia_group_probe.json").read_text())["prior_exposed_ids"])
    auth=sorted([p for p in (ROOT/"data/columbia/4cam_auth").glob("*.tif") if "auth:"+p.stem not in exposed],key=lambda p:stable_key("columbia-auth:"+p.stem))[:40]
    masks=[m for m in columbia_review["masks"] if "fake:"+m["image_id"] not in exposed and m["background_region_exact_pixel_fraction"]>=.9]
    masks=sorted(masks,key=lambda m:stable_key("columbia-fake:"+m["image_id"]))[:40]
    if len(auth)!=40 or len(masks)!=40:raise ValueError("Insufficient eligible reference Columbia images")
    comparison=[]
    for label,sources in [(0,auth),(1,masks)]:
        for item in sources:
            id=item.stem if label==0 else item["image_id"]
            if label==0:source=item
            else:
                matches=list((ROOT/"data/columbia/4cam_splc").glob(id+".*"))
                matches=[p for p in matches if p.suffix.lower() in [".tif",".bmp"]]
                if len(matches)!=1:raise ValueError("Ambiguous spliced source")
                source=matches[0]
            dest=DATA/"tampering/Columbia"/(id+".png");dest.parent.mkdir(parents=True,exist_ok=True)
            with Image.open(source) as im:image=im.convert("RGB");image.save(dest)
            row={"image_id":"Columbia_"+id,"dataset":"Columbia","source_id":id,"group_id":"Columbia:exposed_connected_scenes",
              "role":"comparison","fold":None,"label":label,"path":str(dest.relative_to(ROOT)),"sha256":sha256(dest),
              "source_path":str(source.relative_to(ROOT)),"source_sha256":sha256(source),"condition":"original","factor":"splicing" if label else "",
              "mask_path":item["positive_mask_path"] if label else "","mask_sha256":item["positive_mask_sha256"] if label else "",
              "mask_fraction":item["positive_fraction"] if label else 0,"label_review":"pending"}
            if label:
                if sha256(ROOT/row["mask_path"])!=row["mask_sha256"]:raise ValueError("Reviewed mask hash differs")
                with Image.open(ROOT/row["mask_path"]) as m:
                    if m.size!=image.size:raise ValueError("Mask size mismatch")
            comparison.append(row)
    out=RUN/"columbia_comparison_review";out.mkdir(exist_ok=False)
    panel_rows(comparison,out)
    save_json(RUN/"columbia_comparison_sources_pending.json",{"originals":comparison,"visual_review_completed":False,"scores_used":False,
       "role":"Non-independent comparison only; never candidate fitting or independent validation",
       "scope_status":"Prepared under full240-image authorization; Columbia allocation adjustment presented to user",
       "source_mask_review_sha256":sha256(ROOT/"runs/20261001_original/columbia_review/review.json")})
    print("Prepared replacement pair80 and 80 Columbia reference-only sources",flush=True)
if __name__=="__main__":main()
