from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    retryable: bool


MESSAGES = {
    "INVALID_REQUEST": "요청 필드 또는 형식이 올바르지 않습니다.",
    "AUTHENTICATION_FAILED": "서비스 인증을 확인할 수 없습니다.",
    "FORBIDDEN_CALLER": "호출 권한이 없습니다.",
    "PAYLOAD_TOO_LARGE": "파일 또는 요청 본문 제한을 초과했습니다.",
    "IMAGE_LIMIT_EXCEEDED": "이미지 크기 제한을 초과했습니다.",
    "UNSUPPORTED_IMAGE_FORMAT": "JPEG·PNG 단일 이미지와 일치하는 MIME이 필요합니다.",
    "INVALID_IMAGE": "이미지 파일을 디코딩할 수 없습니다.",
    "IMAGE_TOO_SMALL": "이미지의 최소 크기를 충족하지 못했습니다.",
    "DEADLINE_EXPIRED": "요청 마감 시각이 이미 지났습니다.",
    "AI_BUSY": "현재 분석 슬롯이 사용 중입니다.",
    "MODEL_UNAVAILABLE": "선택 모델 구성이 준비되지 않았습니다.",
    "INTERNAL_ERROR": "정상 분석 응답을 작성하지 못했습니다.",
    "MODEL_TIMEOUT": "모델의 실행 제한 시간을 초과했습니다.",
    "REQUEST_DEADLINE_EXCEEDED": "요청의 응답 마감 예산이 소진되었습니다.",
    "MODEL_OUT_OF_MEMORY": "모델 실행 중 메모리가 부족했습니다.",
    "MODEL_RUNTIME_UNAVAILABLE": "모델 실행기를 안전하게 복구하지 못했습니다.",
    "MODEL_OUTPUT_INVALID": "모델의 필수 출력이 유효하지 않습니다.",
    "MODEL_EXECUTION_FAILED": "모델 실행을 완료하지 못했습니다.",
}
RETRYABLE = {
    "AI_BUSY",
    "MODEL_UNAVAILABLE",
    "INTERNAL_ERROR",
    "MODEL_TIMEOUT",
    "REQUEST_DEADLINE_EXCEEDED",
    "MODEL_OUT_OF_MEMORY",
    "MODEL_RUNTIME_UNAVAILABLE",
}


def error_info(code: str) -> ErrorInfo:
    return ErrorInfo(code=code, message=MESSAGES[code], retryable=code in RETRYABLE)


@dataclass
class TransportError(Exception):
    status_code: int
    code: str


@dataclass
class ModelFailure(Exception):
    code: str
