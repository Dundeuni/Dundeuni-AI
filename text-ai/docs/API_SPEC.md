# 텍스트 위험 분석 API

문서 이슈 #15에서 기능 이슈 #14의 로컬 구현을 기준으로 정리한 AI 내부 API 명세입니다. BE의 사용자용 `/api/analysis`와 구분합니다. 이 문서 작성은 새 서버 호출·OCR·모델 성능·FE/BE 통합 검증을 수행했다는 의미가 아닙니다.

## 엔드포인트·인증·추적

| Method | Endpoint | 입력 | 인증 |
|---|---|---|---|
| GET | `/healthz` | 없음 | 없음 |
| POST | `/internal/v1/text-analyses` | JSON 텍스트 한 건 | 서비스 Bearer 토큰 |
| POST | `/internal/v1/text-analyses/image` | multipart 이미지 한 장 | 서비스 Bearer 토큰 |

두 POST는 `Authorization: Bearer <서비스 토큰>`을 사용합니다. 토큰은 비공개 환경 설정으로 전달하고 문서·저장소·FE에 실제 값을 넣지 않습니다.

선택 헤더 `X-Request-ID`는 UUID4입니다. 생략하거나 빈 문자열이면 서버가 생성합니다. 정상 분석 응답과 정의된 서비스·검증 오류에서는 유효한 값을 응답 본문 `requestId`와 응답 헤더에 보존합니다. 상태 확인의 성공 응답에는 추적 헤더만 포함됩니다. 예상 밖 내부 예외의 오류 응답에서는 헤더 보존을 보장하지 않습니다. 비어 있지 않은 잘못된 값은 `422 INVALID_REQUEST_ID`와 새 `requestId`를 반환하며, 이 조기 오류 응답에는 `X-Request-ID` 헤더를 설정하지 않습니다.

`GET /healthz`의 HTTP 200 응답 필드는 `status`(`ready`), `modelVersion`, `device`, `ocrWorkerAvailable`입니다. `ready`는 분류기 로드·준비 완료를 뜻합니다. `ocrWorkerAvailable`은 OCR Python·worker 파일의 존재만 확인하며 PaddleOCR 실행 성공을 보장하지 않습니다.

## 실행 장치 설정

AI 서버는 `AI_TEXT_DEVICE`로 텍스트 분류기의 실행 장치를 선택합니다. BF16 지원은 에뮬레이션을 제외한 네이티브 지원을 뜻합니다. 설정값과 `/healthz`에 반환하는 실제 `device`를 구분합니다.

| 설정값 | 선택 규칙 | health의 `device` |
|---|---|---|
| `auto`(기본) | CUDA가 없으면 CPU, CUDA와 BF16 지원을 모두 확인하면 CUDA BF16 | `cpu` 또는 `cuda` |
| `cpu` | CUDA 유무와 관계없이 CPU를 명시적으로 선택 | `cpu` |
| `cuda_bf16` | CUDA와 BF16 지원이 모두 필요 | `cuda` |

CUDA는 있지만 BF16을 지원하지 않으면 `auto`와 `cuda_bf16` 모두 모델 초기화 전에 이유를 알리고 기동을 중단합니다. CPU나 FP16으로 자동 전환하지 않습니다. 이 장비에서 CPU를 사용하려면 `AI_TEXT_DEVICE=cpu`를 명시합니다. CUDA가 없는 장비의 `cuda_bf16` 및 허용값 이외의 설정도 기동 오류입니다. 기동 실패는 분석 API의 정상 응답이나 `defer`로 반환하는 상황이 아닙니다.

## 직접 텍스트 요청

`POST /internal/v1/text-analyses`, `Content-Type: application/json`

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `text` | string | Y | 공백뿐인 입력 불가, 공백을 포함한 전체 길이 최대 4,000자 |
| `analysisId` | UUID 또는 null | N | 생략 시 null, 전달 시 응답에 보존 |
| `elementId` | UUID 또는 null | N | 생략 시 null, 전달 시 응답에 보존 |

