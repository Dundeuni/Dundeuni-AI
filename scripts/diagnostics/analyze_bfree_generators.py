# -*- coding: utf-8 -*-
"""Post-hoc B-Free diagnostics. No changes to frozen models or service policies."""
import collections, hashlib, json, os, platform
from pathlib import Path
import numpy as np
from PIL import Image
from sklearn.metrics import roc_auc_score
ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'runs/20261004_followup'
OUT=ROOT/'runs/20261004_bfree_diagnosis'
GENS=['SD3-medium','FLUX.1-schnell','imagen3','FLUX.1-dev']
DATASETS=['synthbuster-plus','synthclic']
SEED=20261004
REPS=2000
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def summary(neg,pos):
 n=np.array([r['raw_score'] for r in neg]);p=np.array([r['raw_score'] for r in pos])
 return {'negative_n':len(n),'positive_n':len(p),'AUROC':float(roc_auc_score([0]*len(n)+[1]*len(p),np.r_[n,p])),
 'FP_A':int((n>0).sum()),'FN_A':int((p<=0).sum()),'TP_A':int((p>0).sum()),
 'FPR_A':float((n>0).mean()),'FNR_A':float((p<=0).mean()),
 'negative_logit_quantiles':np.quantile(n,[0,.1,.25,.5,.75,.9,1]).tolist(),
 'positive_logit_quantiles':np.quantile(p,[0,.1,.25,.5,.75,.9,1]).tolist()}
def rates(neg,pos,t):
 n=np.array([r['raw_score'] for r in neg]);p=np.array([r['raw_score'] for r in pos])
 return {'threshold_logit':float(t),'positive_rule':'raw_score > threshold','FP':int((n>t).sum()),'FN':int((p<=t).sum()),
 'TP':int((p>t).sum()),'negative_n':len(n),'positive_n':len(p),'FPR':float((n>t).mean()),'FNR':float((p<=t).mean())}
def operating(neg,pos,constraint):
 a=np.array([r['raw_score'] for r in neg+pos])
 ts=np.r_[np.nextafter(a.min(),-np.inf),np.unique(a)]
 rs=[rates(neg,pos,t) for t in ts]
 if constraint=='FPR5':
  feasible=[r for r in rs if r['FPR']<=.05+1e-12]
  return min(feasible,key=lambda r:(r['FNR'],r['FPR'],-r['threshold_logit']))
 feasible=[r for r in rs if r['FNR']<=.10+1e-12]
 return min(feasible,key=lambda r:(r['FPR'],r['FNR'],-r['threshold_logit']))
