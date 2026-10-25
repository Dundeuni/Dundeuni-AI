# Dundeuni AI

스마트폰 사용 중 발견한 이미지의 AI 생성 여부와 변조 신호를 분석하는 디지털 안전 서비스 **든든이**의 AI 파트 저장소입니다.

```text
사용자가 이미지 선택 또는 화면 캡처 → BE를 통한 분석 요청
→ AI 생성 탐지·변조 탐지 → 모델별 결과·대표 분류·의심 영역·분석 한계 반환
```

AI 생성·변조 분석과 이미지 내용의 사기 위험 판단은 별도 문제입니다. 현재 이미지 분석 작업은 AI 생성 여부와 변조 신호 평가에 집중합니다.

## 기본 구조

현재 구현된 API 구조입니다.

```text
src/image_analysis/         입력 검증, CuRe·TruFor 추론, 모델별·대표 판정
tests/                      GPU 없이 실행하는 HTTP·판정·오류·설정 테스트
scripts/                    API 검증, 합성 입력 시연, 응답 예시 생성
integration/                기존 CuRe 단독 BE Provider 참조 코드·Node 테스트
examples/                   mock 요청·응답 예시
config*.json                실행·판정 설정 예시
requirements*.txt           API 환경 의존성
docs/                       협업·실험 가이드
.github/                    이슈, PR 템플릿과 라벨 정의
```

아래는 도메인 분리와 실험 자료 정리를 위한 확장 계획입니다. 현재 API는
`src/image_analysis` 패키지를 사용하며 계획의 모든 디렉터리가 구현된 상태는 아닙니다.

```text
src/                        AI 분석 기능 코드
├── common/                 공통 결과 형식, 오류 처리
├── config/                 모델 경로와 실행 환경 설정
└── domains/
    └── image-analysis/     AI 생성 탐지, 변조 탐지, 판정 처리
scripts/                    데이터 준비, 모델 추론, 평가 실행
requirements/               모델별 Python 설치 환경
tests/                      입력 처리, 판정 기준, 평가 계산 검증
reports/                    테스트 결과, 오류 분석, 모델 선정 근거
handoff/                    실험 재현 안내와 고정 입력 목록
docs/api/                   BE와 합의할 AI 요청·응답 문서
.github/                    이슈, PR 템플릿과 라벨 정의
```

## 기술 스택

- Python, PyTorch
- API 서버: FastAPI, Uvicorn
- NumPy, Pillow, scikit-learn
- 현재 v0.2 로컬 API 모델: CuRe 생성 탐지 + TruFor ph3 변조·위치 탐지
- 추가 비교 후보: B-Free, Mesorch, Mesorch-P
- NVIDIA CUDA 기반 GPU 추론
- BE와의 요청·응답 계약을 통한 AI 분석 연동

API 환경과 모델별 GPU 환경은 분리합니다. 현재 구현은 CuRe·TruFor를 연결한
로컬 API이며, 임시 판정 기준의 최종 서비스 성능과 운영 배포 방식은 확정 전입니다.
추가 후보는 비교·검증 대상으로 유지합니다.

## 시작하기

```bash
git clone https://github.com/Dundeuni/Dundeuni-AI.git
cd Dundeuni-AI
```

- 모델 실행에는 해당 모델의 공식 코드·가중치와 호환되는 Python 환경이 필요합니다.
- 실험에는 고정된 평가 이미지·정답·분할 목록이 추가로 필요합니다.
- 이미지·가중치·가상환경·대용량 추론 결과는 Git에서 제외합니다.

### API 환경 설치

현재 API의 설치·테스트 기준은 Windows와 Python 3.9입니다. API용 가상환경에는
HTTP·이미지·검증 도구를 설치합니다. PyTorch와 모델 의존성은 별도 모델 환경에 둡니다.

```powershell
py -3.9 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
```

### 두 모델 API 실행

아래 자산 경로는 각 PC의 기존 모델 코드·가중치·격리 환경이 있는 폴더로 바꿉니다.
CuRe 자산 폴더에는 `third_party/CuRe`, `weights/CuRe`, `.venv/cure`가 필요하며,
TruFor 자산 폴더에는 `third_party/TruFor/TruFor_train_test`, `.venv/trufor`가 필요합니다.
어댑터는 기대한 가중치 SHA-256을 검사합니다. 이 실행 명령은 모델을 다운로드하지 않습니다.

```powershell
$env:DUNDEUNI_CURE_ROOT = 'YOUR_CURE_ASSET_ROOT'
$env:DUNDEUNI_TRUFOR_ROOT = 'YOUR_TRUFOR_ASSET_ROOT'
$env:PYTHONPATH = 'src'
& '.\.venv\Scripts\python.exe' -m image_analysis --mode cure-trufor --config config.signal-pilot.example.json
```

서버는 `127.0.0.1:8765`, worker 1개로 실행하며 CuRe → TruFor 순차 추론을 합니다.
개인 경로 기본값은 없으며 실행 인자 `--cure-root` / `--trufor-root`가 환경변수보다 우선합니다.
CuRe 단독은 `--mode cure`, 모델 없는 계약 시연은 `--mode mock --config config.example.json`입니다.

