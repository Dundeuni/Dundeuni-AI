"""Use a synthetic nonconstant image, separately from any evaluation split."""
import json,time,sys
import numpy as np
from PIL import Image
import torch
from common import ROOT,RUN,save_json,sha256
from mesorch_adapter import load_mesorch
kind=sys.argv[1]
out=RUN/("smoke_"+kind)
attempt=1
while out.exists():
    attempt+=1;out=RUN/("smoke_"+kind+"_attempt"+str(attempt))
out.mkdir(exist_ok=False)
rng=np.random.RandomState(18)
image=rng.randint(0,256,(377,593,3),dtype=np.uint8)
path=out/"synthetic_runtime_probe.png";Image.fromarray(image).save(path)
torch.cuda.set_device(0)
torch.backends.cudnn.benchmark=False
torch.backends.cudnn.deterministic=True
torch.set_num_threads(4)
start=time.perf_counter()
model,predict,weight,meta=load_mesorch(torch,"cuda:0",kind)
with torch.inference_mode():
    scores,maps,size=predict(path)
torch.cuda.synchronize()
# Prove the output does not depend on dummy loss target using the same image.
from IMDLBenCo.transforms.iml_transforms import get_albu_transforms
tensor=get_albu_transforms("resize",output_size=(512,512))(image=image)["image"].unsqueeze(0).cuda()
with torch.inference_mode():
    zero=model(tensor,torch.zeros((1,1,512,512),device="cuda"))["pred_mask"]
    one=model(tensor,torch.ones((1,1,512,512),device="cuda"))["pred_mask"]
same=torch.equal(zero,one)
difference=float(torch.max(torch.abs(zero-one)).item())
print("dummy target difference",difference,flush=True)
if not same:raise ValueError("Official predictions differ; inspect deterministic smoke outputs")
save_json(out/"runtime.json",{"model":kind,"weight_sha256":sha256(weight),"input_scope":"synthetic smoke only",
 "seconds":time.perf_counter()-start,"scores":scores,"shape":list(maps["map"].shape),"native_shape":list(maps["native_map"].shape),
 "map_min":float(maps["map"].min()),"map_max":float(maps["map"].max()),"peak_allocated_bytes":torch.cuda.max_memory_allocated(),
 "dummy_target_independence_verified":same,"torch":torch.__version__,"device":torch.cuda.get_device_name(),"meta":meta})
print(kind,"runtime smoke passed","shape",size,"peak GPU",torch.cuda.max_memory_allocated(),flush=True)
