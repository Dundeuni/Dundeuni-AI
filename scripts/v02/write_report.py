# -*- coding: utf-8 -*-
"""Create a Korean report and static scientific figures from completed frozen results."""
import os,json,collections,statistics,math
from pathlib import Path
from common import ROOT,RUN,CONDITIONS,sha256,save_json,timestamp
os.environ["MPLCONFIGDIR"]=str(RUN/"matplotlib")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
LABELS={"original":"원본","jpeg_q75":"JPEG q75","half_png":"가로·세로 1/2 PNG","messenger_proxy_512_q80":"긴 변 512 JPEG q80","screen_720x1280":"720×1280 화면 재현","screen_photo_crop":"화면의 사진 영역"}
SHORT=["Original","JPEG75","HalfPNG","Long512/JPEG80","Screen720x1280","Photo crop"]
NAMES={"bfree":"B-Free","trufor":"TruFor","mesorch":"Mesorch","mesorch_p":"Mesorch-P"}
def fmt(x,d=3):return "미산출" if x is None else f"{x:.{d}f}"
def pct(x):return "미산출" if x is None else f"{100*x:.1f}%"
def policy_row(model,condition,id,m):
    return [NAMES[model],LABELS[condition],id,f'{m["FP"]}/{m["negative"]}',pct(m["FPR"]),f'{m["FN"]}/{m["positive"]}',pct(m["FNR"]),
        f'{m["abstain_negative"]+m["abstain_positive"]}/{m["success"]}',pct(m["abstain_rate"]),pct(m["balanced_accuracy_with_abstentions_in_denominator"])]
def table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","|"+"|".join(["---"]*len(headers))+"|"]+["| "+" | ".join(map(str,r))+" |" for r in rows])+"\n"
def load_rows(model,role):
    p=RUN/"inference"/model/role/"predictions.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l]
def figures(e,out):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.grid":True,"grid.alpha":.25})
    x=np.arange(6);bf=e["models"]["bfree"];val=bf["roles"]["validation"]["by_condition"]
    policies=["A","B"]
    if bf["selected"] and bf["selected"]["id"] not in policies:policies.append(bf["selected"]["id"])
    fig,axes=plt.subplots(1,2,figsize=(13,4.5),layout="constrained")
    for p in policies:
        for ax,key in zip(axes,["FNR","abstain_rate"]):
            y=[100*val[c]["policies"][p][key] if val[c]["policies"][p][key] is not None else np.nan for c in CONDITIONS]
            ax.plot(x,y,marker="o",label=p)
            ax.set_xticks(x,SHORT,rotation=30,ha="right");ax.set_ylim(-1,100);ax.set_ylabel("Rate (%)");ax.legend()
    axes[0].set_title("False negative rate");axes[1].set_title("Abstention rate")
    axes[0].axhline(10,linestyle="--",color="grey",label="Target10%");axes[1].axhline(20,linestyle="--",color="grey")
    fig.suptitle("B-Free frozen validation: 200 images / 40 source groups per condition")
    fig.savefig(out/"bfree_validation.png",dpi=150);fig.savefig(out/"bfree_validation.svg");plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
    for model in ["trufor","mesorch","mesorch_p"]:
        val=e["models"][model]["roles"]["validation"]["by_condition"]
        y=[val[c]["localization"]["mean_positive_F1"] for c in CONDITIONS]
        ax.plot(x,y,marker="o",label=NAMES[model])
    ax.set_xticks(x,SHORT,rotation=25,ha="right");ax.set_ylim(0,1);ax.set_ylabel("Mean positive-image F1")
    ax.set_title("Localization validation: 40 forged images per condition\nOriginal coordinates; positive forgery >=0.5; no inversion");ax.legend()
    fig.savefig(out/"tampering_location_validation.png",dpi=150);fig.savefig(out/"tampering_location_validation.svg");plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.6),layout="constrained")
    labels=["COVERAGE(validation)","CocoGlide(validation)","Columbia(reference only)"];x=np.arange(3);width=.24
    for index,model in enumerate(["trufor","mesorch","mesorch_p"]):
        roles=e["models"][model]["roles"]
        values=[roles["validation"]["strata"]["original:"+ds]["localization"]["mean_positive_F1"] for ds in ["COVERAGE","CocoGlide"]]
        values.append(roles["comparison"]["by_condition"]["original"]["localization"]["mean_positive_F1"])
        bars=ax.bar(x+(index-1)*width,values,width,label=NAMES[model]);bars[-1].set_hatch("//")
    ax.set_xticks(x,labels);ax.set_ylim(0,1);ax.set_ylabel("Mean positive-image F1");ax.legend()
    ax.set_title("Original input localization; Columbia is not independent validation")
    fig.savefig(out/"tampering_original_datasets.png",dpi=150);fig.savefig(out/"tampering_original_datasets.svg");plt.close(fig)
