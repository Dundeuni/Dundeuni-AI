# 이미지 Baseline 실행 결과 — 2026-10-01

2026-10-02 RAISE 선정 TIFF 40장을 확보해 B-Free 원래 80장·통제된 변형 400장 검증을 완료했다. 최신 결과는 [B-Free 후속 보고서](BFREE_ORIGINAL_RESULTS_20261002.md)와 [재현 가이드](../handoff/TEAM_REPRODUCIBILITY_20261004.md)이다. 아래는 최초 보조 평가 당시 기록이다.

공식 최종 가중치로 B-Free·TruFor의 Windows GPU 추론을 확인했다. 공식 예제 8장과 별도 보조 평가 120개 모델 요청을 정상 처리했다. **원래 계획한 RAISE·COVERAGE 포함 평가, 독립 최종 검증, 위치 성능 검증과 서비스 기준 선택은 아직 완료하지 않았다.**

위 상태는 최초 보조 평가 당시 기록이다. 후속 실행에서 TruFor 80장 구성의 조정용/최종 검증과 위치 성능을 완료했다. 현재 상태와 추가 결과는 [후속 보고서](ORIGINAL_BASELINE_RESULTS_20261001.md)와 [재현 가이드](../handoff/TEAM_REPRODUCIBILITY_20261004.md)를 따른다. 최초 보조 점수·조건은 아래에 보존한다.

이후 TruFor 파생 입력 400장과 두 모델 CPU 4장씩을 정상 처리했다. [변형·CPU 보고서](ROBUSTNESS_AND_CPU_RESULTS_20261001.md)에 추가 결과를 기록했다. 아래 CPU·변형 미측정 상태는 최초 보조 평가 당시 기록이다.

## 1. 실제 실행 환경

작업 폴더는 `프로젝트 루트`이다. 현재 VS Code 폴더에 `scripts/`, `requirements/`, `.venv/`, `third_party/`, `data/`, `runs/`, `reports/`를 작성했다.

| 항목 | 확인 결과 |
|---|---|
| OS | Windows 11 Home 25H2, 10.0.26200, 64-bit이다. |
| CPU·RAM | AMD Ryzen 7 5800X, 8코어·16스레드, OS에서 확인한 총 RAM 약 32GiB이다. |
| GPU·드라이버 | GTX 1080 Ti, 11264MiB VRAM, 드라이버 582.66, Compute Capability 6.1이다. |
| 기본 Python | MSYS2 UCRT Python 3.12.7이다. 설치·추론 환경으로 사용하지 않았다. |
| 모델용 Python | 기존 Visual Studio Windows CPython 3.9.13으로 격리 환경 2개를 만들었다. |
| B-Free 환경 | `.venv/bfree`, torch 2.0.1+cu118, torchvision 0.15.2+cu118, timm 1.0.12, NumPy 1.24.4이다. |
| TruFor 환경 | `.venv/trufor`, torch 1.11.0+cu113, torchvision 0.12.0+cu113, timm 0.5.4, NumPy 1.23.5이다. |

두 PyTorch 빌드의 `get_arch_list()`에 `sm_61`이 있으며 CUDA 실제 추론도 성공했다. 기존 Python·드라이버를 변경하지 않았으며 별도 CUDA Toolkit·WSL을 설치하지 않았다. 공식 Linux conda 전체 환경을 Windows에 그대로 설치하지 않고 사용 중인 추론 경로의 의존성을 고정했다. B-Free 공식 requirements의 pip 패키지명은 `pytorch→torch`, `yaml→PyYAML`로 적용하고 빠진 pandas·NumPy도 명시했다.

전체 패키지 버전·장치·CUDA 런타임·전처리·코드 버전은 각 실행의 `environment.json`에 기록했다. 초기 샌드박스 WMI 접근 거부와 MSYS2 HTTPS 인증서 오류는 Windows 장비 조회 권한과 Windows CPython의 정상 인증서 검증으로 해결했다. 인증서 검증을 끄지 않았다.

## 2. 공식 소스·최종 가중치

