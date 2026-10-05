"""Import legitimately acquired RAISE TIFFs; require reviewed scene grouping.

No registration request, identity submission, RAW development or network access.
Without a reviewed group file this creates review inputs only, never a final list.
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from PIL import Image, ImageDraw
from build_demo_manifest import FIELDS
from build_original_trufor import convert
from run_inference import ROOT, sha256, read_manifest


def split_groups(samples, reviewed):
    expected={s["scene_id"] for s in samples}
    if set(reviewed["group_by_scene"]) != expected or reviewed.get("review_status")!="verified":
        raise ValueError("Every selected real scene must have a verified scene group")
    groups=defaultdict(list)
    for item in samples:
        group=reviewed["group_by_scene"][item["scene_id"]]
        if not isinstance(group,str) or not group:
            raise ValueError("Invalid source-scene group")
        groups[group].append(item["scene_id"])
    # Deterministic subset sum keeps every source scene intact; no scores are read.
    possibilities={0:[]}
    for group in sorted(groups):
        for total, selected in list(possibilities.items()):
            size=total+len(groups[group])
            if size<=20 and size not in possibilities:
                possibilities[size]=selected+[group]
    if 20 not in possibilities:
        raise ValueError("40/40 cannot be achieved without breaking groups; acquire more scenes")
    tuning=set(possibilities[20])
    return {scene:(group,"tune" if group in tuning else "final")
            for group,scenes in groups.items() for scene in scenes}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--raise-dir",type=Path,required=True)
    parser.add_argument("--official-metadata",type=Path,required=True)
    parser.add_argument("--scene-review",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    acquisition=ROOT/"runs/20261001_original/bfree_synthbuster_acquisition.json"
    samples=json.loads(acquisition.read_text(encoding="utf-8"))["samples"]
    # Use the official downloaded metadata as positive evidence of subset membership.
    with args.official_metadata.open(encoding="utf-8-sig",newline="") as source:
        metadata=list(csv.DictReader(source))
    if not metadata:
        raise ValueError("Empty official metadata")
    metadata_ids=set(re.findall(r"\br[0-9a-f]{8}t\b",json.dumps(metadata).lower()))
    files=defaultdict(list)
    for path in args.raise_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".tif",".tiff"):
            files[path.stem.lower()].append(path)
    imported,panels,rows=[],[],[]
    groups=None
    if args.scene_review:
        reviewed=json.loads(args.scene_review.read_text(encoding="utf-8"))
        groups=split_groups(samples,reviewed)
    for item in samples:
        scene=item["scene_id"]
        if scene.lower() not in metadata_ids:
            raise ValueError("Scene not found in supplied official RAISE metadata: "+scene)
        if len(files[scene.lower()])!=1:
            raise ValueError("Need exactly one official TIFF for "+scene)
        original=files[scene.lower()][0]
        with Image.open(original) as image:
            if image.mode not in ("RGB","RGBA"):
                raise ValueError("Review original color/bit-depth conversion first: "+scene)
        png=ROOT/"data/converted/raise"/(scene+".png")
        array=convert(original,png)
        if groups and reviewed.get("input_sha256_by_scene",{}).get(scene)!=sha256(png):
            raise ValueError("Reviewed real input hash differs: "+scene)
        imported.append({"scene_id":scene,"original_path":str(original),"original_sha256":sha256(original),
            "input_path":str(png.relative_to(ROOT)),"input_sha256":sha256(png),
            "width":array.shape[1],"height":array.shape[0],"pixel_identity_verified":True})
        panel=Image.new("RGB",(300,245),"white")
        preview=Image.fromarray(array); preview.thumbnail((295,215)); panel.paste(preview,(0,25))
        ImageDraw.Draw(panel).text((4,2),scene,fill="black"); panels.append(panel)
        if groups:
            group,split=groups[scene]
            for label,path,dataset,source,generator in (
                    (0,png,"RAISE-1k","https://loki.disi.unitn.it/RAISE/download.html",""),
                    (1,ROOT/item["path"],"Synthbuster-v1","https://zenodo.org/records/10066460",item["generator"])):
                rows.append(dict(image_id="bfree_"+dataset+"_"+scene,model="bfree",path=str(path.relative_to(ROOT)),
                    dataset=dataset,source=source,group_id=group,label=label,generator=generator,mask_path="",
                    split=split,variant="official PNG" if label else "TIFF to RGB PNG, identical RGB pixels",
                    label_review="verified",sha256=sha256(path)))
    for start in range(0,len(panels),12):
        subset=panels[start:start+12]
        sheet=Image.new("RGB",(1200,245*((len(subset)+3)//4)),"white")
        for i,panel in enumerate(subset):
            sheet.paste(panel,(300*(i%4),245*(i//4)))
        sheet.save(args.out/("real_scenes_%d.jpg"%(start//12)))
    with (args.out/"audit.json").open("x",encoding="utf-8") as target:
        json.dump({"official_metadata_sha256":sha256(args.official_metadata),
            "source_acquisition_sha256":sha256(acquisition),"scene_group_review_complete":bool(groups),
            "scene_review_sha256":sha256(args.scene_review) if groups else None,
            "imported":imported,"model_inference_executed":False},target,indent=2)
    if groups:
        manifest=args.out/"manifest.csv"
        with manifest.open("x",encoding="utf-8",newline="") as target:
            writer=csv.DictWriter(target,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
        read_manifest(manifest,"bfree")
    print("Imported real TIFFs",len(imported),"scene review complete",bool(groups),"inference not run")


if __name__ == "__main__":
    main()
