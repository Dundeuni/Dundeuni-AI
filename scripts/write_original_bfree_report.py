# -*- coding: utf-8 -*-
"""Generate the B-Free original/robustness report from verified local artifacts."""
import json
from run_inference import ROOT, sha256

BASE = ROOT / "runs/20261002_bfree_raise"


def load(relative):
    return json.loads((BASE / relative).read_text(encoding="utf-8"))


def overall(summary, key):
    return [row for row in summary[key] if row["dataset"] == "all"]


def main():
    acquisition = load("raise_acquisition.json")
    review = load("scene_review.json")
    verification = load("bfree_verification.json")
    robustness = load("robustness/evaluation/summary.json")
    summaries = {split: load("bfree_" + split + "/evaluation/summary.json") for split in ("tune", "final")}
    environments = {split: load("bfree_" + split + "/environment.json") for split in ("tune", "final")}
    final_a = next(row for row in overall(summaries["final"], "policies") if row["policy"] == "A")
    final_b = next(row for row in overall(summaries["final"], "policies") if row["policy"] == "B")
    lines = ["# B-Free 원래 구성·변형 입력 검증 결과", "",
        "2026-10-02 현재 VS Code의 Windows 작업 폴더에서 실행했다. **사용자가 제공한 RAISE CSV의 공식 TIFF 링크로 실제 사진 40장을 확보하고, Synthbuster 생성 40장과 함께 B-Free 원래 80장 평가를 완료했다.** 원본 검증 이후 같은 입력의 변형 400장도 별도 후속 탐색으로 실행했다.", "",
        f"최종 확인용 AUROC는 **{final_a['auroc']:.4f}**이다. A 오탐/미탐은 **{final_a['false_positive']}/20·{final_a['false_negative']}/20**, B 오탐/미탐/보류는 **{final_b['false_positive']}/20·{final_b['false_negative']}/20·{final_b['abstain_positive']+final_b['abstain_negative']}/40**이다. 서비스 기준은 선택하지 않았다.", "",
        f"최종 확인용은 원본 장면 묶음 {verification['splits']['final']['distinct_scene_groups']}개·이미지 40장인 소규모 표본이다. 이 표본에서 오류가 없었다고 실제 서비스의 오류율도 0이라고 해석하지 않는다. 조정용에는 오류가 있었으며 아래에 함께 보고한다.", "",
        "## 1. 자료 확보와 이용 조건", "",
        "전달받은 `RAISE_1k.csv`는 실제 이미지가 아닌 1,000장의 메타데이터·NEF/TIFF 링크 목록이었다. 다운로드 폴더에서 선택 ID의 TIFF가 없음을 확인했다. [공식 가이드](https://loki.disi.unitn.it/RAISE/guide.html)의 안내에 따라 CSV의 TIFF 열에 있는 선택 이미지 40개만 확보했다.", "",
        f"다운로드는 **{acquisition['completed']}장·{acquisition['downloaded_bytes']:,}바이트**이며 파일별 HTTP 크기·TIFF 디코딩·SHA-256을 확인했다. 원본은 `data/raise_official_tiff/`에 보존했다. 새로운 개인정보 제출이나 이전에 거부된 신청 다운로드 엔드포인트 호출은 수행하지 않았다. 사용자가 제공한 공식 CSV로 개별 이미지 확보 경로를 확인했다.", "",
        "RAISE는 비상업적 연구·교육 및 논문 출처 표시 조건이다. 이번 로컬 평가에 사용하고 원자료를 외부에 업로드하지 않았다. 출처는 Dang-Nguyen, Pasquini, Conotter, Boato, *RAISE – A Raw Images Dataset for Digital Image Forensics*, ACM MMSys 2015이다. Synthbuster 이용 조건과 확보 기록은 기존 소스 문서·`bfree_synthbuster_acquisition.json`을 따른다.", "",
        f"공식 CSV SHA-256은 `{acquisition['metadata_sha256']}`이다. TIFF·PNG의 개별 해시는 확보/검수 기록에 보존했다. 로컬 해시는 실험 파일 고정 기록이며 배포기관의 서명 검증으로 표현하지 않는다.", "",
        "## 2. 원본 검수·분할·입력", "",
        "이전 보조 평가에서 본 RAISE ID 40개를 제외해 사전에 선택한 새 40개 ID를 사용했다. 생성 이미지는 9개 모델을 순환해 기존에 확보한 40개이다. 원본 RGB TIFF를 RGB PNG로 변환하고 저장 후 픽셀 일치를 확인했다. 원본 크기·RGB 값을 유지하며 임의 크롭·리사이즈·EXIF 방향 보정을 적용하지 않았다. RAW 현상은 수행하지 않았다.", "",
        f"실제 사진 40장의 썸네일 모음과 DCT pHash/RGB 축소 비교의 가까운 24쌍을 시각 검수했다. {len(set(review['group_by_scene'].values()))}개 원본 장면 묶음을 구성했으며 근접 장면은 같은 묶음으로 관리했다. 실제 사진·해당 ID의 생성 사진·변형 입력을 묶음 밖으로 분리하지 않았다. 고정된 묶음의 결정적 분할로 조정용과 최종 확인용 각각 실제 20장·생성 20장을 구성했다. 모델 점수를 보기 전에 분할했다.", "",
        "선택한 실제 사진 사이의 검수이며 전체 RAISE 1,000장·과거 평가 자료·모든 모델 사전학습 원자료에 대한 완전한 근접 중복 검사를 완료한 것은 아니다. 공식 전처리의 RGB 해석을 유지했다. 실제·생성 자료의 해상도·색공간·원본 처리 경로 차이가 남아 성능 편향 가능성을 함께 기록한다.", "",
        "## 3. 원래 80장 판정 결과", "",
        "A는 공식 참고 기준 `logit > 0`이며 B는 `sigmoid(logit)`의 0.40~0.60 포함 보류이다. 각 분할의 오탐 분모는 음성 20장, 미탐 분모는 양성 20장, 보류 분모는 전체 40장이다. 보류를 성공 판정으로 집계하지 않는다.", "",
        "| 분할 | 정상/요청 | AUROC | A 오탐/20 | A 미탐/20 | B 오탐/20 | B 미탐/20 | B 양성/음성 보류 | B 보류/40 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for split in ("tune", "final"):
        policies = {row["policy"]: row for row in overall(summaries[split], "policies")}
        a, b = policies["A"], policies["B"]
        lines.append(f"| {'조정용' if split=='tune' else '최종 확인용'} | {a['valid']}/{a['requests']} | {a['auroc']:.4f} | {a['false_positive']} | {a['false_negative']} | {b['false_positive']} | {b['false_negative']} | {b['abstain_positive']}/{b['abstain_negative']} | {b['abstain_positive']+b['abstain_negative']} |")
    lines += ["", "조정용 오류·보류 사례는 다음과 같다. 0은 뚜렷한 생성 신호 없음, 1은 생성 의심, 보류는 판별 어려움이다. 시각적 오류 원인을 추측하지 않는다.", "",
        "| 이미지 ID | 정답 | 원본 logit | 정규화 점수 | A | B |", "|---|---:|---:|---:|---:|---:|"]
    for case in verification["splits"]["tune"]["error_or_abstention_cases"]:
        decisions = case["decisions"]
        b_value = "보류" if decisions["B"] is None else str(decisions["B"])
        lines.append(f"| {case['image_id']} | {case['label']} | {case['logit']:.6f} | {case['normalized_score']:.6f} | {decisions['A']} | {b_value} |")
    lines += ["", "조정용 평가 후 A 주 기준·B 사전 정의 부 비교를 고정했다. 최종 점수 확인 후 정책을 다시 조정하지 않았다. 허용 오류·보류·지연 목표 미합의 상태이므로 A를 서비스 최적 정책으로 선정한 것은 아니다. B-Free는 생성 탐지이며 위치 지도를 반환하지 않는다.", "",
        "## 4. GPU 환경·시간", "",
        "Windows 11 Home 25H2·Ryzen 7 5800X·RAM 약 32GiB·GTX 1080 Ti 11264MiB·드라이버 582.66에서 모델을 단독·순차 실행했다. 기존 `.venv/bfree`의 Python 3.9.13·torch 2.0.1+cu118·torchvision 0.15.2+cu118을 사용했다. 기존 환경·드라이버 변경과 신규 설치는 없다.", "",
        "| 분할 | 모델 로딩 초 | 평균 초 | p95 초 | 첫 입력 제외 평균 초 | 최대 GPU 할당 MiB |", "|---|---:|---:|---:|---:|---:|"]
    for split in ("tune", "final"):
        op = overall(summaries[split], "operations")[0]
        lines.append(f"| {split} | {environments[split]['load_seconds']:.4f} | {op['inference_mean_seconds']:.4f} | {op['inference_p95_seconds']:.4f} | {op['after_first_mean_seconds']:.4f} | {op['peak_allocated_mib']:.1f} |")
    lines += ["", "시간은 입력 읽기·공식 전처리·GPU 처리·CPU 출력 변환을 포함하며 프로세스 전체 시간이나 서버 지연은 아니다. 공식 `Wrapper5crops (504)` 영역 처리를 유지했다.", "",
        "## 5. 원본 이후 통제된 변형 400장", "",
        "원본 80장마다 이전 TruFor 실험과 같은 5가지 조건을 적용했다. 독립 표본 400개나 새 최종 검증으로 주장하지 않는다. 실행 범위는 `exploratory`, 원본 분할은 `parent_split`으로 보존해 비교했다. 공식 모델 전처리·가중치·A/B 정책은 유지했다.", "",
        "JPEG 품질 75는 원본 크기·4:2:0이다. 50% 축소는 가로·세로 정수 절반·LANCZOS·PNG이다. 메신저 모사는 긴 변 최대 512픽셀·확대 없음·JPEG 품질 80이다. 화면은 720×1280에 사진을 640×1000 내부로 맞춰 배치하며 확대도 포함할 수 있다. 사진 크롭은 알려진 배치 좌표로 추출했다. 실제 앱·기기나 자동 사진 영역 검출은 미검증이다.", ""]
    names = {"jpeg_q75": "JPEG 품질 75", "half_png": "가로·세로 50% PNG", "messenger_proxy_512_q80": "메신저 저장 모사", "screen_720x1280": "합성 화면 전체", "screen_photo_crop": "캡처 속 사진 영역"}
    for split in ("final", "tune"):
        lines += ["### " + ("최종 원본에서 파생한 입력" if split=="final" else "조정용 원본에서 파생한 입력"), "",
            "| 조건 | AUROC | A 오탐/20 | A 미탐/20 | B 오탐/20 | B 미탐/20 | B 보류/40 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for variant, entries in robustness["variants"].items():
            a, b = entries[split]["policies"]["A"], entries[split]["policies"]["B"]
            lines.append(f"| {names[variant]} | {a['auroc']:.4f} | {a['false_positive']} | {a['false_negative']} | {b['false_positive']} | {b['false_negative']} | {b['abstain_positive']+b['abstain_negative']} |")
        lines.append("")
    lines += ["화면 전체 조건의 정답은 화면에 포함된 사진의 생성 여부이다. 실제 서비스의 전체 화면 유형 판별을 검증한 결과는 아니다.", "",
        "| 변형 조건 | 80장 평균 초 | p95 초 | 최대 GPU 할당 MiB |", "|---|---:|---:|---:|"]
    for variant, entries in robustness["variants"].items():
        op = entries["all_operations"]
        lines.append(f"| {names[variant]} | {op['mean_seconds']:.4f} | {op['p95_seconds']:.4f} | {op['peak_allocated_mib']:.1f} |")
    lines += ["",
        "## 6. 코드·원본 출력·검증", "",
        f"공식 커밋은 `{environments['final']['code_commit']}`이며 최종 가중치 SHA-256은 `{environments['final']['weights_sha256']}`이다. 목록·공식 코드·가중치·추론/정책/평가 코드 고정 기록은 `bfree_protocol.json`이다. 기존 TruFor 고정 파일은 변경하지 않았다.", "",
        "원본 기록은 `runs/20261002_bfree_raise/`이다. `raise_acquisition.json`은 TIFF 확보, `scene_inputs/`·`scene_similarity/`·`scene_review.json`은 원본 검수, `preparation/manifest.csv`는 확정 목록, `bfree_tune/`·`bfree_final/`은 환경·원본 JSONL·평가 결과이다. `bfree_verification.json`에서 80개 ID·정답·해시·묶음 누출·고정 조건과 독립 scikit-learn AUROC를 확인했다.", "",
        "`robustness/`는 파생 조건·목록·원본 400개 결과·분할별 지표·개별 판정 변화를 담는다. `tests.log`는 총 15개 테스트 통과 기록이다. 신규 CSV 검증은 외부 호스트·다른 ID의 링크를 네트워크 호출 전에 거부한다. 추론 실패는 각 결과의 `status`·`error`에 보존했으며 보류와 구분한다.", "",
        "## 7. 완료 범위와 남은 작업", "",
        "RAISE 확보 문제를 해결해 B-Free 원래 80장과 통제된 파생 입력 평가를 완료했다. TruFor 원래 80장·위치 평가·변형 400장과 두 모델 CPU 4장씩의 기존 검증 결과도 유지했다. 생성·변조 점수를 합산하거나 실제 사기 확률로 표현하지 않는다.", "",
        "서비스 오류·보류·지연 목표와 최종 임계값·입력 제한은 미확정이다. 실제 메신저 앱·기기 캡처, 전체 평가셋 CPU·동시 요청·배포 서버 측정은 남아 있다. 학습·파인튜닝·LLM API 호출·서비스 배포·Git push·외부 업로드는 수행하지 않았다.", ""]
    # All report values are read from verified artifacts; preserve existing reports.
    report = ROOT / "reports/BFREE_ORIGINAL_RESULTS_20261002.md"
    with report.open("x", encoding="utf-8", newline="\n") as target:
        target.write("\n".join(lines))
    print("Saved", report.name)


if __name__ == "__main__":
    main()