정의되지 않은 JSON 필드는 허용하지 않습니다. 두 식별자는 UUID4로 한정하지 않습니다. 아래는 요청 형식 예시이며 해당 문장의 실제 모델 판정을 보장하지 않습니다.

```json
{
  "text": "내일 오후 3시 회의가 있습니다.",
  "analysisId": "11111111-1111-4111-8111-111111111111",
  "elementId": "22222222-2222-4222-8222-222222222222"
}
```

## 이미지 문자 분석 요청

`POST /internal/v1/text-analyses/image`, `Content-Type: multipart/form-data`

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `file` | file | Y | 실제 PNG/JPEG 파일, MIME `image/png` 또는 `image/jpeg` |
| `sourceType` | enum | N | `IMAGE`(기본) 또는 `SCREEN_CROP` |
| `analysisId` | UUID | N | 생략 시 응답 null, 전달 시 응답에 보존 |
| `elementId` | UUID | N | 생략 시 응답 null, 전달 시 응답에 보존 |

파일은 최대 10 MiB, 각 변 32~8,192px, 총 1,600만 픽셀 이하, 단일 프레임이어야 합니다. 내용과 MIME 형식이 일치해야 합니다. 전체 POST 본문은 multipart 부가정보를 포함해 최대 11 MiB입니다. OCR 결과가 4,000자를 넘으면 `422 OCR_TEXT_TOO_LONG`을 반환합니다.

이미지 URL을 보내 서버가 내려받는 규격이 아닙니다. `SCREEN_CROP`은 전달한 이미지의 유형이며 이 필드 자체가 서버에 자동 자르기를 요청하는 기능은 아닙니다. multipart boundary는 클라이언트가 설정합니다. 다음은 실행하지 않은 Windows PowerShell 호출 형식 예시입니다. 환경변수와 파일 경로를 먼저 준비해야 합니다.

```powershell
curl.exe --request POST "$env:AI_BASE_URL/internal/v1/text-analyses/image" --header "Authorization: Bearer $env:AI_SERVICE_TOKEN" --form "file=@C:\path\capture.png;type=image/png" --form "sourceType=SCREEN_CROP"
```

## 분석 응답 필드

성공한 분석은 HTTP 200, `status=COMPLETED`입니다. `defer`도 분석 완료 결과이며 실행 실패와 구분합니다. 필드는 응답에 포함되며 null 허용 여부는 아래와 같습니다.

| 필드 | 타입 | 의미·규칙 |
|---|---|---|
| `contractVersion` | string | `text-risk-1.0` |
| `requestId` | UUID4 | 요청 추적 ID |
| `analysisId`, `elementId` | UUID 또는 null | 전달받은 식별자, 생략 시 null |
| `sourceType` | enum | `TEXT`, `IMAGE`, `SCREEN_CROP` |
| `status` | enum | `COMPLETED` |
| `decision` | enum | 최종 `normal`, `phishing`, `defer` |
| `textDecision` | enum | 품질·문맥 검토를 반영한 뒤 URL 위험 목록을 반영하기 전의 텍스트 판단 |
| `decisionSource` | enum | `TEXT_CLASSIFIER`, `KNOWN_MALICIOUS_URL` |
| `riskScore` | number 또는 null | A.X 분류 점수 0~1. 분석 불가 시 null, 실제 사기 확률이 아님 |
| `scoreScale` | string | `0..1` |
| `scoreMeaning` | string | `UNCALIBRATED_CLASSIFIER_SCORE` |
| `modelName`, `modelVersion` | string | `skt/A.X-Encoder-base`, 실제 모델 폴더 이름(기본 `ax_text_actions-20261016`) |
| `policyVersion` | string | `action-decision-v1` |
| `text` | string | 요청 원문 또는 OCR 결과. 분류기 내부 정규화 문자열이 아님 |
| `quality` | object | 아래 품질·검토 정보 |
| `evidence` | string[] | 기본 설정에서는 빈 배열. 선택적 URL 위험 목록의 악성 일치 시 해당 조회 근거 추가 |
| `limitations` | string[] | 점수·발신자 진위·근거·URL 목록 조회의 해석상 한계 |
| `urlReputation` | object | 아래 선택적 URL 조회 정보 |
| `processingMs` | number | AI 내부 처리 시간(ms). 업로드·인증·이미지 검증·직렬화·네트워크 등 전체 왕복 시간이 아님 |

