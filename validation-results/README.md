# AI 내부 응답 검증 자료

## 보존된 실행 기록

- 이미지: `dev` 커밋 `1f7a9b4`에서 189 passed (3.86초).
- 텍스트: 고정 커밋 `dce4451499edf2102e1af17f2d4a5cac5d220fd1`의 별도 추출본에서 API·OpenAPI 테스트 40 passed (9.00초). dev에 병합하지 않았다.
- 기존 XML·환경 목록은 2026-10-30 Windows Python 3.13에서 실행한 기록이다. 문서 파일명의 20261029는 업무 항목 기준일이다.
- 이미지 문서의 기존 기준은 Python 3.9, 텍스트 문서 기준은 Python 3.12다. 새 실행은 실제 사용한 버전과 함께 별도 기록하며 기존 3.13 기록을 바꾸지 않는다.
- 모델·OCR 대역을 사용하는 API 계약 테스트다. 실제 GPU·가중치·OCR·외부 URL 조회·BE/DB/FE 통합이나 탐지 성능 검증은 범위 밖이다.
- 이미지 응답 예시 JSON 7개는 `Envelope` 스키마 검증을 통과했다. 기존 Node 참조 Provider 검증은 Node 실행 파일이 없어 미수행이다.

## 1. 경로 정의

PowerShell에서 이미지 저장소 루트로 이동한 뒤 아래 블록을 같은 세션에서 순서대로 실행한다. 저장소 이름과 개인 PC 경로는 가정하지 않는다. 새 추출본·결과는 저장소 밖 고유한 임시 폴더에 저장한다. 기존 XML·환경 목록을 덮어쓰지 않는다.

```powershell
$repoRoot = (Resolve-Path '.').Path
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'src/image_analysis/schemas.py'))) {
    throw '이미지 저장소 루트에서 시작하세요.'
}
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N')
$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('pr16-validation-' + $runId)
$resultRoot = Join-Path $workRoot 'results'
$archivePath = Join-Path $workRoot 'text-source.zip'
$textCommit = 'dce4451499edf2102e1af17f2d4a5cac5d220fd1'
$textRoot = Join-Path $workRoot 'text-ai'
$imageXml = Join-Path $resultRoot 'image-tests.xml'
$textXml = Join-Path $resultRoot 'text-tests.xml'
New-Item -ItemType Directory -Path $workRoot -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path $resultRoot -ErrorAction Stop | Out-Null
```

## 2. 고정된 텍스트 소스 추출

객체가 없을 때만 기능 브랜치를 fetch한다. pull·체크아웃·병합은 하지 않는다. `git archive --output`으로 ZIP을 직접 저장하고 바이너리 파이프나 `>` 리다이렉션을 사용하지 않는다.

```powershell
git -C $repoRoot cat-file -e "${textCommit}^{commit}"
if ($LASTEXITCODE -ne 0) {
    git -C $repoRoot fetch origin feature/14-text-analysis-api
    if ($LASTEXITCODE -ne 0) { throw '텍스트 기능 브랜치 fetch 실패' }
    git -C $repoRoot cat-file -e "${textCommit}^{commit}"
    if ($LASTEXITCODE -ne 0) { throw '고정 텍스트 커밋을 찾을 수 없습니다.' }
}
git -C $repoRoot archive --format=zip --output="$archivePath" $textCommit text-ai
if ($LASTEXITCODE -ne 0) { throw '텍스트 소스 추출 실패' }
Expand-Archive -LiteralPath $archivePath -DestinationPath $workRoot -ErrorAction Stop
if (-not (Test-Path -LiteralPath (Join-Path $textRoot 'ai_text/api.py'))) {
    throw '텍스트 소스 추출 결과를 확인하세요.'
}
```

## 3. Python 환경 지정

적합한 기존 이미지·텍스트 전용 환경이 있으면 아래 질문에 각각 **본인 환경의 python.exe 실제 경로**를 입력한다. 두 테스트에 같은 Python을 묵시적으로 사용하지 않는다. 기존 학습·서비스 환경에 의존성을 덮어 설치하지 않는다.

```powershell
$imagePython = (Resolve-Path -LiteralPath (Read-Host '이미지 전용 환경의 python.exe 경로')).Path
$textPython = (Resolve-Path -LiteralPath (Read-Host '텍스트 전용 환경의 python.exe 경로')).Path
```