def error_panels(out):
    from policy_selection import decision,candidates
    rows=load_rows("bfree","validation");policy=candidates("bfree")[0]
    missed=[r for r in rows if r["status"]=="success" and r["label"]==1 and decision(r,policy)==0]
    missed.sort(key=lambda r:r["raw_score"])
    examples=missed[:6]
    if examples:
        from PIL import Image
        fig,axes=plt.subplots(len(examples),2,figsize=(10,3*len(examples)),squeeze=False,layout="constrained")
        originals={r["parent_image_id"]:r for r in rows if r["condition"]=="original"}
        for i,row in enumerate(examples):
            parent=originals[row["parent_image_id"]]
            for j,item in enumerate([parent,row]):
                with Image.open(ROOT/item["path"]) as im:axes[i,j].imshow(im.convert("RGB"))
                axes[i,j].axis("off")
                axes[i,j].set_title(item["condition"]+" | score="+fmt(item["scores"]["official"],4))
            axes[i,0].set_ylabel(row.get("generator",""))
        fig.suptitle("Post-validation error illustrations: B-Free A false negatives\nUncalibrated score; no threshold or data changes")
        fig.savefig(out/"bfree_false_negative_examples.png",dpi=125);plt.close(fig)
    import PIL.Image
    indexed={model:{r["image_id"]:r for r in load_rows(model,"validation")} for model in ["trufor","mesorch","mesorch_p"]}
    valid=[r for r in indexed["trufor"].values() if r["condition"]=="original" and r["label"]==1 and r["status"]=="success"]
    valid=[r for r in valid if all(indexed[m][r["image_id"]]["status"]=="success" for m in indexed)]
    examples=sorted(valid,key=lambda r:r["localization"]["F1"])[:4]
    if examples:
        fig,axes=plt.subplots(len(examples),5,figsize=(14,2.8*len(examples)),squeeze=False,layout="constrained")
        for i,row in enumerate(examples):
            with PIL.Image.open(ROOT/row["path"]) as im:rgb=np.asarray(im.convert("RGB"))
            with PIL.Image.open(ROOT/row["mask_path"]) as im:truth=np.asarray(im)>0
            axes[i,0].imshow(rgb);axes[i,0].set_title(row["dataset"]+" original")
            axes[i,1].imshow(truth,cmap="gray",vmin=0,vmax=1);axes[i,1].set_title("Ground truth")
            for j,m in enumerate(indexed,2):
                pred=indexed[m][row["image_id"]]
                with np.load(ROOT/pred["maps_path"]) as saved:map=saved["map"]
                axes[i,j].imshow(map,cmap="magma",vmin=0,vmax=1)
                axes[i,j].set_title(NAMES[m]+" F1="+fmt(pred["localization"]["F1"]))
            for ax in axes[i]:ax.axis("off")
        fig.suptitle("Post-validation examples, selected by lowest TruFor original F1\nAll models shown on identical images; original coordinates, no map inversion")
        fig.savefig(out/"tampering_location_examples.png",dpi=140);plt.close(fig)
    save_json(RUN/"post_validation_error_examples.json",{"BFree_A_false_negative_count":len(missed),"BFree_illustrated_ids":[r["image_id"] for r in missed[:6]],
        "tampering_examples":[r["image_id"] for r in examples],"purpose":"Post-validation illustration only; frozen policies/data remain unchanged"})
