# 텍스트 위험 분석 API

문서 이슈 #15에서 기능 이슈 #14의 로컬 구현을 기준으로 정리한 AI 내부 API 명세입니다. BE의 사용자용 `/api/analysis`와 구분합니다. 이 문서 작성은 새 서버 호출·OCR·모델 성능·FE/BE 통합 검증을 수행했다는 의미가 아닙니다.

## 엔드포인트·인증·추적

| Method | Endpoint | 입력 | 인증 |
|---|---|---|---|
| GET | `/healthz` | 없음 | 없음 |
| POST | `/internal/v1/text-analyses` | JSON 텍스트 한 건 | 서비스 Bearer 토큰 |
| POST | `/internal/v1/text-analyses/image` | multipart 이미지 한 장 | 서비스 Bearer 토큰 |

두 POST는 `Authorization: Bearer <서비스 토큰>`을 사용합니다. 토큰은 비공개 환경 설정으로 전달하고 문서·저장소·FE에 실제 값을 넣지 않습니다.

선택 헤더 `X-Request-ID`는 UUID4입니다. 생략하면 서버가 생성합니다. 정상 응답과 정의된 서비스·검증 오류에서는 유효한 값을 응답 본문 `requestId`와 응답 헤더에 보존합니다. 예상 밖 내부 예외의 오류 응답에서는 헤더 보존을 보장하지 않습니다. 잘못된 값은 `422 INVALID_REQUEST_ID`와 새 `requestId`를 반환하며, 이 조기 오류 응답에는 `X-Request-ID` 헤더를 설정하지 않습니다.

`GET /healthz`의 HTTP 200 응답 필드는 `status`(`ready`), `modelVersion`, `device`, `ocrWorkerAvailable`입니다. `ready`는 분류기 로드·준비 완료를 뜻합니다. `ocrWorkerAvailable`은 OCR Python·worker 파일의 존재만 확인하며 PaddleOCR 실행 성공을 보장하지 않습니다.

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
| 422 | `INVALID_REQUEST_ID` | X-Request-ID가 올바른 UUID4가 아님 |
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

## 구현·OpenAPI 차이와 검토 범위

정적 코드와 함께 저장된 OpenAPI를 대조한 결과이며 새 HTTP 호출 결과가 아닙니다.

| 항목 | 저장된 OpenAPI | 실제 로컬 구현·후속 처리 |
|---|---|---|
| 422 오류 본문 | 기본 `HTTPValidationError`의 detail 형식 | 정의한 검증 오류는 error.code·error.message·requestId 형식. 스키마 보완 필요 |
| 오류 상태 코드 | POST에 200·422 중심으로 기재 | 위 표의 401·413·415·502·503·504 등 보완 필요 |
| 추적·오류 헤더 | X-Request-ID·Retry-After·WWW-Authenticate 설명 누락 | 조건과 전달 규칙을 이 문서에 정의. OpenAPI 보완 필요 |
| health 응답 | 구체적 필드 스키마 없음 | status·modelVersion·device·ocrWorkerAvailable 문서화. OpenAPI 보완 필요 |

입력·성공 응답 스키마는 저장된 OpenAPI와 비교하되 위 누락을 숨기지 않습니다. 서버가 생성하는 OpenAPI를 보완하려면 API 코드의 문서 메타데이터 수정이 필요할 수 있으므로 후속 작업으로 구분합니다. 이 문서 변경에서 원본 openapi.json·API 코드·가중치·임계값은 변경하지 않았습니다. 응답 점수를 이미지 생성·변조용 aiGenerationScore에 넣지 않습니다. FE·BE의 공개 필드 매핑·저장 정책·실제 통합 확인은 별도입니다.
