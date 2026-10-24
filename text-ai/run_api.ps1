param(
    [int]$Port = 8000,
    [string]$BindAddress = '127.0.0.1'
)
$ErrorActionPreference = 'Stop'
if (-not $env:AI_SERVICE_TOKEN) {
    throw 'AI_SERVICE_TOKEN을 설정하세요. 예: $env:AI_SERVICE_TOKEN = [guid]::NewGuid().ToString("N")'
}
$apiPython = Join-Path $PSScriptRoot '.venv-v2\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $apiPython)) { throw '.venv-v2 Python을 찾을 수 없습니다.' }
& $apiPython -X utf8 -m uvicorn ai_text.api:app --app-dir $PSScriptRoot --host $BindAddress --port $Port --workers 1 --limit-concurrency 8 --no-access-log
exit $LASTEXITCODE
