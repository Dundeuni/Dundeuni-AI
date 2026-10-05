# 팀원용 Baseline 실험 재현 가이드

작성일: 2026-10-04
대상: 든든이 AI 파트 팀원 / Claude Code·Codex로 자기 컴퓨터에서 실행
주요 범위: 완료된 v0.2 실험 재현 / 부록: v0.1 최종 확인 재실행

> 같은 실험을 재현하려면 **같은 코드·가중치·입력 파일·정답·장면 그룹·분할·판정 후보**를 사용해야 한다. 같은 데이터셋에서 같은 수의 사진을 새로 뽑는 것은 별도 실험이다. Claude나 Codex는 준비와 실행을 돕는 도구이며 탐지 모델을 대신하지 않는다.

## 1. 팀원에게 전달할 것

저장소 handoff/에 문서와 참조 폴더가 있다. 별도 ZIP은 필요하지 않다. 이미지·마스크·공식 코드·가중치는 별도로 준비한다.

이 문서와 함께 아래 세 묶음을 전달한다.

| 묶음 | 내용 | 전달 방식 |
|---|---|---|
| 코드·문서 | scripts/, requirements/, tests/, 루트 설명 문서, reports/, handoff/ | 팀 Git 저장소 또는 검수한 코드 묶음 |
| 재현 참조 자료 | 이 문서 옆의 team-reproduction-reference-20261004/ 전체 | 코드와 함께 전달한다. 고정 목록·정책·해시·환경 스냅샷을 포함한다. |
| 실제 실행 자산 | 목록의 이미지·정답 마스크, 공식 소스, 공식 가중치 | 이용 조건을 확인한 팀 자료 전달 또는 같은 공식 리비전에서 확보한다. |

**현재 상태:** 참조 자료를 추출했지만 새 컴퓨터에서 실행까지 검증한 배포 패키지는 아니다. 현재 .gitignore는 data/, runs/, third_party/, .venv/, 가중치를 제외한다. 따라서 일반적인 코드 clone만으로는 실험할 수 없다. 사용할 작업 브랜치 또는 머지된 버전을 checkout한다.

이미지·마스크·가중치는 참조 폴더에 포함하지 않았다. 일부 데이터는 재배포·상업 이용 제한이 있으므로 Public GitHub에 그대로 올리지 않는다. 공개 참조 목록에는 개인 절대 경로가 없는지 검사했다. 과거 승인·완료 기록은 새 실행의 승인·완료 증거가 아니다.

### 참조 폴더 구성

~~~text
team-reproduction-reference-20261004/
├─ README.json                     # 환경·필요한 자산 용량 요약
├─ required_data_files.json        # 실제 필요한 입력 경로·SHA-256·바이트
├─ required_v01_data_files.json    # v0.1 원본·파생본·CPU probe 입력 목록
├─ model_reference.json            # 모델 가중치 경로·SHA-256·코드 리비전
├─ code_sha256.json                # 실행 코드·동결된 공식 소스 해시
├─ check_inputs.py                 # 읽기 전용 사전 점검
├─ inventory.json                  # 참조 묶음 파일 해시
├─ environment/
│  ├─ bfree-installed.txt
│  ├─ trufor-installed.txt
│  ├─ mesorch-installed.txt
│  └─ v02-data-installed.txt
└─ reference/experiments/
   ├─ 20261001_baseline/            # B-Free·TruFor 공식 출처
   ├─ 20261001_original/            # v0.1 TruFor 목록·고정 정책
   ├─ 20261002_bfree_raise/         # v0.1 B-Free 목록·고정 정책
   ├─ 20261004_followup/            # v0.2 목록·정책·출처·과거 비교 결과
   ├─ 20261001_robustness/          # v0.1 변조 탐지 파생 조건·CPU 목록
   └─ 20261002_bfree_raise/robustness/ # v0.1 생성 탐지 파생 조건 목록

~~~

공개 보고서는 reports/에 있다. 집계 그래프를 포함하고 사진이 들어간 오류 예시 그림은 제외했다. reference/input-lists/manifests/official_demos.csv에는 v0.1 B-Free CPU 확인에 사용한 공식 예제 목록이 있다.

reference/의 정책과 결과는 **원래 실험의 비교 자료**이다. 이를 새 실행의 출력 폴더에 통째로 복사하지 않는다. 복사한 결과를 새로 실행한 결과라고 보고하지 않는다.

## 2. v0.2에서 재현할 실험

새 학습이나 파인튜닝 없이 공개된 완성 가중치로 추론한다. 생성 탐지와 변조 탐지는 별도 문제이며 점수를 합쳐 사기 확률로 표현하지 않는다.

| 분야 | 모델 | 원본 | 설정용 | 독립 검증용 | 참고 비교용 |
|---|---|---:|---:|---:|---:|
| AI 생성 탐지 | B-Free | 실제 80 + 생성 320 = 400장 | 200장 | 200장 | 없음 |
| 변조 탐지 | TruFor·Mesorch·Mesorch-P 각각 | 정상 120 + 변조 120 = 240장 | 80장 | 80장 | Columbia 80장 |

B-Free는 SynthBuster+ 200장과 SynthCLIC 200장을 사용한다. 실제 사진 80장은 **SynthBuster+의 RAISE 기반 40장 + SynthCLIC의 CLIC2020 기반 40장**이다. 생성 이미지는 Imagen 3·FLUX.1-dev·FLUX.1-schnell·SD3-medium 각각 80장이다. 설정용·검증용은 각각 실제 40장 + 생성 160장이다.

