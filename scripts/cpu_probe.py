"""Record CPU thread settings then invoke the unchanged official-inference runner."""
import argparse
import datetime
import json
import runpy
import sys
from pathlib import Path
from run_inference import ROOT, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu-name", required=True, help="Actual CPU model of this machine")
    parser.add_argument("--model", choices=("bfree", "trufor"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import torch
    args.out.mkdir(exist_ok=False)
    metadata = {"created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wrapper_sha256": sha256(__file__), "intraop_threads": torch.get_num_threads(),
        "interop_threads": torch.get_num_interop_threads(), "thread_settings_modified": False,
        "cpu": args.cpu_name, "scope": "four-input functional and paired numerical probe; no throughput claim"}
    (args.out / "cpu_probe.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    sys.argv = [str(ROOT / "scripts/run_inference.py"), "--model", args.model, "--manifest", str(args.manifest),
        "--out", str(args.out), "--device", "cpu", "--limit", "4"]
    runpy.run_path(str(ROOT / "scripts/run_inference.py"), run_name="__main__")


if __name__ == "__main__":
    main()
