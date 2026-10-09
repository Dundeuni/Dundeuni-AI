"""Prepare unexposed COVERAGE/CocoGlide pairs without detector outputs."""
import csv,json,collections,re,itertools
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from scipy.io import loadmat
from scipy.fft import dctn
from common import ROOT,RUN,DATA,stable_key,sha256,save_json
def fingerprint(path):
    with Image.open(path) as im:
        gray=np.asarray(im.convert("L").resize((32,32),Image.Resampling.LANCZOS),dtype=float)
        rgb=np.asarray(im.convert("RGB").resize((16,16),Image.Resampling.LANCZOS),dtype=float)/255
    values=dctn(gray,type=2,norm="ortho")[:8,:8].ravel()[1:]
    return values>np.median(values),rgb
def validate_pair(real,fake,mask):
    with Image.open(real) as r,Image.open(fake) as f,Image.open(mask) as m:
        truth=np.asarray(m);valid=r.size==f.size==m.size and truth.ndim==2 and np.isin(truth,[0,255]).all() and np.any(truth)
        return bool(valid),{"real_size":list(r.size),"fake_size":list(f.size),"mask_size":list(m.size),"mask_fraction":float(np.mean(truth>0))}
def main():
    previous=set()
    old=ROOT/"runs/20261001_original/trufor_preparation/manifest.csv"
    with old.open(encoding="utf-8-sig",newline="") as f:
        previous_rows=list(csv.DictReader(f))
    for row in previous_rows:
        if "COVERAGE" in row["dataset"]:
            previous.add(int(re.search(r"coverage_(\d+)",row["image_id"]).group(1)))
    c=ROOT/"data/coverage/COVERAGE"
    labels=np.asarray(loadmat(c/"label/TFlabel.mat")["TFlabel"]).squeeze()
    pairs=[];excluded=[];buckets=collections.defaultdict(list)
    for index in range(1,101):
        real=c/"image"/(str(index)+".tif");fake=c/"image"/(str(index)+"t.tif");mask=c/"mask"/(str(index)+"forged.tif")
        valid,audit=validate_pair(real,fake,mask)
        if not valid or index in previous:
            excluded.append({"dataset":"COVERAGE","id":str(index),"reason":"prior exposure" if index in previous else "official pair or mask invalid","audit":audit});continue
        factor=int(labels[index-1])
        buckets[factor].append({"dataset":"COVERAGE","source_id":str(index),"real":real,"fake":fake,"mask":mask,"factor":factor,"audit":audit})
    for factor in buckets:buckets[factor].sort(key=lambda p:stable_key("coverage:"+p["source_id"]))
    chosen=[]
    while len(chosen)<40:
        for factor in sorted(buckets):
            if buckets[factor] and len(chosen)<40:chosen.append(buckets[factor].pop(0))
        if not any(buckets.values()) and len(chosen)<40:raise ValueError("Insufficient new COVERAGE pairs")
    # Split inside each factor stratum; alternate the extra item for odd sizes.
    strata=collections.defaultdict(list)
    for pair in chosen:strata[pair["factor"]].append(pair)
    odd_index=0;setting_index=0
    for factor,subset in sorted(strata.items()):
        subset.sort(key=lambda p:stable_key("coverage-role:"+p["source_id"]))
        count=len(subset)//2
        if len(subset)%2:
            count+=int(odd_index%2==0);odd_index+=1
        for index,pair in enumerate(subset):
            is_setting=index<count
            pair.update(role="setting" if is_setting else "validation",fold=setting_index%5 if is_setting else None)
            if is_setting:setting_index+=1
            pairs.append(pair)
    if setting_index!=20:raise ValueError("Unbalanced COVERAGE group split")
    c=DATA/"cocoglide_upstream"
    with (c/"table.csv").open(encoding="utf-8",newline="") as f:table=list(csv.DictReader(f))
    available=[]
    for row in table:
        id=re.search(r"(\d+)_up",row["fake"]).group(1)
        real=c/row["real"];fake=c/row["fake"];mask=c/row["mask"]
        valid,audit=validate_pair(real,fake,mask)
        if not valid:excluded.append({"dataset":"CocoGlide","id":id,"reason":"official pair/mask invalid","audit":audit});continue
        available.append({"dataset":"CocoGlide","source_id":id,"real":real,"fake":fake,"mask":mask,"factor":row["prompt"],"audit":audit})
    selected=sorted(available,key=lambda p:stable_key("cocoglide:"+p["source_id"]))[:40]
    if len({p["source_id"] for p in selected})!=40:raise ValueError("Repeated COCO parent")
    for index,pair in enumerate(selected):
        pair.update(role="setting" if index<20 else "validation",fold=index%5 if index<20 else None);pairs.append(pair)
    originals=[]
    for pair in pairs:
        for label,key in [(0,"real"),(1,"fake")]:
            source=pair[key]
            if source.suffix.lower() in [".tif",".tiff",".bmp"]:
                dest=DATA/"tampering"/pair["dataset"]/(pair["source_id"]+("_fake" if label else "_real")+".png")
                dest.parent.mkdir(parents=True,exist_ok=True)
                with Image.open(source) as im:
                    rgb=im.convert("RGB");rgb.save(dest)
                    with Image.open(dest) as check:
                        if not np.array_equal(np.asarray(rgb),np.asarray(check)):raise ValueError("Conversion pixel mismatch")
            else:dest=source
            originals.append({"image_id":pair["dataset"]+"_"+pair["source_id"]+("_fake" if label else "_real"),
               "dataset":pair["dataset"],"source_id":pair["source_id"],"group_id":pair["dataset"]+":"+pair["source_id"],
               "role":pair["role"],"fold":pair["fold"],"label":label,"path":str(dest.relative_to(ROOT)),"sha256":sha256(dest),
               "mask_path":str(pair["mask"].relative_to(ROOT)) if label else "",
               "mask_sha256":sha256(pair["mask"]) if label else "",
               "factor":pair["factor"],"condition":"original","source_path":str(source.relative_to(ROOT)),
               "source_sha256":sha256(source),"mask_fraction":pair["audit"]["mask_fraction"] if label else 0,
               "label_review":"pending"})
    out=RUN/"tampering_review_v2";out.mkdir(exist_ok=False)
    for dataset in ["COVERAGE","CocoGlide"]:
        subset=[p for p in pairs if p["dataset"]==dataset]
        for start in range(0,len(subset),8):
            sheet=Image.new("RGB",(960,8*170),"white");draw=ImageDraw.Draw(sheet)
            for i,pair in enumerate(subset[start:start+8]):
                y=i*170
                draw.text((5,y+1),dataset+" "+pair["source_id"]+" "+pair["role"]+" factor "+str(pair["factor"]),fill="black")
                with Image.open(pair["real"]) as r,Image.open(pair["fake"]) as f,Image.open(pair["mask"]) as m:
                    real=r.convert("RGB");fake=f.convert("RGB");truth=np.asarray(m)>0
                    overlay=np.asarray(fake).copy();overlay[truth]=(.55*overlay[truth]+.45*np.array([255,0,255])).astype(np.uint8)
                    for j,image in enumerate([real,fake,Image.fromarray(overlay)]):
                        image.thumbnail((315,145));sheet.paste(image,(j*320,y+20))
            sheet.save(out/(dataset+"_pairs_"+str(start//8)+".jpg"))
    images=[{"id":p["dataset"]+":"+p["source_id"],"role":p["role"],"path":str(p["real"].relative_to(ROOT)),"old":False} for p in pairs]
    images.extend({"id":row["group_id"],"role":"prior_exposed","path":row["path"],"old":True} for row in previous_rows if row["label"]=="0")
    fingerprints={p["id"]:fingerprint(ROOT/p["path"]) for p in images}
    similarities=[]
    for a,b in itertools.combinations(images,2):
        if a["old"] and b["old"]:continue
        x,y=fingerprints[a["id"]],fingerprints[b["id"]]
        similarities.append({"left":a["id"],"right":b["id"],"left_role":a["role"],"right_role":b["role"],
            "hamming":int(np.count_nonzero(x[0]!=y[0])),"rgb_rmse":float(np.sqrt(np.mean((x[1]-y[1])**2)))})
    queue=sorted(similarities,key=lambda p:(p["hamming"],p["rgb_rmse"]))[:24]
    byid={p["id"]:p for p in images}
    for start in range(0,len(queue),8):
        sheet=Image.new("RGB",(800,8*170),"white");draw=ImageDraw.Draw(sheet)
        for i,pair in enumerate(queue[start:start+8]):
            y=i*170
            for j,key in enumerate(["left","right"]):
                id=pair[key];draw.text((j*400+4,y+1),id+" h="+str(pair["hamming"]),fill="black")
                with Image.open(ROOT/byid[id]["path"]) as im:
                    im=im.convert("RGB");im.thumbnail((390,145));sheet.paste(im,(j*400+4,y+20))
        sheet.save(out/("closest_"+str(start//8)+".jpg"))
    save_json(RUN/"tampering_source_review_pending_v2.json",{"originals":originals,"selected_pair_count":len(pairs),"excluded":excluded,
       "previous_coverage_pairs":sorted(previous),"similarity_queue":queue,"scores_used":False,"visual_review_completed":False,
       "columbia_scope":"pending user reply; not included in independent selection"})
    print("Prepared",len(originals),"fresh originals; reviews",out,flush=True)
if __name__=="__main__":main()