BE와 같은 `DUNDEUNI_AI_SERVICE_TOKEN`을 설정하면 서비스 Bearer 토큰을 검사합니다.
토큰 미설정 시 `MOCK_ONLY_NOT_A_SECRET`이라는 공개 로컬 테스트 인증값을 사용합니다.
이 기본 인증과 loopback 실행은 운영 인증·HTTPS 구성이 아닙니다. 비밀값은 저장소에 넣지 않습니다.

## 이미지 분석 API

`POST /internal/v1/image-analyses`는 BE가 호출하는 동기 `multipart/form-data` API입니다.
앱의 사용자 토큰이나 공개 BE 응답 wrapper를 그대로 사용하지 않습니다.

| 요청 항목 | 설명 |
| --- | --- |
| Authorization | BE→AI 서비스 Bearer 토큰 또는 미설정 개발 서버의 공개 테스트 인증값 |
| X-Request-ID | 호출 시도마다 새 UUID v4 |
| file | JPEG/PNG 파일 한 장 |
| analysisId / elementId | BE가 발급한 UUID. 재시도에서 유지 |
| sourceType | IMAGE / SCREEN_CROP |
| models | ALL 기본값 / GENERATION / MANIPULATION |
| deadlineAt | 응답 완료 마감. 미래 UTC RFC3339 Z 시각 |

개발 입력 제한은 파일 10 MiB, EXIF 정규화 후 각 변 32~8192 px,
총 16,000,000 px입니다. 최대 입력·부하에 대한 운영 제한은 별도 검증 대상입니다.

`generation`은 CuRe, `manipulation`은 TruFor의 모델별 상태·원점수·표시 점수·판정·
문구·근거·한계·버전·오류를 유지합니다. `manipulation.localization`은 PNG/base64
의심 강도 지도이며 분석 이미지 기준 크기·좌표계를 제공합니다. 확정 변조 영역은 아닙니다.

### 모델별 임시 판정

| 모델 | 뚜렷한 해당 신호 없음 | 판단 불가 | 의심 |
| --- | --- | --- | --- |
| CuRe | score < 0.000004 | 0.000004 ≤ score < 0.02 | score ≥ 0.02 |
| TruFor | score < 0.12 | 0.12 ≤ score < 0.70 | score ≥ 0.70 |

반올림 전 원점수로 판정합니다. 표시 점수는 `floor(score × 100 + 0.5)`이며
판단 불가·실패일 때 null입니다. 점수는 보정 확률이나 사기 확률이 아닙니다.
위 경계는 임시 파일럿 설정이며 최종 서비스 성능 승인을 뜻하지 않습니다.

### 대표 결과

모델별 결과를 유지하면서 `overallResult`를 함께 반환합니다. 대표 점수는 만들지 않습니다.

| 우선순위 | 조건 | 대표 분류 |
| --- | --- | --- |
| 1 | 성공한 모델 하나 이상이 생성 또는 변조 의심 | 생성·변조 의심 |
| 2 | 의심은 없지만 판단 불가·실패·미요청 모델이 있음 | 판단 불가 |
| 3 | 두 모델 모두 성공하고 각각 뚜렷한 해당 신호 없음 | 뚜렷한 신호 없음 |

대표 객체에는 `decision`, `decisionLabel`, `policyVersion=image-overall-v1`,
`suspectedKinds`, `uncertainKinds`를 반환합니다. 의심인 모델과 불확실한 모델을
상세에서 확인할 수 있습니다. ‘생성·변조 의심’은 둘 중 하나 이상에 신호가 있다는 뜻입니다.

대표 판정과 실행 상태는 별개입니다. 모델이 정상 추론 후 판단 불가여도 root는
COMPLETED입니다. 일부 실패는 PARTIAL_FAILED, 요청 모델 모두 실패는 FAILED이며,
정상 envelope를 만들 수 있으면 내부 HTTP 200으로 반환합니다. 입력·인증 등의 오류는
별도 4xx/5xx 응답입니다. 판단 불가와 실행 실패의 상세 상태·오류를 유지합니다.

단일 재시도 응답은 이번 호출만 반영합니다. BE는 동일 분석·요소 ID와 입력·정규화·
정책·현재 시도를 확인하고 이전 성공 결과와 병합한 뒤 대표 판정을 다시 계산해야 합니다.
미요청 null로 이전 성공 결과를 지우거나 단일 재시도의 대표값을 세션 대표값으로 덮어쓰지 않습니다.

현재 `integration`의 Node Provider는 기존 CuRe 단독 네 필드 계약의 참조 구현입니다.
두 모델·대표 결과·nullable 점수·위치를 실제 BE/FE로 연결하는 Provider는 후속 작업입니다.

