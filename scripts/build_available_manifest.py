"""Supplementary available-data experiment; no independent final split is claimed."""
import csv
import json
import tarfile
from collections import defaultdict
from pathlib import Path
import numpy as np
from PIL import Image
from run_inference import ROOT, sha256
from build_demo_manifest import FIELDS


def extract_columbia():
    target = ROOT / "data/columbia"
    for archive in sorted(target.glob("*.tar.bz2")):
        with tarfile.open(archive) as packed:
            for item in packed.getmembers():
                if not (target / item.name).resolve().is_relative_to(target.resolve()):
                    raise ValueError("Unsafe TAR member")
                if item.issym() or item.islnk() or not (item.isfile() or item.isdir()):
                    raise ValueError("Unsupported TAR member")
            packed.extractall(target)


def select_round_robin(paths, size, key):
    buckets = defaultdict(list)
    for path in sorted(paths):
        buckets[key(path)].append(path)
    selected = []
    index = 0
    while len(selected) < size:
        added = False
        for group in sorted(buckets):
            if index < len(buckets[group]) and len(selected) < size:
                selected.append(buckets[group][index])
                added = True
        if not added:
            raise ValueError("Insufficient files")
        index += 1
    return selected


def convert(path):
    destination = ROOT / "data/converted/columbia" / (path.stem + ".png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as source:
        image = source.convert("RGB")
        original = np.asarray(image)
        image.save(destination, format="PNG")
    with Image.open(destination) as saved:
        if not np.array_equal(original, np.asarray(saved)):
            raise ValueError("PNG conversion changed RGB pixels")
    return destination


def main():
    extract_columbia()
    base = ROOT / "data/columbia"
    real = select_round_robin(list((base / "4cam_auth").glob("*.tif")) +
                             list((base / "4cam_auth").glob("*.bmp")), 40,
                             lambda p: p.stem.split("_")[0])
    fake = select_round_robin(list((base / "4cam_splc").glob("*.tif")) +
                             list((base / "4cam_splc").glob("*.bmp")), 20,
                             lambda p: "_".join(p.stem.split("_")[:2]))
    rows, conversions = [], []
    for path in real + fake:
        png = convert(path)
        conversions.append({"original_path": str(path.relative_to(ROOT)), "input_path": str(png.relative_to(ROOT)),
                            "original_sha256": sha256(path), "input_sha256": sha256(png),
                            "pixel_identity_verified": True})
        for model in (("bfree", "trufor") if path in real[:20] else
                      (("bfree",) if path in real else ("trufor",))):
            # Original Columbia photos are also trusted camera negatives for generation.
            label = int(path in fake)
            rows.append(dict(image_id=model + "_columbia_" + path.stem, model=model,
                             path=str(png.relative_to(ROOT)), dataset="Columbia",
                             source="https://www.ee.columbia.edu/ln/dvmm/downloads/authsplcuncmp/",
                             group_id="columbia_all_source_relations_unresolved", label=label, generator="",
                             mask_path="", split="exploratory", variant="TIFF/BMP to RGB PNG, identical RGB pixels",
                             label_review="verified", sha256=sha256(png)))
    samples = json.loads((ROOT / "runs/20261001_baseline/synthbuster_samples.json").read_text())["samples"]
    for sample in samples:
        path = ROOT / sample["path"]
        rows.append(dict(image_id="bfree_synthbuster_" + path.parent.name + "_" + path.stem,
                         model="bfree", path=sample["path"], dataset="Synthbuster-v1",
                         source="https://zenodo.org/records/10066460", group_id="raise_" + path.stem,
                         label=1, generator=path.parent.name, mask_path="", split="exploratory",
                         variant="official PNG original", label_review="verified", sha256=sample["sha256"]))
    target = ROOT / "data/manifests/available_exploratory.csv"
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    record = {"selection_before_scores": True, "selection": "sorted filenames, camera/generator round robin",
              "scope": "exploratory, no independent tune/final separation",
              "reason": "RAISE requires user data acquisition; COVERAGE browser download failed; Columbia source relationships unresolved",
              "columbia_mask_evaluation": "pending: camera-color masks do not establish pasted-vs-background ownership",
              "columbia_conversion": conversions,
              "samples": len(rows), "manifest_sha256": sha256(target)}
    (ROOT / "runs/20261001_baseline/available_data_audit.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("Manifest samples:", len(rows), "B-Free:", sum(r["model"] == "bfree" for r in rows),
          "TruFor:", sum(r["model"] == "trufor" for r in rows))


if __name__ == "__main__":
    main()