기존 전용 환경이 없다면 위 입력 블록 **대신** 아래 선택 블록을 실행한다. Python 3.9·3.12가 설치되어 있어야 한다. 문서 정적 검토만 할 때는 환경 생성·패키지 설치·테스트 실행이 필요 없다. 텍스트 환경 설치에는 판정 함수 import에 필요한 torch·transformers 등이 포함되지만 모델 가중치 다운로드나 추론은 하지 않는다.

```powershell
$imageVenv = Join-Path $workRoot 'image-venv'
$textVenv = Join-Path $workRoot 'text-venv'
py -3.9 -m venv "$imageVenv"
if ($LASTEXITCODE -ne 0) { throw '이미지 전용 환경 생성 실패' }
py -3.12 -m venv "$textVenv"
if ($LASTEXITCODE -ne 0) { throw '텍스트 전용 환경 생성 실패' }
$imagePython = Join-Path $imageVenv 'Scripts/python.exe'
$textPython = Join-Path $textVenv 'Scripts/python.exe'
& $imagePython -m pip install -r (Join-Path $repoRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw '이미지 의존성 설치 실패' }
& $textPython -m pip install -r (Join-Path $textRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw '텍스트 의존성 설치 실패' }
```

## 4. 테스트와 이미지 예시 7개 스키마 검증

이미지는 저장소 루트에서 전체 기존 테스트를 실행한다. 텍스트는 추출한 `$textRoot`에서 두 파일만 실행해 기존 40개 범위와 맞춘다. 전체 76개 테스트 검증과 혼동하지 않는다. 현재 폴더와 환경변수는 실패 시에도 `finally`에서 복구한다.

```powershell
$originalLocation = Get-Location
$hadPythonPath = Test-Path Env:PYTHONPATH
$originalPythonPath = $env:PYTHONPATH
try {
    Set-Location -LiteralPath $repoRoot
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $imageVersion = & $imagePython --version
    if ($LASTEXITCODE -ne 0) { throw '이미지 Python 실행 실패' }
    $imageVersion | Set-Content -LiteralPath (Join-Path $resultRoot 'image-python.txt') -Encoding UTF8
    $imagePackages = & $imagePython -m pip freeze
    if ($LASTEXITCODE -ne 0) { throw '이미지 환경 기록 실패' }
    $imagePackages | Set-Content -LiteralPath (Join-Path $resultRoot 'image-environment.txt') -Encoding UTF8
    & $imagePython -m pytest -q --junitxml="$imageXml"
    if ($LASTEXITCODE -ne 0) { throw '이미지 API 계약 테스트 실패' }

    $schemaCheck = @'
import sys
from pathlib import Path
from image_analysis.schemas import Envelope

files = sorted(p for p in Path(sys.argv[1]).glob('*.json') if p.name != 'request-description.json')
if len(files) != 7:
    raise SystemExit(f'Expected 7 response examples, found {len(files)}')
for path in files:
    Envelope.model_validate_json(path.read_text(encoding='utf-8'))
print('7 image response examples passed Envelope schema validation')
'@
    $schemaResult = & $imagePython -c $schemaCheck (Join-Path $repoRoot 'examples')
    if ($LASTEXITCODE -ne 0) { throw '이미지 응답 예시 스키마 검증 실패' }
    $schemaResult | Set-Content -LiteralPath (Join-Path $resultRoot 'image-schema.txt') -Encoding UTF8
    $schemaResult

    Set-Location -LiteralPath $textRoot
    $env:PYTHONPATH = $textRoot
    $textVersion = & $textPython --version
    if ($LASTEXITCODE -ne 0) { throw '텍스트 Python 실행 실패' }
    $textVersion | Set-Content -LiteralPath (Join-Path $resultRoot 'text-python.txt') -Encoding UTF8
    $textPackages = & $textPython -m pip freeze
    if ($LASTEXITCODE -ne 0) { throw '텍스트 환경 기록 실패' }
    $textPackages | Set-Content -LiteralPath (Join-Path $resultRoot 'text-environment.txt') -Encoding UTF8
    & $textPython -m pytest -q tests/test_text_api.py tests/test_openapi_contract.py --junitxml="$textXml"
    if ($LASTEXITCODE -ne 0) { throw '텍스트 API 계약 테스트 실패' }
}
finally {
    Set-Location -LiteralPath $originalLocation.Path
    if ($hadPythonPath) { $env:PYTHONPATH = $originalPythonPath }
    else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    Write-Output "새 결과 폴더: $resultRoot"
}
```

새 실행을 공유할 때 새 XML의 건수·실패·오류와 실제 Python 버전을 확인해 기록한다. 기존 XML의 건수·시간·환경을 새 결과에 맞춰 수정하지 않는다.
