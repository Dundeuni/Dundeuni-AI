# 이미지 분석 API 응답 예시

이 폴더는 합성64×48 이미지와 mock 어댑터로 생성한 요청 설명·응답 예시입니다.
모델 버전은 MOCK 접두어이며 정상 모델의 limitations에도 mock임을 표시합니다.
실제 CuRe·TruFor 추론, 실제 의심 위치 또는 성능 검증 결과가 아닙니다.

| 파일 | 모델별 상태 | 대표 분류 |
| --- | --- | --- |
| [completed.json](completed.json) | 생성·변조 모두 의심 | 생성·변조 의심 |
| [inconclusive.json](inconclusive.json) | 생성 판단 불가·변조 의심 | 생성·변조 의심 |
| [both_inconclusive.json](both_inconclusive.json) | 생성·변조 모두 판단 불가 | 판단 불가 |
| [no_clear_signal.json](no_clear_signal.json) | 두 모델 모두 뚜렷한 해당 신호 없음 | 뚜렷한 신호 없음 |
| [partial_failed.json](partial_failed.json) | 생성 의심·변조 실행 실패 | 생성·변조 의심 |
| [failed.json](failed.json) | 요청 모델 모두 실행 실패 | 판단 불가 |
| [manipulation_only.json](manipulation_only.json) | 생성 미요청·변조 의심 | 생성·변조 의심 |

[request-description.json](request-description.json)은 multipart 요청을 설명하는 JSON입니다.
이 파일을 JSON 요청 본문으로 그대로 전송하지 않습니다. 저장된 deadlineAt은 재실행 시 갱신합니다.
Bearer 값은 공개 테스트 문자열이며 운영 서비스 토큰이 아닙니다.

mock 모드는 공통 판단 불가 경계 0.4~0.6과 생성 logit 변환을 사용합니다.
이는 실제 CuRe·TruFor의 임시 threshold와 원점수 계산을 재현하는 예시가 아닙니다.
실제 CuRe는 rawScore.score를 반환하며 공식 softmax(logits)[1]을 사용합니다.
실제 TruFor는 rawScore.score를 반환하며 공식 sigmoid(det)를 한 번 적용합니다.
이 예시의 모델별 상태·대표 판정·null·오류·PNG 전달 구조만 참조합니다.

재생성은 저장소 루트의 PowerShell에서 실행합니다.

```powershell
$env:PYTHONPATH = 'src'
& '.\.venv\Scripts\python.exe' scripts/export_examples.py
```

AI 응답은 이번 호출의 결과입니다. 단일 재시도 결과는 BE의 기존 성공 결과와 병합한 뒤
세션 대표 판정을 다시 계산해야 합니다. 실제 BE 병합·저장·FE 표시 구현을 뜻하지 않습니다.
