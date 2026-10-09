from pathlib import Path
p=Path.cwd()/"scripts/v02/write_report.py"
s=p.read_text(encoding="utf-8")
function='''def decision_text(e):
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
'''
s=s.replace("def main():",function+"\ndef main():",1)
s=s.replace('parts.append("## 실제 평가 구성','parts.append(decision_text(e))\n    parts.append("## 실제 평가 구성',1)
paragraph="장면 그룹을 자료별로 재추출한 고정시드2000회 부트스트랩의 조건부95%구간은validation_group_uncertainty.json에 기록했다. 같은 원본의 실제/생성4종 또는 실제/편집 쌍은 함께 재추출했다. 0건 관측에서 부트스트랩0~0이 나오더라도 미관측 오류 위험 상한은 아니다. 검증 음성40장이 독립 이항 관측이고 오탐0건이라고 가정해도 단측95%오탐률 상한은7.2%이므로 모집단 오탐률5%이하를 증명할 표본 규모는 아니다."
s=s.replace('parts.append("## 근거 파일과 공식 출처','parts.append('+repr(paragraph+'\n')+')\n    parts.append("## 근거 파일과 공식 출처',1)
compile(s,str(p),"exec")
p.write_text(s,encoding="utf-8")
print("Decision and uncertainty narrative added")
