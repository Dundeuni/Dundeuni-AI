"""Run B-Free input conditions sequentially using the unchanged pinned runner."""
import json
import subprocess
from build_robustness_data import VARIANTS
from freeze_protocol import verify_freeze
from run_inference import ROOT, sha256


def main():
    base = ROOT / "runs/20261002_bfree_raise"
    directory = base / "robustness"
    record = json.loads((directory / "conditions.json").read_text(encoding="utf-8"))
    verify_freeze(base / "preparation/manifest.csv", "bfree", base / "bfree_protocol.json")
    if sha256(ROOT / "scripts/build_bfree_robustness_data.py") != record["generator_sha256"] or sha256(ROOT / "scripts/build_robustness_data.py") != record["shared_transform_code_sha256"]:
        raise ValueError("Recorded transformations changed")
    for variant in VARIANTS:
        manifest = directory / (variant + ".csv")
        if sha256(manifest) != record["variant_manifest_sha256"][variant]:
            raise ValueError("Manifest changed")
        print("Starting", variant, flush=True)
        with (directory / (variant + ".log")).open("x", encoding="utf-8") as target:
            subprocess.run([str(ROOT / ".venv/bfree/Scripts/python.exe"), str(ROOT / "scripts/run_inference.py"),
                "--model", "bfree", "--manifest", str(manifest), "--out", str(directory / ("bfree_" + variant)),
                "--device", "cuda:0"], cwd=ROOT, stdout=target, stderr=subprocess.STDOUT, check=True)
        print("Finished", variant, flush=True)


if __name__ == "__main__":
    main()