### 품질·추가 확인 정보

`quality`에는 `needsReview`, `reasonCodes`, `ocrUsed`, `poorOcrConfidence`, `layoutUncertain`, `contextDisagreement`가 포함됩니다. `reasonCodes`만 string[]이고 나머지는 boolean입니다. `needsReview`는 검토 사유가 있음을 뜻하며, `phishing`과 true가 함께 반환될 수 있습니다.

현재 생성되는 `reasonCodes`는 다음과 같습니다. 스키마는 문자열 배열이므로 소비자는 향후 새 사유를 받아도 원문을 보존할 수 있어야 합니다.

| 값 | 의미 |
|---|---|
| `NO_ANALYZABLE_TEXT` | 분석 가능한 텍스트 없음 |
| `LOW_OCR_CONFIDENCE` | OCR 신뢰도 낮음 |
| `UNCERTAIN_MESSAGE_LAYOUT` | 메시지 본문 영역 구분 불확실 |
| `CONTEXT_DISAGREEMENT` | 문장·주변 문맥의 판정 차이로 검토 필요 |
| `SCORE_IN_REVIEW_INTERVAL` | 다른 사유 없이 점수 구간으로 판단 보류 |

### 선택적 URL 조회 정보

`urlReputation` 필드는 다음과 같습니다.

- `provider=GOOGLE_WEB_RISK_LOOKUP`, `policyVersion=url-reputation-lookup-v1`
- `enabled`: boolean, 기본 false
- `status`: `no_urls`, `disabled`, `malicious`, `not_found`, `incomplete`
- `checkedAt`: URL 평가 시작 시각 문자열. 실제 개별 조회 시각과 구분
- `urlCount`: 발견한 URL 수, `submittedCount`: 제출 수(0~5)
- `targetVisited=false`
- `notFoundMeaning=NO_KNOWN_THREAT_MATCH_NOT_A_SAFETY_GUARANTEE`
- `results`: URL별 결과 배열. 항목은 `originalUrl`, `lookupUrl`(null 허용), `schemeInferred`, `status`, `reasonCode`(null 허용), `threatTypes`, `cacheHit`, `lookupCheckedAt`(null 허용), `providerExpireTime`(null 허용)을 포함
- 항목의 `status`: `malicious`, `not_found`, `unavailable`, `disabled`, `skipped`
- `threatTypes`: `MALWARE`, `SOCIAL_ENGINEERING`, `UNWANTED_SOFTWARE`의 배열

URL 조회는 기본 비활성입니다. URL이 없으면 비활성 상태에서도 `status=no_urls`이며 결과 배열은 비어 있습니다. 사용자 URL 방문·단축 URL 확장·새 스캔은 하지 않습니다. 활성화하면 URL을 외부 목록 제공자에 제출하며, 미일치·실패를 안전 보장으로 해석하지 않습니다.

## 임시 판정 규칙

| 분류 점수 | 기본 텍스트 판단 |
|---|---|
| `score < 0.3` | `normal` |
| `0.3 ≤ score < 0.5` | `defer` |
| `score ≥ 0.5` | `phishing` |

반올림 전 값을 사용합니다. 분석 가능한 본문이 없으면 점수는 null이고 `defer`입니다. 공백뿐인 직접 입력 등 잘못된 요청은 분석 보류가 아닌 입력 오류입니다.

