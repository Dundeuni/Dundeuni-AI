# -*- coding: utf-8 -*-
"""Replay published running_test for deterministic samples; preserve prior predictions."""
import contextlib,hashlib,io,json,os,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runs/20261004_bfree_diagnosis'
source=ROOT/'third_party/B-Free/code'
sys.path.insert(0,str(source))
import torch
from main_bfree_single import running_test
torch.set_num_threads(4)
records=[]
input_hashes={}
for role in ['setting','validation']:
 p=ROOT/'runs/20261004_followup/inference/bfree'/role/'predictions.jsonl'
 input_hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 rows=[json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
 # First source_id in each dataset, selected lexicographically without scores.
 for ds in ['synthbuster-plus','synthclic']:
  rr=[r for r in rows if r['condition']=='original' and r['dataset']==ds]
  src=sorted({r['source_id'] for r in rr})[0]
  for gen in ['', 'SD3-medium','FLUX.1-dev','FLUX.1-schnell']:
   row=next(r for r in rr if r['source_id']==src and r['generator']==gen)
   image=ROOT/row['path']
   assert hashlib.sha256(image.read_bytes()).hexdigest()==row['sha256']
   previous=Path.cwd();capture=io.StringIO();start=time.perf_counter()
   try:
    os.chdir(source)
    with contextlib.redirect_stdout(capture):
     running_test(str(image),'BFREE_dino2reg4','cuda:0')
   finally:os.chdir(previous)
   matches=re.findall(r'logit score: ([+-]?[0-9]+\.[0-9]+)',capture.getvalue())
   if len(matches)!=1:raise ValueError(capture.getvalue())
   official=float(matches[0]);difference=abs(official-row['raw_score'])
   # Official CLI prints only three decimals, hence 0.0006 comparison tolerance.
   ok=difference<=.0006
   records.append({'image_id':row['image_id'],'dataset':ds,'role':role,'generator':gen or 'real',
    'selection':'lexicographically first source_id in each role and dataset, independent of score',
    'stored_logit':row['raw_score'],'official_printed_logit':official,'absolute_difference':difference,
    'passed':ok,'elapsed_seconds':time.perf_counter()-start})
   print(role,ds,gen or 'real',official,'pass',ok,flush=True)
   assert ok,records[-1]
   torch.cuda.empty_cache()
for p,h in input_hashes.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
output={'official_function':'third_party/B-Free/code/main_bfree_single.py:running_test',
 'samples':len(records),'all_passed':all(r['passed'] for r in records),'tolerance':.0006,
 'tolerance_reason':'official function prints three decimal digits',
 'original_predictions_unchanged':True,'records':records}
p=OUT/'official_replay.json'
if p.exists():raise FileExistsError('Preserve completed replay')
p.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print('REPLAY_COMPLETE',output['samples'],output['all_passed'],flush=True)