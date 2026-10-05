"""Check selected TIFF links from user-supplied RAISE metadata, without form submission."""
import argparse
import csv
import datetime
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from run_inference import ROOT, sha256


def selected_rows(metadata):
    with metadata.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 1000 or not {"File", "TIFF", "NEF"}.issubset(rows[0]):
        raise ValueError("Expected RAISE-1k image metadata")
    by_id = {row["File"].lower(): row for row in rows}
    samples = json.loads((ROOT / "runs/20261001_original/bfree_synthbuster_acquisition.json").read_text(encoding="utf-8"))["samples"]
    selected = []
    for sample in samples:
        scene = sample["scene_id"].lower()
        if not re.fullmatch(r"r[0-9a-f]{8}t", scene) or scene not in by_id:
            raise ValueError("Selected ID missing from supplied metadata")
        url = by_id[scene]["TIFF"]
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname != "193.205.194.113" or parsed.path.lower() != "/raise/tiff/" + scene + ".tif" or parsed.query or parsed.username:
            raise ValueError("Unexpected official TIFF URL")
        selected.append({"scene_id": scene, "url": url})
    return rows, selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "runs/20261002_bfree_raise")
    args = parser.parse_args()
    rows, selected = selected_rows(args.metadata)
    args.out.mkdir(exist_ok=True)
    saved = args.out / "RAISE_1k.csv"
    if saved.exists() and sha256(saved) != sha256(args.metadata):
        raise ValueError("Preserve existing metadata")
    if not saved.exists():
        shutil.copyfile(args.metadata, saved)
    results = []
    for item in selected[:3]:
        result = dict(item)
        try:
            request = urllib.request.Request(item["url"], method="HEAD", headers={"User-Agent": "RAISE-baseline-research/1.0"})
            with urllib.request.urlopen(request, timeout=12) as response:
                result.update(status=response.status, content_length=response.headers.get("Content-Length"),
                    content_type=response.headers.get("Content-Type"), final_url=response.geturl())
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error))
        results.append(result)
        print(json.dumps(result), flush=True)
    record = {"created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "user_supplied_metadata": True, "metadata_sha256": sha256(saved), "rows": len(rows),
        "selected_scenes": len(selected), "probe_code_sha256": sha256(__file__),
        "official_guide": "https://loki.disi.unitn.it/RAISE/guide.html", "method": "HEAD only, three selected TIFF URLs from supplied CSV",
        "results": results, "image_download_executed": False}
    with (args.out / "raise_csv_probe.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)


if __name__ == "__main__":
    main()
