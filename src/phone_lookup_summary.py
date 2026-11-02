"""Fact-only THECHEAT v2 response projection; no HTTP, decryption or risk score.

BE must authenticate/decrypt and bind the response to its request before calling.
This module checks the binding again, but cannot prove transport authenticity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

DOCUMENTATION = "https://apidocs.thecheat.co.kr/docs/api-usage/api-search-plain/"
GUIDANCE = (
    "안전한 번호라는 의미는 아닙니다. 송금·개인정보 제공 전 상대를 별도로 확인하세요."
)


@dataclass(frozen=True)
class LookupSource:
    provider: Literal["THECHEAT"]
    documentation_url: str
    queried_at: str
    period_start: Optional[str]
    period_end: Optional[str]
    mode: Literal["production", "test"]


@dataclass(frozen=True)
class PhoneLookupSummary:
    """Candidate local projection, not an approved public API contract."""

    status: Literal["COMPLETED", "FAILED"]
    verdict: Optional[Literal["INCONCLUSIVE"]]
    reason: str
    summary: str
    facts: tuple[str, ...]
    sources: tuple[LookupSource, ...]
    limitations: tuple[str, ...]
    request_reference: str
    guidance: str = GUIDANCE


def summarize_thecheat(
    envelope: object,
    decrypted_content: object,
    *,
    expected_keyword: str,
    queried_at: datetime,
    mode: Literal["production", "test"],
    request_reference: str,
    transport: Literal["received", "failed", "timeout"] = "received",
) -> PhoneLookupSummary:
    """Validate official envelope and BE-decrypted content without retaining PII.

    Caller mistakes in context raise ValueError. Broken provider data produces
    FAILED. No data means caution=N in a valid production response, not an empty
    object, missing field, error or zero score. Test responses never supply facts.
    """
    if (
        type(expected_keyword) is not str
        or not expected_keyword
        or not expected_keyword.isascii()
        or not expected_keyword.isdecimal()
        or len(expected_keyword) > 32
    ):
        raise ValueError("expected keyword must be an ASCII digit string")
    if (
        not isinstance(queried_at, datetime)
        or queried_at.tzinfo is None
        or queried_at.utcoffset() is None
    ):
        raise ValueError("queried_at must be timezone-aware")
    if (
        type(request_reference) is not str
        or not request_reference
        or len(request_reference) > 128
    ):
        raise ValueError("request_reference must be an opaque request identifier")
    if mode not in ("production", "test") or transport not in (
        "received",
        "failed",
        "timeout",
    ):
        raise ValueError("unsupported lookup context")
    source = LookupSource(
        "THECHEAT", DOCUMENTATION, queried_at.isoformat(), None, None, mode
    )

    def failed(reason: str) -> PhoneLookupSummary:
        return PhoneLookupSummary(
            "FAILED",
            None,
            reason,
            "전화번호 정보를 확인하지 못했습니다.",
            (),
            (source,),
            ("조회 실패를 신고 정보 없음으로 해석할 수 없습니다.",),
            request_reference,
        )

    if transport != "received":
        return failed("LOOKUP_TIMEOUT" if transport == "timeout" else "LOOKUP_FAILED")
    if not isinstance(envelope, dict):
        return failed("INVALID_RESPONSE")
    code = envelope.get("result_code")
    message = envelope.get("result_msg")
    if type(code) is not int or type(message) is not str:
        return failed("INVALID_RESPONSE")
    if code != 1:
        return failed("PROVIDER_REJECTED")
    if (
        message not in ("success", "success (test)")
        or type(envelope.get("content")) is not str
        or not envelope["content"]
        or not isinstance(decrypted_content, dict)
    ):
        return failed("INVALID_RESPONSE")
    content = decrypted_content
    if (
        content.get("keyword_type") != "phone"
        or content.get("keyword") != expected_keyword
    ):
        return failed("REQUEST_MISMATCH")
    caution = content.get("caution")
    if type(caution) is not str or caution not in ("Y", "N"):
        return failed("INVALID_RESPONSE")
    dates = []
    for key in ("date_start", "date_end"):
        value = content.get(key)
        if (
            type(value) is not str
            or len(value) != 14
            or not value.isascii()
            or not value.isdecimal()
        ):
            return failed("INVALID_RESPONSE")
        try:
            dates.append(datetime.strptime(value, "%Y%m%d%H%M%S"))
        except ValueError:
            return failed("INVALID_RESPONSE")
    if dates[0] > dates[1]:
        return failed("INVALID_RESPONSE")
    # Timezone for provider period is unspecified in the public contract.
    effective_mode: Literal["production", "test"] = (
        "test" if message == "success (test)" or mode == "test" else "production"
    )
    source = LookupSource(
        "THECHEAT",
        DOCUMENTATION,
        queried_at.isoformat(),
        content["date_start"],
        content["date_end"],
        effective_mode,
    )
    limitations = (
        "더치트의 해당 조회 기간·수집 범위에 한정된 결과입니다.",
        "피해사례 등록 여부는 범죄 확정이나 현재 발신자의 신원 확인이 아닙니다.",
        "개별 신고 내용·건수는 이 API 응답으로 확인할 수 없습니다.",
        "위험 단계 기준은 미확정입니다. "
        "조회 기간의 시간대·자료 최신성은 별도 확인이 필요합니다.",
    )
    if effective_mode == "test":
        return PhoneLookupSummary(
            "COMPLETED",
            "INCONCLUSIVE",
            "TEST_DATA",
            "테스트 DB 결과입니다.",
            (),
            (source,),
            limitations + ("실제 신고 정보로 사용할 수 없습니다.",),
            request_reference,
        )
    fact = (
        "더치트 조회에서 해당 기간의 피해사례 등록 정보가 확인되었습니다."
        if caution == "Y"
        else "확인된 신고 정보 없음"
    )
    return PhoneLookupSummary(
        "COMPLETED",
        "INCONCLUSIVE",
        "REPORT_INFORMATION_FOUND"
        if caution == "Y"
        else "NO_CONFIRMED_REPORT_INFORMATION",
        fact,
        (fact,),
        (source,),
        limitations,
        request_reference,
    )


def compare_thecheat_results(
    first: PhoneLookupSummary, second: PhoneLookupSummary
) -> str:
    """Compare same-target results (binding is BE's responsibility), no fusion.

    Different windows, test data or failures cannot establish contradiction.
    No cross-number inference or final risk classification is performed.
    """
    for result in (first, second):
        if not isinstance(result, PhoneLookupSummary) or len(result.sources) != 1:
            raise ValueError("expected a single-source phone lookup summary")
    usable = {"REPORT_INFORMATION_FOUND", "NO_CONFIRMED_REPORT_INFORMATION"}
    if first.request_reference != second.request_reference:
        return "INSUFFICIENT_EVIDENCE"
    if first.reason not in usable or second.reason not in usable:
        return "INSUFFICIENT_EVIDENCE"
    a, b = first.sources[0], second.sources[0]
    if (
        first.status != "COMPLETED"
        or second.status != "COMPLETED"
        or a.mode != "production"
        or b.mode != "production"
    ):
        return "INSUFFICIENT_EVIDENCE"
    if (a.period_start, a.period_end) != (b.period_start, b.period_end):
        return "INSUFFICIENT_EVIDENCE"
    return "CONFLICTING_EVIDENCE" if first.reason != second.reason else "CONSISTENT"
