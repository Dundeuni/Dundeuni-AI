"""Official schema-shaped synthetic data, never a real report or API call."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from phone_lookup_summary import (
    DOCUMENTATION,
    compare_thecheat_results,
    summarize_thecheat,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pb04_thecheat_response.json").read_text(
        encoding="utf-8"
    )
)


def summarize(envelope=None, content=None, **kwargs):
    return summarize_thecheat(
        deepcopy(FIXTURE["envelope"]) if envelope is None else envelope,
        deepcopy(FIXTURE["decrypted_content"]) if content is None else content,
        expected_keyword="00000000000",
        queried_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        mode=kwargs.pop("mode", "production"),
        request_reference=kwargs.pop("request_reference", "synthetic-request"),
        **kwargs,
    )


def test_schema_fixture_and_fact_projection_have_no_invented_details():
    assert FIXTURE["synthetic"] is True
    assert FIXTURE["purpose"] == "SCHEMA_TEST_ONLY_NOT_A_LIVE_LOOKUP"
    result = summarize()
    assert result.status == "COMPLETED"
    assert result.verdict == "DANGER"
    assert result.reason == "REPORT_INFORMATION_FOUND"
    assert "피해사례 등록" in result.summary
    assert result.sources[0].documentation_url == DOCUMENTATION
    assert result.sources[0].period_start == "20260803000000"
    assert result.sources[0].period_end == "20261103000000"
    assert result.sources[0].queried_at == "2026-11-03T00:00:00+00:00"
    assert "안전한 번호라는 의미는 아닙니다" in result.guidance
    encoded = json.dumps(asdict(result), ensure_ascii=False)
    for forbidden in (
        "00000000000",
        "keyword_url",
        "rawScore",
        "displayScore",
        "reportCount",
        "fraud_score",
    ):
        assert forbidden not in encoded


def test_no_information_is_not_safe_or_zero_reports():
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = "N"
    result = summarize(content=content)
    assert result.summary == "조회 범위 내 피해사례 등록 정보 없음"
    assert result.reason == "NO_CONFIRMED_REPORT_INFORMATION"
    assert result.status == "COMPLETED" and result.verdict == "NORMAL"
    assert "안전한 번호라는 의미는 아닙니다" in result.guidance
    assert "조회 기간·수집 범위" in result.limitations[0]


@pytest.mark.parametrize(
    "marker,mode", [("success (test)", "production"), ("success", "test")]
)
def test_test_database_is_never_presented_as_actual_report(marker, mode):
    envelope = deepcopy(FIXTURE["envelope"])
    envelope["result_msg"] = marker
    result = summarize(envelope=envelope, mode=mode)
    assert result.reason == "TEST_DATA"
    assert result.facts == ()
    assert result.sources[0].mode == "test"


@pytest.mark.parametrize(
    "transport,reason", [("failed", "LOOKUP_FAILED"), ("timeout", "LOOKUP_TIMEOUT")]
)
def test_transport_failures_do_not_become_absent_reports(transport, reason):
    result = summarize(transport=transport)
    assert (result.status, result.verdict, result.reason) == ("FAILED", None, reason)
    assert result.facts == ()


@pytest.mark.parametrize("code", [-1, -2, -3, -4])
def test_provider_errors_are_not_facts(code):
    result = summarize(envelope={"result_code": code, "result_msg": "SYNTHETIC_ERROR"})
    assert result.reason == "PROVIDER_REJECTED"
    assert result.verdict is None and not result.facts


@pytest.mark.parametrize(
    "field,value",
    [
        ("result_code", True),
        ("result_code", "1"),
        ("result_msg", None),
        ("result_msg", "success unknown"),
        ("content", ""),
        ("content", {}),
    ],
)
def test_invalid_envelope_types_and_unknown_success_messages(field, value):
    envelope = deepcopy(FIXTURE["envelope"])
    envelope[field] = value
    assert summarize(envelope=envelope).reason == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    "field", ["keyword", "keyword_type", "caution", "date_start", "date_end"]
)
@pytest.mark.parametrize("missing", [True, False])
def test_missing_and_null_required_content_are_rejected(field, missing):
    content = deepcopy(FIXTURE["decrypted_content"])
    if missing:
        del content[field]
    else:
        content[field] = None
    result = summarize(content=content)
    assert result.status == "FAILED" and result.facts == ()


@pytest.mark.parametrize("value", [True, 1, "yes", "", "n", [], float("nan")])
def test_caution_is_exact_provider_enum(value):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = value
    assert summarize(content=content).reason == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    "value", ["20260230000000", "20260101", "2026-11-03", 20261103]
)
def test_invalid_period(value):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["date_start"] = value
    assert summarize(content=content).reason == "INVALID_RESPONSE"


def test_reversed_period_and_cross_request_binding():
    content = deepcopy(FIXTURE["decrypted_content"])
    content["date_start"] = "20270101000000"
    assert summarize(content=content).reason == "INVALID_RESPONSE"
    content = deepcopy(FIXTURE["decrypted_content"])
    content["keyword"] = "00000000001"
    assert summarize(content=content).reason == "REQUEST_MISMATCH"
    content["keyword"] = "00000000000"
    content["keyword_type"] = "account"
    assert summarize(content=content).reason == "REQUEST_MISMATCH"


@pytest.mark.parametrize(
    "envelope,content", [(None, {}), ({}, None), ([], []), ("bad", "bad")]
)
def test_non_object_or_empty_provider_results(envelope, content):
    result = summarize_thecheat(
        envelope,
        content,
        expected_keyword="00000000000",
        queried_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        mode="production",
        request_reference="synthetic-request",
    )
    assert result.status == "FAILED"


def test_conflict_and_insufficient_evidence_preserve_both_facts():
    positive = summarize()
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = "N"
    negative = summarize(content=content)
    assert compare_thecheat_results(positive, negative) == "CONFLICTING_EVIDENCE"
    assert compare_thecheat_results(positive, positive) == "CONSISTENT"
    assert (
        compare_thecheat_results(positive, summarize(mode="test"))
        == "INSUFFICIENT_EVIDENCE"
    )
    assert (
        compare_thecheat_results(positive, summarize(transport="timeout"))
        == "INSUFFICIENT_EVIDENCE"
    )
    assert (
        compare_thecheat_results(
            positive, replace(negative, request_reference="another-request")
        )
        == "INSUFFICIENT_EVIDENCE"
    )
    content["date_start"] = "20260903000000"
    assert (
        compare_thecheat_results(positive, summarize(content=content))
        == "INSUFFICIENT_EVIDENCE"
    )


def test_untrusted_free_text_and_personal_fields_never_reach_summary():
    content = deepcopy(FIXTURE["decrypted_content"])
    content.update(
        {
            "add_info": "SYNTHETIC_UNTRUSTED_TEXT",
            "keyword_url": "https://example.invalid/private",
            "reportCount": 999,
        }
    )
    encoded = json.dumps(asdict(summarize(content=content)))
    assert "SYNTHETIC_UNTRUSTED_TEXT" not in encoded
    assert "example.invalid" not in encoded
    assert "999" not in encoded


def test_invalid_context_does_not_trigger_provider_fallback():
    with pytest.raises(ValueError):
        summarize(mode="unknown")
    with pytest.raises(ValueError):
        summarize(request_reference=None)
    with pytest.raises(ValueError):
        summarize_thecheat(
            {},
            {},
            expected_keyword="bad",
            queried_at=datetime.now(),
            mode="test",
            request_reference="synthetic",
        )


def test_comparison_rejects_missing_source_and_does_not_fuse_test_data():
    result = summarize()
    with pytest.raises(ValueError):
        compare_thecheat_results(replace(result, sources=()), result)
    source = replace(result.sources[0], mode="test")
    assert (
        compare_thecheat_results(replace(result, sources=(source,)), result)
        == "INSUFFICIENT_EVIDENCE"
    )


@pytest.mark.parametrize("caution,verdict", [("Y", "DANGER"), ("N", "NORMAL")])
def test_valid_production_mapping_at_equal_period_boundary(caution, verdict):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = caution
    content["date_start"] = content["date_end"]
    result = summarize(content=content)
    assert (result.status, result.verdict) == ("COMPLETED", verdict)
    assert result.sources[0].mode == "production"
    assert result.sources[0].period_start == result.sources[0].period_end


@pytest.mark.parametrize("caution", ["Y", "N"])
@pytest.mark.parametrize(
    "marker,mode",
    [("success (test)", "production"), ("success", "test"), ("success (test)", "test")],
)
def test_valid_enum_in_test_database_never_maps_to_risk_or_normal(
    caution, marker, mode
):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = caution
    envelope = deepcopy(FIXTURE["envelope"])
    envelope["result_msg"] = marker
    result = summarize(envelope=envelope, content=content, mode=mode)
    assert (result.status, result.verdict, result.reason) == (
        "COMPLETED",
        "INCONCLUSIVE",
        "TEST_DATA",
    )
    assert result.facts == ()


@pytest.mark.parametrize("caution", ["Y", "N"])
@pytest.mark.parametrize(
    "case,reason",
    [
        ("failed", "LOOKUP_FAILED"),
        ("timeout", "LOOKUP_TIMEOUT"),
        ("rejected", "PROVIDER_REJECTED"),
        ("mismatch", "REQUEST_MISMATCH"),
        ("invalid_period", "INVALID_RESPONSE"),
    ],
)
def test_valid_enum_cannot_override_failed_validation(caution, case, reason):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = caution
    envelope = deepcopy(FIXTURE["envelope"])
    if case == "rejected":
        envelope["result_code"] = -1
    elif case == "mismatch":
        content["keyword"] = "00000000001"
    elif case == "invalid_period":
        content["date_start"] = "20270101000000"
    result = summarize(
        envelope=envelope,
        content=content,
        transport=case if case in ("failed", "timeout") else "received",
    )
    assert (result.status, result.verdict, result.reason) == ("FAILED", None, reason)
    assert result.facts == ()


@pytest.mark.parametrize("value", ["y", " Y", "Y ", " N", "N ", "Ｎ", "Ｙ"])
def test_near_enum_values_are_not_normalized_into_verdicts(value):
    content = deepcopy(FIXTURE["decrypted_content"])
    content["caution"] = value
    result = summarize(content=content)
    assert (result.status, result.verdict, result.reason) == (
        "FAILED",
        None,
        "INVALID_RESPONSE",
    )
