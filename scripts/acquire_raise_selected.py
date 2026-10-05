"""Acquire only 40 prespecified official TIFFs from user-supplied RAISE CSV links."""
import concurrent.futures
import datetime
import json
import os
import shutil
import urllib.request
from PIL import Image
from probe_raise_csv import selected_rows
from run_inference import ROOT, sha256

BASE = ROOT / "runs/20261002_bfree_raise"
DESTINATION = ROOT / "data/raise_official_tiff"
MAX_BYTES = 128 * 1024 * 1024


def inspect(item):
    request = urllib.request.Request(item["url"], method="HEAD", headers={"User-Agent": "RAISE-baseline-research/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        size = int(response.headers["Content-Length"])
        if response.status != 200 or not 0 < size <= MAX_BYTES or response.headers.get_content_type() != "image/tiff":
            raise ValueError("Unexpected TIFF response")
        return {**item, "expected_bytes": size}


def acquire(item):
    path = DESTINATION / (item["scene_id"] + ".TIF")
    partial = path.with_suffix(".TIF.partial")
    if path.exists() or partial.exists():
        raise FileExistsError("Preserve existing source: " + str(path))
    request = urllib.request.Request(item["url"], headers={"User-Agent": "RAISE-baseline-research/1.0"})
    size = 0
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as target:
        if response.status != 200 or response.headers.get_content_type() != "image/tiff":
            raise ValueError("Unexpected TIFF GET response")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("Source exceeds bounded download")
            target.write(chunk)
    if size != item["expected_bytes"]:
        raise ValueError("TIFF download size mismatch")
    with Image.open(partial) as image:
        if image.format != "TIFF":
            raise ValueError("Not a TIFF image")
        image.load()
        details = {"mode": image.mode, "width": image.width, "height": image.height,
            "bits_per_sample": list(image.tag_v2.get(258, ())), "compression_tag": image.tag_v2.get(259),
            "orientation_tag": image.tag_v2.get(274), "frames": getattr(image, "n_frames", 1)}
    os.rename(partial, path)
    result = {**item, "path": str(path.relative_to(ROOT)), "bytes": size, "sha256": sha256(path), **details}
    print(item["scene_id"], size, details["mode"], details["width"], details["height"], flush=True)
    return result


def main():
    _, selected = selected_rows(BASE / "RAISE_1k.csv")
    DESTINATION.mkdir(exist_ok=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        plan = list(pool.map(inspect, selected))
    total = sum(item["expected_bytes"] for item in plan)
    if shutil.disk_usage(ROOT).free < total * 3 + 2 * 1024**3:
        raise ValueError("Insufficient room for sources, RGB PNGs and outputs")
    record = {"created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "metadata_sha256": sha256(BASE / "RAISE_1k.csv"),
        "acquisition_code_sha256": sha256(__file__), "source": "TIFF links from user-supplied official RAISE-1k CSV",
        "official_guide": "https://loki.disi.unitn.it/RAISE/guide.html", "registration_endpoint_invoked": False,
        "license": "non-commercial research and education; cite RAISE, ACM MMSys 2015", "planned_bytes": total, "requests": plan}
    with (BASE / "raise_acquisition_plan.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Download plan: 40 TIFFs", total, "bytes", flush=True)
    samples, errors = [], []
    with (BASE / "raise_acquisition_progress.jsonl").open("x", encoding="utf-8") as progress:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(acquire, item): item for item in plan}
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    samples.append(result)
                    progress.write(json.dumps({"status": "success", **result}) + "\n")
                except Exception as error:
                    failure = {"scene_id": futures[future]["scene_id"], "type": type(error).__name__, "message": str(error)}
                    errors.append(failure)
                    progress.write(json.dumps({"status": "failed", **failure}) + "\n")
                progress.flush()
    record.update(samples=sorted(samples, key=lambda s: s["scene_id"]), errors=errors, completed=len(samples),
        downloaded_bytes=sum(s["bytes"] for s in samples))
    with (BASE / "raise_acquisition.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    if errors or len(samples) != 40:
        raise ValueError("Acquisition incomplete; preserve failures and sources")
    print("Completed 40 official TIFFs", record["downloaded_bytes"], "bytes", flush=True)


if __name__ == "__main__":
    main()