## 테스트와 응답 예시

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check src tests scripts
& '.\.venv\Scripts\python.exe' -m ruff format --check src tests scripts
& '.\.venv\Scripts\python.exe' -m mypy src
node --test integration/cure-provider.test.mjs
```

Python 189개와 Node 3개 테스트, Ruff·포맷·mypy 17개 소스 검사를 통과했습니다.
Python 검사는 GPU 없이 실행합니다. Node 테스트는 해당 실행 파일을 PATH에서 찾을 수 있어야 하며
검증에 사용한 Node 버전은 24.19.0입니다. Python 가상환경에 Node를 설치하는 명령은 아닙니다.
실제 CuRe·TruFor의 합성 입력 GPU/HTTP·PNG 기능 검증과 실제 BE·DB·FE 통합은 구분합니다.
실제 BE·DB·FE 통합, 운영 부하, 최종 threshold 및 위치 정확도 검증은 남아 있습니다.

[응답 예시](examples/README.md)는 모델 다운로드 없이 mock HTTP 응답으로 생성합니다.
실제 CuRe·TruFor 추론 점수·위치 지도나 성능 검증 결과로 사용하지 않습니다.

```powershell
$env:PYTHONPATH = 'src'
& '.\.venv\Scripts\python.exe' scripts/export_examples.py
```

정식 v0.2 명세의 저장소 정리는 #9에서 진행합니다.

- [AI 이미지 분석 모델 API 명세서 v0.2](https://app.notion.com/p/3f77b8236c5a802cbf45ef85068c042d)
- [API 상세 설명](https://app.notion.com/p/3f77b8236c5a80a9bbecdecc062a7d18)
- [BE 수정·협의 사항](https://app.notion.com/p/d587b8236c5a83a98ab001cef3e95392)

## 텍스트 API 검증 — Python 3.12 별도 환경

텍스트 API는 [text-ai 실행 안내](text-ai/docs/INSTALL_WINDOWS.md)를 따릅니다. 기존 Python 3.9 이미지 서비스의 `scripts/verify.py`와 루트 testpaths는 유지하며, 텍스트 테스트를 해당 환경에 합치지 않습니다.

저장소 루트에서 text-ai용 Python 3.12 실행 파일을 명시합니다.

```powershell
& '.\text-ai\.venv-v2\Scripts\python.exe' scripts/verify_text.py --python '.\text-ai\.venv-v2\Scripts\python.exe'
```

`scripts/verify_text.py`는 지정된 실행 파일의 Python 3.12 여부를 확인하고 text-ai 작업 폴더에서 `pytest tests -q`와 `check_package.py --code-only`를 실행합니다. 기존 Python 환경에 설치·변경하지 않습니다. 대역 API·작은 CPU 모델·장치 탐지 대역만 사용하고 실제 A.X 가중치·OCR·외부 URL·GPU 추론·BE 호출을 실행하지 않습니다. 새 결과는 Git 제외 경로 `text-ai/results/text-verification/latest.json`에 저장합니다. 새 회귀 테스트를 포함한 전체 텍스트 검증이므로 기존 이미지 검증 결과와 따로 보고합니다.

## 협업

BE·FE와 같은 방식으로 이슈를 생성하고 작업 브랜치와 PR을 통해 변경 사항을 공유합니다.

- GitHub 운영·협업 규칙: [GIT_CONVENTION.md](./GIT_CONVENTION.md)
- Python 코드 작성 규칙: [CODE_CONVENTION.md](./CODE_CONVENTION.md)
- 이슈·PR 라벨 가이드: [LABELS_GUIDE.md](./.github/LABELS_GUIDE.md)
- API 문서는 [docs/api](./docs/api/README.md)에서 관리한다.
- CuRe·TruFor의 요청·응답 계약은 [이미지 분석 API v0.2](./docs/api/image-analysis-v0.2.md)를 참조한다.

```text
main: 검토된 배포·데모 기준
dev: 개발 통합
feature/*, fix/*, chore/*, docs/*, refactor/*: dev를 대상으로 PR
experiment/*: 모델 비교·검증 작업, dev를 대상으로 PR
```

- 작업 브랜치에는 이슈 번호를 포함합니다.
- 커밋과 PR 제목은 영문 타입과 한글 설명을 사용합니다.
- 일반 작업은 최소 1명 승인 후 Squash merge합니다.
- 모델·전처리·판정 기준 변경은 테스트 결과와 함께 기록합니다.
- AI 입력·출력이 바뀌면 FE·BE 담당자와 공유합니다.


## MVP 범위

우선 이미지 입력에 대한 AI 생성 탐지·변조 탐지 성능을 검증하고, 서비스에 적용할 모델과 판정 기준을 검토합니다. 평가 결과를 바탕으로 처리 상태·모델별 판정·판별 보류·지원 입력 범위를 정의하며, 변조 위치 표시의 적용 가능성도 확인합니다.

AI 생성 탐지와 변조 탐지 결과는 구분하여 제공합니다. 모델 점수를 실제 확률로 단정하지 않으며, 낮은 점수도 원본 인증을 의미하지 않습니다. 변조 탐지 결과만으로 AI를 사용한 편집인지 확정하지 않습니다.

이미지 내용의 사기 여부 판단, 영상·통화 분석, 모델 학습·파인튜닝과 서비스 배포는 현재 이미지 Baseline 검증 범위에 포함하지 않습니다.
