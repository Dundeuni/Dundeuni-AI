"""One A.X encoder with risk and auxiliary action heads; local safetensors."""
from contextlib import nullcontext
import json
import math
import re
from pathlib import Path

import torch
from torch import nn
from safetensors.torch import load_file,save_file
from transformers import AutoConfig,AutoModel,AutoTokenizer
from .device_policy import select_device
from .message_context import ACTION_NAMES,message_spans,normalize,format_input

class ActionModel(nn.Module):
    def __init__(self,config,base_path=None):
        super().__init__()
        config.reference_compile=False
        self.config=config
        if base_path is None:
            self.encoder=AutoModel.from_config(config,attn_implementation='sdpa')
        else:
            self.encoder=AutoModel.from_pretrained(base_path,config=config,local_files_only=True,
                trust_remote_code=False,use_safetensors=True,attn_implementation='sdpa',torch_dtype=torch.float32)
        h=config.hidden_size
        self.projection=nn.Sequential(nn.Linear(h,h),nn.GELU(),nn.LayerNorm(h))
        self.dropout=nn.Dropout(.1)
        self.risk_head=nn.Linear(h,2)
        self.action_head=nn.Linear(h,len(ACTION_NAMES))

    def forward(self,input_ids,attention_mask,**unused):
        out=self.encoder(input_ids=input_ids,attention_mask=attention_mask).last_hidden_state
        mask=attention_mask.unsqueeze(-1).to(out.dtype)
        pooled=(out*mask).sum(1)/mask.sum(1).clamp(min=1)
        shared=self.dropout(self.projection(pooled))
        return self.risk_head(shared),self.action_head(shared)

    def save(self,folder,tokenizer,metadata):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        self.config.save_pretrained(folder);tokenizer.save_pretrained(folder)
        save_file({k:v.detach().cpu().contiguous() for k,v in self.state_dict().items()},str(folder/'model.safetensors'))
        (folder/'action_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')

    @classmethod
    def load(cls, folder: str | Path, device: str | torch.device) -> "ActionModel":
        config = AutoConfig.from_pretrained(
            folder, local_files_only=True, trust_remote_code=False
        )
        cpu_loading = torch.device(device).type == "cpu"
        if cpu_loading:
            # Casting after loading cannot recover FP32 values rounded to BF16.
            config.dtype = torch.float32
        model = cls(config)
        if cpu_loading:
            # Heads also need FP32 before loading, even with a custom default dtype.
            model.float()
        model.load_state_dict(
            load_file(str(Path(folder) / "model.safetensors"), device="cpu"),
            strict=True,
        )
        return model.to(device).eval()

def sentence_neighborhoods(text):
    """Keep adjacent sentences together; OCR line wraps are not sentence boundaries.

    Supplement length windows only for long inputs. No risk keywords or label
    lookups are used. Offsets refer to the normalized visible input.
    """
    text=normalize(text)
    if len(text)<=240:
        return []
    cuts=[0]+[match.end() for match in re.finditer(r'(?<=[.!?。！？])\s+',text)]+[len(text)]
    units=[(a,b) for a,b in zip(cuts,cuts[1:]) if text[a:b].strip()]
    if len(units)<2:
        return []
    result=[];seen=set()
    for i in range(len(units)):
        start=units[max(0,i-1)][0];end=units[min(len(units)-1,i+1)][1]
        focus=text[start:end].strip()
        if focus in seen:
            continue
        seen.add(focus)
        result.append({'focus':focus,'context':'','input_text':format_input(focus),
            'start':start,'end':end,'speaker':'unknown',
            'boundary_basis':'adjacent_sentence_neighborhood_not_verified_message_turn'})
    # An isolated sentence is diagnostic only: conflicting context must not
    # become a confident low-risk result or an automatic risk override.
    seen_single=set()
    for start,end in units:
        focus=text[start:end].strip()
        if focus in seen_single:
            continue
        seen_single.add(focus)
        result.append({'focus':focus,'context':'','input_text':format_input(focus),
            'start':start,'end':end,'speaker':'unknown',
            'boundary_basis':'isolated_sentence_review_only'})
    return result


def decide_action(result,body=None,low=.3,high=.5):
    from .body_policy_v2 import decide_body
    final=decide_body(result['score'],low,high,body or {})
    if result.get('requires_context_review') and final['decision']=='normal':
        final.update(decision='defer',basis='sentence_context_disagreement')
    return final


class ActionEncoder:
    def __init__(self, folder: str | Path, device: str | None = None) -> None:
        self.folder = Path(folder)
        # Resolve/validate before allocating the classifier or loading a tokenizer.
        self.device = select_device(device)
        self.model = ActionModel.load(folder, self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(
            folder, local_files_only=True, trust_remote_code=False
        )

    def analyze_text(self,text,threshold=.5,low=.3):
        text=normalize(text)
        if text and not any(character.isalnum() for character in text):
            return {'score':None,'decision':'defer','interval_decision':'defer','basis':'no_analyzable_characters','spans':[],'actions':{},'windows':0}
        spans=message_spans(text)
        if not spans:
            return {'score':None,'decision':'defer','basis':'empty_text','spans':[],'actions':{},'windows':0}
        spans += sentence_neighborhoods(text)
        batch=self.tokenizer([s['input_text'] for s in spans],padding=True,truncation=True,max_length=384,
            return_tensors='pt',return_overflowing_tokens=True,stride=64)
        mapping=batch.pop('overflow_to_sample_mapping').tolist()
        values=[];actions=[]
        with torch.inference_mode():
            for start in range(0,len(mapping),8):
                b={k:v[start:start+8].to(self.device) for k,v in batch.items()}
                with (torch.autocast('cuda',dtype=torch.bfloat16) if self.device=='cuda' else nullcontext()):
                    risk,aux=self.model(**b)
                values.extend(risk.float().softmax(-1)[:,1].cpu().tolist())
                actions.extend(aux.float().sigmoid().cpu().tolist())
        assert all(math.isfinite(p) and 0<=p<=1 for p in values)
        for i,s in enumerate(spans):
            indices=[j for j,v in enumerate(mapping) if v==i]
            j=max(indices,key=lambda j:values[j])
            s.update(score=values[j],actions=dict(zip(ACTION_NAMES,actions[j])))
        primary=[s for s in spans if s['boundary_basis']!='isolated_sentence_review_only']
        isolated=[s['score'] for s in spans if s['boundary_basis']=='isolated_sentence_review_only']
        worst=max(primary,key=lambda s:s['score']);score=worst['score']
        isolated_score=max(isolated,default=0.0)
        context_review=isolated_score>=threshold and score<threshold
        return {'score':score,'decision':'phishing' if score>=threshold else 'normal',
            'interval_decision':'phishing' if score>=threshold else 'normal' if score<low else 'defer',
            'basis':'single_learned_risk_head_text_and_sentence_neighborhoods','actions':worst['actions'],'spans':spans,
            'highest_risk_visible_text':worst['focus'],'windows':len(values),
            'score_meaning':'Uncalibrated risk score; action scores are weak-label topics, not proof of scam',
            'requires_context_review':context_review,'isolated_sentence_score':isolated_score,
            'external_source_information_used':False,'keyword_decision_override':False}
