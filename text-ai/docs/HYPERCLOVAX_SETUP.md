# HyperCLOVAX 직접 텍스트 분석

ECoG 방식으로 7에폭 추가학습한 HyperCLOVAX `checkpoint-18669`를 기존 `POST /internal/v1/text-analyses`에 연결합니다. 직접 입력과 붙여넣기를 지원합니다. 이 실행 모드에서 OCR 경로를 호출하면 HTTP 503과 `OCR_UNAVAILABLE`을 반환합니다.

## 준비

1. [Windows 설치·실행](INSTALL_WINDOWS.md#2-api분류기-환경-만들기)에 따라 API·분류기용 `.venv-v2`를 준비합니다.
2. 팀에서 전달받은 `checkpoint-18669` 폴더에 모델 가중치, 모델 설정, 토크나이저 파일, `instruction.txt`가 있는지 확인합니다. 가중치는 별도로 전달받습니다.

## 서버 실행

PowerShell에서 저장소의 `text-ai` 폴더를 열고 실행합니다. 모델 경로를 전달받은 폴더로 바꿉니다.

```powershell
$env:AI_TEXT_MODEL_DIR = 'C:\models\checkpoint-18669'
$env:AI_TEXT_DEVICE = 'cpu'
$env:AI_URL_REPUTATION_ENABLED = '0'
$env:AI_SERVICE_TOKEN = Read-Host '서비스 토큰' -MaskInput
.\.venv-v2\Scripts\python.exe -m uvicorn ai_text.hyperclovax_api:app --host 127.0.0.1 --port 8765
```

CUDA를 지원하는 PyTorch 환경에서는 `AI_TEXT_DEVICE`를 `cuda`로 지정합니다. HyperCLOVAX는 CPU와 CUDA에서 FP32로 실행합니다. BE와 연동할 때는 BE가 사용하는 서비스 토큰을 입력합니다.

## 호출 확인

별도 PowerShell에서 서버와 같은 서비스 토큰을 입력합니다.

```powershell
$base = 'http://127.0.0.1:8765'
Invoke-RestMethod "$base/healthz" | Select-Object status, modelVersion, device

$token = Read-Host '서버에 설정한 서비스 토큰' -MaskInput
$headers = @{ Authorization = "Bearer $token" }
$messages = @(
    '[택배] 주문하신 상품이 오늘 오후 2시에 문 앞에 배송되었습니다.'
    '[택배] 배송지 오류로 반송 예정입니다. 지금 아래 링크에서 주소와 카드 정보를 입력하세요. https://parcel-check.invalid/verify'
)
foreach ($message in $messages) {
    $body = @{ text = $message } | ConvertTo-Json -Compress
    Invoke-RestMethod "$base/internal/v1/text-analyses" -Method Post `
        -Headers $headers -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) |
        Select-Object modelVersion, decision, riskScore
}
```

`/healthz`에서 `status=ready`와 `modelVersion=checkpoint-18669`를 확인합니다. 예시 문자의 판정은 각각 `normal`과 `phishing`입니다. 서비스 토큰을 빼고 요청하면 HTTP 401이 반환됩니다.
