"""Restore immutable replay inputs without copying historical inference outputs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "handoff/team-reproduction-reference-20261004"
INITIAL = ("approved_protocol.json", "scope_adjustment.json",
           "bfree_manifest.json", "tampering_manifest.json")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def restore(root, include_v01=False, bundle=BUNDLE):
    root = Path(root).resolve()
    bundle = Path(bundle).resolve()
    run = root / "runs/20261004_followup"
    if run.exists():
        raise FileExistsError("Use a fresh replay folder; active v0.2 run already exists.")
    source = bundle / "reference/experiments"
    pairs = [(source / "20261004_followup" / n, run / n) for n in INITIAL]
    if include_v01:
        for item in sorted(source.rglob("*")):
            rel = item.relative_to(source)
            if item.is_file() and rel.parts[0] != "20261004_followup":
                pairs.append((item, root / "runs" / rel))
        source_data = bundle / "reference/input-lists"
        pairs.extend((p, root / "data" / p.relative_to(source_data))
                     for p in sorted(source_data.rglob("*")) if p.is_file())
    inventory = json.loads((bundle / "inventory.json").read_text(encoding="utf-8"))["files"]
    # Validate ALL operations before any output is created.
    for src, dest in pairs:
        dest.resolve().relative_to(root)
        rel = src.relative_to(bundle).as_posix()
        if not src.is_file() or digest(src) != inventory[rel]["sha256"]:
            raise ValueError("Reference input changed: " + rel)
        if dest.exists():
            raise FileExistsError("Preserve existing file: " + str(dest))
    for src, dest in pairs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as target:
            target.write(src.read_bytes())
    return len(pairs)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--v01", action="store_true")
    args = parser.parse_args()
    print("Restored", restore(args.root, args.v01),
          "initial inputs. No historical v0.2 scores/freezes/completions restored.")

if __name__ == "__main__":
    main()
