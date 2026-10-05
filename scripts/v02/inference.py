"""Sequential inference; validation requires a matching immutable policy freeze."""
import argparse,json,math,time,sys,traceback,os
from pathlib import Path
from common import ROOT,RUN,sha256,save_json,timestamp
sys.path.insert(0,str(ROOT/"scripts"))
from run_inference import load_bfree,load_trufor
def location_metrics(predicted,truth,label):
    import numpy as np
    if predicted.shape!=truth.shape:raise ValueError("Map/truth coordinate mismatch")
    if not np.isfinite(predicted).all() or predicted.min()<0 or predicted.max()>1:raise ValueError("Invalid probability map")
    positive=predicted>=.5;truth=truth.astype(bool)
    result={"positive_area_fraction":float(positive.mean()),"gt_area_fraction":float(truth.mean()),"coordinate_shape":list(truth.shape),"map_threshold":.5}
    if label==0:
        if truth.any():raise ValueError("Negative truth is nonempty")
        result.update(false_positive_area_fraction=float(positive.mean()),IoU=None,F1=None)
    elif not truth.any():
        result.update(IoU=None,F1=None,location_status="empty_positive_mask_after_geometry")
    else:
        intersection=int(np.count_nonzero(positive&truth));union=int(np.count_nonzero(positive|truth))
        result.update(IoU=intersection/union,F1=2*intersection/(int(positive.sum())+int(truth.sum())),location_status="evaluated")
    return result
