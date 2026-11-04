# PB-04 실제 조회 요구사항·제공자 조사 및 사실 요약

조사일: 2026-11-03 (KST). 주기능 번호 조회, 상세 신고·스팸 DB/API 조회, 우선순위 P1.
2026-11-04 리뷰 반영: 유효한 운영 Y/N에만 위험/정상을 매핑한다.
N은 **조회 범위 내 피해사례 등록 정보 없음**이며 절대적인 안전을 뜻하지 않는다.
아래는 공식 문서 기준이며 실제 계정 권한·과금·국내 데이터 품질은 확인하지 못했다.

## 공식 API 비교

| 후보 | 제공 정보 | 인증·이용 조건 | 무료 여부·현재 판단 |
| --- | --- | --- | --- |
| 더치트 사기이력조회 v2 | 전화번호의 피해사례 등록 여부 Y/N, 조회 기간. 개별 사건·신고 건수는 문서 응답에 없음 | 기업 회원·사업자 등록·앱 등록, X-TheCheat-ApiKey와 ENC Key, 허용 IP 및 제휴 확인 필요 | 비제휴는 테스트 DB. 운영 무료 사용·요금은 확인되지 않음. 국내 요구사항에 가까우나 권한 확인 전 실제 연동 불가 |
| IPQualityScore Phone Validation | spammer, recent_abuse, risky, 제공자 점수 등. 국내 신고 원문·건수 제공 근거 없음 | 계정/API 키. IPQS-KEY 헤더도 지원, 기능별 요금제·추가 활성화 조건 존재 | 무료 계정·매월 무료 크레딧 안내 있음. 구체 쿼터·필드 접근·한국 품질 확인 필요. 현재 키 없음 |
| Truecaller Number Verification | 사용자 번호 인증 기능. 임의 번호의 신고 DB 조회 계약으로 볼 수 없음 | 개발자 등록·플랫폼 연동. 공식 지원 페이지는 2026-04-01부터 상용 전환 안내 | 무료 스팸 조회 API로 채택할 근거 없음. 번호 인증 SDK를 이 요구사항에 대체 적용하지 않음 |

근거 문서:

- [더치트 소개](https://apidocs.thecheat.co.kr/docs/intro/)
- [더치트 준비사항](https://apidocs.thecheat.co.kr/docs/api-prerequisite/)
- [더치트 인증·복호화](https://apidocs.thecheat.co.kr/docs/api-usage/api-common/)
- [더치트 조회 형식·테스트 DB 구분](https://apidocs.thecheat.co.kr/docs/api-usage/api-search-plain/)
- [더치트 API 센터·요금 안내 진입점](https://apicenter.thecheat.co.kr/)
- [IPQS 개요·응답 예시](https://www.ipqualityscore.com/documentation/phone-number-validation-api/overview)
- [IPQS 필드 정의](https://www.ipqualityscore.com/documentation/phone-number-validation-api/response-parameters)
- [IPQS 인증 대안](https://www.ipqualityscore.com/documentation/phone-number-validation-api/advanced-options)
- [IPQS 무료 계정 안내](https://www.ipqualityscore.com/create-account/phone-validation)
- [Truecaller 번호 인증 FAQ](https://developer.truecaller.com/phone-number-verification/faq)
- [Truecaller 지원·상용화 안내](https://developer.truecaller.com/support)

약관 동의·제휴 신청·계정 생성·구매는 수행하지 않았다. 무료 크레딧이 운영 재배포나
모든 필드 이용 권한을 보장하지 않는다. 더치트도 운영 결과 표시·보관 권한은 계약 확인이 필요하다.

## 저장소·환경 조사

AI에는 기존 합성 실험 모듈만 있고 BE dev에는 PHONE API·DB 유형이 없다.
로컬 AI/BE 최상위 .env 계열 파일과 현재 프로세스의 전화번호 관련 변수 이름을
확인했다. AI에는 .env 파일이 없고 BE에는 .env.example만 있으며 관련 키 설정은 없었다.
BE 인프라 원격 브랜치에는 OPENAPI_SERVICE_KEY 예시 설정과 Phone OpenAPI 설명이 있지만
제공자 식별·권한·실제 키의 존재를 입증하지 않는다. 키 값은 문서에 기록하지 않는다.
배포 플랫폼의 Secret 및 다른 담당자 환경은 확인하지 못했다.

## 이번 구현 경계

src/phone_lookup_summary.py는 더치트 공식 v2의 envelope와 BE가 복호화한 content를
받는 독립 순수 함수다. 실제 HTTP·인증·복호화·DB·FastAPI 라우트는 추가하지 않는다.
기존 phone_policy_experiment.py는 추상 합성 정책 검사로 유지하며 실제 응답 파서로
재사용하지 않는다. 두 모듈 모두 점수·신고 이력을 생성하지 않는 원칙을 따른다.

BE 책임:

1. 기업·제휴·실제 DB 권한·요금·허용 IP 확인, API/ENC 키 안전한 관리.
2. 번호 형식 검증·정규화·요청 연계 ID 생성, 외부 요청·timeout·재시도·사용량 처리.
3. 공식 방식의 응답 복호화 후 JSON 검증, 조회 대상과 응답의 일치 확인.
4. 키·원번호·암호문·개인 조회 URL·외부 메시지의 로그 노출 방지.
5. 필요한 공개 API·저장·동의·보관·삭제 정책 구현 및 AI 호출/공유 코드 실행 위치 협의.

AI 파트의 함수 입력:

- envelope: result_code(int), result_msg(str), 성공 시 암호문 content(str).
- decrypted_content: keyword, keyword_type=phone, caution=Y/N, date_start/date_end.
- expected_keyword: BE가 조회한 번호. 출력에 보존하지 않으며 재일치 검사에만 사용.
- queried_at: timezone-aware datetime. BE가 실제 완료 시각을 전달해야 함.
- mode: production/test. 권한·환경을 확인한 BE가 전달. 입력만으로 실제 권한을 검증하지 못함.
- request_reference: 원번호가 아닌 BE의 불투명 요청 연계 ID.
- transport: received/failed/timeout. 외부 호출을 수행하거나 성공을 추정하지 않음.

출력은 로컬 dataclass이며 최종 공개 JSON 계약은 미확정이다. 필드 화이트리스트로
출처·조회 기간·요약·한계·안내만 반환한다. 알려지지 않은 제공자 필드는 무시한다.
개인정보를 포함할 수 있는 keyword_url/add_info 및 result_msg 원문은 출력하지 않는다.
필수 자료형·Y/N·기간 형식/역전·요청 대상 불일치를 검증한다. 잘못된 외부 응답은
FAILED, 잘못된 호출 컨텍스트는 ValueError다. 빈 객체·누락을 자료 없음으로 바꾸지 않는다.

| 입력 의미 | 결과 |
| --- | --- |
| 유효한 운영 응답 caution=Y | DANGER(위험). 조회 범위 내 피해사례 등록 정보 확인. 범죄 확정 아님 |
| 유효한 운영 응답 caution=N | NORMAL(정상). 조회 범위 내 피해사례 등록 정보 없음. 절대적 안전·신고 0건 보장 아님 |
| success (test) 또는 test mode | INCONCLUSIVE / TEST_DATA, 실제 확인 사실은 빈 목록. Y/N이어도 위험·정상 분류 금지 |
| 외부 실패/timeout | FAILED 및 별도 원인. verdict=null, 확인 사실 없음 |
| 잘못된 형식·요청 불일치 | FAILED, 확인 사실 없음 |

이 매핑은 PR #19 리뷰 요청에 따른 단일 제공자 조회의 로컬 분류다. 공개 JSON 계약은
여전히 미확정이며, 기존 추상 합성 정책의 NO_DATA·INSUFFICIENT_EVIDENCE·
CONFLICTING_EVIDENCE·POLICY_UNCONFIRMED 처리를 대체하지 않는다. 빈 객체나 누락을
N으로 취급하지 않으며, 모든 검증을 통과한 운영 응답에만 적용한다.

compare_thecheat_results는 동일 요청 연계 ID·조회 기간의 Y/N 상충을 표시할 뿐
어느 쪽이 옳은지 결정하거나 위험 점수를 합성하지 않는다. 기간이 다르거나 테스트·실패가
섞이면 근거 부족으로 반환한다. BE는 동일 ID가 실제 같은 대상을 뜻하도록 보장해야 한다.
조회 기간의 시간대와 최신성 유효기간은 공식 형식만으로 확정할 수 없어 한계로 보존한다.

## LLM 필요 여부

현재 응답은 등록 여부·기간뿐이므로 규칙 기반 문구로 충분하다. 개별 신고 내용이 없는
응답에서 사건 유형을 생성할 수 없다. LLM·외부 모델 호출은 추가하지 않는다.
향후 내용 제공 API를 채택하더라도 출처·검증 여부·개인정보·인용 범위를 먼저 정의해야 한다.

## 테스트와 미완료

tests/fixtures/pb04_thecheat_response.json은 공식 형식을 따른 합성 데이터다.
000으로 시작하는 비실사용 번호와 가짜 암호문 표지만 사용하며 암호화·실제 DB 조회를
검증하지 않는다. production 모드 테스트도 함수 분기 검사이며 운영 조회 성공의 증거가 아니다.
기존 추상 fixture 10개도 그대로 보존한다.

최초 구현 검증 기록: 전체 pytest 298개 통과(기존 252개 + 신규 46개), Ruff 전체 lint 통과,
신규 Python 파일 포맷 검사 통과, mypy 19개 소스 통과, git diff --check 통과.
이 수치는 로컬 합성 검증이며 실제 조회·복호화·운영 데이터 정확도 검증이 아니다.

2026-11-04 Y/N 매핑 검증: 기존 테스트의 기대 판정을 갱신하고 25개 사례를 추가했다.
운영 Y/N·동일 시작/종료 기간, 테스트 DB의 모든 모드 조합, 실패·시간 초과·제공자 거부·
번호 불일치·역전 기간, 소문자·공백·전각 enum을 검사한다. 전체 pytest 323개 통과,
Ruff 전체 lint 및 mypy 19개 소스 통과. 모두 합성 응답 기반 검사다.

실제 API 키·권한이 확인되지 않아 외부 조회는 수행하지 않았다. 제품 연동 완료 아님.
제공자 선정·계약/키 확인·BE 구현·실제 응답 통합 테스트·국내 데이터 품질 평가·정책 및
공개 결과 계약 합의가 PB-04 전체 완료를 위해 남아 있다. 이미지 분석 코드는 변경하지 않는다.