기본 판단이 normal이어도 OCR 신뢰도·본문 영역·문맥이 불확실하면 defer로 바뀝니다. 높은 위험 점수는 phishing을 유지하면서 추가 검토가 필요할 수 있습니다. 이 단계의 결과를 `textDecision`에 보존합니다.

선택적 URL 조회에서 악성 목록 일치가 있으면 `riskScore`와 `textDecision`은 유지하고 `decision=phishing`, `decisionSource=KNOWN_MALICIOUS_URL`로 반환하며 조회 근거를 `evidence`에 추가합니다. 미일치·조회 실패로 기존 텍스트 위험 판단을 낮추지 않습니다. 기준은 출시 성능이 승인된 최종 임계값이 아닙니다.

## 응답 예시

아래는 스키마 설명용 가상 값이며 실제 모델·OCR 실행 결과나 성능 측정값이 아닙니다. URL이 없는 직접 텍스트 요청의 예입니다.

```json
{
  "contractVersion": "text-risk-1.0",
  "requestId": "33333333-3333-4333-8333-333333333333",
  "analysisId": null,
  "elementId": null,
  "sourceType": "TEXT",
  "status": "COMPLETED",
  "decision": "normal",
  "textDecision": "normal",
  "decisionSource": "TEXT_CLASSIFIER",
  "riskScore": 0.1,
  "scoreScale": "0..1",
  "scoreMeaning": "UNCALIBRATED_CLASSIFIER_SCORE",
  "modelName": "skt/A.X-Encoder-base",
  "modelVersion": "ax_text_actions-20261016",
  "policyVersion": "action-decision-v1",
  "text": "내일 오후 3시 회의가 있습니다.",
  "quality": {
    "needsReview": false,
    "reasonCodes": [],
    "ocrUsed": false,
    "poorOcrConfidence": false,
    "layoutUncertain": false,
    "contextDisagreement": false
  },
  "evidence": [],
  "limitations": [
    "위험 점수는 실제 사기 확률이 아닙니다.",
    "화자·발신자·URL의 진위는 확인하지 않습니다.",
    "본문 분류 모델의 개별 사기 근거는 검증하지 않았습니다.",
    "URL 위험 목록 미등록은 안전 보장이 아닙니다."
  ],
  "urlReputation": {
    "provider": "GOOGLE_WEB_RISK_LOOKUP",
    "policyVersion": "url-reputation-lookup-v1",
    "enabled": false,
    "status": "no_urls",
    "checkedAt": "2026-10-25T00:00:00+00:00",
    "urlCount": 0,
    "submittedCount": 0,
    "targetVisited": false,
    "notFoundMeaning": "NO_KNOWN_THREAT_MATCH_NOT_A_SAFETY_GUARANTEE",
    "results": []
  },
  "processingMs": 0.0
}
```

## 오류·동시 요청·시간 제한

