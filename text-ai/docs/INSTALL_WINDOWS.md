# Windows 설치·실행

아래 명령은 사용자가 직접 실행합니다. 준비본 제작 중 새 가상환경 설치나 서버 실행은 하지 않았습니다. Python 3.12가 필요하며, 패키지의 기존 환경을 재사용한 점검과 새 PC 설치 검증은 구분합니다.

## 1. 폴더 열기

VS Code에서 준비본의 `text-ai` 폴더를 열고 **터미널 → 새 터미널**을 선택합니다. GitHub에 올린 뒤에는 내려받은 저장소의 `text-ai` 폴더를 사용합니다. 이하 명령의 현재 위치는 이 폴더입니다.

## 2. API·분류기 환경 만들기

```powershell
py -3.12 -m venv .venv-v2
.\.venv-v2\Scripts\python.exe -m pip install --upgrade pip
.\.venv-v2\Scripts\python.exe -m pip install -r requirements-dev.txt
```

원래 환경은 PyTorch `2.9.1+cu128`이었습니다. 위 설치 목록은 `2.9.1` 버전을 고정하지만 GPU 드라이버·플랫폼에 맞는 PyTorch 빌드는 별도로 선택해야 할 수 있습니다. CPU용으로 설치하려면 requirements 설치 전에 PyTorch 공식 CPU 인덱스의 `torch==2.9.1`을 설치합니다. 새 PC에서의 전체 의존성 설치는 아직 실행하지 않았습니다.

## 3. OCR 환경 만들기

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

기존 구현은 Windows의 `.venv\Scripts\python.exe`를 OCR 프로세스로 실행합니다. `.venv-v2`와 `.venv`를 따로 만드는 이유입니다. OCR은 CPU를 사용하며 첫 요청에서 공식 PaddleOCR 모델을 내려받을 수 있습니다. 첫 요청 시간과 반복 요청 시간을 구분해서 확인해야 합니다.

## 4. 별도 모델 연결·API 경계 확인

```powershell
.\.venv-v2\Scripts\python.exe check_package.py --code-only
$env:AI_TEXT_MODEL_DIR = 'C:\work\AI-text-sprint2\03_model_assets\ax_text_actions-20261016'
.\.venv-v2\Scripts\python.exe check_package.py --model-dir $env:AI_TEXT_MODEL_DIR
.\.venv-v2\Scripts\python.exe ..\scripts\verify_text.py --python .\.venv-v2\Scripts\python.exe
```

가중치는 Git에 없습니다. [별도 모델 설치](WEIGHTS_SETUP.md)에 따라 학습된 모델 폴더를 받은 뒤 위 예시의 AI_TEXT_MODEL_DIR 경로를 실제 받은 위치로 바꿉니다. 모델 경로 설정은 서버를 실행할 터미널에도 유지해야 합니다. 검증 진입점은 text-ai에서 `pytest tests -q`와 `check_package.py --code-only`를 실행합니다. 별도 모델 파일 없이 대역 API·작은 임시 모델·장치 탐지 대역으로 검사하며, 실제 A.X 정확도·OCR·GPU·BE 검증은 실행하지 않습니다. 결과는 Git 제외 경로 `results/text-verification/latest.json`에 저장합니다. 기존 루트 이미지 검증은 Python 3.9에서 별도로 실행합니다.

## 4-1. 추론 장치 선택

`AI_TEXT_DEVICE`의 허용값은 `auto`(기본), `cpu`, `cuda_bf16`입니다. `.env.example`은 안내용이므로 실제 환경변수를 지정합니다.

```powershell
$env:AI_TEXT_DEVICE = 'cpu'
```

- `cpu`: CUDA가 있는 PC에서도 CPU를 명시적으로 사용합니다. 모델 생성 전에 설정을 FP32로 지정하고 FP32 파라미터에 가중치를 strict=True로 읽습니다.
- `cuda_bf16`: 현재 CUDA 장치가 사용 가능하고 native BF16을 지원해야 합니다. 미지원이면 모델 초기화 전에 원인을 안내하고 중단합니다.
- `auto`: CUDA가 없으면 CPU를 선택합니다. CUDA가 있으면 native BF16 지원을 요구하며, 미지원 시 CPU나 FP16으로 조용히 전환하지 않습니다. CPU를 쓰려면 위처럼 명시합니다.

`/healthz`의 device는 실제 선택 장치인 `cpu` 또는 `cuda`입니다. `cuda_bf16`은 설정값이며 health 응답의 새 enum이 아닙니다. 검증 진입점은 CPU 설정으로 실행하지만 장치 정책 테스트는 탐지 함수를 대역으로 바꿔 CUDA 지원·미지원 조건을 검사합니다. 실제 GPU 검증과 구분합니다.

## 5. 서버 실행

```powershell
$env:AI_SERVICE_TOKEN = [guid]::NewGuid().ToString("N")
$env:AI_URL_REPUTATION_ENABLED = '0'
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_api.ps1
```

토큰은 직접 안전하게 보관하고 BE 담당자에게는 비공개 방법으로 전달합니다. GitHub 이슈·README·커밋에는 넣지 않습니다. `.env.example`은 항목 안내용이며 이 구현은 `.env` 파일을 자동으로 읽지 않습니다. 서버가 실행 중인 터미널은 열어 둡니다. 주소는 `http://127.0.0.1:8000/docs`입니다.

## 6. 실제 HTTP 호출 확인

다른 터미널에서 같은 폴더로 이동하고 서버와 같은 토큰을 설정한 뒤 실행합니다.

```powershell
$env:AI_SERVICE_TOKEN = '서버에서 설정한 토큰을 이 컴퓨터에서만 입력'
.\.venv-v2\Scripts\python.exe smoke_text_api.py
```

이미지 확인을 추가하려면 위 명령에 `--image '검사할 실제 PNG 또는 JPEG의 전체 경로'`를 덧붙입니다. 결과는 `results/api-baseline-20261016/http-smoke.json`에 저장되며 Git에서 제외합니다. 이 스크립트는 AI API에 직접 요청합니다. 실제 BE를 거친 연동은 별도 확인합니다.

## 7. 환경변수

| 항목 | 의미 |
|---|---|
| AI_SERVICE_TOKEN | 필수 서비스 인증 토큰 |
| AI_TEXT_MODEL_DIR | 별도로 받은 학습 모델 폴더의 전체 경로. Git에는 가중치가 없으므로 실행 전 설정 |
| AI_TEXT_DEVICE | auto(기본), cpu, cuda_bf16. CUDA 사용 시 native BF16 미지원이면 초기화 전 중단 |
| AI_OCR_TIMEOUT_SECONDS | OCR 제한 시간. 기본 90초, 1~600초 |
| AI_URL_REPUTATION_ENABLED | 기본 0. 이번 전달본에서도 비활성 유지 |
| AI_WEBRISK_API_KEY | 조회를 별도 활성화할 때만 필요한 키. 실제 키 미포함 |

외부 주소 공개와 ngrok 실행도 이 준비 작업에서는 수행하지 않았습니다.
