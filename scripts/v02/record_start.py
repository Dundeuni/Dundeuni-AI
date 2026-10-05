"""Record user-approved scope and read-only preflight without reading old scores."""
import json
import subprocess
import sys
import shutil
import hashlib
from common import ROOT, RUN, CONDITIONS, SEED, sha256, save_json, timestamp

sys.path.insert(0, str(ROOT/"scripts"))
from freeze_protocol import verify_freeze


def main():
    approval = {
        "version": "baseline-v0.2-20261004", "recorded_at_utc": timestamp(),
        "authorization": "User explicitly selected full draft scope and draft targets in this conversation.",
        "generation_originals": 400, "generation_setting": 200, "generation_validation": 200,
        "tampering_originals": 240, "tampering_setting": 120, "tampering_validation": 120,
        "generation_datasets": ["SynthBuster+", "SynthCLIC"],
        "tampering_datasets": ["Columbia", "COVERAGE", "CocoGlide"],
        "conditions": CONDITIONS, "scene_group_cv_folds": 5, "seed": SEED,
        "targets": {"false_positive_rate": .05, "false_negative_rate": .10, "abstain_rate": .20},
        "selection_rule": {
            "gates": "Each of the six input conditions must meet all three targets using successful rows. No candidate is selected if either class is absent or an inference failed in the selection data.",
            "ranking": ["worst_condition_false_negative_rate", "mean_condition_false_negative_rate",
                        "mean_condition_abstain_rate", "mean_condition_false_positive_rate", "canonical_candidate_order"],
            "no_eligible_candidate": "Record selection failure; retain prespecified A/B validation comparisons, without inventing an improved service policy.",
            "strata": "Report dataset/generator and mask-area strata separately; small strata are not additional selection gates.",
        },
        "bfree_candidate_definitions": {"A": "raw logit > 0", "B": "p<.4 negative; .4<=p<=.6 abstain; p>.6 positive",
            "binary": [.30,.40,.50,.60,.70], "binary_boundary": "p>t positive, otherwise negative",
            "abstain_lower": [.20,.30,.40], "abstain_upper": [.60,.70,.80], "abstain_boundary": "inclusive lower/upper"},
        "trufor_reference": {"A": "score >= .5", "B": "score<.4 negative; inclusive .4..6 abstain; score>.6 positive"},
        "mesorch_score_aggregations": ["mean", "maximum", "top_1_percent_mean"],
        "map_threshold": .5, "map_boundary": ">=.5", "map_direction": "official positive forgery, never inverted",
        "common_location_evaluation": "Original input coordinates; Mesorch 512 map restored by fixed bilinear interpolation, align_corners=False; ground truth never passed to model.",
        "model_execution": "Official final weights, float32 for B-Free/TruFor/Mesorch; batch one, sequential single-GPU processes, no training.",
        "fake_shield": "Official standard execution feasibility first; no automatic quantization, offload, paid resources or external upload.",
        "actual_device_capture_and_human_explanation_review": "Requires real device/app metadata and human reviewers; never fabricate these results.",
        "prior_score_access": "v0.1 prediction scores are excluded from candidate selection. Prior manifest identities/images are used only for exposure and scene audit."
    }
    save_json(RUN/"approved_protocol.json", approval)
    models=[]
    for model,manifest,freeze in [
        ("bfree","runs/20261002_bfree_raise/preparation/manifest.csv","runs/20261002_bfree_raise/bfree_protocol.json"),
        ("trufor","runs/20261001_original/trufor_preparation/manifest.csv","runs/20261001_original/trufor_protocol.json")]:
        frozen=verify_freeze(ROOT/manifest,model,ROOT/freeze)
        code = "import torch,sys,json; print(json.dumps(dict(python=sys.version,executable=sys.executable,torch=torch.__version__,cuda_runtime=torch.version.cuda,available=torch.cuda.is_available(),gpu=torch.cuda.get_device_name(0),capability=torch.cuda.get_device_capability(0),architectures=torch.cuda.get_arch_list(),matmul=float((torch.ones((2,2),device='cuda')@torch.ones((2,2),device='cuda'))[0,0]))))"
        result=subprocess.run([str(ROOT/".venv"/model/"Scripts/python.exe"),"-X","utf8","-c",code],capture_output=True,text=True,encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stderr)
        models.append({"model":model,"runtime":json.loads(result.stdout),"weights_sha256":frozen["weights_sha256"],
            "protocol_sha256":sha256(ROOT/freeze),"manifest_sha256":sha256(ROOT/manifest),"frozen_integrity_verified":True})
    sources=json.loads((RUN/"source_probe/fake_weights.json").read_text())
    files=sources["siblings"]
    dte=sum(f.get("size",0) for f in files if f["rfilename"].startswith("DTE-FDM/model-") and f["rfilename"].endswith(".safetensors"))
    mflm=sum(f.get("size",0) for f in files if f["rfilename"].startswith("MFLM/pytorch_model-") and f["rfilename"].endswith(".bin"))
    index=json.loads((RUN/"source_probe/fake_dte_index.txt").read_text())
    fake={"status":"deferred_official_standard_configuration","assessment":"Memory lower bound from official checkpoint inventory, not an actual failed inference.",
        "dte_shard_bytes":dte,"dte_tensor_bytes":index["metadata"]["total_size"],"mflm_shard_bytes":mflm,
        "gpu_memory_bytes":11264*1024**2,"dte_exceeds_total_gpu_memory":index["metadata"]["total_size"]>11264*1024**2,
        "weights_downloaded":False,"inference_executed":False,"explanation_evaluated":False,
        "official_sources":["https://github.com/zhipeixu/FakeShield","https://huggingface.co/zhipeixu/fakeshield-v1-22b"],
        "limitations":"Modified offload/quantized execution has not been evaluated; performance cannot be inferred.",
        "repo_commit":json.loads((RUN/"source_probe/fake_repo.json").read_text())["sha"],"weights_commit":sources["sha"]}
    save_json(RUN/"fake_shield_feasibility.json",fake)
    save_json(RUN/"preflight.json",{"created_at_utc":timestamp(),"root":str(ROOT),"models":models,
        "disk":{d:shutil.disk_usage(d)._asdict() for d in (str(ROOT.anchor),)},
        "v01_scores_opened_for_selection":False,
        "code_sha256":sha256(__file__),
        "handoff_files":[{"path":str(p.relative_to(ROOT)),"sha256":sha256(p)} for p in sorted((ROOT/"handoff/v0.2-2026-10-04").glob("*.md"))]})
    print("Approved scope, preflight, prior frozen integrity and FakeShield feasibility recorded.")


if __name__=="__main__":
    main()