AI 서비스가 정의한 오류 본문은 다음 형식입니다. 예시 ID는 설명용입니다. 프레임워크의 경로·메서드·일부 파싱 오류나 프록시 오류까지 같은 형식을 보장하지는 않습니다.

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "요청 필드와 형식을 확인해주세요."
  },
  "requestId": "33333333-3333-4333-8333-333333333333"
}
```

| HTTP | `error.code` | 조건 |
|---|---|---|
| 401 | `UNAUTHORIZED` | 토큰 누락·불일치. `WWW-Authenticate: Bearer` 포함 |
| 422 | `INVALID_REQUEST` | JSON·form 필드/UUID/길이 등의 요청 검증 실패 |
| 422 | `INVALID_REQUEST_ID` | 비어 있지 않은 X-Request-ID가 올바른 UUID4가 아님 |
| 422 | `INVALID_TEXT` | 서비스 계층의 텍스트 방어 검증. HTTP 빈 입력·길이 오류는 보통 INVALID_REQUEST |
| 422 | `EMPTY_IMAGE`, `INVALID_IMAGE`, `IMAGE_DIMENSIONS`, `OCR_TEXT_TOO_LONG` | 빈 파일·손상·해상도·OCR 텍스트 길이 오류 |
| 413 | `REQUEST_TOO_LARGE`, `IMAGE_TOO_LARGE` | 전체 본문 11 MiB 또는 파일 10 MiB 초과 |
| 415 | `UNSUPPORTED_IMAGE`, `IMAGE_TYPE_MISMATCH`, `ANIMATED_IMAGE` | 미지원 MIME·실제 내용 불일치·복수 프레임 |
| 503 | `ANALYZER_BUSY` | 다른 분석 실행 중. `Retry-After: 2` 포함 |
| 503 | `OCR_UNAVAILABLE` | OCR 실행 파일 환경 미준비 |
| 503 | `ANALYSIS_FAILED` | 그 밖의 처리 실패. 내부 예외 내용을 응답에 노출하지 않음 |
| 504 | `OCR_TIMEOUT` | OCR 프로세스 제한 시간 초과 |
| 502 | `OCR_FAILED` | OCR 프로세스 실패 또는 결과 형식 오류 |

텍스트·이미지 경로는 같은 서비스 인스턴스의 분석 잠금을 공유합니다. 동시 분석을 큐에 쌓지 않고 503으로 거절합니다. `Retry-After: 2`는 2초 뒤 성공을 보장하지 않습니다. 식별자 보존이 중복 요청 방지나 멱등성을 보장하는 것은 아닙니다.

OCR 프로세스의 기본 제한 시간은 90초이며 `AI_OCR_TIMEOUT_SECONDS`로 1~600초를 설정합니다. 이는 전체 HTTP/BE 왕복 제한 시간이 아닙니다. `processingMs`는 분류와 선택적 URL 조회를 포함하며, 이미지 요청에서는 검증·잠금 획득 이후 임시 파일 준비와 OCR부터 측정합니다.

## OpenAPI 대응과 검토 범위

기능 브랜치의 API 응답 모델·라우트 메타데이터와 생성 OpenAPI를 함께 보완했습니다. 문서 브랜치에는 설명 문서만 반영하며, 아래 계약은 기능 변경과 합친 구조의 `openapi.json`을 기준으로 확인합니다.

| 경로 | 선언한 응답 상태 | 스키마·헤더 |
|---|---|---|
| `GET /healthz` | 200, 422, 503 | 200에 상태 확인의 네 필드, 오류에 공통 오류 모델 |
| `POST /internal/v1/text-analyses` | 200, 401, 413, 422, 503 | 분석 성공 모델과 공통 오류 모델 |
| `POST /internal/v1/text-analyses/image` | 200, 401, 413, 415, 422, 502, 503, 504 | 분석 성공 모델과 공통 오류 모델 |

정의한 422 오류는 기본 `HTTPValidationError.detail` 대신 실제 `error.code`·`error.message`·`requestId` 구조를 참조합니다. OpenAPI에는 선택 요청 헤더 `X-Request-ID`와 응답 헤더의 조건도 설명합니다. `WWW-Authenticate: Bearer`는 인증 실패, `Retry-After: 2`는 `ANALYZER_BUSY`에 해당합니다. 503 전체에 재시도 헤더가 있다는 뜻은 아닙니다. 잘못된 요청 ID와 예상 밖 내부 예외의 추적 헤더 예외도 위 전달 규칙을 따릅니다.

이 문서의 예시는 계약 설명용입니다. 실제 GPU·OCR·외부 URL 조회·BE·DB·FE 연동과 모델 성능의 검증 결과로 해석하지 않습니다. 과거 PB-23 기록은 재측정 결과로 바꾸지 않습니다. 응답 점수를 이미지 생성·변조용 aiGenerationScore에 넣지 않습니다. FE·BE의 공개 필드 매핑·저장 정책·실제 통합 확인은 별도입니다.
