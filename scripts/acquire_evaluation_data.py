"""Official Columbia download; Synthbuster index/sample acquisition with CRC checks."""
import argparse
import json
import zipfile
from pathlib import Path
from acquire_models import ROOT, fetch, hashes
from remote_zip import RangeReader

URL = "https://zenodo.org/api/records/10066460/files/synthbuster.zip/content"
SIZE = 12372557226


def synthbuster(download):
    stream = RangeReader(URL, SIZE)
    with zipfile.ZipFile(stream) as packed:
        entries = [{"path": i.filename, "bytes": i.file_size, "compressed_bytes": i.compress_size,
                    "crc32": f"{i.CRC:08x}"} for i in packed.infolist()]
        out = ROOT / "runs/20261001_baseline/source_access/synthbuster_index.json"
        out.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        print("ZIP entries:", len(entries), "examples:", entries[:15], flush=True)
        if download:
            # Select before observing model scores, balanced round robin across generators.
            groups = {}
            for info in packed.infolist():
                if not info.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    continue
                parts = Path(info.filename).parts
                generator = parts[-2]
                groups.setdefault(generator, []).append(info)
            generators = sorted(groups)
            by_name = {g: {Path(i.filename).name: i for i in values} for g, values in groups.items()}
            common = sorted(set.intersection(*(set(v) for v in by_name.values())))
            if len(common) < 40:
                raise ValueError("Insufficient shared scene IDs")
            selected = [by_name[generators[index % len(generators)]][name]
                        for index, name in enumerate(common[:40])]
            records = []
            for info in selected:
                destination = ROOT / "data/synthbuster" / info.filename
                if not destination.resolve().is_relative_to((ROOT / "data/synthbuster").resolve()):
                    raise ValueError("Unsafe ZIP path")
                destination.parent.mkdir(parents=True, exist_ok=True)
                # zipfile.read validates the selected entry's CRC; whole ZIP MD5 is unavailable.
                data = packed.read(info)
                if destination.exists() and destination.read_bytes() != data:
                    raise ValueError("Existing sample mismatch")
                destination.write_bytes(data)
                records.append({"path": str(destination.relative_to(ROOT)), "source_entry": info.filename,
                                "crc32": f"{info.CRC:08x}", **hashes(destination)})
                print(info.filename, info.file_size, flush=True)
            (ROOT / "runs/20261001_baseline/synthbuster_samples.json").write_text(
                json.dumps({"url": URL, "date": "2026-10-01", "version": "v1",
                            "license": "CC-BY-NC-SA-4.0", "selection": "first 40 sorted shared RAISE IDs, generators round robin",
                            "archive_md5_verified": False, "validation": "entry CRC32 plus local SHA256",
                            "samples": records}, indent=2), encoding="utf-8")
    print("Transferred bytes:", stream.transferred, flush=True)


def columbia():
    url = "https://www.dropbox.com/sh/786qv3yhvc7s9ki/AACbEEzGPrD3_y38bpWHzgdqa?dl=1"
    destination = ROOT / "data/archives/columbia.zip"
    if not destination.exists():
        partial = destination.with_suffix(".zip.part")
        fetch(url, partial)
        partial.replace(destination)
    target = ROOT / "data/columbia"
    with zipfile.ZipFile(destination) as packed:
        for info in packed.infolist():
            if info.filename == "/" and info.is_dir():
                continue  # Dropbox's empty root marker is not a payload path.
            if not (target / info.filename).resolve().is_relative_to(target.resolve()):
                raise ValueError("Unsafe ZIP path")
        bad = packed.testzip()
        if bad:
            raise ValueError("ZIP CRC mismatch: " + bad)
        for info in packed.infolist():
            if info.filename != "/":
                packed.extract(info, target)
    record = {"url": url, "official_page": "https://www.ee.columbia.edu/ln/dvmm/downloads/authsplcuncmp/dlform.html",
              "date": "2026-10-01", "license": "noncommercial academic research, attribution required",
              "archive": hashes(destination)}
    (ROOT / "runs/20261001_baseline/columbia_source.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(record, flush=True)
    print([str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()][:25], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", choices=("synthbuster", "columbia"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.dataset == "synthbuster":
        synthbuster(args.download)
    elif args.download:
        columbia()
    else:
        parser.error("Columbia acquisition requires --download")