변조 데이터는 COVERAGE·CocoGlide·Columbia 각 80장이다. COVERAGE와 CocoGlide를 설정용·검증용으로 나누며 Columbia는 v0.1 노출 장면과 연결되어 **참고 비교로만 사용**한다. 옛 계획의 변조 설정용 120장 / 검증용 120장을 그대로 적용하지 않는다. 실제 범위는 scope_adjustment.json에 기록되어 있다.

모든 원본에 아래 6개 조건을 적용한다.

| 코드 조건 | 내용 |
|---|---|
| original | 확보·준비한 원본 입력이다. 공식 모델 전처리는 그대로 수행한다. |
| jpeg_q75 | JPEG 품질 75로 재압축한다. |
| half_png | 가로·세로를 절반으로 줄여 PNG로 저장한다. |
| messenger_proxy_512_q80 | 긴 변 최대 512픽셀과 JPEG 품질 80을 적용한다. |
| screen_720x1280 | 720×1280 화면과 주변 UI를 코드로 재현한다. |
| screen_photo_crop | 재현 화면의 알려진 사진 영역을 추출한다. |

실제 메신저·실기기 캡처 실험이 아니다. 사진 영역은 알려진 좌표로 추출하며 자동 영역 탐지 성능을 평가한 것도 아니다. 변조 마스크에는 같은 기하 변환을 적용한다.

전체 요청은 B-Free 2,400건 + 변조 모델 3종 × 1,440건 = **6,720건**이다. 변조 지도는 4,320개이다. 파생본은 독립적인 새 사진으로 세지 않는다.

### 고정해야 할 평가 규칙

- 시드: 20261004이다. 같은 장면 그룹·원본·파생본을 같은 분할에 둔다.
- 기준 선택에는 설정용만 사용한다. 설정용 장면 그룹 5분할 교차검증을 수행한다.
- 모든 모델의 기준을 고정한 뒤 독립 검증용 추론을 시작한다.
- 각 6개 조건 모두에서 오탐률 ≤5%, 미탐률 ≤10%, 보류율 ≤20%를 동시에 만족해야 후보가 선택된다.
- 후보가 없으면 selection_failed로 남긴다. 검증 결과를 보고 목표를 낮추거나 새 후보를 추가하지 않는다.
- 원래 결과를 이미 알고 하는 재현은 실행·계산 검증이다. 이를 새 미공개 자료의 독립 검증이라고 주장하지 않는다.

B-Free A 기준은 raw logit >0, TruFor A 기준은 공식 전체 이미지 점수 ≥0.5이다. B 기준은 점수 <0.4이면 음성, >0.6이면 양성, **0.4~0.6 경계 포함이면 보류**이다. 추가 후보는 이진 경계 0.3·0.4·0.5·0.6·0.7과 하한 0.2·0.3·0.4 / 상한 0.6·0.7·0.8의 보류 구간이다. 정확한 비교 연산은 scripts/v02/policy_selection.py를 따른다.

Mesorch 계열에는 공식 전체 이미지 판정 점수가 없다. 지도 평균·최댓값·상위 1% 평균을 각각 평가하며 임의 집계를 공식 AI 확률로 표현하지 않는다. 위치 지도 이진화는 ≥0.5이다. B-Free AUROC는 sigmoid 포화로 순서가 손실되지 않도록 raw logit으로 계산한다.

## 3. 컴퓨터와 Python 환경

원래 실행은 Windows / Python **3.9.13 64비트** / GTX 1080 Ti 11GB / 시스템 메모리 32GB에서 수행했다. 11GB는 검증한 장비 용량이며 모든 모델의 엄밀한 최소 요구량을 측정한 값은 아니다.

현재 v0.2 실행기는 Windows의 Scripts/python.exe와 cuda:0을 사용한다. NVIDIA CUDA GPU가 필요하다. macOS·Linux·CPU 실행은 환경·경로 또는 실행기 수정이 필요한 별도 이식 작업이다. 특히 v0.2에는 --device cpu 옵션이 없다.

| 격리 환경 | 주요 고정 버전 |
|---|---|
| .venv/bfree | torch 2.0.1+cu118, torchvision 0.15.2+cu118, timm 1.0.12, numpy 1.24.4, Pillow 10.4.0 |
| .venv/trufor | torch 1.11.0+cu113, torchvision 0.12.0+cu113, timm 0.5.4, numpy 1.23.5, Pillow 9.5.0 |
| .venv/mesorch | B-Free와 같은 torch 계열 + IMDLBenCo 0.1.45, albumentations 1.3.0, opencv-python-headless 4.8.1.78, scikit-image 0.22.0, rich 13.9.4 |
| .venv/v02-data | numpy 1.24.4, Pillow 10.4.0, scipy 1.13.1, scikit-learn 1.3.2, pyarrow 17.0.0, matplotlib 3.7.5 |

