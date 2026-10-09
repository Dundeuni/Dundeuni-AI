"""Sequential isolated-process GPU runs for pre-recorded robustness inputs."""
import json
import subprocess
import sys
from run_inference import ROOT, sha256
from freeze_protocol import verify_freeze
from build_robustness_data import VARIANTS


def main():
    base=ROOT/"runs/20261001_robustness"
    conditions=json.loads((base/"conditions.json").read_text(encoding="utf-8"))
    if sha256(ROOT/"scripts/build_robustness_data.py")!=conditions["generator_sha256"]:
        raise ValueError("Transformation generator changed after recording conditions")
    verify_freeze(ROOT/"runs/20261001_original/trufor_preparation/manifest.csv","trufor",
                  ROOT/"runs/20261001_original/trufor_protocol.json")
    interpreter=ROOT/".venv/trufor/Scripts/python.exe"
    for variant in VARIANTS:
        manifest=base/(variant+".csv")
        if sha256(manifest)!=conditions["variant_manifest_sha256"][variant]:
            raise ValueError("Recorded variant manifest changed")
        output=base/("trufor_"+variant)
        print("Starting",variant,flush=True)
        with (base/(variant+".log")).open("x",encoding="utf-8") as log:
            subprocess.run([str(interpreter),str(ROOT/"scripts/run_inference.py"),"--model","trufor",
                "--manifest",str(manifest),"--out",str(output),"--device","cuda:0"],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,check=True)
        count=sum(bool(line.strip()) for line in (output/"predictions.jsonl").read_text(encoding="utf-8").splitlines())
        if count!=80:
            raise ValueError("Incomplete variant run: "+variant)
        print("Finished",variant,"requests",count,flush=True)
    print("Completed 400 derived requests; original final protocol unchanged",flush=True)


if __name__ == "__main__":
    main()