| 모델 | 공식 코드 커밋 | 최종 가중치 SHA-256 |
|---|---|---|
| B-Free | `c6a9f898782fb466b29af01f21960b67415afb0e` | `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947` |
| TruFor | `ae54475df6f41a491d7615100feb19263dec13f7` | `ac1d90e329a72e0d66e8665e123a19e94bfae3209c3ef8a4f9ca3b91578c7844` |

B-Free ZIP은 321,653,488바이트, MD5 `f3f53fa647848b16cf81c913f148a198`이다. TruFor ZIP은 260,878,690바이트, MD5 `7bee48f3476c75616c3c5721ab256ff8`이다. 두 값이 공식 안내와 일치했다. ZIP SHA-256과 추출 설정·가중치 해시는 `bfree_sources.json`, `trufor_sources.json`에 보존했다. [B-Free 공식 안내](https://github.com/grip-unina/B-Free/tree/main/code), [TruFor 공식 안내](https://github.com/grip-unina/TruFor/blob/main/TruFor_train_test/README.md)를 사용했다.

TruFor ZIP 내부 경로가 `weights/trufor.pth.tar`여서 실제 추출 경로 `third_party/TruFor/TruFor_train_test/pretrained_models/weights/trufor.pth.tar`를 명시했다. 학습 초기화용 파일을 사용하지 않았다. 모델 코드의 비영리 이용 조건을 확인했으며 상용 서비스 이용 허가까지 확인한 것은 아니다.

## 3. 공식 예제 재현

- B-Free 공식 단일 이미지 CLI를 실행했다. 첫 예제 logit은 약 -5.937이다.
- 공식 예제 4장의 별도 실행 결과와 제공된 `results.csv` 차이는 최대 `0.0000291911`이다. GPU 수치 차이 범위이며 4장의 이진 판정이 일치했다.
- TruFor 공식 CLI를 `trufor_ph3`·최종 가중치로 실행했다. `pristine1.jpg` score는 `0.1896636933`이다.
- 작성한 실행기와 TruFor 공식 CLI의 첫 예제 score·map·conf 차이는 모두 0이다. 출력 크기와 [0,1] 범위를 확인했다.
- 두 모델의 공식 예제는 각각 4장 모두 정상 처리됐고 A·B 모두 오탐·미탐·보류가 없었다. 예제 지표를 독립 성능 결과로 해석하지 않는다.

공식 RGB 변환·B-Free 정규화와 특징 공간 5영역 처리·TruFor `/256.0` 입력·`trufor_ph3` CUDNN 설정을 유지했다. 임의 리사이즈·추가 크롭·EXIF 방향 보정·지도 반전은 적용하지 않았다. TruFor 내부 det에는 공식 sigmoid를 한 번 적용했으며 저장 score에 다시 sigmoid를 적용하지 않았다.

## 4. 보조 평가 데이터와 미완료 조건

| 모델 | 실제 사용한 보조 평가 입력 | 분할 |
|---|---|---|
| B-Free | Columbia 실제 촬영 40장 + Synthbuster 생성 40장이다. | exploratory 80장이다. |
| TruFor | Columbia 원본 20장 + 합성 20장이다. | exploratory 40장이다. |

Columbia의 현재 [공식 다운로드 안내](https://www.ee.columbia.edu/ln/dvmm/downloads/authsplcuncmp/dlform.html)에는 직접 Dropbox 링크가 있다. 401,426,612바이트 ZIP을 확보하고 CRC를 확인했다. 원본 TIFF/BMP를 보존하고 Pillow로 RGB PNG를 생성했다. 공식 RGB 변환 후의 픽셀과 PNG 픽셀의 완전 일치를 확인했다. 선택 이미지와 변환 해시는 `available_data_audit.json`에 기록했다.

[Synthbuster v1](https://zenodo.org/records/10066460)은 9개 생성 모델을 사용한 공개 데이터이다. ZIP 파일 목록을 조회한 뒤 서로 다른 RAISE ID 40개에 생성 모델을 순환 배정해 약 55.2MB만 전송했다. 파일별 ZIP CRC32와 SHA-256을 검증했다. 전체 12.4GB ZIP은 받지 않아 배포된 전체 ZIP MD5를 검증했다고 주장하지 않는다. CC-BY-NC-SA-4.0 조건을 기록했다.

[RAISE 공식 확인 페이지](https://loki.disi.unitn.it/RAISE/confirm.php?package=1k)는 이름·소속·이메일·이용약관 동의가 필요하다. 개인정보를 임의 제출하지 않았으며 사용자의 로컬 경로 회신을 기다린다. [COVERAGE 공식 저장소](https://github.com/wenbihan/coverage)의 OneDrive 공개 폴더는 확인했으나 공개 API는 401, 브라우저 다운로드 도구는 `Invalid InterceptionId`로 실패했다. 파일 확보가 완료되지 않았고 미러로 대체하지 않았다.

이미지 선택은 모델 점수를 보기 전에 고정했다. Columbia는 파일명 정렬과 카메라·카메라 쌍 순환, Synthbuster는 공통 파일명 정렬과 생성 모델 순환을 사용했다. 같은 Columbia 원본의 여러 하위 이미지와 합성 원본 관계를 아직 완전히 확정하지 못해 Columbia 전체를 같은 묶음에 두었다. 이 보조 평가에는 조정용·최종 확인용 분할이 없으며 누출 없는 독립 최종 평가라고 주장하지 않는다. 근접 중복과 사전학습 중복 검수도 미완료이다.

## 5. A·B 정책 비교

실패 0건이며 유효 입력은 B-Free 80장·TruFor 40장이다. 모델별 점수를 합산하지 않는다. AUROC는 B-Free logit과 TruFor 공식 score로 계산했다.

| 모델 | 정책 | AUROC | 오탐 / 유효 음성 | 미탐 / 유효 양성 | 보류 / 유효 전체 | 판정 비율 |
|---|---|---:|---:|---:|---:|---:|
| B-Free | A | 0.9950 | 2/40 = 5.0% | 3/40 = 7.5% | 0/80 = 0% | 100% |
| B-Free | B | 0.9950 | 1/40 = 2.5% | 2/40 = 5.0% | 2/80 = 2.5% | 97.5% |
| TruFor | A | 0.9975 | 1/20 = 5.0% | 0/20 = 0% | 0/40 = 0% | 100% |
| TruFor | B | 0.9975 | 1/20 = 5.0% | 0/20 = 0% | 1/40 = 2.5% | 97.5% |

B-Free의 B 보류는 양성 1장·음성 1장이다. TruFor의 B 보류는 음성 1장이다. 보류는 정답 판정이나 즉시 탐지 성공으로 계산하지 않았다. 표본이 작으므로 특히 미탐 0건을 실제 미탐 위험 0으로 해석하지 않는다.

A는 B-Free `logit>0`, TruFor `score>=0.5`이다. B는 정규화 점수 0.40~0.60을 양쪽 경계 포함 보류한다. 표시 반올림 전에 판정하며 보류 표시 점수는 null이다. 지표 계산은 동일 원본 추론 결과에 정책만 적용했다. 독립 scikit-learn AUROC와 비교했고 두 모델 값이 일치했다.

## 6. 오류·보류 사례와 선택 판단

| 모델·입력 | 정답 | 원본 점수 | A | B |
|---|---:|---:|---|---|
| B-Free·Columbia canonxt_02_sub_03 | 실제 촬영 | 1.464844 | 생성 의심 오탐이다. | 생성 의심 오탐이다. |
| B-Free·Columbia nikond70_02_sub_05 | 실제 촬영 | 0.117156 | 생성 의심 오탐이다. | 보류이다. |
| B-Free·SD2 r006b0e4bt | 생성 | -0.074333 | 신호 없음 미탐이다. | 보류이다. |
| B-Free·Glide r0141f0c9t | 생성 | -0.606607 | 신호 없음 미탐이다. | 신호 없음 미탐이다. |
| B-Free·Glide r018ba134t | 생성 | -1.672131 | 신호 없음 미탐이다. | 신호 없음 미탐이다. |

| TruFor 입력 | 정답 | 공식 score | A | B |
|---|---|---:|---|---|
| Columbia kodakdcs330_02_sub_01 | 원본 | 0.809927 | 변조 의심 오탐이다. | 변조 의심 오탐이다. |
| Columbia nikond70_02_sub_05 | 원본 | 0.456247 | 신호 없음이다. | 보류이다. |

오류·보류 입력과 정확한 원본 점수는 `verification.json`에 기록했다. 확인되지 않은 손가락·조명·노이즈 등 시각적 원인을 추정하지 않았다.

B-Free B는 오류 2건을 보류로 전환했으나 Glide 미탐 2건과 실제 촬영 오탐 1건이 남았다. TruFor B는 음성 1장을 보류했지만 오탐 1건을 줄이지 못했다. 이 결과만으로 B를 두 모델의 최종 서비스 정책으로 채택하지 않는다. 허용 오류·보류·지연 목표를 정하고 원래 평가셋의 조정용에서 정책을 고정한 뒤 새로운 최종 확인용으로 검증해야 한다.

## 7. 위치 지도와 운영 측정

TruFor 보조 입력 40장의 원본 score·map·conf·imgsize를 `.npz`로 저장하고 지도 크기·방향·유한 값·범위를 검사했다. Columbia 색상 마스크는 카메라 1·2 영역과 경계를 나타내며 실제 붙여넣은 영역의 소유권을 자동 확정한 것은 아니다. **IoU·픽셀 F1은 정답 마스크 검수 미완료로 계산하지 않았다.** 보류 시에도 원본 지도는 실험 자료로 보존하며 서비스 표시 정책과 구분한다.

| 실행 | 로딩 | 평균 입력 처리 | p95 입력 처리 | 최대 GPU 할당 메모리 |
|---|---:|---:|---:|---:|
| B-Free 보조 80장 | 2.496초 | 0.264초 | 0.304초 | 637.9MiB |
| TruFor 보조 40장 | 2.504초 | 0.635초 | 0.880초 | 2651.8MiB |

첫 입력을 제외하면 B-Free 79장 평균 0.261초·p95 0.303초, TruFor 39장 평균 0.604초·p95 0.869초이다. 입력 처리 시간에는 파일 읽기·공식 전처리·GPU 연산·CPU 출력 변환이 포함된다. 지도 저장까지의 처리 시간은 각 JSONL에 따로 있다. 프로세스 시작·네트워크·API 응답 시간을 포함한 서버 전체 지연을 측정한 것은 아니다.

TruFor 공식 고해상도 예제에서는 최대 10058.7MiB GPU 할당 메모리와 약 23.3초의 단일 입력 시간이 관측됐다. 작은 Columbia 입력의 평균만으로 고해상도 지원·시간 제한을 정할 수 없다. CPU 추론·동시 요청·실사용 재압축/축소/메신저/캡처 파생본은 이번에 평가하지 않았다.

## 8. 실패 이력·검증·다음 작업

- TruFor 최초 CLI는 Matplotlib가 작업 폴더 밖 캐시를 쓰려다 실패했다. `MPLCONFIGDIR`을 `runs/.matplotlib`로 지정하고 재실행해 해결했다. 원본 실패 로그를 보존했다.
- Columbia ZIP의 빈 루트 디렉터리 `/`는 안전 경로 검사를 통과하지 못했다. 데이터가 없는 루트 표시만 건너뛰고 모든 실제 ZIP/TAR 경로와 링크를 검사한 뒤 해제했다.
- COVERAGE 다운로드 실패는 자료 확보 실패이며 모델 추론 실패율에 섞지 않았다.
- 정책 경계값·반올림·극단 logit·AUROC 동점·실패/보류 분모 단위 테스트 5개가 통과했다. 실제 공식 출력과 독립 AUROC를 검증했다.

다음 작업은 RAISE·COVERAGE 로컬 확보, 원본 관계·중복·마스크 검수, 조정용/최종 확인용 분할 고정, 운영 허용 목표 합의, 실사용 변형·위치 평가와 독립 최종 검증이다. 상세 명령은 `RUN_BASELINE.md`에 기록했다. 원본 자료는 `runs/20261001_baseline/`, 평가 목록은 `data/manifests/`에 있다. Git 커밋·push·외부 업로드는 수행하지 않았다.