전체 설치 버전은 참조 폴더의 environment/에서 확인한다. 이는 **설치 목록 스냅샷**이며 wheel 해시까지 고정한 완전한 설치 lock 파일은 아니다. torch CUDA 빌드는 일반 PyPI 설치와 구분하여 해당 공식 배포처에서 확보한다. requirements/*.txt에는 torch가 별도로 설치된다는 전제가 있다.

기존 .venv를 다른 컴퓨터에 복사해서 사용하지 않는다. 팀원 컴퓨터에서 네 환경을 새로 만든다. 아래 예시는 Python 위치 확인 후 환경을 만드는 단계만 수행한다. 의존성 설치와 실행 자산 확보까지 자동 완료하는 명령은 아니다.

~~~powershell
# 실제 설치한 Python 3.9 64비트 경로로 바꾼다.
$python39 = 'C:\YOUR_PYTHON39\python.exe'
& $python39 -m venv .venv/bfree
& $python39 -m venv .venv/trufor
& $python39 -m venv .venv/mesorch
& $python39 -m venv .venv/v02-data
~~~

에이전트는 environment/, requirements/, scripts/v02/mesorch_adapter.py, scripts/v02/install_mesorch.py를 함께 보고 설치한다. Mesorch 설치 보조 스크립트는 기존 환경과 source_probe/IMDLBenCo-0.1.45-py3-none-any.whl이 이미 있다는 전제여서 새 PC에서 무조건 실행하면 안 된다. 같은 버전의 공식 배포 wheel을 확보하거나 설치 명령을 새 작업 기록으로 작성한다.

Mesorch 공식 안내의 Python 권장은 3.10이지만 이번 실행은 3.9.13에서 확인했다. 최신 GPU가 과거 torch 빌드를 지원하지 않으면 억지로 같은 환경을 강요하지 않는다. 대체 환경 버전과 변경 이유를 기록하고 **환경을 변경한 재현**으로 구분한다. 드라이버·기존 Python을 무단 변경하지 않는다.

각 GPU 환경에서 아래와 같이 확인한다. 환경 이름을 바꾸어 세 번 실행한다.

~~~powershell
& '.venv/bfree/Scripts/python.exe' -c 'import torch; print(torch.__version__, torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CUDA unavailable")'
~~~

GPU 메모리 여유를 확보하고 모델은 한 번에 하나씩 실행한다. 정밀도는 float32, batch size는 1이다. mixed precision·양자화·임의 리사이즈를 자동 적용하지 않는다. 장비별 실행 시간은 원래 장비와 다르므로 성능 지표와 실행 시간을 분리해 비교한다.

필요한 입력과 가중치의 실제 바이트 합계는 README.json에 있다. 공식 소스·네 Python 환경·추론 지도·다운로드 임시 파일을 위한 추가 공간도 필요하다. 데이터셋 전체를 무조건 다운로드할 필요는 없다.

## 4. 공식 코드와 가중치 확보

프로젝트 루트 아래의 다음 경로를 유지한다.

| 모델 | 공식 소스 리비전 | 최종 가중치 상대 경로 |
|---|---|---|
| B-Free | c6a9f898782fb466b29af01f21960b67415afb0e | third_party/B-Free/code/weights/BFREE_dino2reg4/model_epoch_best.pth |
| TruFor | ae54475df6f41a491d7615100feb19263dec13f7 | third_party/TruFor/TruFor_train_test/pretrained_models/weights/trufor.pth.tar |
| Mesorch·Mesorch-P | 33454cb6d595267033ce1109b62ad373110678db | third_party/Mesorch/weights/mesorch-98.pth / mesorch_p-118.pth |

- [B-Free 공식 저장소](https://github.com/grip-unina/B-Free)와 [공식 가중치 ZIP](https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip)을 사용한다. 함께 제공되는 config.yaml도 필요하다.
- [TruFor 공식 저장소](https://github.com/grip-unina/TruFor)와 [공식 가중치 ZIP](https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip)을 사용한다.
- [Mesorch 공식 저장소](https://github.com/scu-zjz/Mesorch)의 최종 두 가중치를 사용한다. ImageNet 사전학습 가중치만으로 대체하지 않는다.

최신 main을 받아 그대로 실행하지 않는다. 해당 리비전을 checkout하고 model_reference.json의 SHA-256과 비교한다. 링크가 바뀌면 공식 안내를 확인하며 다른 파일을 같은 파일명으로 저장해 통과시키지 않는다.

Git의 줄바꿈 변환도 코드 해시를 바꿀 수 있다. 원본 코드 바이트를 보존한다. 공식 소스에 파일을 추가하거나 전처리를 수정하면 새 실행의 코드 동결 기록에도 변화가 생기므로 차이를 기록한다.

B-Free의 공식 크롭·정규화, TruFor의 공식 RGB 처리·지도 방향·det sigmoid, Mesorch의 공식 512×512 입력 변환과 지도 좌표 복원은 현재 로더를 따른다. Mesorch-P의 일부 사용하지 않는 키 허용을 모든 가중치 불일치를 무시하는 strict=False로 확대하지 않는다. 정답 마스크는 추론 입력에 사용하지 않는다.

## 5. 동일한 데이터 확보

### 가장 쉬운 방법: 기존 선정 자산을 그대로 준비한다

실험 담당자가 required_data_files.json에 적힌 **이미지·마스크 파일만** 이용 조건에 맞는 방식으로 제공한다. 수신자는 상대 경로를 유지하여 프로젝트 루트 아래에 배치한다. 모델 가중치와 공식 소스는 별도이다.

전체 runs/나 .venv/를 복사할 필요는 없다. v0.2 사전 점검과 추론은 manifest의 path, mask_path로 지정된 준비 파일을 사용한다. source_path 등의 항목은 출처 확인·다시 준비하는 데 필요한 기록이다.

### 공식 배포처에서 다시 받는 경우

| 자료 | 사용 목적 | 출처 |
|---|---|---|
| SynthBuster+ | 실제 RAISE 기반 사진·4개 생성기 이미지 | [데이터 카드](https://huggingface.co/datasets/marco-willi/synthbuster-plus) |
| SynthCLIC | 실제 CLIC2020 기반 사진·4개 생성기 이미지 | [데이터 카드](https://huggingface.co/datasets/marco-willi/synthclic) |
| COVERAGE | 복사·붙여넣기 변조와 정답 마스크 | [공식 저장소](https://github.com/wenbihan/coverage) |
| CocoGlide | COCO 기반 국소 생성 편집과 정답 마스크 | [공식 ZIP](https://www.grip.unina.it/download/prog/TruFor/CocoGlide.zip) |
| Columbia | 합성 변조·참고 비교 | [공식 안내](https://www.ee.columbia.edu/ln/dvmm/downloads/authsplcuncmp/) |

manifest와 출처 JSON의 리비전·파일·행 위치·선정 ID를 따라 같은 파일을 확보한다. 같은 수량만 맞추거나 무작위로 재선정하지 않는다. COVERAGE의 변조 마스크와 일반 객체 마스크를 혼동하지 않는다.

bfree_images_provenance_v3.json은 실제 최종 확보 기록이다. _v2, _pending, 초기 선정 초안으로 되돌리지 않는다. 시각 검수에 따른 그룹·fold 조정은 bfree_source_review_confirmed.json을 따른다.

변환이 필요하면 scripts/v02/build_inputs.py와 scripts/build_robustness_data.py를 읽고 참조 manifest의 파일 SHA-256에 맞는 결과를 확보한다. 준비 스크립트는 검수 JSON과 원본 파일이 이미 있다는 전제이며 기존 파생본·manifest 덮어쓰기를 거부한다. 공식 재확보부터 실행까지의 범용 자동 다운로드 설치기는 아직 없다.

복원 파일의 해시가 다르면 데이터셋 업데이트, 인코딩, Pillow 버전, 마스크 변환, 잘못된 선정 목록을 조사한다. **새 해시로 기존 manifest를 고쳐 통과시키지 않는다.** 같은 픽셀이라도 파일 바이트가 다른 경우 원인을 기록하고 엄밀한 동일 입력 재현과 구분한다.

v0.1을 재현하려면 RAISE 공식 TIFF 40장과 당시 Synthbuster 40장 등 별도 목록을 따른다. v0.2의 실제 사진이 전부 별도 다운로드한 RAISE TIFF라는 뜻은 아니다.

## 6. 새 실행 폴더 준비

팀원은 **새 작업 폴더**를 사용한다. 예: C:\work\Dundeuni-AI-replay이다. 담당자의 D 드라이브 경로를 그대로 만들 필요는 없다. 프로젝트 루트를 기준으로 실행한다.

현재 scripts/v02/common.py의 출력 경로는 runs/20261004_followup으로 고정되어 있고 run_suite.py에 출력 경로 옵션은 없다. 여러 재현 실행을 같은 폴더에 겹치지 않는다. 새 결과와 기존 결과를 모두 보존하려면 작업 폴더를 따로 둔다.

새 작업 폴더의 runs/20261004_followup/에는 시작 전에 **아래 네 파일만** 참조 자료에서 바이트 그대로 복사한다.

~~~text
approved_protocol.json
scope_adjustment.json
bfree_manifest.json
tampering_manifest.json
~~~

PowerShell 예시는 다음과 같다. 이미 존재하는 출력 폴더를 덮어쓰지 않는다.

~~~powershell
# 프로젝트 루트에서 실행한다.
$ref = '.\handoff\team-reproduction-reference-20261004\reference\experiments\20261004_followup'
$run = '.\runs\20261004_followup'
if (Test-Path -LiteralPath $run) { throw '새 작업 폴더를 사용한다. 기존 결과를 지우지 않는다.' }
New-Item -ItemType Directory -Path $run | Out-Null
foreach ($name in @('approved_protocol.json','scope_adjustment.json','bfree_manifest.json','tampering_manifest.json')) {
    Copy-Item -LiteralPath (Join-Path $ref $name) -Destination (Join-Path $run $name)
}
~~~

이 네 파일은 원래 구성의 역사적 기록으로 재사용한다. 새 팀원이 과거 승인자가 되었다는 의미는 아니다. 새 PC에서 설치·실행할 범위는 팀원의 직접 요청과 현재 권한을 따른다.

원래 *_policy_freeze.json, inference/, completion.json, evaluation.json, suite_state.json은 활성 실행 폴더에 복사하지 않는다. run_suite.py는 완료 표시가 있으면 추론을 건너뛰기 때문이다. 새 기준 동결은 새 설정용 점수로 생성한다.

코드 묶음에 기존 reports/FOLLOWUP_BASELINE_RESULTS_20261004.md가 있으면 자동 보고서 생성과 충돌한다. **재현용 작업 폴더에서만** 기존 보고서를 비교 자료로 보존하거나 새 출력 경로를 구분한다. 담당자의 원본 작업 폴더를 이동·삭제하지 않는다.

## 7. 입력 확인 → 전체 실행 → 결과 확인

### 7.1 실행 전 읽기 전용 확인

코드·공식 소스·가중치·이미지·마스크·네 초기 JSON이 배치된 후 실행한다.

~~~powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& '.venv/v02-data/Scripts/python.exe' -X utf8 'handoff/team-reproduction-reference-20261004/check_inputs.py'
~~~

고정 코드·가중치·입력의 SHA-256, 원본/파생본의 역할, 그룹 분리와 설정 fold, Columbia 참고 전용 처리를 확인한다. GPU 호환성이나 실제 추론 성공까지 확인하는 검사는 아니다. 환경별 CUDA 확인도 별도로 수행한다.

처음에는 설정용 입력으로 로더 동작을 확인한다. v0.2 실행기에는 --limit 옵션이 없으므로 존재하지 않는 옵션을 붙이지 않는다. 한 장 smoke를 위해 별도 확인 코드를 쓰더라도 정식 manifest와 분할·후보를 바꾸지 않는다. 검증용 일부를 먼저 보고 기준을 조정하지 않는다.

### 7.2 전체 v0.2 실행

~~~powershell
& '.venv/v02-data/Scripts/python.exe' -X utf8 -u 'scripts/v02/run_suite.py'
~~~

설정용 추론 → 네 모델 기준 동결 → 검증용 추론 → 변조 모델의 Columbia 참고 추론 → 평가 순서로 진행한다. GPU 모델은 순차 실행한다.

로그는 runs/20261004_followup/suite_logs/에 남으며 모델·역할별 출력은 다음과 같다.

~~~text
runs/20261004_followup/inference/<모델>/<역할>/
├─ metadata.json
├─ predictions.jsonl
├─ completion.json
└─ maps/                  # 변조 탐지 모델
~~~

정상 중단 후 같은 코드·manifest·환경에서 다시 실행하면 기록된 행을 이어간다. 기존 결과를 삭제해 억지로 진행하지 않는다. 실패 행도 기록된 행으로 취급하므로 **재실행하면 실패가 자동으로 재시도된다고 가정하지 않는다.** 실패 후 변경·재시도는 별도 실행으로 기록한다.

### 7.3 종료 후 확인

state=complete와 종료 코드만으로 모든 추론 성공을 단정하지 않는다. predictions.jsonl의 성공·실패를 직접 집계한다.

| 모델 | 설정용 요청 | 검증용 요청 | 참고 요청 | 합계 |
|---|---:|---:|---:|---:|
| B-Free | 1,200 | 1,200 | 0 | 2,400 |
| TruFor | 480 | 480 | 480 | 1,440 |
| Mesorch | 480 | 480 | 480 | 1,440 |
| Mesorch-P | 480 | 480 | 480 | 1,440 |
| 합계 | 2,640 | 2,640 | 1,440 | 6,720 |

다음 항목을 확인한다.

1. 전체 6,720행이 성공했고 중복·누락 ID가 없으며 실패 수가 0인지 확인한다.
2. 입력 목록과 결과 ID가 역할별로 일치하고 완료 표시의 prediction SHA-256이 실제 JSONL과 일치하는지 확인한다.
3. 각 변조 모델의 지도 1,440개, 전체 4,320개의 존재·해시·유한값·좌표를 확인한다.
4. validation metadata가 **새로 만든** 해당 모델 policy freeze를 참조하는지 확인한다.
5. 환경·가중치·코드·manifest 해시와 전처리를 원래 참조 자료와 비교한다.
6. evaluation.json에서 지표·보류·실패와 그룹별 5분할 결과를 확인한다.

불확실성 계산은 새 실행의 evaluation.json과 예측이 준비된 뒤 수행한다.

~~~powershell
& '.venv/v02-data/Scripts/python.exe' -X utf8 'scripts/v02/uncertainty.py'
~~~

scripts/v02/verify_followup.py는 v0.1 보존 자료·워크스페이스 이동 기록·보고서 그림까지 검사하는 **담당자 PC의 전체 이력 검증기**이다. 이 참조 묶음에는 이동 기록과 그림·전체 v0.1 자산이 없으므로 새 PC에서 그대로 실행해 성공을 기대하지 않는다. v0.2 재현 검증과 원래 컴퓨터의 과거 보존 검증을 구분한다.

finish_artifacts.py도 자동 보고서와 전체 이력 검증기를 호출한다. 이를 범용 새 PC 설치·완료 명령으로 사용하지 않는다. 새 PC용 보고서는 새 결과에서 작성하고 실시한 검사와 미실시한 검사를 구분한다.

## 8. 원래 결과와 비교할 값

| 항목 | 원래 v0.2 결과 |
|---|---|
| 실행 완료 | 6,720건 정상, 실패 0건 |
| B-Free 원본 A 기준 | 정상 40장 중 오탐 0장, 생성 160장 중 미탐 80장 = 50.0% |
| 생성기별 원본 A 미탐률 | SD3-medium 0%, FLUX.1-schnell 32.5%, Imagen 3 77.5%, FLUX.1-dev 90.0% |
| B-Free A 조건별 미탐률 | 원본 50.0%, JPEG 65.6%, 절반 축소 92.5%, 긴 변 512 90.0%, 화면 79.4%, 사진 영역 82.5% |
| 원본 위치 F1 | TruFor 0.442 / Mesorch 0.584 / Mesorch-P 0.517 |
| 판정 후보 선택 | 네 모델 모두 selection_failed, 5분할 선택 성공 0/5 |

수치는 빠른 확인용 반올림 값이다. 자세한 값은 reference/experiments/20261004_followup/evaluation.json과 완료 보고서를 따른다. 차이를 없애기 위해 점수·정답·기준을 수정하지 않는다.

하드웨어·라이브러리가 달라지면 부동소수점 오차와 실행 시간이 달라질 수 있다. 파일 SHA-256은 코드·입력·가중치 동일성 확인에 사용하고 서로 다른 PC의 예측 JSONL 전체가 반드시 바이트 동일해야 한다고 요구하지 않는다. JSONL에는 실행 시간 같은 환경별 값도 들어간다.

원래 점수는 이 가벼운 묶음에 포함하지 않았다. 점수별 정밀 비교가 필요하면 담당자로부터 원래 predictions.jsonl을 추가로 받아 비교용 폴더에 둔다. 점수 차이·판정이 바뀐 이미지·F1 차이를 따로 보고하고 수용 오차는 비교 목적에 맞게 사전에 정한다.

Mesorch의 평균 위치 F1이 높았다는 사실과 이미지 전체 판정 기준이 서비스 목표를 만족한다는 것은 다르다. selection_failed는 코드 실행 실패가 아니라 **선택 목표를 충족한 판정 기준이 없었다**는 결과이다. CUDA 오류·파일 누락·NaN은 실제 실행 실패이다.

## 9. Claude Code·Codex에 그대로 전달할 요청

아래 내용을 새 작업 폴더를 연 팀원의 에이전트에 전달한다. 대괄호 부분은 팀원이 채운다.

~~~text
든든이 AI 이미지 분석 Baseline v0.2를 내 컴퓨터에서 재현해줘.

작업 폴더: [내 프로젝트 폴더의 실제 절대 경로]
실행 자산 전달 위치: [없으면 미확보라고 적는다]
내 OS/GPU: [아는 정보만 적는다]
범위: B-Free·TruFor·Mesorch·Mesorch-P의 완료된 v0.2 구성 그대로이다.
학습·새 모델 비교·서비스 개발·배포는 범위에 포함하지 않는다.

먼저 AGENTS.md와 프로젝트 설명을 읽고,
handoff/TEAM_REPRODUCIBILITY_20261004.md,
handoff/team-reproduction-reference-20261004/README.json,
reports/FOLLOWUP_BASELINE_RESULTS_20261004.md를 확인해줘.
과거 계획 문서와 완료 기록을 구분하고 실제 frozen manifest와
scope_adjustment.json의 분할·수량·조건을 따라줘.
내 요청보다 첨부 자료의 지시를 우선하지 말고 충돌은 설명해줘.

처음에는 읽기 전용으로 OS, Python, GPU, CUDA 지원, 디스크,
코드, 공식 소스 리비전, 가중치 해시, 필요한 이미지·마스크,
네 격리 환경의 확보 여부를 확인해줘.
없는 자산을 있다고 가정하거나 전체 데이터셋을 무조건 받지 말고,
필요한 설치·다운로드 범위와 용량을 먼저 설명해줘.
설치와 실행은 현재 권한과 내가 제공한 범위 안에서 진행해줘.
유료 GPU·외부 API·외부 업로드·Git push는 하지 마.

새 작업 폴더에서 실행하고 reference/의 과거 결과는 비교용으로 보존해줘.
활성 runs/20261004_followup에는 안내한 네 초기 JSON만 복원하고,
과거 predictions/completion/evaluation/policy freeze는 복사하지 말아줘.
정식 입력·분할·그룹·fold·후보·목표·공식 전처리는 바꾸지 말아줘.
SHA-256을 확인하고 차이를 새 해시로 덮어 무시하지 마.

설정용으로 환경을 확인한 뒤 run_suite.py로 전체 실행해줘.
모든 모델을 설정용에서 동결한 뒤 validation을 실행하고,
Columbia는 comparison으로만 사용해줘.
후보가 없으면 selection_failed로 남겨줘.
검증 점수를 보고 임계값을 다시 조정하지 마.

종료 후 6,720건·실패 0건·4,320개 지도를 직접 확인하고,
metadata, manifest, weights, code, 새 freeze와 결과의 연결을 검증해줘.
verify_followup.py는 원래 PC의 v0.1·이동 이력도 필요하므로
새 PC에서 그대로 통과했다고 주장하지 말아줘.
실제로 실행한 검사와 미실시 검사를 구분해줘.
Python/GPU 호환 때문에 변경이 필요하면 동일 재현과 환경 변경 실험을 구분해줘.

새 보고서에 내 OS/GPU, 설치 버전, 코드·가중치·입력 해시,
실제 명령, 성공/실패 수, 기준 선택 결과, 원래 수치와의 차이,
오류·해결 과정·한계를 남겨줘.
이미 알고 있는 자료의 재현을 새로운 독립 성능 검증이라고 표현하지 말아줘.
~~~

프로젝트를 읽고 로컬 명령을 실행할 수 있는 Claude Code 또는 Codex 환경이 필요하다. 일반 웹 채팅에 문서만 첨부하면 파일을 정리할 수는 있어도 팀원 컴퓨터의 GPU 추론을 직접 실행할 수 있는 것은 아니다.

## 10. 팀원 실행 후 공유할 결과

새 보고서를 만든다. 예: reports/REPRODUCTION_팀원명_날짜.md이다. 다음 내용을 포함한다.

- OS·GPU·드라이버·Python·주요 패키지와 네 환경의 설치 목록이다.
- 프로젝트 버전, 공식 소스 리비전, 가중치·manifest 해시이다.
- 수행 명령·시작/완료 시각·성공/실패·총 요청 수이다.
- 원래 수치와 새 수치, 차이, 입력·환경 변경 여부를 비교한 표이다.
- 실패 로그·해결 과정·재시도 범위이다.
- 미실시 작업과 추가로 필요한 자료이다.

Git에는 검수한 코드·문서·가벼운 결과 요약을 공유한다. 평가 사진·정답·가중치·대용량 지도·인증정보는 별도로 관리한다. 다른 팀원에게 실행을 부탁할 때는 문서와 참조 폴더 버전도 전달한다.

## 부록 A. v0.1 최종 확인을 재실행하려면

v0.1은 B-Free와 TruFor를 사용했다. B-Free는 RAISE 실제 사진 40장 + Synthbuster 생성 40장, TruFor는 Columbia·COVERAGE의 정상/변조 총 80장으로 원래 구성을 확인했다. 파생 조건 평가는 원본 결과를 본 뒤의 강건성 탐색으로 독립 최종 검증과 구분한다.

참조 묶음의 아래 파일을 같은 상대 경로로 복원한다.

~~~text
runs/20261001_baseline/bfree_sources.json
runs/20261001_baseline/trufor_sources.json
runs/20261002_bfree_raise/preparation/manifest.csv
runs/20261002_bfree_raise/bfree_protocol.json
runs/20261001_original/trufor_preparation/manifest.csv
runs/20261001_original/trufor_protocol.json
~~~

별도 v0.1 manifest에 적힌 이미지·마스크도 확보한다. v0.2 입력만으로 v0.1을 재현할 수 있는 것은 아니다. v0.1 policy freeze가 참조하는 코드·공식 파일 해시까지 확인한다.

새 출력 경로에서 최종 분할 전체를 실행한다. 같은 이름의 출력이 있으면 다른 새 이름을 사용한다.

~~~powershell
& '.venv/bfree/Scripts/python.exe' 'scripts/run_inference.py' --model bfree --manifest 'runs/20261002_bfree_raise/preparation/manifest.csv' --split final --policy-freeze 'runs/20261002_bfree_raise/bfree_protocol.json' --out 'runs/bfree_original_repeat' --device cuda:0
& '.venv/bfree/Scripts/python.exe' 'scripts/evaluate.py' 'runs/bfree_original_repeat/predictions.jsonl' --out 'runs/bfree_original_repeat/evaluation'

& '.venv/trufor/Scripts/python.exe' 'scripts/run_inference.py' --model trufor --manifest 'runs/20261001_original/trufor_preparation/manifest.csv' --split final --policy-freeze 'runs/20261001_original/trufor_protocol.json' --out 'runs/trufor_original_repeat' --device cuda:0
& '.venv/bfree/Scripts/python.exe' 'scripts/evaluate.py' 'runs/trufor_original_repeat/predictions.jsonl' --out 'runs/trufor_original_repeat/evaluation'
~~~

처음 환경을 확인할 때 최종 분할 일부를 미리 확인하지 않는다. 최종 분할에는 --limit를 적용하지 않는다.

### v0.1 설정용·파생 조건·CPU 확인까지 재현하려면

참조 폴더에는 다음 원래 강건성 입력 목록도 포함했다. required_v01_data_files.json의 이미지·마스크는 별도로 확보한다. 이 목록은 초기 보조 실험 전체가 아니라 당시 원래 구성의 원본·5개 파생 조건·CPU probe 입력을 위한 목록이다.

- runs/20261001_robustness/의 conditions.json, 5개 조건 CSV, cpu_trufor.csv이다.
- runs/20261002_bfree_raise/robustness/의 conditions.json과 5개 조건 CSV이다.

새 PC에서 이 목록을 원래 상대 경로로 복원하고 각 입력의 SHA-256을 확인한다. 출력·로그·evaluation은 복사하지 않는다. 위 최종 확인 명령으로 실행한 결과는 *_original_repeat에 있으므로 아래 강건성 평가기의 원본 참조 경로와 다르다.

원래 고정 출력 경로에 새로 실행하려면 **아직 그 경로에 결과가 없는 새 작업 폴더에서만** 설정용과 최종 확인용을 각각 실행한다.

~~~powershell
& '.venv/bfree/Scripts/python.exe' 'scripts/run_inference.py' --model bfree --manifest 'runs/20261002_bfree_raise/preparation/manifest.csv' --split tune --out 'runs/20261002_bfree_raise/bfree_tune' --device cuda:0
& '.venv/bfree/Scripts/python.exe' 'scripts/run_inference.py' --model bfree --manifest 'runs/20261002_bfree_raise/preparation/manifest.csv' --split final --policy-freeze 'runs/20261002_bfree_raise/bfree_protocol.json' --out 'runs/20261002_bfree_raise/bfree_final' --device cuda:0

& '.venv/trufor/Scripts/python.exe' 'scripts/run_inference.py' --model trufor --manifest 'runs/20261001_original/trufor_preparation/manifest.csv' --split tune --out 'runs/trufor_tune_replay' --device cuda:0
& '.venv/trufor/Scripts/python.exe' 'scripts/run_inference.py' --model trufor --manifest 'runs/20261001_original/trufor_preparation/manifest.csv' --split final --policy-freeze 'runs/20261001_original/trufor_protocol.json' --out 'runs/20261001_original/trufor_final' --device cuda:0
~~~

TruFor 원래 강건성 평가기는 설정용 점수를 runs/20261001_original/trufor_preparation/tune_predictions.jsonl에서 읽는다. 새 설정용 추론이 성공한 뒤 **새로 만든** runs/trufor_tune_replay/predictions.jsonl을 해당 경로에 복사한다. 참조 자료의 과거 점수를 새 추론 대신 넣지 않는다. 기존 파일이 있다면 덮어쓰지 않는다.

두 모델 각각 설정용 40장 + 최종 확인용 40장 = 80장을 확인한 뒤, 원래 고정된 A/B 정책을 유지하여 5개 파생 조건을 실행·평가한다.

~~~powershell
& '.venv/trufor/Scripts/python.exe' 'scripts/run_robustness_suite.py'
& '.venv/bfree/Scripts/python.exe' 'scripts/run_bfree_robustness.py'
& '.venv/bfree/Scripts/python.exe' 'scripts/evaluate_robustness.py'
& '.venv/bfree/Scripts/python.exe' 'scripts/evaluate_bfree_robustness.py'
~~~

각 모델의 파생 추론은 80장 × 5개 조건 = 400건이다. v0.2와 실험 수량을 합쳐 해석하지 않는다. 재실행 금지 상태가 생기면 원본을 보존하고 별도 새 작업 폴더를 사용한다.

B-Free CPU 확인에는 참조 자료의 data/manifests/official_demos.csv를 같은 위치에 복원한다. 공식 예제 이미지도 확보한다. RAISE 최종 확인 입력으로 대체하지 않는다.

CPU probe는 동일한 4개 입력으로 기능·수치·시간을 확인했던 별도 작업이다. 원래 공유 사본의 scripts/cpu_probe.py는 --cpu-name을 필수로 받는다. 원래 CPU 이름을 새 장비 결과에 사용하지 않는다. 아래처럼 직접 CPU 추론을 실행하고 실제 CPU 모델·torch 스레드·환경을 새 보고서에 별도로 기록한다.

~~~powershell
& '.venv/bfree/Scripts/python.exe' 'scripts/run_inference.py' --model bfree --manifest 'data/manifests/official_demos.csv' --limit 4 --out 'runs/bfree_cpu_replay' --device cpu
& '.venv/trufor/Scripts/python.exe' 'scripts/run_inference.py' --model trufor --manifest 'runs/20261001_robustness/cpu_trufor.csv' --limit 4 --out 'runs/trufor_cpu_replay' --device cpu
~~~

CPU 4장으로 서비스 처리량이나 동시 요청 성능을 검증했다고 주장하지 않는다. 당시 보고서와 지금 실행 시점의 상태를 구분한다. 예를 들어 10월 1일 보고서의 RAISE 확보 대기 문구는 10월 2일 완료 결과보다 오래된 기록이다. 이 가이드와 reports/의 해당 날짜 보고서를 함께 확인한다.

선택 사항으로 v0.2 이후 수행한 B-Free 생성기 원인 진단은 scripts/diagnostics/ 아래의 별도 분석이다. 검증을 마친 점수에 대한 사후 분석이며 새 판정 기준 선택이나 새로운 독립 검증이 아니다. 이 재현 가이드의 기본 실행에는 자동 포함하지 않는다.

## 부록 B. 자주 막히는 원인

| 증상 | 먼저 확인할 것 |
|---|---|
| clone했는데 데이터·모델이 없다 | Git에서 제외된 실행 자산을 별도로 확보했는지 확인한다. |
| Python 실행 파일을 못 찾는다 | 네 .venv/<이름>/Scripts/python.exe와 작업 루트를 확인한다. |
| CUDA unavailable이다 | CPU 빌드 설치 여부, NVIDIA GPU·드라이버·아키텍처 지원을 확인한다. |
| Mesorch import 실패이다 | timm·IMDLBenCo·albumentations 버전과 어댑터의 import 범위를 확인한다. |
| SHA-256이 다르다 | 리비전·선정 목록·줄바꿈·재인코딩·마스크 변환을 확인한다. |
| 실행이 금방 끝난다 | 과거 completion·점수·평가를 활성 폴더에 복사해 skip된 것인지 확인한다. |
| 기존 파일이 있다며 중단한다 | 덮어쓰기 방지 동작이다. 원본 보존 후 새 재현 폴더를 사용한다. |
| 이동 manifest가 필요하다고 한다 | 원래 PC 전용 전체 이력 검증 의존성이다. |
| 기준 선택이 모두 실패한다 | 원래 v0.2도 같은 결과이다. 실행 실패와 후보 선택 실패를 구분한다. |
| FLUX 미탐률이 높다 | 원래 일반화 문제이다. 결과를 낮추려고 기준을 바꾸지 않는다. |

## 공유 사본 보완·빠른 준비

원본 실험 폴더는 변경하지 않았다. 공유 사본에서는 보조 스크립트 5개의 경로·장비 기록을 수정했다. 추론·판정·평가 코어, 입력·분할·원래 정책 freeze는 유지했다. original_code_sha256.json은 원래 코드, code_sha256.json은 공유 코드 해시이다. 변경 전후 해시와 보고서 변경 이유는 PUBLIC_COPY_PROVENANCE.json에 있다.

.gitattributes는 scripts/, tests/, requirements/와 참조 묶음의 바이트를 보존한다. 자동 포맷이나 줄바꿈 변환을 적용하지 않는다. 공식 소스 clone에도 git -c core.autocrlf=false clone을 사용하여 원본 코드 바이트를 보존한다.

새 작업 폴더에서 아래 명령으로 네 초기 JSON만 복원할 수 있다. --v01을 추가하면 v0.1 준비 목록도 복원한다. 기존 실행 폴더가 있으면 중단한다. 과거 점수·완료 표시·v0.2 freeze·evaluation은 복원하지 않는다.

~~~powershell
py -3.9 scripts/sharing/prepare_replay.py
# v0.1도 수행할 새 폴더에서는 처음부터 --v01을 추가한다.
~~~

설치 목록은 requirements/mesorch-inference.txt와 requirements/v02-data.txt를 추가했다. Mesorch는 torch를 먼저 설치하고 B-Free 의존성을 함께 사용한다. IMDLBenCo는 --no-deps로 설치하여 학습용 의존성이 추론 환경을 교체하지 않게 한다. 전체 버전 스냅샷은 참조 묶음 environment/에 있다. 스냅샷은 완전한 설치 lock이 아니며 새 PC 설치 검증은 아직 수행하지 않았다.

~~~powershell
# 앞 절의 Python 3.9 가상환경 생성 후 실행한다.
& '.venv/bfree/Scripts/python.exe' -m pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 --index-url https://download.pytorch.org/whl/cu118
& '.venv/bfree/Scripts/python.exe' -m pip install -r requirements/bfree-windows.txt
& '.venv/trufor/Scripts/python.exe' -m pip install torch==1.11.0+cu113 torchvision==0.12.0+cu113 --extra-index-url https://download.pytorch.org/whl/cu113
& '.venv/trufor/Scripts/python.exe' -m pip install -r requirements/trufor-windows.txt
& '.venv/mesorch/Scripts/python.exe' -m pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 --index-url https://download.pytorch.org/whl/cu118
& '.venv/mesorch/Scripts/python.exe' -m pip install -r requirements/mesorch-inference.txt
& '.venv/mesorch/Scripts/python.exe' -m pip install --no-deps IMDLBenCo==0.1.45
& '.venv/v02-data/Scripts/python.exe' -m pip install -r requirements/v02-data.txt
~~~

자신의 GPU가 해당 torch 빌드를 지원하는지 설치 전에 확인한다. 위 명령은 원래 구성의 설치 안내이며 지금 패키지를 내려받아 검증한 명령은 아니다. record_start.py·finish_artifacts.py·verify_followup.py는 과거 이력에 의존하므로 범용 새 PC 시작/완료 명령으로 사용하지 않는다.
