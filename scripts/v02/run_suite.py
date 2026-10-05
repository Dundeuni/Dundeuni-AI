"""Resume-safe single-GPU full suite; all four selections freeze before validation."""
import json,subprocess,os,sys
from pathlib import Path
from common import ROOT,RUN,sha256,save_json,timestamp
def step(name,exe,args):
    state=RUN/"suite_state.json"
    save_json(state,{"updated_at_utc":timestamp(),"state":"running","current_step":name},exclusive=False)
    log=RUN/"suite_logs"/(name+".log");log.parent.mkdir(exist_ok=True)
    if log.exists():
        index=2
        while log.with_name(name+"_attempt"+str(index)+".log").exists():index+=1
        log=log.with_name(name+"_attempt"+str(index)+".log")
    env=dict(os.environ);env.update(PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1")
    print("Starting",name,flush=True)
    with log.open("x",encoding="utf-8") as stream:
        process=subprocess.run([str(exe),"-X","utf8","-u"]+args,cwd=str(ROOT),env=env,stdout=stream,stderr=subprocess.STDOUT)
    if process.returncode:
        save_json(state,{"updated_at_utc":timestamp(),"state":"failed","current_step":name,"returncode":process.returncode,"log":str(log.relative_to(ROOT))},exclusive=False)
        raise RuntimeError(name+" failed; inspect "+str(log))
    print("Completed",name,flush=True)
def complete(model,role):
    folder=RUN/"inference"/model/role
    p=folder/"completion.json"
    if not p.exists():return False
    record=json.loads(p.read_text())
    if record["prediction_sha256"]!=sha256(folder/"predictions.jsonl"):raise ValueError("Completed score file changed")
    if record["recorded"]!=record["requests"]:raise ValueError("Incomplete completion marker")
    return True
def main():
    data_exe=ROOT/".venv/v02-data/Scripts/python.exe"
    environments={"bfree":"bfree","trufor":"trufor","mesorch":"mesorch","mesorch_p":"mesorch"}
    models=["trufor","mesorch","mesorch_p","bfree"]
    for model in models:
        if not complete(model,"setting"):
            step("setting_"+model,ROOT/".venv"/environments[model]/"Scripts/python.exe",["scripts/v02/inference.py","--model",model,"--role","setting"])
    # Never start validation until all models have completed frozen setting selection.
    for model in models:
        freeze=RUN/(model+"_policy_freeze.json")
        if not freeze.exists():step("freeze_"+model,data_exe,["scripts/v02/freeze_selection.py",model])
    for model in ["bfree","trufor","mesorch","mesorch_p"]:
        if not complete(model,"validation"):
            step("validation_"+model,ROOT/".venv"/environments[model]/"Scripts/python.exe",["scripts/v02/inference.py","--model",model,"--role","validation","--freeze",str(RUN/(model+"_policy_freeze.json"))])
    for model in ["trufor","mesorch","mesorch_p"]:
        if not complete(model,"comparison"):
            step("comparison_"+model,ROOT/".venv"/environments[model]/"Scripts/python.exe",["scripts/v02/inference.py","--model",model,"--role","comparison"])
    if not (RUN/"evaluation.json").exists():step("evaluate",data_exe,["scripts/v02/evaluate_followup.py"])
    save_json(RUN/"suite_state.json",{"updated_at_utc":timestamp(),"state":"complete","evaluation_sha256":sha256(RUN/"evaluation.json")},exclusive=False)
    print("Full6720-request experiment and frozen evaluation complete",flush=True)
if __name__=="__main__":main()
