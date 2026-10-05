"""Reuse recorded input transformations for B-Free after its original final validation."""
import csv
import datetime
import json
from PIL import Image, __version__ as PIL_VERSION
from build_demo_manifest import FIELDS
from build_robustness_data import VARIANTS, EXTRA_FIELDS, transform
from freeze_protocol import verify_freeze
from run_inference import ROOT, read_manifest, sha256

BASE = ROOT / "runs/20261002_bfree_raise"


def main():
    source = BASE / "preparation/manifest.csv"
    verify_freeze(source, "bfree", BASE / "bfree_protocol.json")
    # Original final predictions must be complete before labeling this post-hoc exploration.
    final = [json.loads(line) for line in (BASE / "bfree_final/predictions.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len(final) != 40:
        raise ValueError("Original final experiment must complete first")
    parents = read_manifest(source, "bfree")
    out = BASE / "robustness"
    out.mkdir(exist_ok=False)
    images = ROOT / "data/bfree_robustness"
    images.mkdir(exist_ok=False)
    by_variant = {variant: [] for variant in VARIANTS}
    audit = []
    for parent in parents:
        with Image.open(ROOT / parent["path"]) as original:
            image = original.convert("RGB")
        for variant in VARIANTS:
            rendered, _, condition = transform(image, None, variant)
            suffix = ".jpg" if condition["format"] == "JPEG" else ".png"
            path = images / variant / (parent["image_id"] + suffix)
            path.parent.mkdir(exist_ok=True)
            options = {key: condition[key] for key in ("quality", "subsampling") if key in condition}
            rendered.save(path, format=condition["format"], **options)
            row = {**parent, "image_id": parent["image_id"] + "__" + variant, "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path), "split": "exploratory", "variant": variant, "parent_image_id": parent["image_id"],
                "parent_sha256": parent["sha256"], "parent_split": parent["split"], "condition": json.dumps(condition, sort_keys=True)}
            by_variant[variant].append(row)
            audit.append({"image_id": row["image_id"], "parent_image_id": parent["image_id"], "parent_split": parent["split"],
                "input_sha256": row["sha256"], "size": list(rendered.size), "condition": condition})
        print("Prepared variants", parent["image_id"], flush=True)
    hashes = {}
    for variant, rows in by_variant.items():
        path = out / (variant + ".csv")
        with path.open("x", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS + EXTRA_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        read_manifest(path, "bfree")
        hashes[variant] = sha256(path)
    record = {"created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "generator_sha256": sha256(__file__),
        "shared_transform_code_sha256": sha256(ROOT / "scripts/build_robustness_data.py"), "Pillow": PIL_VERSION,
        "source_manifest_sha256": sha256(source), "policies": ["A", "B"], "new_thresholds_selected": False,
        "official_preprocessing_modified": False, "original_parents": 80, "derived_requests": 400,
        "study": "post-hoc controlled robustness exploration after original B-Free final validation",
        "variant_manifest_sha256": hashes, "samples": audit,
        "limitations": "Synthetic screen/proxy only; screen labels describe the embedded photo, not a production screenshot classifier"}
    with (out / "conditions.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Prepared B-Free 80 parents x 5 variants")


if __name__ == "__main__":
    main()
