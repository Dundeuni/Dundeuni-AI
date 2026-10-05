"""Source-only B-Free independence review, excluding prior exposed images."""
import csv,json,itertools
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from common import ROOT,RUN,save_json
from prepare_tampering import fingerprint
def main():
    audit=json.loads((RUN/"bfree_images_provenance_v2.json").read_text())
    originals=[r for r in audit["images"] if r["label"]==0]
    if len(originals)!=80:raise ValueError("Expected80real source parents")
    images=[{"id":r["group_id"],"role":r["role"],"path":r["path"],"old":False} for r in originals]
    with (ROOT/"runs/20261002_bfree_raise/preparation/manifest.csv").open(encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            if r["label"]=="0":images.append({"id":r["image_id"],"role":"prior_exposed","path":r["path"],"old":True})
    out=RUN/"bfree_source_review_v2";out.mkdir(exist_ok=False)
    for dataset in ["synthbuster-plus","synthclic"]:
        rows=sorted([r for r in originals if r["dataset"]==dataset],key=lambda r:(r["role"],r["image_id"]))
        for start in range(0,len(rows),8):
            sheet=Image.new("RGB",(1000,800),"white");draw=ImageDraw.Draw(sheet)
            for i,row in enumerate(rows[start:start+8]):
                x=i%2*500;y=i//2*200
                draw.text((x+4,y+2),row["image_id"]+" "+row["role"],fill="black")
                with Image.open(ROOT/row["path"]) as im:
                    im=im.convert("RGB");im.thumbnail((490,175));sheet.paste(im,(x+4,y+22))
            sheet.save(out/(dataset+"_real_"+str(start//8)+".jpg"))
    features={r["id"]:fingerprint(ROOT/r["path"]) for r in images}
    queue=[]
    for a,b in itertools.combinations(images,2):
        if a["old"] and b["old"]:continue
        x,y=features[a["id"]],features[b["id"]]
        queue.append({"left":a["id"],"right":b["id"],"left_role":a["role"],"right_role":b["role"],
          "hamming":int(np.count_nonzero(x[0]!=y[0])),"rgb_rmse":float(np.sqrt(np.mean((x[1]-y[1])**2)))})
    closest=sorted(queue,key=lambda p:(p["hamming"],p["rgb_rmse"]))[:32]
    byid={r["id"]:r for r in images}
    for start in range(0,len(closest),8):
        sheet=Image.new("RGB",(1000,8*200),"white");draw=ImageDraw.Draw(sheet)
        for i,pair in enumerate(closest[start:start+8]):
            for j,key in enumerate(["left","right"]):
                id=pair[key];x=j*500;y=i*200
                draw.text((x+4,y+2),id+" h="+str(pair["hamming"]),fill="black")
                with Image.open(ROOT/byid[id]["path"]) as im:
                    im=im.convert("RGB");im.thumbnail((490,175));sheet.paste(im,(x+4,y+22))
        sheet.save(out/("closest_"+str(start//8)+".jpg"))
    save_json(RUN/"bfree_source_review_pending_v2.json",{"original_count":80,"prior_real_count":len(images)-80,"pairs_checked":len(queue),
       "closest":closest,"scores_used":False,"visual_review_completed":False,"limitations":"Selected real source groups and previous40real inputs reviewed; model pretraining overlap cannot be established"})
    print("B-Free source review ready",flush=True)
if __name__=="__main__":main()
