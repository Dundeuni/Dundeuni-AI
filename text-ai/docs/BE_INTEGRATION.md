# 텍스트 AI–BE 연동 설명

문서 이슈 #15, 관련 기능 이슈 #14의 연동 설명입니다.

## 호출 흐름과 문서 범위

사용자 → BE → 텍스트 AI API → BE → 사용자 순서입니다. BE의 사용자용 `/api/analysis`와 AI 내부 `/internal/v1/text-analyses`는 별도 계약입니다. 상세 입력·응답·오류·판정 규칙은 [API_SPEC.md](API_SPEC.md)를 참조합니다.

직접 입력·붙여넣기 본문은 JSON의 text로, 문자 캡처는 multipart의 실제 file로 전달합니다. 캡처는 PaddleOCR로 읽은 뒤 동일 분류기에 전달합니다. 문자 캡처 분석과 이미지 생성·변조 탐지는 구분합니다.

이 문서는 로컬 구현·기존 공유 기록의 대조 결과입니다. 이번 문서 작업에서 새 OCR·HTTP·BE 호출이나 DB·FE 통합을 실행하지 않았습니다.

## BE에 전달할 접속·요청 정보

- 접근 가능한 AI 서버 기본 주소: 다른 PC의 BE에 내 PC의 127.0.0.1을 전달하지 않음
- 상태 확인: `GET /healthz`, 인증 없음. OCR 파일 존재 확인이 실제 추출 성공 보장은 아님
- 본문: `POST /internal/v1/text-analyses`, JSON의 text 필수, 최대 4,000자
- 이미지: `POST /internal/v1/text-analyses/image`, PNG/JPEG file 필수. sourceType은 IMAGE 또는 SCREEN_CROP
- 서비스 Bearer 토큰: 비공개 경로로 전달, 저장소·FE·공개 문서에 실제 값 기재 금지
- analysisId·elementId: 선택 UUID. 전달한 값은 응답에 보존
- X-Request-ID: 선택 UUID4. 미전달 또는 빈 문자열이면 생성, 정상 분석 응답과 정의된 서비스·검증 오류에서 유효한 값은 응답 본문·헤더에 보존. 상태 확인의 성공 응답에는 헤더만 포함. 비어 있지 않은 잘못된 값은 422이며 이때와 예상 밖 내부 예외의 오류 응답에서는 헤더 보존을 보장하지 않음
- 파일 최대 10 MiB, 전체 POST 본문 최대 11 MiB. multipart boundary는 클라이언트가 설정

BE 환경변수 이름, timeout, 재시도·저장 정책은 담당자와 확인합니다. 이미지 생성·변조 API의 models·deadlineAt·overallResult를 텍스트 계약에 자동으로 추가하지 않습니다. ID 전달이 요청 중복 방지를 보장하지는 않습니다.

AI 서버의 `AI_TEXT_DEVICE` 허용값은 `auto`(기본), `cpu`, `cuda_bf16`입니다. `auto`는 CUDA가 없으면 CPU를 선택하고, CUDA가 있으면 에뮬레이션을 제외한 네이티브 BF16 지원을 확인합니다. CUDA는 있지만 BF16이 미지원이면 CPU·FP16으로 전환하지 않고 모델 초기화 전에 기동을 중단합니다. 이때 CPU로 실행하려면 `cpu`를 명시합니다. `cuda_bf16`은 CUDA와 BF16 지원을 모두 요구하며, 허용값 이외의 설정도 기동 오류입니다. `/healthz`의 `device`에는 설정 문자열이 아닌 실제 선택 장치 `cpu` 또는 `cuda`가 표시됩니다. 실제 GPU 검증 여부는 장치 선택 대역 테스트와 구분합니다.

## 결과·추가 검토 처리

