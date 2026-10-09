"""Build source components and mask review sheets from exact-pixel audit evidence."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from audit_columbia import colors, rgb
from run_inference import ROOT, sha256


def components(audit):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def merge(a, b):
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)
    authentic = sorted(p.stem for p in (ROOT / "data/columbia/4cam_auth").glob("*.tif"))
    for name in authentic:
        merge(name, "_".join(name.split("_")[:2]))
    for sample in audit["samples"]:
        find(sample["image_id"])
        for name in sample["source_links"]:
            merge(sample["image_id"], name)
    groups = defaultdict(list)
    for name in authentic + [s["image_id"] for s in audit["samples"]]:
        groups[find(name)].append(name)
    return dict(groups)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=ROOT/"runs/20261001_original/columbia_audit.json")
    parser.add_argument("--out", type=Path, default=ROOT/"runs/20261001_original/columbia_review")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    groups = components(audit)
    group_id = {name: group for group, names in groups.items() for name in names}
    records, panels = [], []
    for sample in audit["samples"]:
        if not sample["source_links_have_evidence"]:
            continue
        name = sample["image_id"]
        original = ROOT/"data/columbia/4cam_splc"/(name+".tif")
        image = rgb(original)
        regions, ambiguous = colors(rgb(original.parent/"edgemask"/(name+"_edgemask.jpg")))
        background_name = sample["background_candidates"][0]["source"]
        bg_camera = background_name.split("_")[0]
        cameras = name.split("_")[:2]
        bg_region = cameras.index(bg_camera)
        region_fraction = sample["background_same_position_fraction_by_camera_region"][bg_region]
        if region_fraction < .99:
            continue
        truth = (regions != bg_region).astype(np.uint8)*255
        mask_path = ROOT/"data/masks/columbia"/(name+".png")
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        if mask_path.exists():
            with Image.open(mask_path) as existing:
                if not np.array_equal(np.asarray(existing), truth):
                    raise ValueError("Existing mask would change")
        else:
            Image.fromarray(truth).save(mask_path)
        record = {"image_id": name, "group_id": group_id[name], "background_source": background_name,
                  "background_region_exact_pixel_fraction": region_fraction,
                  "positive_camera": cameras[1-bg_region], "positive_mask_path": str(mask_path.relative_to(ROOT)),
                  "positive_mask_sha256": sha256(mask_path), "positive_fraction": float((truth>0).mean()),
                  "jpeg_ambiguous_fraction": float(ambiguous.mean()),
                  "review_status": "awaiting visual verification", "ground_truth_used_to_flip_detector": False}
        records.append(record)
        # Resizing is solely for an audit sheet, never for inference or metric masks.
        overlay = image.copy()
        positive = truth > 0
        overlay[positive] = (.55*image[positive] + .45*np.array([255, 0, 255])).astype(np.uint8)
        panel = Image.new("RGB", (600, 245), "white")
        for x, array in ((0, image), (300, overlay)):
            preview = Image.fromarray(array)
            preview.thumbnail((295, 205))
            panel.paste(preview, (x, 35))
        ImageDraw.Draw(panel).text((4, 2), name+"\nbackground="+background_name, fill="black")
        panels.append(panel)
    for offset in range(0, len(panels), 12):
        subset = panels[offset:offset+12]
        sheet = Image.new("RGB", (1200, 245*((len(subset)+1)//2)), "white")
        for index, panel in enumerate(subset):
            sheet.paste(panel, (600*(index%2), 245*(index//2)))
        sheet.save(args.out/("sheet_%03d.jpg" % (offset//12)))
    record = {"source_audit_sha256": sha256(args.audit), "source_components": groups,
              "components_are_lower_bound": True, "unresolved_images": [s["image_id"] for s in audit["samples"]
                  if not s["source_links_have_evidence"]], "masks": records,
              "mask_definition": "camera region opposite the pixel-matched background; nearest official red/green; all pixels included",
              "split_warning": "Do not split a component or treat unresolved sources as independent."}
    (args.out/"review.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("Components", [(k, len(v)) for k,v in groups.items()], "Mask candidates", len(records))


if __name__ == "__main__":
    main()
