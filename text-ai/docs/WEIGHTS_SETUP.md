# 학습 가중치 별도 설치

팀 저장소 README 정책에 따라 가중치·원문 데이터·가상환경은 Git에 올리지 않습니다. 이 서비스의 코드와 설정은 Git으로 받고, 학습 가중치는 별도 전달받습니다. LFS로 가중치를 올리는 방식도 이번 전달에서는 사용하지 않습니다.

## 별도로 받을 것

버전은 ax_text_actions-20261016입니다. model.safetensors와 같은 모델의 config·토크나이저를 함께 담은 폴더를 받습니다. 작성자 PC의 전달용 위치는 C:\work\AI-text-sprint2\03_model_assets\ax_text_actions-20261016입니다. 팀원은 전달받은 폴더를 본인 PC의 저장소 밖 원하는 위치에 둡니다. 실제 전달 경로·공유 방식은 팀에서 정하며 이 준비 작업이 외부 업로드를 수행한 것은 아닙니다.

MODEL_ASSETS.json에 필요한 파일 8개와 SHA-256을 기록했습니다. 기반 모델을 새로 다운로드하는 것으로 이 학습 가중치를 대체하지 않습니다. 학습 원문·실제 캡처·서비스 토큰은 이 자산 폴더에 없습니다. 폴더 이름은 ax_text_actions-20261016으로 유지하는 것을 권장합니다.

## 코드만 확인

VS Code에서 저장소의 text-ai 폴더를 열고 기존 설치 설명대로 환경을 만든 뒤 실행합니다.

```powershell
.\.venv-v2\Scripts\python.exe check_package.py --code-only
```

코드 존재·Python 구문과 PACKAGE_MANIFEST.json의 크기·SHA-256을 검사합니다. 직접 작성한 텍스트는 CRLF를 LF로 정규화하고, 원본 모델 설정·고지는 바이트 그대로 비교합니다. 모델 가중치·성능·OCR·BE 검증은 아닙니다.

## 모델 연결·검증

서버를 실행할 PowerShell에서 별도로 받은 폴더의 실제 전체 경로를 환경변수에 설정합니다. 아래 경로는 작성자 PC의 예시이므로 팀원은 자기 PC 경로로 바꿉니다.

```powershell
$env:AI_TEXT_MODEL_DIR = 'C:\work\AI-text-sprint2\03_model_assets\ax_text_actions-20261016'
.\.venv-v2\Scripts\python.exe check_package.py --model-dir $env:AI_TEXT_MODEL_DIR
```

PASS를 확인한 같은 터미널에서 서비스 토큰을 설정하고 run_api.ps1을 실행합니다. .env.example은 안내용이며 자동 로드되지 않습니다. AI_TEXT_MODEL_DIR를 설정하지 않으면 기존 기본 경로 models/ax_text_actions-20261016을 사용하지만 Git에는 가중치가 없으므로 실제 추론은 시작할 수 없습니다.

출력 점수나 threshold는 이번 분리로 바꾸지 않았습니다. 이 검사는 정확한 파일을 받았는지 확인하며 새 모델 성능 평가가 아닙니다.
