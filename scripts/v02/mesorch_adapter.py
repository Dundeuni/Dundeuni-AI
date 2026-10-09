"""Unmodified official Mesorch models and official IMDLBenCo resizing."""
import importlib,importlib.util,sys,types
from pathlib import Path
import numpy as np
from PIL import Image
from common import ROOT,sha256
def load_mesorch(torch,device,kind):
    site=Path(importlib.util.find_spec("IMDLBenCo").origin).parent
    # The installed official package eagerly imports unrelated models requiring
    # Windows-unavailable libraries. Scope the namespace to the actual official
    # registry/transform modules; neither their source nor model source is edited.
    namespace=types.ModuleType("IMDLBenCo");namespace.__path__=[str(site)]
    sys.modules["IMDLBenCo"]=namespace
    transforms_namespace=types.ModuleType("IMDLBenCo.transforms");transforms_namespace.__path__=[str(site/"transforms")]
    sys.modules["IMDLBenCo.transforms"]=transforms_namespace
    from IMDLBenCo.transforms.iml_transforms import get_albu_transforms
    source=ROOT/"third_party/Mesorch"
    sys.path.insert(0,str(source))
    if kind=="mesorch":
        from mesorch import MesorchFull
        model=MesorchFull(seg_pretrain_path=None,conv_pretrain=False,image_size=512)
        filename="mesorch-98.pth"
    elif kind=="mesorch_p":
        from mesorch_p import Mesorch_P
        model=Mesorch_P(seg_pretrain_path=None,conv_pretrain=False,image_size=512)
        filename="mesorch_p-118.pth"
    else:raise ValueError(kind)
    weight=source/"weights"/filename
    checkpoint=torch.load(str(weight),map_location="cpu")
    if not isinstance(checkpoint,dict) or "model" not in checkpoint:raise ValueError("Unexpected official checkpoint structure")
    state=checkpoint["model"]
    unused=[]
    if kind=="mesorch":
        model.load_state_dict(state,strict=True)
    else:
        status=model.load_state_dict(state,strict=False)
        unused=list(status.unexpected_keys)
        if status.missing_keys or any(not key.startswith(("convnext.head.","convnext.stages.3.")) for key in unused):
            raise ValueError("Unexpected checkpoint mismatch beyond officially removed modules")
    del checkpoint,state
    model=model.to(device).eval()
    transform=get_albu_transforms("resize",output_size=(512,512))
    def predict(path):
        with Image.open(path) as image:
            array=np.asarray(image.convert("RGB"));size=array.shape[:2]
        tensor=transform(image=array)["image"].unsqueeze(0).to(device)
        dummy=torch.zeros((1,1,512,512),device=device)
        output=model(image=tensor,mask=dummy)
        if output["pred_label"] is not None:raise ValueError("Unexpected official image score")
        native=output["pred_mask"]
        if tuple(native.shape)!=(1,1,512,512):raise ValueError("Unexpected native map shape")
        restored=torch.nn.functional.interpolate(native,size=size,mode="bilinear",align_corners=False)
        result=restored[0,0].float().cpu().numpy()
        native_array=native[0,0].float().cpu().numpy()
        if not np.isfinite(result).all() or result.min()<0 or result.max()>1:raise ValueError("Invalid native map")
        k=max(1,int(np.ceil(native_array.size*.01)))
        values=native_array.reshape(-1)
        scores={"mean":float(values.mean()),"max":float(values.max()),"top1":float(np.partition(values,len(values)-k)[-k:].mean())}
        return scores,{"map":result,"native_map":native_array},size
    meta={"model_module_sha256":sha256(source/("mesorch.py" if kind=="mesorch" else "mesorch_p.py")),
          "preprocessing_module_sha256":sha256(site/"transforms/iml_transforms.py"),
          "official_model_class":type(model).__name__,"strict_checkpoint_load":kind=="mesorch",
          "unused_checkpoint_keys":unused,"missing_checkpoint_keys":[],
          "checkpoint_loading":"Mesorch strict; Mesorch-P official strict=False limited to explicitly removed convnext head/stage3",
          "preprocessing":"Official IMDLBenCo 0.1.45 resize transform: cv2 linear resize512, ImageNet Normalize, Crop512, ToTensorV2",
          "dummy_loss_target":"Zero tensor; no evaluation ground truth passed to model",
          "registry_import_scope":"Official namespace limited to registry/transforms; unrelated model auto-imports skipped",
          "native_output":"pred_mask 512x512 sigmoid; pred_label=None",
          "evaluation_map_restore":"Adapter bilinear interpolation to original coordinates, align_corners=False",
          "image_scores":"Adapter aggregations of native 512x512 map; mean,max,largest ceil(1%) mean"}
    return model,predict,weight,meta
