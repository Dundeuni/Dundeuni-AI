"""Official demos are smoke checks, never independent tune/final evaluations."""
import csv
from pathlib import Path
from run_inference import ROOT, sha256

FIELDS = ["image_id", "model", "path", "dataset", "source", "group_id", "label",
          "generator", "mask_path", "split", "variant", "label_review", "sha256"]


def main():
    rows = []
    base = ROOT / "third_party/B-Free/code/demo_images"
    with (base / "metainfo.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            image = base / row["filename"]
            rows.append(dict(image_id="bfree_" + image.stem, model="bfree", path=str(image.relative_to(ROOT)),
                             dataset="B-Free official demo", source="https://github.com/grip-unina/B-Free",
                             group_id="bfree_demo_relationships_unknown", label=row["label"], generator="unknown",
                             mask_path="", split="smoke", variant="official demo original",
                             label_review="verified", sha256=sha256(image)))
    base = ROOT / "third_party/TruFor/test_docker/images"
    for image in sorted(base.glob("*")):
        if image.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        rows.append(dict(image_id="trufor_" + image.stem, model="trufor", path=str(image.relative_to(ROOT)),
                         dataset="TruFor official demo", source="https://github.com/grip-unina/TruFor",
                         group_id="trufor_demo_relationships_unknown", label=int(image.stem.startswith("tampered")),
                         generator="", mask_path="", split="smoke", variant="official demo original",
                         label_review="verified", sha256=sha256(image)))
    destination = ROOT / "data/manifests/official_demos.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(destination, "samples:", len(rows))


if __name__ == "__main__":
    main()
