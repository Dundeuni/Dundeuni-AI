"""Find exact source-pixel evidence, independently of detector predictions.

This audit proposes source links; unresolved links never become independent groups.
Camera-color masks are decoded by nearest official red/green color, with JPEG
ambiguity counted. No detector output is read to choose a mask or orientation.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from PIL import Image
from run_inference import ROOT, sha256


def rgb(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def colors(mask):
    value = mask.astype(np.int16)
    # The official README defines camera 1 as red, camera 2 as green.
    prototypes = np.array([[200, 0, 0], [255, 0, 0], [0, 200, 0], [0, 255, 0]])
    # int32 arithmetic is essential for 255**2; cast before multiplication.
    delta = value[..., None, :].astype(np.int32) - prototypes.astype(np.int32)
    distance = (delta * delta).sum(-1)
    nearest = distance.argmin(-1)
    ambiguous = (np.abs(value[..., 0] - value[..., 1]) < 20) | (distance.min(-1) > 12000)
    return (nearest >= 2).astype(np.uint8), ambiguous


def packed(image):
    value = image.astype(np.uint32)
    return (value[..., 0] << 16) | (value[..., 1] << 8) | value[..., 2]


def anchors(image, regions, count=24):
    result = []
    for region in (0, 1):
        # Grid placement is deterministic and does not depend on model scores.
        candidates = []
        for y in range(3, image.shape[0] - 3, 13):
            for x in range(3, image.shape[1] - 3, 13):
                if not np.all(regions[y-2:y+3, x-2:x+3] == region):
                    continue
                patch = image[y-1:y+2, x-1:x+2]
                texture = float(patch.astype(float).std(axis=(0, 1)).sum())
                if texture > 30:
                    candidates.append((y, x))
        if candidates:
            for index in np.linspace(0, len(candidates)-1, min(count, len(candidates)), dtype=int):
                y, x = candidates[index]
                result.append((region, y, x, int(packed(image[y:y+1, x:x+1])[0, 0])))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "runs/20261001_original/columbia_audit.json")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Preserve the existing audit; choose a fresh output")
    base = ROOT / "data/columbia"
    sources = {p.stem: rgb(p) for p in sorted((base / "4cam_auth").glob("*.tif"))}
    fakes = sorted((base / "4cam_splc").glob("*.tif"))
    if args.limit:
        fakes = fakes[:args.limit]
    jobs, requested = [], set()
    for path in fakes:
        image = rgb(path)
        mask_path = path.parent / "edgemask" / (path.stem + "_edgemask.jpg")
        regions, ambiguous = colors(rgb(mask_path))
        if regions.shape != image.shape[:2]:
            raise ValueError("Official mask/image shape mismatch")
        points = anchors(image, regions)
        requested.update(p[3] for p in points)
        jobs.append((path, image, regions, ambiguous, points))
    requested_array = np.array(sorted(requested), dtype=np.uint32)
    # Index only colors that are needed for the sampled forensic pixel checks.
    index = defaultdict(list)
    overflow = set()
    for name, image in sources.items():
        values = packed(image)
        ys, xs = np.nonzero(np.isin(values, requested_array))
        for y, x in zip(ys.tolist(), xs.tolist()):
            color = int(values[y, x])
            if color in overflow:
                continue
            if len(index[color]) >= 3000:
                overflow.add(color)
                del index[color]
                continue
            index[color].append((name, y, x))
    records = []
    for path, image, regions, ambiguous, points in jobs:
        cameras = path.stem.split("_")[:2]
        same_position = []
        for name, original in sources.items():
            if name.split("_")[0] not in cameras or original.shape != image.shape:
                continue
            equality = np.all(original[::5, ::5] == image[::5, ::5], axis=2)
            same_position.append((float(equality.mean()), name))
        same_position.sort(reverse=True)
        evidence = defaultdict(list)
        for region, y, x, color in points:
            patch = image[y-1:y+2, x-1:x+2]
            for name, oy, ox in index.get(color, []):
                original = sources[name]
                if (name.split("_")[0] not in cameras or oy == 0 or ox == 0
                        or oy >= original.shape[0]-1 or ox >= original.shape[1]-1):
                    continue
                if np.array_equal(patch, original[oy-1:oy+2, ox-1:ox+2]):
                    evidence[(region, name)].append([y, x, oy, ox])
        region_sources = []
        for region in (0, 1):
            matches = sorted([(len({tuple(p[:2]) for p in points}), name, points)
                              for (r, name), points in evidence.items() if r == region], reverse=True)
            region_sources.append([{"source": n, "anchor_count": c, "positions": p}
                                   for c, n, p in matches if c >= 3])
        background = same_position[0] if same_position else (0, None)
        background_regions = []
        if background[1]:
            equality = np.all(sources[background[1]] == image, axis=2)
            background_regions = [float(equality[regions == region].mean())
                                  if np.any(regions == region) else None for region in (0, 1)]
        resolved = bool(background[0] > .5 and all(region_sources))
        record = {"image_id": path.stem, "image_sha256": sha256(path),
                  "official_mask_sha256": sha256(path.parent / "edgemask" / (path.stem+"_edgemask.jpg")),
                  "background_candidates": [{"source": n, "same_position_pixel_fraction": c}
                                            for c, n in same_position[:3]],
                  "camera_regions": region_sources,
                  "background_same_position_fraction_by_camera_region": background_regions,
                  "ambiguous_mask_pixel_fraction": float(ambiguous.mean()),
                  "source_links_have_evidence": resolved,
                  "source_links": sorted({m["source"] for bucket in region_sources for m in bucket}),
                  "review_status": "pixel evidence; cross-camera scenes and full mask still require review"}
        records.append(record)
        print(path.stem, "background", background, "sources",
              [[(v["source"], v["anchor_count"]) for v in bucket] for bucket in region_sources], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"detector_scores_used": False,
        "method": "identical 3x3 RGB patches and same-position background pixels",
        "source_count": len(sources), "samples": records,
        "limitations": "exact links are positive evidence; missed transformed sources do not prove independence"},
        indent=2), encoding="utf-8")
    print("Recorded", len(records), "pixel-supported", sum(r["source_links_have_evidence"] for r in records))


if __name__ == "__main__":
    main()