def verify_validation_guard(manifest,model,freeze):
    if not freeze or not Path(freeze).is_file():raise ValueError("Validation requires completed frozen selection")
    record=json.loads(Path(freeze).read_text())
    if record["manifest_sha256"]!=sha256(manifest) or record["model"]!=model:raise ValueError("Wrong validation freeze/manifest")
    for filename,digest in record["code_sha256"].items():
        if sha256(ROOT/filename)!=digest:raise ValueError("Frozen implementation changed")
    if sha256(ROOT/record["weights_path"])!=record["weights_sha256"]:raise ValueError("Frozen weights changed")
    if record["selection"]["status"] not in ["selected","selection_failed"]:raise ValueError("Unfinished selection")
    return record
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",choices=["bfree","trufor","mesorch","mesorch_p"],required=True)
    parser.add_argument("--role",choices=["setting","validation","comparison"],required=True)
    parser.add_argument("--freeze",type=Path)
    args=parser.parse_args()
    task="bfree" if args.model=="bfree" else "tampering"
    manifest=RUN/(task+"_manifest.json")
    frozen=verify_validation_guard(manifest,args.model,args.freeze) if args.role=="validation" else None
    if args.role!="validation" and args.freeze:raise ValueError("Freeze argument is validation-only")
    source=json.loads(manifest.read_text())
    rows=[r for r in source["rows"] if r["role"]==args.role]
    if not rows:raise ValueError("No requests in role")
    # Process originals first; all five fixed variants follow.
    from build_inputs import verify_rows
    verify_rows(rows)
    import torch,numpy as np
    from PIL import Image
    torch.set_num_threads(4);torch.cuda.set_device(0)
    if args.model in ["mesorch","mesorch_p"]:
        torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
        from mesorch_adapter import load_mesorch
        loader=lambda:load_mesorch(torch,"cuda:0",args.model)
    else:loader=lambda:(load_bfree if args.model=="bfree" else load_trufor)(torch,"cuda:0")
    out=RUN/"inference"/args.model/args.role
    out.mkdir(parents=True,exist_ok=True)
    metadata_path=out/"metadata.json";result_path=out/"predictions.jsonl"
    implementation={str(p.relative_to(ROOT)):sha256(p) for p in [Path(__file__),ROOT/"scripts/v02/mesorch_adapter.py",ROOT/"scripts/v02/policy_selection.py",ROOT/"scripts/v02/build_inputs.py"]}
    if metadata_path.exists():
        existing=json.loads(metadata_path.read_text())
        if existing["manifest_sha256"]!=sha256(manifest) or existing["code_sha256"]!=implementation:raise ValueError("Resume input/implementation mismatch")
    torch.cuda.synchronize();start=time.perf_counter()
    model,predict,weight,preprocessing=loader()
    torch.cuda.synchronize()
    metadata={"model":args.model,"role":args.role,"task":task,"created_at_utc":timestamp(),"manifest_sha256":sha256(manifest),
       "weights_path":str(weight.relative_to(ROOT)),"weights_sha256":sha256(weight),"code_sha256":implementation,
       "preprocessing":preprocessing,"python":sys.version,"python_executable":sys.executable,"torch":torch.__version__,
       "cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(),"load_seconds":time.perf_counter()-start,
       "freeze_sha256":sha256(args.freeze) if args.freeze else None,"requested":len(rows)}
    if frozen and metadata["weights_sha256"]!=frozen["weights_sha256"]:raise ValueError("Loaded weights differ from freeze")
    if not metadata_path.exists():save_json(metadata_path,metadata)
    existing_rows=[]
    if result_path.exists():
        existing_rows=[json.loads(line) for line in result_path.read_text().splitlines() if line]
        if len({r["image_id"] for r in existing_rows})!=len(existing_rows):raise ValueError("Repeated resume result")
    done={r["image_id"] for r in existing_rows}
    if not done<={r["image_id"] for r in rows}:raise ValueError("Unexpected resume requests")
    maps_dir=out/"maps";maps_dir.mkdir(exist_ok=True)
    errors=out/"errors.log"
    with result_path.open("a",encoding="utf-8") as stream:
        for index,row in enumerate(rows,1):
            if row["image_id"] in done:continue
            output={**row,"model":args.model,"status":"failed","latency_seconds":None,"peak_gpu_allocated_bytes":None}
            try:
                if sha256(ROOT/row["path"])!=row["sha256"]:raise ValueError("Input changed after preparation")
                torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();start=time.perf_counter()
                with torch.inference_mode():value,maps,size=predict(ROOT/row["path"])
                torch.cuda.synchronize()
                output["latency_seconds"]=time.perf_counter()-start
                output["peak_gpu_allocated_bytes"]=torch.cuda.max_memory_allocated()
                if args.model=="bfree":
                    from policies import probability
                    if not math.isfinite(value):raise ValueError("Nonfinite logit")
                    output.update(raw_score=value,scores={"official":probability("bfree",value)})
                elif args.model=="trufor":output.update(raw_score=value,scores={"official":value})
                else:output.update(raw_score=None,scores=value)
                if maps:
                    array=maps["map"]
                    if tuple(array.shape)!=tuple(size):raise ValueError("Map/input shape mismatch")
                    if row.get("mask_path"):
                        with Image.open(ROOT/row["mask_path"]) as mask:truth=np.asarray(mask)>0
                    else:truth=np.zeros(size,dtype=bool)
                    output["localization"]=location_metrics(array,truth,row["label"])
                    path=maps_dir/(row["image_id"]+".npz")
                    if path.exists():raise FileExistsError("Preserve existing map without completed record")
                    with path.open("xb") as target:np.savez_compressed(target,**maps)
                    output["maps_path"]=str(path.relative_to(ROOT));output["maps_sha256"]=sha256(path)
                output.update(status="success",original_coordinate_shape=list(size))
                del maps
            except Exception as exc:
                output["error_type"]=type(exc).__name__;output["error_message"]=str(exc)[:1000]
                with errors.open("a",encoding="utf-8") as log:log.write(row["image_id"]+"\n"+traceback.format_exc()+"\n")
                torch.cuda.empty_cache()
            stream.write(json.dumps(output,ensure_ascii=False,allow_nan=False)+"\n");stream.flush()
            done.add(row["image_id"]);existing_rows.append(output)
            if index%20==0 or index==len(rows):
                print(args.model,args.role,index,"/",len(rows),row["condition"],"failures",sum(r["status"]!="success" for r in existing_rows),flush=True)
    save_json(out/"completion.json",{"completed_at_utc":timestamp(),"requests":len(rows),"recorded":len(existing_rows),
       "failures":sum(r["status"]!="success" for r in existing_rows),"prediction_sha256":sha256(result_path)},exclusive=not (out/"completion.json").exists())
if __name__=="__main__":main()
