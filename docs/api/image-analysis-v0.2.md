# AI 이미지 분석 API 명세서 v0.2

## 1. 범위와 버전

CuRe로 AI 생성 신호를, TruFor ph3로 변조 신호와 의심 위치를 분석한다.
모델별 결과를 유지하면서 대표 분류를 반환한다. 이미지 내용의 사기 여부는 분석하지 않는다.

| 항목 | 값 |
| --- | --- |
| 문서 버전 | v0.2 |
| 내부 응답 `contractVersion` | `1.0` |
| 기준 구현 | [`d6b591b`](https://github.com/Dundeuni/Dundeuni-AI/commit/d6b591bea2c1d88b269556fcb4861722994a3538), 기능 PR #11 |
| 대표 판정 버전 | `image-overall-v1` |
| 실행 모드 | `CURE_TRUFOR` |

문서 버전과 wire 계약 버전은 구분한다. 이 명세는 기준 구현을 설명하며,
PR 병합·BE 공개 응답 연결·서비스 정책 승인을 완료한 것으로 표시하지 않는다.

## 2. 호출과 입력

`POST /internal/v1/image-analyses`를 BE가 동기 호출한다.
Path Variable과 Query Parameter는 사용하지 않는다. Query가 있으면 400으로 거부한다.
요청은 `multipart/form-data`로 전송하며 boundary는 클라이언트가 생성한다.
현재 개발 서버는 `http://127.0.0.1:8765`에서 실행하고 loopback 호출만 허용한다.

### 헤더

| 헤더 | 필수 | 규칙 |
| --- | --- | --- |
| `Authorization` | O | `Bearer <서비스 토큰>`으로 전송한다. 사용자 Access Token과 구분한다. |
| `X-Request-ID` | O | 호출 시도마다 새 소문자·하이픈 포함 UUID v4를 발급한다. |
| `Content-Type` | O | boundary가 포함된 `multipart/form-data`를 사용한다. |

실제 모델 모드에서 `DUNDEUNI_AI_SERVICE_TOKEN`을 설정하면 같은 토큰을 BE에서 사용한다.
미설정 시 공개 개발용 인증값 `MOCK_ONLY_NOT_A_SECRET`을 사용한다.
개발 인증과 loopback 실행을 운영 인증·HTTPS 구성으로 간주하지 않는다.

### multipart 필드

| 필드 | 타입 | 필수 | 규칙 |
| --- | --- | --- | --- |
| `file` | binary | O | JPEG/PNG 이미지 한 장을 전달한다. MIME은 `image/jpeg` 또는 `image/png`로 지정한다. |
| `analysisId` | string | O | BE가 발급한 소문자·하이픈 포함 UUID 36자를 전달한다. |
| `elementId` | string | O | 같은 형식의 UUID로 이미지 요소를 식별한다. |
| `sourceType` | enum | O | `IMAGE` 또는 `SCREEN_CROP`을 전달한다. |
| `models` | enum | X | `ALL`을 기본값으로 사용하며 `GENERATION`과 `MANIPULATION`도 허용한다. |
| `deadlineAt` | string | O | 미래 UTC 시각을 RFC3339 `Z` 형식으로 전달한다. 소수 초는 선택한다. |

`ALL`은 generation → manipulation 순서로 실행한다. 단일 선택은 해당 모델만 실행한다.
알 수 없는 필드·중복 필드·추가 파일을 거부하고 텍스트 필드마다 128 UTF-8 바이트로 제한한다.
AI는 UUID 형식을 검사하며 분석 소유권·DB 연결은 BE에서 확인한다.

### 개발 입력 제한

| 항목 | 제한 |
| --- | --- |
| 파일 / multipart 본문 | 10 MiB / 11 MiB |
| 가로·세로 | 각 32~8192 px |
| 총 픽셀 수 | 16,000,000 px 이하 |
| 프레임 수 | 1개 |
| 동시 요청 | 프로세스당 1개 |
| 전체 응답 본문 | 2 MiB 이하 |

파일 시그니처·MIME·디코딩 결과를 확인한다. EXIF 방향을 적용하고 알파 채널은
흰 배경에 합성한 뒤 RGB로 변환한다. 모델별 전처리는 각 어댑터에서 수행한다.
위 값은 개발 설정이며 운영 입력·부하 제한은 별도로 검증한다.

## 3. 응답 구조

정상 분석 envelope는 내부 HTTP 200으로 반환한다. 모델 실행 실패도 envelope로 표현할 수
있으면 HTTP 200으로 반환하고 root·모델별 상태에 실패를 기록한다.
BE의 `isSuccess/code/message/result` wrapper와 구분한다.

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `contractVersion` | string | `1.0`을 반환한다. |
| `requestId / analysisId / elementId` | string | 이번 요청의 추적 ID와 분석·요소 ID를 반환한다. |
| `sourceType` | enum | 요청의 입력 유형을 반환한다. |
| `requestedModels` | string[] | 요청한 `generation / manipulation` 선택자를 실행 순서대로 반환한다. |
| `status` | enum | `COMPLETED / PARTIAL_FAILED / FAILED`로 실행 결과를 표현한다. |
| `analysisImage` | object | `width/height`는 정규화 크기, `inputSha256`은 업로드 원본 바이트의 SHA-256을 반환한다. |
| `generation / manipulation` | object 또는 null | 요청한 모델의 성공·실패 객체를 반환하고 미요청 모델만 null로 반환한다. |
| `overallResult` | object | 대표 결과를 반드시 반환하며 null을 허용하지 않는다. |
| `completedAt` | string | 응답 작성 시각을 UTC `Z` 형식으로 반환한다. |

`analysisImage.normalizationVersion`은
`CURE_TRUFOR-normalization-v1-exif-rgb-white-alpha`를 반환한다.
응답 헤더에 `X-Request-ID`, `X-AI-Mode`, `Cache-Control: no-store`를 포함한다.

### 모델별 객체

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `status` | enum | `SUCCEEDED / FAILED`로 실행 상태를 표현한다. |
| `modelName / modelVersion / policyVersion` | string | 모델·가중치·설정 기준을 식별한다. 실패 객체에도 유지한다. |
| `rawScore` | object 또는 null | 실제 모델 성공 시 `{"score": 0~1}`을 반환하고 실패 시 null로 반환한다. |
| `displayScore` | integer 또는 null | 판정 가능 시 0~100 정수를 반환한다. 판단 불가·실패 시 null로 반환한다. |
| `decision / decisionLabel` | enum / string 또는 null | 모델별 판정과 한국어 문구를 반환한다. 실패 시 둘 다 null로 반환한다. |
| `reasons / limitations` | string[] | 점수 기반 근거와 해석 한계를 반환한다. 손가락·그림자 이상 등 추론하지 않은 근거를 생성하지 않는다. |
| `localization` | object 또는 null | TruFor 의심 위치 지도를 반환한다. CuRe는 항상 null로 반환한다. |
| `errorCode / error` | string / object 또는 null | 성공 시 null로 반환한다. 실패 시 `errorCode=error.code`를 유지한다. |

`error`에는 `code/message/retryable`을 포함한다.
`policyVersion`은 설정 전체를 해시하여 `CURE_TRUFOR-policy-v2-<16자리 해시>`로 생성한다.
예시의 버전 문자열을 고정 운영값으로 복사하지 않는다.

## 4. 점수와 판정

CuRe는 `softmax(logits)[1]`, TruFor는 `sigmoid(det)`를 한 번 적용한 값을 사용한다.
반올림 전 `rawScore.score`로 판정한다. 점수를 보정 확률·사기 확률로 해석하거나
두 모델 점수를 합산·평균하지 않는다.

### 모델별 임시 threshold

| 모델 | 뚜렷한 해당 신호 없음 | 판단 불가 | 의심 |
| --- | --- | --- | --- |
| CuRe | score < 0.000004 | 0.000004 ≤ score < 0.02 | score ≥ 0.02 |
| TruFor | score < 0.12 | 0.12 ≤ score < 0.70 | score ≥ 0.70 |

| 모델 | 의심 decision / 문구 | 신호 없음 decision / 문구 |
| --- | --- | --- |
| CuRe | `AI_GENERATED_SUSPECTED` / AI 생성 의심 | `NO_CLEAR_GENERATION_SIGNAL` / 뚜렷한 AI 생성 신호 없음 |
| TruFor | `MANIPULATION_SUSPECTED` / 변조 의심 | `NO_CLEAR_MANIPULATION_SIGNAL` / 뚜렷한 변조 신호 없음 |

판단 불가는 `INCONCLUSIVE / 판단 불가`로 반환하고,
`status=SUCCEEDED`, `rawScore` 유지, `displayScore=null`, `reasons=[]`로 처리한다.
판정 가능한 점수는 `floor(score × 100 + 0.5)`로 표시한다.
이 경계는 `hold_enabled=true`인 임시 파일럿 설정이며 최종 승인 기준으로 간주하지 않는다.

### 대표 결과

| 우선순위 | 조건 | decision / decisionLabel |
| --- | --- | --- |
| 1 | 성공한 모델 하나 이상이 생성 또는 변조 의심 | `GENERATION_OR_MANIPULATION_SUSPECTED` / 생성·변조 의심 |
| 2 | 의심 없이 판단 불가·실패·미요청 모델이 존재 | `INCONCLUSIVE` / 판단 불가 |
| 3 | 두 모델 모두 성공하고 각각 해당 신호가 없음 | `NO_CLEAR_SIGNAL` / 뚜렷한 신호 없음 |

`overallResult`에 `decision/decisionLabel/policyVersion/suspectedKinds/uncertainKinds`를 반환한다.
`policyVersion`은 `image-overall-v1`로 유지한다. 의심인 모델을 `suspectedKinds`,
판단 불가·실패·미요청 모델을 `uncertainKinds`에 포함한다.
배열은 generation → manipulation 순서로 작성하고 해당 모델이 없으면 빈 배열로 반환한다.
대표 점수는 생성하지 않는다. ‘생성·변조 의심’은 둘 중 하나 이상의 신호를 의미한다.

### 실행 상태와 대표 판정의 구분

| 요청 모델 실행 결과 | root status | 대표 결과 예시 |
| --- | --- | --- |
| 모두 성공 | `COMPLETED` | 둘 다 판단 불가이면 대표도 판단 불가로 반환한다. |
| 일부 실패 | `PARTIAL_FAILED` | 성공한 모델이 의심이면 대표는 의심으로 반환한다. |
| 모두 실패 | `FAILED` | 대표는 판단 불가로 반환하고 모델별 오류를 유지한다. |

단일 모델만 요청한 경우 그 모델의 성공·실패로 root 상태를 정한다.
미요청 모델은 대표 판정의 불확실성에 포함한다. 판단 불가를 0점이나 신호 없음으로 치환하지 않는다.

## 5. 의심 위치 지도

| 필드 | 값·규칙 |
| --- | --- |
| `format / kind / mimeType` | `PNG_BASE64 / MANIPULATION_HEATMAP / image/png`로 반환한다. |
| `data` | 흑백 PNG의 base64를 반환한다. PNG는 1 MiB, 문자열은 1,398,104자로 제한한다. |
| `imageSize` | `analysisImage`와 같은 정규화 이미지 크기를 반환한다. |
| `mapSize` | PNG 크기를 반환한다. 긴 변을 최대 1024 px로 제한하고 비율을 유지하며 입력보다 확대하지 않는다. |
| `coordinateSpace` | `ANALYSIS_IMAGE`로 반환한다. |

좌상단을 (0, 0), 오른쪽을 x 증가, 아래쪽을 y 증가 방향으로 사용한다.
BE·FE는 `mapSize → imageSize` 비율을 적용하고 SCREEN_CROP의 화면 좌표 변환을 담당한다.
원본·overlay·raw map/conf 배열·확정 변조 bbox는 반환하지 않는다.

map/conf 필수 출력이 잘못되면 모델을 FAILED로 처리한다.
필수 출력은 유효하지만 표시 PNG 생성만 실패하면 모델 판정은 유지하고
`localization=null`과 limitations로 위치 생성 실패를 안내한다.
유효한 지도는 판단 불가에서도 내부 반환할 수 있다.
지도는 연속적인 의심 강도이며 확정 변조 영역이나 AI 편집 증거로 해석하지 않는다.
FE 노출·접근권한·TTL·영구 보관과 지도 이진화 threshold는 별도로 합의한다.

## 6. 오류

### 요청·인증·전송 단계

| HTTP | error.code | 상황 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | 필드·UUID·multipart·Query 등 형식이 잘못된 요청을 거부한다. |
| 401 | `AUTHENTICATION_FAILED` | 서비스 인증 누락·불일치를 거부한다. |
| 403 | `FORBIDDEN_CALLER` | 호출 권한이 없거나 loopback 이외에서 호출하면 거부한다. |
| 413 | `PAYLOAD_TOO_LARGE / IMAGE_LIMIT_EXCEEDED` | 파일·본문·이미지 크기 제한 초과를 거부한다. |
| 415 | `UNSUPPORTED_IMAGE_FORMAT` | MIME·시그니처·형식 불일치나 다중 프레임을 거부한다. |
| 422 | `INVALID_IMAGE / IMAGE_TOO_SMALL / DEADLINE_EXPIRED` | 디코딩 실패·최소 크기 미충족·지난 마감 시각을 거부한다. |
| 503 | `AI_BUSY / MODEL_UNAVAILABLE` | 슬롯 사용 중이거나 선택 모델 구성을 사용할 수 없으면 거부한다. |
| 500 | `INTERNAL_ERROR` | 분석 응답을 작성할 수 없는 내부 오류를 반환한다. |

오류 본문은 `requestId/analysisId/elementId/error` 네 필드로 반환한다.
확인하지 못한 분석·요소 ID는 null로 반환하고 `overallResult`는 포함하지 않는다.
유효하지 않은 추적 ID는 서버가 새 UUID v4로 대체한다.
503에는 `Retry-After`를 초 단위로 포함한다. 개발 기본값은 1초로 사용한다.
401에는 `WWW-Authenticate: Bearer`를 포함한다.

### 모델 실행 단계

`MODEL_TIMEOUT`, `REQUEST_DEADLINE_EXCEEDED`, `MODEL_OUT_OF_MEMORY`,
`MODEL_RUNTIME_UNAVAILABLE`, `MODEL_OUTPUT_INVALID`, `MODEL_EXECUTION_FAILED`를
모델별 `errorCode/error`에 기록한다.
실패 모델의 원점수·표시 점수·판정·문구·위치는 null로 반환한다.
`retryable`은 재시도 가능성 안내로 사용하며 자동 재시도나 성공을 보장하지 않는다.

## 7. 실행 예산과 재시도

개발 모델당 timeout은 120초, 응답 여유는 1초로 설정하고 두 모델을 순차 실행한다.
각 모델 예산은 `min(모델 timeout, deadlineAt까지 남은 시간 - 응답 여유)`로 계산한다.
BE·프록시 timeout과 세션 TTL은 전체 cold load·최대 입력·부하를 측정한 뒤 합의한다.
기존 CuRe 단독 Provider의 130초를 두 모델 전체 예산으로 그대로 적용하지 않는다.

AI 내부 queue·자동 retry·멱등성 키·성공 결과 캐시는 구현하지 않는다.
실패 모델 재시도 시 같은 입력·analysisId·elementId와 새 requestId·deadlineAt을 사용한다.
BE는 입력 해시·정규화 버전·모델별 정책 버전·현재 시도를 확인하고 이전 성공 결과를 보존한다.
미요청 null로 기존 성공 결과를 지우지 않으며, 병합한 모델별 결과에서 대표 판정을 다시 계산한다.
단일 재시도 응답의 대표 결과를 세션 대표 결과로 그대로 덮어쓰지 않는다.

## 8. 응답 예시와 BE·FE 연동

기준 구현의 [응답 예시 안내](https://github.com/Dundeuni/Dundeuni-AI/blob/d6b591bea2c1d88b269556fcb4861722994a3538/examples/README.md)에서
정상·판단 불가·부분 실패·전체 실패·단일 모델 응답을 확인한다.
[요청 설명](https://github.com/Dundeuni/Dundeuni-AI/blob/d6b591bea2c1d88b269556fcb4861722994a3538/examples/request-description.json)은
multipart 구성 설명용 JSON이며 JSON 요청 본문으로 전송하지 않는다.
예시의 저장된 deadlineAt은 호출 시 미래 시각으로 갱신한다.

예시는 MOCK 모드로 생성하고 B-Free 이름의 생성 mock, logit 변환, 공통 0.4~0.6 판단 불가 구간을 사용한다.
실제 CuRe·TruFor 점수·threshold·위치 정확도를 재현하는 예시로 해석하지 않는다.
필드·상태·대표 분류·null·PNG 전달 구조만 참조한다.

| 항목 | 현재 범위와 후속 작업 |
| --- | --- |
| AI 내부 API | 모델별 결과·대표 분류·위치 전달 규칙을 구현한다. |
| 기존 Node Provider / CuRe 호환 API | CuRe 단독 참조로 유지한다. 두 모델·대표 결과를 자동으로 공개 전달하지 않는다. |
| BE | 실제 Provider·공개 DTO·상태 매핑·재시도 병합·이용량·저장 정책을 연결한다. |
| FE | 대표 문구와 모델별 상세·실패·위치 상태를 연결하고 지도 노출 정책을 합의한다. |
| 성능·운영 | 최종 threshold·위치 정확도·부하·인증·HTTPS·TTL 정책을 검증·합의한다. |
| 자동 API 문서 | 현재 Swagger UI 비활성화와 미명시 요청·응답 스키마를 보강하는 후속 작업으로 관리한다. |

후속 작업을 이번 문서 작성만으로 완료 표시하지 않는다.
BE 문서의 현재 POST 응답과 AI 내부 envelope를 동일한 계약으로 취급하지 않는다.

## 9. 근거와 문서 관리

- [기준 스키마](https://github.com/Dundeuni/Dundeuni-AI/blob/d6b591bea2c1d88b269556fcb4861722994a3538/src/image_analysis/schemas.py)와 같은 커밋의 validation·policy·overall·service·app 구현을 계약 근거로 사용한다.
- [API 명세서 v0.2](https://app.notion.com/p/3f77b8236c5a802cbf45ef85068c042d)에서 팀 공유 명세를 참조한다.
- [API 상세 설명](https://app.notion.com/p/3f77b8236c5a80a9bbecdecc062a7d18)에서 모델·파일럿 검증 근거와 한계를 참조한다.
- [BE 수정·협의 사항](https://app.notion.com/p/d587b8236c5a83a98ab001cef3e95392)에서 공개 응답·재시도·저장·노출 정책의 합의 항목을 확인한다.

#9에서 이 명세를 관리한다. 구현 계약을 변경하면 기준 커밋·표·예시와 Notion 공유 내용을 갱신한다.
명세의 코드 일치 확인과 BE·FE 합의, 실제 통합 검증·성능 승인은 각각 구분한다.