def decision_text(e):
    bf=e["models"]["bfree"]
    lines=["## 결과 해석과 결정 근거", ""]
    if bf["selected"] is None:
        lines.append("**B-Free 판정 기준 변경은 보류한다.** 사전 후보 중 모든 입력 조건에서 목표를 만족하는 정책이 없어 이번 실험은 개선된 서비스 기준을 선정하지 못했다. 원본 결과만으로 압축·축소·화면 입력까지 지원한다고 판단하지 않는다.")
    else:
        id=bf["selected"]["id"]
        metrics=[bf["roles"]["validation"]["by_condition"][c]["policies"][id] for c in CONDITIONS]
        passed=all(m["FPR"] is not None and m["FPR"]<=.05 and m["FNR"]<=.1 and m["abstain_rate"]<=.2 and not m["failed"] for m in metrics)
        lines.append("B-Free는 설정용에서 "+id+"를 선택했다. 검증용 전체 입력 조건의 목표는 "+("만족했다" if passed else "만족하지 못했다")+". 이번 표본 결과이며 출시 승인이나 모집단 보장은 아니다.")
    base=e["models"]["trufor"]["roles"]["validation"]["by_condition"]
    comparisons=[]
    for model in ["mesorch","mesorch_p"]:
        loc=e["models"][model]["roles"]["validation"]["by_condition"]
        higher=sum(loc[c]["localization"]["mean_positive_F1"]>base[c]["localization"]["mean_positive_F1"] for c in CONDITIONS)
        comparisons.append(NAMES[model]+" 원본 평균F1 "+fmt(loc["original"]["localization"]["mean_positive_F1"])+", TruFor보다 높은 입력 조건 "+str(higher)+"/6")
    lines.append("TruFor 원본 평균F1은 "+fmt(base["original"]["localization"]["mean_positive_F1"])+"이다. "+"; ".join(comparisons)+"이다. 자료별·입력별 결과와 오탐/미탐을 함께 검토해야 한다. Mesorch 계열에는 공식 이미지 분류 점수가 없어 위치 개선만으로 기존 탐지 응답을 바로 교체할 근거가 되지 않는다.")
    return chr(10).join(lines)+chr(10)