def main():
 if (OUT/'analysis.json').exists():raise FileExistsError('Preserve completed diagnostic output')
 OUT.mkdir(parents=True,exist_ok=True)
 rows={}
 frozen={}
 for role in ['setting','validation']:
  f=RUN/'inference/bfree'/role/'predictions.jsonl'
  frozen[str(f.relative_to(ROOT))]=sha(f)
  rows[role]=[json.loads(x) for x in f.read_text(encoding='utf-8').splitlines()]
  assert len(rows[role])==1200 and all(r['status']=='success' for r in rows[role])
 result={'analysis':'post-hoc diagnostic; no independent new validation, no policy selection for service',
 'seed':SEED,'bootstrap_reps':REPS,'original_inference_hashes':frozen,'by_role':{},'metadata':{},'paired':{},'threshold_diagnostics':{}}
 originals={}
 for role,allrows in rows.items():
  orig=[r for r in allrows if r['condition']=='original']; originals[role]=orig
  result['by_role'][role]={}
  for condition in sorted({r['condition'] for r in allrows}):
   rr=[r for r in allrows if r['condition']==condition];result['by_role'][role][condition]={}
   for ds in ['all']+DATASETS:
    nn=[r for r in rr if r['label']==0 and (ds=='all' or r['dataset']==ds)]
    result['by_role'][role][condition][ds]={g:summary(nn,[r for r in rr if r['generator']==g and (ds=='all' or r['dataset']==ds)]) for g in GENS}
  groups=collections.defaultdict(dict)
  format_counts=collections.defaultdict(collections.Counter)
  for r in orig:
   assert sha(ROOT/r['path'])==r['sha256']
   with Image.open(ROOT/r['path']) as im:
    assert list((im.height,im.width))==r['original_coordinate_shape']
    format_counts[r['generator'] or 'real'][(im.format,im.mode,bool(im.info.get('icc_profile')),len(im.getexif()))]+=1
   groups[r['dataset']+':'+r['source_id']][r['generator'] or 'real']=r
  assert len(groups)==40 and all(set(v)==set(GENS+['real']) for v in groups.values())
  equal=sum(all(v[g]['original_coordinate_shape']==v['SD3-medium']['original_coordinate_shape'] for g in ['FLUX.1-dev','FLUX.1-schnell']) for v in groups.values())
  pairs=[]
  for group,v in sorted(groups.items()):
   pairs.append({'source_pair_id':group,'scene_group_id':v['real']['group_id'],'dataset':v['real']['dataset'],'sd_minus_dev':v['SD3-medium']['raw_score']-v['FLUX.1-dev']['raw_score'],
    'schnell_minus_dev':v['FLUX.1-schnell']['raw_score']-v['FLUX.1-dev']['raw_score']})
  result['metadata'][role]={'original_count':len(orig),'verified_image_hashes':len(orig),
   'format_mode_icc_exif_counts':{g:[{'format':k[0],'mode':k[1],'icc_present':k[2],'exif_tags':k[3],'n':n} for k,n in c.items()] for g,c in format_counts.items()},
   'sd_dev_schnell_same_dimensions_groups':equal,'source_pairs':len(groups),'scene_groups':len({r['group_id'] for r in orig}),
   'all_min_dimension_ge_504':all(min(r['original_coordinate_shape'])>=504 for r in orig)}
  result['paired'][role]={'same_caption_source_group_not_pixel_aligned':True,'pairs':pairs,
   'sd_score_above_dev_groups':sum(p['sd_minus_dev']>0 for p in pairs),
   'schnell_score_above_dev_groups':sum(p['schnell_minus_dev']>0 for p in pairs),
   'median_sd_minus_dev':float(np.median([p['sd_minus_dev'] for p in pairs]))}
  neg=[r for r in orig if r['label']==0]
  result['threshold_diagnostics'][role]={}
  for g in GENS:
   pos=[r for r in orig if r['generator']==g]
   result['threshold_diagnostics'][role][g]={'empirical_oracle_FPR5':operating(neg,pos,'FPR5'),'empirical_oracle_FNR10':operating(neg,pos,'FNR10')}
 # A rule determined on setting originals only, chosen to maximize all-generator recall at <=5% observed FPR.
 setting_neg=[r for r in originals['setting'] if r['label']==0]
 setting_pos=[r for r in originals['setting'] if r['label']==1]
 fit=operating(setting_neg,setting_pos,'FPR5')
 validation_neg=[r for r in originals['validation'] if r['label']==0]
 result['setting_only_threshold']={'fit_objective':'all-generator original TPR maximum at setting FPR <=5%; post-hoc diagnostic, not service policy','setting':fit,
 'validation_by_generator':{g:rates(validation_neg,[r for r in originals['validation'] if r['generator']==g],fit['threshold_logit']) for g in GENS}}
 # Shared source-group bootstrap stratified by dataset preserves paired real and generated versions.
 orig=originals['validation'];groups=collections.defaultdict(dict)
 for r in orig:groups[r['dataset']+':'+r['source_id']][r['generator'] or 'real']=r['raw_score']
 ids=sorted(groups)
 matrix=np.array([[groups[i][g] for g in ['real']+GENS] for i in ids])
 strata=[np.array([j for j,i in enumerate(ids) if i.startswith(ds+':')]) for ds in DATASETS]
 assert [len(x) for x in strata]==[20,20]
 rng=np.random.default_rng(SEED);boot=np.empty((REPS,len(GENS)));delta=np.empty(REPS)
 for b in range(REPS):
  ix=np.concatenate([rng.choice(s,len(s),replace=True) for s in strata]);m=matrix[ix]
  for j in range(len(GENS)):
   dif=m[:,j+1,None]-m[None,:,0];boot[b,j]=np.mean((dif>0)+.5*(dif==0))
  delta[b]=np.median(m[:,1]-m[:,4])
 result['validation_group_bootstrap']={'method':'percentile 95% CI, dataset-stratified shared group resampling, 40 groups','AUROC_CI95':{g:np.quantile(boot[:,j],[.025,.975]).tolist() for j,g in enumerate(GENS)},
 'SD_minus_dev_AUROC_CI95':np.quantile(boot[:,0]-boot[:,3],[.025,.975]).tolist(),
 'median_SD_minus_dev_logit_CI95':np.quantile(delta,[.025,.975]).tolist()}
 verification=json.loads((RUN/'final_verification.json').read_text(encoding='utf-8'))
 protected={p:sha(ROOT/p)==h for p,h in verification['protected_artifacts_sha256'].items()}
 assert all(protected.values())
 result['protected_artifacts_unchanged']=protected
 result['environment']={'python':platform.python_version(),'numpy':np.__version__}
 (OUT/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 # Scientific plots use English labels so no dependency on installed Korean fonts.
 os.environ['MPLCONFIGDIR']=str(OUT/'matplotlib')
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 from sklearn.metrics import roc_curve
 colors=['#238b45','#377eb8','#e6ab02','#d73027']
 fig,axes=plt.subplots(1,2,figsize=(12,4.8))
 arrays=[matrix[:,j] for j in range(5)]
 axes[0].boxplot(arrays,labels=['Real','SD3','FLUX schnell','Imagen 3','FLUX dev'],showfliers=False)
 jitter=np.random.default_rng(SEED).uniform(-.12,.12,(40,5))
 for j,a in enumerate(arrays):axes[0].scatter(j+1+jitter[:,j],a,s=13,alpha=.55,color='#555555' if j==0 else colors[j-1])
 axes[0].axhline(0,color='black',linestyle='--',label='Original A threshold (0)')
 axes[0].axhline(fit['threshold_logit'],color='#777777',linestyle=':',label='Setting-only diagnostic threshold')
 axes[0].set_ylabel('Uncalibrated B-Free logit');axes[0].set_title('Original validation scores (n=40 per class)');axes[0].tick_params(axis='x',labelrotation=20);axes[0].legend(fontsize=8)
 for j,g in enumerate(GENS):
  fpr,tpr,_=roc_curve([0]*40+[1]*40,np.r_[matrix[:,0],matrix[:,j+1]])
  auc=result['by_role']['validation']['original']['all'][g]['AUROC']
  axes[1].plot(fpr,tpr,label=g+' (AUC '+format(auc,'.3f')+')',color=colors[j])
 axes[1].plot([0,1],[0,1],':',color='gray');axes[1].axvline(.05,color='gray',linestyle='--');axes[1].set(xlabel='False positive rate',ylabel='Detection rate',title='Original validation ROC (post-hoc diagnostic)',xlim=(0,1),ylim=(0,1.02));axes[1].legend(loc='lower right',fontsize=8)
 fig.tight_layout();fig.savefig(OUT/'score_distribution_roc.png',dpi=180);plt.close(fig)
 lines=['# B-Free SD3 / FLUX 성능 격차 원인 분석 (2026-10-04)',
 '', '기존 v0.2 점수·원본 이미지·공식 실행 코드를 이용한 사후 진단이다. 새 독립 검증이나 서비스 판정 기준 선정 결과가 아니다. 모델·가중치·기존 결과는 변경하지 않았다.',
 '', '## 확인된 결론', '', 'FLUX.1-dev의 미탐에는 기존 임계값과 맞지 않는 점수 이동, 정상 사진과의 점수 겹침이 함께 있다. 파일 형식·색상 모드·해상도 차이만으로 SD3와의 격차를 설명할 수 없다. 학습 분포와 생성 방식 차이는 가능한 배경 원인이며 개별 픽셀 특징의 인과관계는 입증하지 않았다.',
 '', '## 원본 검증 결과', '', '| 생성기 | 탐지 / 40장 | AUROC | AUROC 95% 그룹 CI | logit 중앙값 |', '|---|---:|---:|---|---:|']
 for g in GENS:
  s=result['by_role']['validation']['original']['all'][g];ci=result['validation_group_bootstrap']['AUROC_CI95'][g]
  lines.append(f"| {g} | {s['TP_A']} | {s['AUROC']:.4f} | {ci[0]:.3f}–{ci[1]:.3f} | {s['positive_logit_quantiles'][3]:.3f} |")
 lines+=['',f"정상 사진 logit 중앙값은 {np.median(matrix[:,0]):.3f}이다. AUROC는 점수 순위의 구분 능력이며 0.5는 무작위 순위 수준, 1은 이 표본에서 완전 분리이다. 실제 서비스 정확도나 보정된 확률이 아니다.",
 '', '## 임계값만 바꾸면 해결되는가', '', '| 생성기 | 현재 A 미탐률 | 설정용에서 정한 진단 기준의 검증 미탐률 | 검증 점수를 보고 고른 최선의 FPR≤5% 미탐률 | FNR≤10%를 위한 최소 오탐률 |', '|---|---:|---:|---:|---:|']
 for g in GENS:
  s=result['by_role']['validation']['original']['all'][g];f=result['setting_only_threshold']['validation_by_generator'][g];o=result['threshold_diagnostics']['validation'][g]
  lines.append(f"| {g} | {s['FNR_A']:.1%} | {f['FNR']:.1%} | {o['empirical_oracle_FPR5']['FNR']:.1%} | {o['empirical_oracle_FNR10']['FPR']:.1%} |")
 valrule=result['setting_only_threshold']['validation_by_generator']['FLUX.1-dev']
 lines+=['',f"진단 기준 logit > {fit['threshold_logit']:.6f}은 설정용 원본에서만 계산했다. 설정용 FPR {fit['FPR']:.1%}, 검증용 FPR {valrule['FPR']:.1%}이다. 이번 요청 후 정한 사후 분석 규칙이며 기존 A/B·선택 실패를 대체하지 않는다.",
 '', '검증 점수를 보고 고른 최선의 경계는 임계값 개선의 관찰 가능한 한계를 설명하는 용도이다. 출시 기준으로 채택하거나 독립 검증 성능으로 주장하지 않는다. 정상 40장에서는 오탐 한 장이 2.5%p이며 소표본 불확실성이 크다. 오탐·미탐 거래 관계는 보류 없는 이진 경계의 결과이다.',
 '', '## 데이터 출처별 원본 결과', '', '| 출처 | SD3 AUROC / 탐지 | FLUX dev AUROC / 탐지 | FLUX schnell AUROC / 탐지 |', '|---|---|---|---|']
 for ds in DATASETS:
  s=result['by_role']['validation']['original'][ds]
  lines.append(f"| {ds} | {s['SD3-medium']['AUROC']:.4f} / {s['SD3-medium']['TP_A']}/20 | {s['FLUX.1-dev']['AUROC']:.4f} / {s['FLUX.1-dev']['TP_A']}/20 | {s['FLUX.1-schnell']['AUROC']:.4f} / {s['FLUX.1-schnell']['TP_A']}/20 |")
 lines+=['', '각 출처의 실제 사진 20장을 음성 비교 대상으로 사용했다. 두 출처에서 모두 dev의 낮은 탐지가 반복되므로 한 출처만의 현상은 아니다. 출처 차이는 사진 내용·생성 설정·저장 이력이 함께 달라 인과적으로 분리되지 않았다.',
 '', '## 제외하거나 가능성을 낮춘 설명', '', '- 설정용과 검증용 모두 SD3 40/40, FLUX dev 4/40 탐지였다. 한쪽 분할에서만 나타난 현상은 아니다.',
 '- 설정용·검증용 각각 40개 원본 대응 묶음에서 SD3·FLUX dev·FLUX schnell의 가로·세로 크기가 정확히 같았다. 모든 원본의 짧은 변은 504 이상이므로 작은 입력의 반복 패딩이 원본 격차를 설명하지 않는다.',
 '- 400개 원본 파일의 해시·크기를 재검증했다. 모두 RGB PNG, ICC 프로필·EXIF 태그가 없다. 이는 제공된 파일에 대한 사실이며 생성 이후 저장·압축이 전혀 없었다는 보증은 아니다.',
 '- 공식 config의 resnet 정규화·RGB 변환·가중치·5영역 Wrapper·출력 logit 처리와 현재 어댑터를 확인했다. 코드 검토에서 불일치가 발견되지 않았다. 별도 공식 함수 재실행의 결과는 official_replay.json에 기록한다.',
 '- 같은 출처·장면 그룹·크기의 생성물끼리 비교했지만 정확히 같은 픽셀 내용은 아니다. 프롬프트·학습 데이터·추론 파라미터·시드의 독립 효과를 확정한 통제 실험은 아니다.',
 '', '## 가능한 배경 원인과 미확정 사항', '',
 'B-Free 공식 학습은 COCO 실제 사진과 Stable Diffusion 2.1 생성·재구성·인페인팅 자료를 사용한다. SD3도 SD2.1과 다른 구조이므로 브랜드 계열만으로 탐지 차이를 단정할 수 없다. 이번 점수 격차는 이 가중치가 생성기별 특징에 다르게 반응한다는 관찰이다.',
 'FLUX dev와 schnell은 서로 다른 증류 방법을 사용한다. 같은 FLUX 계열 안에서도 점수 차이가 크므로 단순히 rectified flow 전체를 탐지하지 못한다고 말할 수 없다. 증류·샘플링·재구성 과정이 다른 흔적을 만들었을 가능성은 있지만 이번 자료로 특정 단계의 인과관계를 입증하지 않았다.',
 'FLUX dev가 더 사실적이어서 실패했다거나 특정 주파수·VAE 흔적이 원인이라고 확정할 수 없다. 이를 밝히려면 생성 파라미터가 통제된 새 이미지, 복수 탐지기, 주파수·영역별 개입 실험이 필요하다.',
 '', '## 다음 검증에 반영할 사항', '',
 '서비스 모델 선정에서는 기존 기준 재조정만으로 해결된다고 가정하지 않는다. 별도 설정 자료에서 후보 탐지 모델을 비교하고, 현재 분석에 노출되지 않은 새 검증 자료에서 생성기별 저오탐 탐지율을 평가한다. 추가 학습을 하더라도 학습에서 제외한 생성기로 일반화 여부를 확인해야 한다.',
 '', '## 공식 자료', '', '- [B-Free](https://grip-unina.github.io/B-Free/)',
 '- [SD3 medium](https://huggingface.co/stabilityai/stable-diffusion-3-medium)',
 '- [FLUX dev](https://huggingface.co/black-forest-labs/FLUX.1-dev)',
 '- [FLUX schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell)',
 '', '## 재현 자료', '', '- scripts/diagnostics/analyze_bfree_generators.py',
 '- runs/20261004_bfree_diagnosis/analysis.json',
 '- runs/20261004_bfree_diagnosis/score_distribution_roc.png',
 '- runs/20261004_bfree_diagnosis/official_replay.json (별도 공식 함수 재실행)',
 '', f"그룹 부트스트랩 {REPS}회, seed {SEED}. 재표집은 출처별 20개 장면을 복원 추출하고 동일 장면의 실제·각 생성기 이미지를 함께 사용했다. 보호된 v0.1 코드·보고서와 기존 B-Free 예측 파일 해시는 유지되었다."]
 report=ROOT/'reports/BFREE_GENERATOR_DIAGNOSIS_20261004.md'
 if report.exists():raise FileExistsError(report)
 report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 assert all(sha(ROOT/p)==h for p,h in frozen.items())
 print(json.dumps({'report':str(report),'validation':result['by_role']['validation']['original']['all'],'thresholds':result['threshold_diagnostics']['validation'],'setting_only_threshold':result['setting_only_threshold'],'bootstrap':result['validation_group_bootstrap'],'paired':{k:{a:b for a,b in v.items() if a!='pairs'} for k,v in result['paired'].items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()