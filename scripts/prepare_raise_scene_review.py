"""Create source-only near-duplicate review evidence before any B-Free scores."""
import itertools
import json
import numpy as np
from PIL import Image, ImageDraw
from scipy.fft import dctn
from run_inference import ROOT, sha256

BASE = ROOT / "runs/20261002_bfree_raise"


def main():
    audit = json.loads((BASE / "scene_inputs/audit.json").read_text(encoding="utf-8"))
    items = audit["imported"]
    fingerprints, previews = {}, {}
    for item in items:
        with Image.open(ROOT / item["input_path"]) as image:
            preview = image.copy()
            preview.thumbnail((390, 275))
            previews[item["scene_id"]] = preview
            gray = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=float)
            rgb = np.asarray(image.resize((16, 16), Image.Resampling.LANCZOS), dtype=float) / 255
        block = dctn(gray, type=2, norm="ortho")[:8, :8].ravel()[1:]
        fingerprints[item["scene_id"]] = {"phash": block > np.median(block), "rgb": rgb}
    pairs = []
    for left, right in itertools.combinations(items, 2):
        lf, rf = fingerprints[left["scene_id"]], fingerprints[right["scene_id"]]
        pairs.append({"left": left["scene_id"], "right": right["scene_id"],
            "same_rgb_png_hash": left["input_sha256"] == right["input_sha256"],
            "phash_hamming_63": int(np.count_nonzero(lf["phash"] != rf["phash"])),
            "thumbnail_rgb_rmse": float(np.sqrt(np.mean((lf["rgb"] - rf["rgb"])**2)))})
    pairs.sort(key=lambda row: (row["phash_hamming_63"], row["thumbnail_rgb_rmse"]))
    # A review queue rather than a claim that a hash proves scene independence.
    candidates = pairs[:24]
    out = BASE / "scene_similarity"
    out.mkdir(exist_ok=False)
    for start in range(0, len(candidates), 8):
        sheet = Image.new("RGB", (800, 300 * min(8, len(candidates)-start)), "white")
        draw = ImageDraw.Draw(sheet)
        for index, pair in enumerate(candidates[start:start+8]):
            top = index * 300
            for column, key in enumerate(("left", "right")):
                scene = pair[key]
                draw.text((400*column+5, top+4), scene + "  hamming " + str(pair["phash_hamming_63"]), fill="black")
                sheet.paste(previews[scene], (400*column+5, top+23))
        sheet.save(out / ("closest_pairs_%d.jpg" % (start//8)))
    record = {"source_import_sha256": sha256(BASE / "scene_inputs/audit.json"), "code_sha256": sha256(__file__),
        "parents": len(items), "pairs_compared": len(pairs), "method": "63 non-DC DCT pHash bits and 16x16 RGB RMSE; nearest 24 pairs queued for visual review",
        "pairs": pairs, "review_completed": False, "inference_scores_used": False,
        "limitations": "Source-only 40-image review; not an exhaustive duplicate check against all 1000 RAISE images or model pretraining corpora"}
    with (out / "similarity.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Prepared", len(pairs), "source-only pair comparisons and 24-pair visual queue")


if __name__ == "__main__":
    main()