- decision의 normal/phishing/defer를 보존합니다. defer는 HTTP 200의 COMPLETED 결과일 수 있습니다. 오류·보류를 normal로 바꾸지 않습니다.
- riskScore는 보정 전 텍스트 분류 점수이며 사기 확률·발신자 진위·URL 안전 인증 결과가 아닙니다.
- textDecision은 품질·문맥 검토 이후, URL 목록 반영 이전 판단입니다. 최종 decision 및 decisionSource와 함께 전달합니다.
- quality.needsReview와 quality.reasonCodes를 보존합니다. phishing과 needsReview=true가 함께 나올 수 있습니다.
- evidence는 기본 설정에서는 빈 배열입니다. 선택적 URL 위험 목록의 악성 일치 시에는 조회 근거가 추가됩니다. 행동 유형 보조 점수를 검증된 사기 근거로 표시하지 않습니다.
- 위험 목록 악성 일치는 최종 decision을 phishing으로 올릴 수 있지만 텍스트 점수·textDecision은 유지합니다. 미일치·조회 실패로 위험을 낮추지 않습니다.
- URL 조회는 기본 비활성입니다. 사용자 URL 방문·단축 URL 확장·새 스캔을 하지 않습니다. 외부 제공자 조회 활성화는 별도 설정·서비스 정책 확인 대상입니다.
- modelVersion·policyVersion·contractVersion·requestId와 원래 분석·요소 ID를 연결합니다. 텍스트 점수를 이미지 생성·변조용 aiGenerationScore로 저장하지 않습니다.

## 응답 지연·실패·재시도

processingMs는 AI 내부 처리 시간입니다. 이미지 업로드·인증·이미지 검증·직렬화·네트워크를 포함하는 BE 전체 왕복 시간과 구분합니다. 이미지에서는 OCR 과정이 포함되고, 선택적 URL 조회가 켜지면 조회 시간도 포함됩니다.

OCR 프로세스 제한은 기본 90초이며 AI_OCR_TIMEOUT_SECONDS로 1~600초 설정 가능합니다. 전체 요청 deadline과 같지 않습니다. 초기 모델 다운로드·초기화와 반복 요청 시간을 구분하고 BE 대기 시간을 협의합니다.

텍스트·이미지 요청은 같은 서비스 인스턴스에서 한 번에 하나만 분석합니다. 겹치면 503 ANALYZER_BUSY와 Retry-After: 2를 반환합니다. 큐·2초 뒤 성공 보장은 없습니다. 실패 원인을 구분해 BE의 재시도 정책을 정하고 무조건 재시도하거나 정상 결과로 저장하지 않습니다.

주요 오류 형식과 코드는 API_SPEC.md의 표를 확인합니다. 기능 브랜치에서 공통 오류·상태 확인 응답 모델과 라우트별 오류 상태·헤더 메타데이터를 보완하고 OpenAPI를 갱신했습니다. 합친 구조의 `openapi.json`은 422에 실제 error·requestId 모델을 사용하며, POST 두 경로의 오류 상태를 구분합니다. 401의 WWW-Authenticate, 분석 중 503의 Retry-After 및 X-Request-ID의 실제 전달 조건을 따릅니다. 모든 503에 재시도 헤더가 있거나 프레임워크·프록시의 모든 오류가 이 오류 모델을 따른다는 뜻은 아닙니다.

## 담당자 확인이 필요한 항목

아래 항목은 이번 문서 대조로 완료 처리하지 않습니다.

- [ ] 현재 배포된 BE의 TEXT 요청 필드와 AI JSON 요청의 연결 확인
- [ ] 이미지 multipart 및 원래 analysisId·elementId·requestId 연결 확인
- [ ] 공개 DTO·FE 표시 문구·DB 저장 필드에 decision·점수·추가 검토·오류가 보존되는지 확인
- [ ] BE의 대기 시간, 동시 요청·503·504·502의 재시도 정책 합의
- [ ] 실제 요청의 AI 내부 처리 시간과 BE 전체 왕복 시간을 별도 측정

[PB23_REPORT_20261020.md](PB23_REPORT_20261020.md)는 과거 팀원이 공유한 두 입력 사례의 호출 기록입니다. 이 문서 작성에서 같은 요청을 재실행하거나 현재 FE·DB 연결을 재검증한 것은 아닙니다. 한 요청의 성공·소요 시간으로 평균·p95 성능을 일반화하지 않습니다.
