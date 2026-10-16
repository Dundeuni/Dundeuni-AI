"""HTTP representative verdicts with independently controlled model outputs."""

from itertools import product

import pytest
from conftest import request_parts
from starlette.testclient import TestClient
from test_cure_contract import ControlledCuRe

from image_analysis.adapters import MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.overall import make_overall_result
from image_analysis.schemas import Envelope
from image_analysis.trufor import dual_settings

STATES = ("suspected", "absent", "inconclusive", "failed", "unrequested")
CASES = [
    pair for pair in product(STATES, repeat=2) if pair != ("unrequested", "unrequested")
]


@pytest.mark.parametrize("generation,manipulation", CASES)
def test_overall_http_combinations_preserve_model_results(
    headers, generation, manipulation
):
    generation_score = {"suspected": 0.02, "absent": 0.000003}.get(generation, 0.01)
    manipulation_score = {"suspected": 0.70, "absent": 0.119}.get(manipulation, 0.4)
    selection = (
        "MANIPULATION"
        if generation == "unrequested"
        else "GENERATION"
        if manipulation == "unrequested"
        else "ALL"
    )
    with TestClient(
        create_app(
            dual_settings(),
            {
                "generation": ControlledCuRe(
                    generation_score,
                    error="MODEL_TIMEOUT" if generation == "failed" else None,
                ),
                "manipulation": MockAdapter(
                    "manipulation",
                    value=manipulation_score,
                    failure="MODEL_TIMEOUT" if manipulation == "failed" else None,
                ),
            },
        ),
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(fields={"models": selection}),
        )
    assert response.status_code == 200
    body = response.json()
    Envelope.model_validate(body)
    states = {"generation": generation, "manipulation": manipulation}
    expected = (
        ("GENERATION_OR_MANIPULATION_SUSPECTED", "생성·변조 의심")
        if "suspected" in states.values()
        else ("NO_CLEAR_SIGNAL", "뚜렷한 신호 없음")
        if generation == manipulation == "absent"
        else ("INCONCLUSIVE", "판단 불가")
    )
    overall = body["overallResult"]
    assert (overall["decision"], overall["decisionLabel"]) == expected
    assert overall["policyVersion"] == "image-overall-v1"
    assert overall["suspectedKinds"] == [
        kind for kind, state in states.items() if state == "suspected"
    ]
    assert overall["uncertainKinds"] == [
        kind
        for kind, state in states.items()
        if state in ("failed", "inconclusive", "unrequested")
    ]
    failures = list(states.values()).count("failed")
    requested = 2 - list(states.values()).count("unrequested")
    assert body["status"] == (
        "COMPLETED"
        if failures == 0
        else "FAILED"
        if failures == requested
        else "PARTIAL_FAILED"
    )
    for kind, state in states.items():
        result = body[kind]
        if state == "unrequested":
            assert result is None
        elif state == "failed":
            assert result["status"] == "FAILED"
            assert result["decision"] is result["decisionLabel"] is None
            assert result["rawScore"] is result["displayScore"] is None
            assert result["errorCode"] == result["error"]["code"] == "MODEL_TIMEOUT"
        else:
            assert result["status"] == "SUCCEEDED"
            assert result["rawScore"] == {
                "score": generation_score
                if kind == "generation"
                else manipulation_score
            }
            assert result["policyVersion"] == dual_settings().policy_version
            assert result["errorCode"] is result["error"] is None
            assert (result["displayScore"] is None) == (state == "inconclusive")
            assert (result["localization"] is None) == (kind == "generation")
    assert "score" not in overall and "displayScore" not in overall


def test_retry_recomputes_after_merging_preserved_results(headers):
    app = create_app(
        dual_settings(),
        {
            "generation": ControlledCuRe(0.02),
            "manipulation": MockAdapter("manipulation", value=0.1),
        },
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        first = Envelope.model_validate(
            client.post(ENDPOINT, headers=headers, files=request_parts()).json()
        )
        retry = Envelope.model_validate(
            client.post(
                ENDPOINT,
                headers=headers,
                files=request_parts(fields={"models": "MANIPULATION"}),
            ).json()
        )
    assert retry.generation is None
    assert retry.overallResult.decision == "INCONCLUSIVE"
    assert retry.overallResult.uncertainKinds == ["generation"]
    before = first.generation.model_dump()
    merged = make_overall_result(first.generation, retry.manipulation)
    assert merged.decision == "GENERATION_OR_MANIPULATION_SUSPECTED"
    assert merged.suspectedKinds == ["generation"]
    assert first.generation.model_dump() == before


def test_no_result_cannot_be_called_no_signal():
    result = make_overall_result(None, None)
    assert result.decision == "INCONCLUSIVE"
    assert result.uncertainKinds == ["generation", "manipulation"]
