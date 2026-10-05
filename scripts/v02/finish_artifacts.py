"""Wait for numerical suite completion, then create and verify local artifacts."""
import json,time,subprocess,sys,os
from common import ROOT,RUN,save_json,timestamp
def main():
    status=RUN/"finish_state.json"
    save_json(status,{"state":"waiting_for_suite","updated_at_utc":timestamp()},exclusive=False)
    while True:
        try:
            state=json.loads((RUN/"suite_state.json").read_text())
        except (FileNotFoundError,json.JSONDecodeError):
            time.sleep(10);continue
        if state["state"]=="failed":raise RuntimeError("Numerical suite failed; see suite_state.json")
        if state["state"]=="complete":break
        time.sleep(10)
    exe=ROOT/".venv/v02-data/Scripts/python.exe"
    env=dict(os.environ);env.update(PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1")
    for name in ["uncertainty","write_report","verify_followup"]:
        save_json(status,{"state":"running","step":name,"updated_at_utc":timestamp()},exclusive=False)
        print("Post-processing",name,flush=True)
        log=RUN/(name+"_execution.log")
        with log.open("x",encoding="utf-8") as stream:
            result=subprocess.run([str(exe),"-X","utf8","-u","scripts/v02/"+name+".py"],cwd=str(ROOT),env=env,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            save_json(status,{"state":"failed","step":name,"log":str(log.relative_to(ROOT)),"updated_at_utc":timestamp()},exclusive=False)
            raise RuntimeError(name+" failed; see "+str(log))
    save_json(status,{"state":"artifacts_created_and_numerically_verified","visual_QA":"pending_root_inspection","updated_at_utc":timestamp()},exclusive=False)
    print("Report and numerical verification ready for visual QA",flush=True)
if __name__=="__main__":main()
