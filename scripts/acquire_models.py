"""Fetch pinned official inference sources and verified final weights locally."""
import argparse
import hashlib
import json
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "bfree": ("B-Free", "c6a9f898782fb466b29af01f21960b67415afb0e",
              "https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip",
              "f3f53fa647848b16cf81c913f148a198"),
    "trufor": ("TruFor", "ae54475df6f41a491d7615100feb19263dec13f7",
               "https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip",
               "7bee48f3476c75616c3c5721ab256ff8"),
}


def fetch(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dundeuni-baseline-research"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)


def hashes(path):
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            md5.update(chunk)
            sha.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha.hexdigest(), "bytes": path.stat().st_size}


def acquire(name, include_weights):
    repo, commit, weight_url, expected_md5 = MODELS[name]
    base = ROOT / "third_party" / repo
    url = f"https://api.github.com/repos/grip-unina/{repo}/git/trees/{commit}?recursive=1"
    with urllib.request.urlopen(url, timeout=60) as response:
        tree = json.load(response)
    if tree.get("truncated"):
        raise RuntimeError("Incomplete source tree")
    records = []
    for entry in tree["tree"]:
        path = entry["path"]
        if entry["type"] != "blob":
            continue
        # No training checkpoints, large archives or unneeded training datasets.
        code = path.endswith((".py", ".yaml", ".yml", ".md", ".txt", ".csv"))
        demo = ((name == "bfree" and path.startswith("code/demo_images/")) or
                (name == "trufor" and path.startswith("test_docker/images/")))
        license_file = "license" in path.lower()
        if not (code or demo or license_file) or entry.get("size", 0) > 30 * 1024**2:
            continue
        destination = base / path
        if not destination.exists():
            fetch(f"https://raw.githubusercontent.com/grip-unina/{repo}/{commit}/{path}", destination)
        payload = destination.read_bytes()
        git_blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if git_blob != entry["sha"]:
            raise RuntimeError(f"Pinned source mismatch; existing file preserved: {path}")
        records.append({"path": path, **hashes(destination)})
    metadata = {"model": name, "repository": f"https://github.com/grip-unina/{repo}",
                "commit": commit, "date": "2026-10-01", "files": records}
    print(name, "sources:", len(records), "bytes:", sum(r["bytes"] for r in records), flush=True)
    if include_weights:
        archive = ROOT / "weights" / (name + ".zip")
        if not archive.exists():
            print("Downloading", weight_url, flush=True)
            partial = archive.with_suffix(".zip.part")
            fetch(weight_url, partial)
            partial.replace(archive)
        digest = hashes(archive)
        if digest["md5"] != expected_md5:
            raise RuntimeError(f"Official weight MD5 mismatch: {name}")
        target = (base / "code" / "weights" if name == "bfree" else
                  base / "TruFor_train_test" / "pretrained_models")
        with zipfile.ZipFile(archive) as packed:
            for member in packed.infolist():
                resolved = (target / member.filename).resolve()
                if target.resolve() not in resolved.parents and resolved != target.resolve():
                    raise RuntimeError("Unsafe archive path")
            packed.extractall(target)
        metadata["weight_archive"] = {"url": weight_url, **digest}
        metadata["weights"] = [{"path": str(p.relative_to(ROOT)), **hashes(p)}
                               for p in target.rglob("*") if p.is_file()]
        print(name, "weights verified:", digest, flush=True)
    record = ROOT / "runs" / "20261001_baseline" / (name + "_sources.json")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("--weights", action="store_true")
    args = parser.parse_args()
    acquire(args.model, args.weights)
