"""Install inference dependencies in the new environment only."""
import subprocess,sys
from pathlib import Path
from common import ROOT,RUN
exe=ROOT/".venv/mesorch/Scripts/python.exe"
result=subprocess.run([str(exe),"-m","pip","freeze"],capture_output=True,text=True,check=True)
constraints=RUN/"mesorch_existing_constraints.txt"
constraints.write_text(result.stdout,encoding="utf-8")
log=RUN/"install_mesorch.log"
with log.open("x",encoding="utf-8") as stream:
    for args in [
      ["install","--disable-pip-version-check","-c",str(constraints),"rich==13.9.4","opencv-python-headless==4.8.1.78","albumentations==1.3.0","scikit-image==0.22.0"],
      ["install","--disable-pip-version-check","--no-deps",str(RUN/"source_probe/IMDLBenCo-0.1.45-py3-none-any.whl")]]:
        p=subprocess.run([str(exe),"-m","pip"]+args,stdout=stream,stderr=subprocess.STDOUT)
        if p.returncode:raise RuntimeError("Installation failed, see "+str(log))
print("Mesorch inference dependencies installed; original environments preserved")
