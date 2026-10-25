# 텍스트 위험 분석 AI · FastAPI

문자·메신저 본문 또는 캡처 한 장의 텍스트를 분석합니다. 직접 텍스트는 OCR 없이, 이미지는 PaddleOCR → 본문 정리 → A.X 단일 분류기로 처리합니다.

| 기능 | 주소 |
|---|---|
| 상태 확인 | GET /healthz |
| 직접 텍스트 | POST /internal/v1/text-analyses |
| 이미지 OCR + 텍스트 | POST /internal/v1/text-analyses/image |
| Swagger UI | GET /docs |

두 POST는 서비스 Bearer 토큰이 필요합니다. `normal` / `phishing` / `defer`와 보정 전 분류 점수, 추가 검토 사유를 반환합니다. 점수는 실제 사기 확률이 아니며 이미지 생성·변조 API와 별도입니다.

## 실행·기본 호출

[Windows 설치·실행](docs/INSTALL_WINDOWS.md)에 따라 Python 3.12 기반 `.venv-v2`와 OCR용 `.venv`를 설치합니다. `.env.example`은 항목 안내용이며 자동으로 읽히지 않습니다. 실행 중인 서버의 `/docs`에서 직접 확인할 수 있습니다.

직접 텍스트는 `Content-Type: application/json`, `Authorization: Bearer <서비스 토큰>`과 함께 다음 본문을 보냅니다.

```json
{"text":"내일 오후 3시 회의가 있습니다."}
```

선택 필드는 `analysisId`·`elementId` UUID입니다. 이미지 요청은 multipart의 `file`에 PNG/JPEG를 넣습니다. 선택 `sourceType`은 IMAGE 또는 SCREEN_CROP입니다. 기본 한도는 텍스트 4,000자, 이미지 10 MiB이며 전체 입력·응답 스키마는 [OpenAPI](docs/openapi.json)에 있습니다. 위 문장은 호출 형식 예시이며 미리 정답을 보장하는 예제가 아닙니다.

오류나 `defer`를 정상으로 바꾸지 않습니다. 이미지 OCR이 사용되면 `quality.ocrUsed`가 true이며 `quality.needsReview`·`reasonCodes`를 함께 전달합니다. `evidence`는 기본 설정에서 빈 배열이며 선택적 URL 목록의 악성 일치 시 조회 근거를 포함합니다. URL 위험 목록 조회는 기본 비활성이고 사용자 URL을 방문하거나 단축 URL을 확장하지 않습니다.

## 코드·기본 모델

- ai_text/api.py: HTTP 요청·응답·인증·오류
- ai_text/api_service.py: 모델 유지 로딩·분석 흐름
- ai_text/api_ocr_worker.py: 별도 PaddleOCR 프로세스
- ai_text/action_encoder.py: 위험 분류·행동 유형 보조 head
- ai_text/message_body_v2.py, message_body.py: 메시지 본문 정리
- v2_core.py: 기존 모듈의 공통 의존 파일
- [기본 모델](models/ax_text_actions-20261016/README.md): ax_text_actions-20261016 모델 정보·토크나이저·설정 (가중치는 별도 전달)

기존 BE API의 기본 모델이며, 연구 비교 기준인 single-screen-20261017 모델과 구분합니다. CPU 로더는 모델 생성 전에 FP32 설정을 적용하고 strict=True로 가중치를 읽어 로드 도중 BF16 반올림을 피합니다. 디스크 가중치·토크나이저·전처리·임계값·위험 집계·정상 응답 정책은 유지합니다.

`AI_TEXT_DEVICE`는 `auto`(기본), `cpu`, `cuda_bf16`을 지원합니다. auto는 CUDA가 없으면 CPU를 선택하고, CUDA가 있으면 native BF16 지원을 확인합니다. 미지원 CUDA에서는 초기화 전에 오류로 중단하며 CPU/FP16으로 전환하지 않습니다. CPU를 쓰려면 `AI_TEXT_DEVICE=cpu`를 지정합니다. health의 실제 장치 표시는 기존 `cpu`/`cuda`입니다.

## 검증 기록

[패키지 검증](PACKAGE_VALIDATION.json), [API 경계 테스트](docs/API_TEST_RESULTS.xml), [CPU 동작 기록](docs/MODEL_SMOKE_VALIDATION.json)을 포함합니다. 앞선 준비본에서 API 경계 테스트 21개와 CPU 텍스트 입력 3건을 확인했습니다. 이번 작업은 파일 분리이므로 모델·API 테스트를 새로 측정한 것으로 표기하지 않습니다. 경계 테스트는 대역을 사용하며 CPU 입력 확인도 정확도 평가가 아닙니다.

새 환경 설치·실제 OCR/HTTP/BE 재검증·GPU 재검증·출시 성능 승인은 별도입니다. 학습·평가 원문·이미지·가상환경·캐시·실제 서비스 토큰은 동봉하지 않았습니다.

## 수정 후 검증 진입점

text-ai 폴더에서 Python 3.12의 별도 환경으로 실행합니다. 실제 가중치·OCR·서비스 토큰은 필요 없습니다.

```powershell
.\.venv-v2\Scripts\python.exe ..\scripts\verify_text.py --python .\.venv-v2\Scripts\python.exe
```

`pytest tests -q`로 CPU 로더·장치 탐지·API/OpenAPI 회귀 테스트를 포함한 전체 텍스트 테스트를 실행하고 `check_package.py --code-only`로 파일 무결성을 확인합니다. 작은 임시 모델의 수치·대역 응답 확인이며 실제 GPU·모델 성능 평가와 구분합니다. 기존 검증 기록은 과거 자료로 보존하고 이번 실행은 `results/text-verification/latest.json`에 별도로 기록합니다.

## 가중치와 고지

팀 저장소 정책에 따라 약 300MB의 model.safetensors는 Git에 포함하지 않습니다. 코드·모델 설정·토크나이저와 MODEL_ASSETS.json의 고정 해시만 관리합니다. [가중치 별도 설치](docs/WEIGHTS_SETUP.md)에 따라 학습된 모델 폴더를 별도로 받고 AI_TEXT_MODEL_DIR로 지정합니다. Git LFS 업로드는 사용하지 않습니다. GitHub에서 코드만 내려받으면 실제 모델 추론은 아직 실행할 수 없습니다.

[제3자 고지](THIRD_PARTY_NOTICES.md)와 기반 모델 라이선스를 licenses 폴더에 함께 제공합니다. 기반 모델 조건은 학습 자료·제3자 이미지 이용 권한이나 팀 코드 전체의 라이선스를 확정하는 의미가 아닙니다.

## 파일 무결성 기준

check_package.py --code-only는 파일 존재·Python 구문과 현재 패키지의 해시를 검사합니다. PACKAGE_MANIFEST.json의 lf 항목은 CRLF만 LF로 바꾼 정규 바이트를, raw 항목은 모델 설정·원본 고지의 실제 바이트를 비교합니다. 마지막 줄바꿈·공백·Unicode 문자는 임의로 제거하지 않습니다. manifest 자신은 자기 해시 대상에서 제외합니다. SOURCE_COPY_AUDIT.json과 과거 실행 기록의 복사 해시는 그 시점의 이력을 뜻하며 현재 파일의 해시와 구분합니다.