def main():
    e=json.loads((RUN/"evaluation.json").read_text())
    out=ROOT/"reports/assets/followup_20261004";out.mkdir(parents=True,exist_ok=False)
    figures(e,out);error_panels(out)
    parts=["# 추가 Baseline 검증 결과 — 2026-10-04\n"]
    total=sum(e["models"][m]["roles"][r]["by_condition"][c]["requests"] for m in e["models"] for r in e["models"][m]["roles"] for c in CONDITIONS)
    failures=sum(e["models"][m]["roles"][r]["by_condition"][c]["failures"] for m in e["models"] for r in e["models"][m]["roles"] for c in CONDITIONS)
    parts.append(f"**B-Free 원본 400장, 변조 탐지 원본 240장에 원본·입력 변형 5종을 평가했다. 총 {total:,}개 모델·입력 요청 중 {total-failures:,}개 정상 처리, {failures}개 실패이다.** 작업 폴더는 프로젝트 루트이다. 기존 v0.1 결과·환경·모델 코어는 보존했다.\n")
    selectionrows=[]
    for model,m in e["models"].items():
        sel=m["selected"];cv=m["cv"]["folds"]
        selectionrows.append([NAMES[model],"선택 성공" if sel else "선택 실패",sel["id"] if sel else "없음",f'{sum(x["selection_status"]=="selected" for x in cv)}/5'])
    parts.append(table(["모델","설정 전체 후보 선택","선택 후보","CV에서 선택 성공한 분할"],selectionrows))
    parts.append("후보 선택 목표는 **각 입력 조건에서 오탐률 ≤5%·미탐률 ≤10%·보류율 ≤20%**이다. 목표를 만족하는 후보가 없으면 실패로 기록하고, 사전에 정한 비교 기준만 검증했다. 교차검증은 설정용 내 장면 그룹 5분할이며 별도 검증 결과가 아니다.\n")
    parts.append(decision_text(e))
    parts.append("## 실제 평가 구성\n")
    parts.append(table(["분야/자료","원본 수","설정용 원본","검증용 원본","참고 비교 원본"],[
      ["B-Free / SynthBuster+","200","100","100","0"],["B-Free / SynthCLIC","200","100","100","0"],
      ["변조 / COVERAGE","80","40","40","0"],["변조 / CocoGlide","80","40","40","0"],["변조 / Columbia","80","0","0","80"]]))
    parts.append("B-Free 각 자료는 실제 사진 40장과 동일 원본에 연결된 Imagen3·FLUX.1-dev·FLUX.1-schnell·SD3-medium 각40장이다. 원본 장면 기준으로 설정용200장/검증용200장을 분리했다. 설정용은 시각적으로 유사한 장면을 묶은 **34그룹**, 검증용은 **40그룹**이다. 변조의 설정용·검증용은 각각 **40원본 쌍 그룹/80장**이다. 같은 원본의 실제·생성·편집·변형은 같은 소속이다.\n")
    parts.append("**초안 변경:** Columbia의 원본·합성 출처를 보수적으로 연결하면 변조180장 모두가 기존 노출 장면과 같은 연결요소에 속한다. 이 때문에 Columbia80장은 설정이나 독립 검증에 포함하지 않았다. 전체240장은 유지하되 설정80/검증80/참고80으로 조정했다. 범위 선호 질문을 제시하고, 답변이 기록되지 않은 동안 과학적 독립성을 보존하는 기본 구성으로 진행했다. 이 조정을 사용자의 별도 승인으로 서술하지 않는다.\n")
    parts.append("COVERAGE는 기존20쌍과 원본/마스크 오류 자료를 제외했다. 유사한 컵케이크 장면83·96은 양쪽에 나누지 않고83을 같은 유형의80으로 교체했다. B-Free는 기존 원본ID를 제외하고, 이전 퍼레이드·시계·박물관·호수와 공유가 의심되는 검증 장면6개를 점수 확인 전에 교체했다. 설정용 유사 호수·고양이·튤립 장면은 같은 CV그룹에 묶었다. 이 검수는 모든 촬영 행사·장소 또는 모델 사전학습 데이터와의 독립성을 증명하지 않는다.\n")
    parts.append(table(["입력 조건","고정 처리"],[["원본","추가 압축·크기 변경 없음"],["JPEG q75","같은 크기, q75, subsampling2"],["가로·세로1/2 PNG","LANCZOS 축소, 정답 NEAREST"],["긴 변512 JPEG q80","확대하지 않음, q80, subsampling2"],["720×1280 화면 재현","고정 UI 및 사진 상자, 정답에 같은 기하 변환"],["화면 사진 영역","알려진 사진 상자를 잘라낸 입력, 자동 영역 검출 아님"]]))
    parts.append("입력 변형은 기존 v0.1 함수로 생성했다. 실제 메신저 저장·실기기 화면 캡처 측정은 아니며, 화면 사진 상자는 알고 있는 재현 위치를 사용했다. 정답은 이진값·크기·해시를 검증했고, 양성 정답이 사라진 변형은 없었다.\n")
    parts.append("## B-Free 검증 결과\n")
    b=e["models"]["bfree"];rows=[]
    for c in CONDITIONS:
        for id,m in b["roles"]["validation"]["by_condition"][c]["policies"].items():rows.append(policy_row("bfree",c,id,m))
    parts.append(table(["모델","입력","기준","오탐/음성","오탐률","미탐/양성","미탐률","보류/전체","보류율","균형 정확도"],rows))
    parts.append("A는 원래 logit>0이고, B는 sigmoid 점수<0.4 음성, 0.4~0.6 양끝 포함 보류, >0.6 양성이다. 이 점수는 사기 확률이 아니다. 각 조건의 분모는 실제40장·생성160장이다. 원본과 변형이나 네 생성기 결과를 독립 관측으로 합산하지 않는다.\n")
    parts.append("![B-Free 검증](assets/followup_20261004/bfree_validation.png)\n")
    rocrows=[]
    for c in CONDITIONS:
        s=b["roles"]["validation"]["by_condition"][c]["scores"][0]
        rocrows.append([LABELS[c],fmt(s["AUROC"],4),fmt(s["AP"],4),"80%"])
    parts.append(table(["입력","AUROC","AP","양성 비율"],rocrows))
    parts.append("AUROC/AP는 sigmoid 포화로 동점이 생기는 문제를 피하도록 원래 logit으로 계산했다. 생성기·자료별 전체 표와 후보 탐색 기록은 evaluation.json과 정책 고정 파일에 있다. 높은 AUROC/AP가 정한 기준의 미탐을 대신하지 않는다.\n")
    parts.append("## 변조 탐지 검증 결과\n")
    locationrows=[]
    for c in CONDITIONS:
        for model in ["trufor","mesorch","mesorch_p"]:
            summary=e["models"][model]["roles"]["validation"]["by_condition"][c];loc=summary["localization"]
            locationrows.append([NAMES[model],LABELS[c],loc["positive_evaluated"],fmt(loc["mean_positive_F1"]),fmt(loc["mean_positive_IoU"]),pct(loc["mean_negative_false_area"])])
    parts.append(table(["모델","입력","양성 위치 평가 수","평균 F1","평균 IoU","음성 오표시 면적"],locationrows))
    parts.append("위치 평가는 **원래 입력 좌표**, 공식 변조 양성 방향, 지도값≥0.5로 고정했고 정답을 이용해 방향을 뒤집지 않았다. F1/IoU는 양성 이미지별 값을 평균하고, 음성의 잘못 표시한 면적 비율은 따로 계산했다. Mesorch의512지도를 원래 좌표에 bilinear, align_corners=False로 복원했다. 이는 평가용 어댑터 처리이며 공식 CLI가 원래 좌표로 복원한다고 주장하지 않는다.\n")
    parts.append("![변조 위치 검증](assets/followup_20261004/tampering_location_validation.png)\n")
    datasetrows=[]
    for model in ["trufor","mesorch","mesorch_p"]:
        m=e["models"][model]
        for ds in ["COVERAGE","CocoGlide"]:
            loc=m["roles"]["validation"]["strata"]["original:"+ds]["localization"]
            datasetrows.append([NAMES[model],ds,"검증",loc["positive_evaluated"],fmt(loc["mean_positive_F1"]),fmt(loc["mean_positive_IoU"])])
        loc=m["roles"]["comparison"]["by_condition"]["original"]["localization"]
        datasetrows.append([NAMES[model],"Columbia","비독립 참고",loc["positive_evaluated"],fmt(loc["mean_positive_F1"]),fmt(loc["mean_positive_IoU"])])
    parts.append(table(["모델","자료","역할","양성 수","원본 평균 F1","원본 평균 IoU"],datasetrows))
    parts.append("![자료별 원본 위치 평가](assets/followup_20261004/tampering_original_datasets.png)\n")
    detectionrows=[]
    for model in ["trufor","mesorch","mesorch_p"]:
        m=e["models"][model]
        for c in CONDITIONS:
            policies=m["roles"]["validation"]["by_condition"][c]["policies"]
            for id,metric in policies.items():
                if model=="trufor" or id.endswith("_binary_0.5") or (m["selected"] and id==m["selected"]["id"]):
                    detectionrows.append(policy_row(model,c,id,metric))
    parts.append(table(["모델","입력","기준/집계","오탐/음성","오탐률","미탐/양성","미탐률","보류/전체","보류율","균형 정확도"],detectionrows))
    parts.append("TruFor A는 공식 sigmoid(det)≥0.5, B는 양끝 포함0.4~0.6보류이다. **Mesorch·Mesorch-P에는 공식 이미지 단위 분류 점수가 없다.** mean/max/top1은 공식512지도에서 만든 평가용 집계 점수이며, 이 표의 기본 기준은 >0.5이다. top1은 값이 큰 ceil(픽셀 수×1%)의 평균이다. 이를 공식 탐지 헤드나 보정된 확률로 해석하지 않는다.\n")
    parts.append("균형 정확도는 클래스별 정답률의 평균이다. 보류를 정답으로 세지 않고 각 실제 클래스 전체를 분모에 남겼다. 이 수치와 조건부 신뢰구간은 사전 후보 선택 규칙을 변경하지 않는다.\n")
    u=json.loads((RUN/"validation_group_uncertainty.json").read_text())
    intervalrows=[]
    for model in ["trufor","mesorch","mesorch_p"]:
        point=e["models"][model]["roles"]["validation"]["by_condition"]["original"]["localization"]["mean_positive_F1"]
        ci=u["models"][model]["original"]["localization"]["mean_positive_F1"]
        intervalrows.append([NAMES[model],fmt(point),fmt(ci["low"])+"~"+fmt(ci["high"])])
    parts.append("원본 위치 F1의 자료별 층화·원본 쌍 그룹 부트스트랩 95% 구간이다. 선택된 자료와 확인한 그룹 관계를 조건으로 한 불확실성이며 모든 서비스 입력을 대표하지 않는다.\n")
    parts.append(table(["모델","원본 평균 F1","조건부 95% 구간"],intervalrows))
    pairedrows=[]
    for model in ["mesorch","mesorch_p"]:
        ci=u["paired_location_F1_difference_vs_TruFor"][model]["original"]
        point=e["paired_location"]["validation:original"]["mean_F1_by_model"][model]-e["paired_location"]["validation:original"]["mean_F1_by_model"]["trufor"]
        pairedrows.append([NAMES[model]+" − TruFor",fmt(point),fmt(ci["low"])+"~"+fmt(ci["high"])])
    parts.append("같은 이미지·같은 원본 쌍 재추출에서 계산한 원본 F1 차이도 별도로 기록한다. 여러 조건/모델 비교에 대한 다중검정 보정 구간은 아니며, 구간이 0을 포함하면 양의 평균 차이가 안정적이라는 증거가 약하다.\n")
    parts.append(table(["짝지은 비교","원본 평균 F1 차이","조건부 95% 구간"],pairedrows))
    parts.append("## 실행 시간·메모리와 구현 검증\n")
    resource=[]
    for model in ["bfree","trufor","mesorch","mesorch_p"]:
        for c in ["original","screen_720x1280"]:
            m=e["models"][model]["roles"]["validation"]["by_condition"][c]
            resource.append([NAMES[model],LABELS[c],m["success"],m["failures"],fmt(m["latency_p50"]),fmt(m["latency_p95"]),fmt(m["peak_gpu_GiB"],2)])
    parts.append(table(["모델","입력","정상","실패","p50 초","p95 초","최대 GPU 할당 GiB"],resource))
    parts.append("GTX1080Ti11GB에서 배치1·모델별 순차 실행했다. 시간은 동기화한 입력 전처리·전송·모델 추론·지도 복원/집계를 포함하고 모델 초기 로딩, 지도 파일 저장, 정답 지표 계산은 제외한다. GPU값은 PyTorch 최대 할당량으로 전체 드라이버·예약 메모리와 다르다. p95는 이번 고정 장비의 표본 측정이며 서비스 지연 보장이 아니다.\n")
    parts.append("- 기존 B-Free/TruFor 환경은 수정하지 않았고, 데이터/그래프 환경과 Mesorch 환경을 분리했다.\n- Mesorch 공식 소스 커밋은33454cb6d595267033ce1109b62ad373110678db이며 각 Git blob을 검증했다. 전체 모델의 실제 클래스는MesorchFull이다.\n- Mesorch는 체크포인트 엄격 로딩, Mesorch-P는 공식 코드가 제거한convnext.head와stages.3잔여 가중치만 허용했다. 사용되는 가중치 누락은 없고 공식 소스를 편집하지 않았다.\n- 공식 IMDLBenCo0.1.45 resize/Normalize/Crop/ToTensorV2를 사용했다. 무관한 모델·시각화 자동 import를 건너뛰는 어댑터를 기록했다.\n- Mesorch README 권장Python3.10과 달리 기존 호환Python3.9.13·torch2.0.1+cu118·timm1.0.12를 사용했다. 별도 합성 입력에서 동작·좌표 복원·정답 대신0/1더미 마스크를 넣었을 때 예측 동일성을 검증했다. 실제 정답은 모델 호출 뒤 지표 계산에만 썼다.\n- 정책 경계·후보 선택 실패·입력 조건 누락/추론 실패·검증 데이터의 선택 차단·장면 그룹CV분리·위치 지표/좌표 검사의6개 단위 검사가 통과했다.\n")
    parts.append("## 수행하지 않은 범위\n")
    parts.append("**FakeShield는 실행 가능성 사전 점검만 수행했다.** 공식 DTE-FDM 텐서 크기만27,308,693,504바이트로11GB GPU의 전체 GPU 적재 범위를 넘는다. 실제 모델 추론이나 OOM실험을 수행했다고 기록하지 않는다. 양자화·CPU offload·해상도 변경·유료GPU·외부 업로드는 적용하지 않았다. 따라서 FakeShield 설명 출력, 2인 검토에 의한 설명 정확성·이해도 평가는 미수행이다. 실기기/메신저 실제 캡처도 미수행이며 이번5종은 입력 재현이다.\n")
    parts.append("## 오류 사례와 해석 범위\n")
    if (out/"bfree_false_negative_examples.png").exists():parts.append("![B-Free 미탐 사례](assets/followup_20261004/bfree_false_negative_examples.png)\n")
    if (out/"tampering_location_examples.png").exists():parts.append("![변조 지도 사례](assets/followup_20261004/tampering_location_examples.png)\n")
    parts.append("오류 그림은 검증 완료 뒤 고정된 기준으로 골라 보여주는 사후 설명 자료이다. 이 그림을 보고 기준·모델·입력을 다시 조정하지 않았다. 검증 표본을 좋은 결과가 나올 때까지 반복 평가하거나 Columbia 참고 결과를 독립 검증으로 합치지 않았다.\n")
    parts.append("오탐/미탐의 분모는 정상 추론된 음성/양성 전체이며 보류를 정답으로 세지 않는다. 클래스별 보류와 (미탐+양성보류)/양성은JSON에 별도 기록한다. 같은 사진의 생성기·변형은 상관되어 있다. 음성40장 또는 자료별양성20장 같은 작은 표본과CV변동은 모집단 오류를 보장하지 않으며, 0건 오류도 무오류 보장이 아니다. 사전학습 자료 중복과 숨은 행사·장소 중복은 확인하지 못한 제한이다.\n")
    parts.append('장면 그룹을 자료별로 재추출한 고정시드2000회 부트스트랩의 조건부95%구간은validation_group_uncertainty.json에 기록했다. 같은 원본의 실제/생성4종 또는 실제/편집 쌍은 함께 재추출했다. 0건 관측에서 부트스트랩0~0이 나오더라도 미관측 오류 위험 상한은 아니다. 검증 음성40장이 독립 이항 관측이고 오탐0건이라고 가정해도 단측95%오탐률 상한은7.2%이므로 모집단 오탐률5%이하를 증명할 표본 규모는 아니다.\n')
    parts.append("## 근거 파일과 공식 출처\n")
    parts.append("실행·목록·정책·평가는 [runs/20261004_followup](../runs/20261004_followup)에 있다. 핵심 파일은approved_protocol.json,scope_adjustment.json,bfree_manifest.json,tampering_manifest.json,각 모델_policy_freeze.json,evaluation.json,source_probe/및inference/이다. 고정해시, 모든 후보·CV 결과, 원본 점수·지도·클래스/생성기/자료/마스크 면적별표, 개별 시간·실패는 여기서 확인한다. 부분Parquet의 전체LFS해시를 검증했다고 주장하지 않으며, 공식 리비전·행 위치·받은 개별 원본 바이트의SHA256을 기록했다. CocoGlide는ZIP CRC를 검증하고 원본별라이선스 목록을 보존했다.\n")
    parts.append("- [B-Free 공식 저장소](https://github.com/grip-unina/B-Free)\n- [TruFor 공식 저장소](https://github.com/grip-unina/TruFor)\n- [Mesorch 공식 저장소](https://github.com/scu-zjz/Mesorch)\n- [SynthBuster+ 공식 데이터 카드](https://huggingface.co/datasets/marco-willi/synthbuster-plus)\n- [SynthCLIC 공식 데이터 카드](https://huggingface.co/datasets/marco-willi/synthclic)\n- [COVERAGE 공식 저장소](https://github.com/wenbihan/coverage)\n- [CocoGlide 공식 ZIP](https://www.grip.unina.it/download/prog/TruFor/CocoGlide.zip)\n- [FakeShield 공식 가중치 저장소](https://huggingface.co/zhipeixu/fakeshield-v1-22b)\n")
    path=ROOT/"reports/FOLLOWUP_BASELINE_RESULTS_20261004.md"
    with path.open("x",encoding="utf-8") as f:f.write("\n".join(parts))
    save_json(RUN/"report_artifacts.json",{"report_path":str(path.relative_to(ROOT)),"report_sha256":sha256(path),"created_at_utc":timestamp(),
       "artifacts":{str(p.relative_to(ROOT)):sha256(p) for p in out.glob("*") if p.is_file()}})
    print("Written",path,flush=True)
if __name__=="__main__":main()
