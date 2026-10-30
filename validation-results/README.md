# AI 내부 응답 검증 자료

- 이미지: `dev` 커밋 `1f7a9b4`, 저장소의 `.venv` 사용.
- 텍스트: `origin/feature/14-text-analysis-api` 커밋 `dce4451499edf2102e1af17f2d4a5cac5d220fd1`의 `text-ai`를 저장소 밖 `../text-api-validation/text-ai`에 추출. 해당 폴더의 별도 `.venv` 사용. dev로 병합하지 않았다.
- 실행 Python: Windows 3.13. 이미지 README의 기존 Python 3.9 기준 재검증은 아니다.
- API 테스트는 mock/stub 모델 및 OCR 프로세스 대역을 사용한다. 실제 GPU·가중치·OCR·외부 URL 조회·BE/DB/FE 통합이나 탐지 성능을 검증하지 않는다.

이미지 저장소 루트에서:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pytest -q --junitxml=validation-results/image-tests.xml
```

텍스트 추출 폴더 `../text-api-validation/text-ai`에서:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest -q tests/test_text_api.py tests/test_openapi_contract.py --junitxml=../../Dundeuni-AI-synced/validation-results/text-tests.xml
```

`image-tests.xml`과 `text-tests.xml`은 2026-10-30 실행 결과다. 이미지 189개와 텍스트 40개 테스트가 모두 통과했다. 환경 목록은 각 `*-environment.txt`에 저장한다. 검증 문서 파일명의 20261029는 업무 항목 기준일이다.

이미지 저장 응답 JSON 7개는 현재 `Envelope` 스키마 검증을 통과했다. Node 참조 Provider 테스트는 이 환경에 Node 실행 파일이 없어 실행하지 않았다.
