"""Verify source/artifact hashes and preserve a final local experiment snapshot."""
import datetime
import json
from freeze_protocol import verify_freeze
from run_inference import ROOT, sha256


def main():
    base = ROOT / "runs/20261002_bfree_raise"
    verify_freeze(base / "preparation/manifest.csv", "bfree", base / "bfree_protocol.json")
    old = ROOT / "runs/20261001_original"
    verify_freeze(old / "trufor_preparation/manifest.csv", "trufor", old / "trufor_protocol.json")
    old_robustness = ROOT / "runs/20261001_robustness/verification_manifest.json"
    previous = json.loads(old_robustness.read_text(encoding="utf-8"))
    for record in previous["files"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError("Previous preserved experiment artifact changed: " + record["path"])
    acquisition = json.loads((base / "raise_acquisition.json").read_text(encoding="utf-8"))
    for item in acquisition["samples"]:
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Official downloaded TIFF changed")
    names = ["probe_raise_csv.py", "acquire_raise_selected.py", "prepare_raise_scene_review.py", "finalize_raise_scene_review.py",
        "verify_original_bfree.py", "build_bfree_robustness_data.py", "run_bfree_robustness.py", "evaluate_bfree_robustness.py",
        "write_original_bfree_report.py", "verify_bfree_snapshot.py", "import_original_raise.py"]
    files = [ROOT / "scripts" / name for name in names] + [ROOT / "tests/test_raise_metadata.py",
        ROOT / "reports/BFREE_ORIGINAL_RESULTS_20261002.md"]
    for suffix in ("*.json", "*.jsonl", "*.csv", "*.log"):
        files.extend(path for path in base.rglob(suffix)
            if not path.name.startswith("verification_manifest") and path.name != "snapshot_verification.log")
    record = {"created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "bfree_and_trufor_freezes_verified": True,
        "previous_robustness_artifact_hashes_verified": len(previous["files"]), "official_tiff_hashes_verified": 40,
        "files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sorted(set(files))]}
    with (base / "verification_manifest.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Verified official TIFFs, both original freezes, previous experiment, and", len(record["files"]), "current code/artifact hashes")


if __name__ == "__main__":
    main()
