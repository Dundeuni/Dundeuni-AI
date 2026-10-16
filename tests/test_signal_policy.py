"""Pilot score bands through HTTP: labels, nulls, failures and real map contract."""

import json
import math
import sys
from dataclasses import replace

import pytest
from conftest import request_parts
from starlette.testclient import TestClient
from test_cure_contract import ControlledCuRe

from image_analysis.adapters import MockAdapter
from image_analysis.app import ENDPOINT, create_app
from image_analysis.config import Settings
from image_analysis.cure import cure_settings
from image_analysis.trufor import dual_settings


@pytest.mark.parametrize(
    "kind,low,high,absent,suspected,absent_label,suspected_label",
    [
        (
            "generation",
            0.000004,
            0.02,
            "NO_CLEAR_GENERATION_SIGNAL",
            "AI_GENERATED_SUSPECTED",
            "뚜렷한 AI 생성 신호 없음",
            "AI 생성 의심",
        ),
        (
            "manipulation",
            0.12,
            0.70,
            "NO_CLEAR_MANIPULATION_SIGNAL",
            "MANIPULATION_SUSPECTED",
            "뚜렷한 변조 신호 없음",
            "변조 의심",
        ),
    ],
)
@pytest.mark.parametrize(
    "position",
    [
        "zero",
        "below_low",
        "low",
        "above_low",
        "below_high",
        "high",
        "above_high",
        "one",
    ],
)
def test_pilot_http_boundaries(
    headers, kind, low, high, absent, suspected, absent_label, suspected_label, position
):
    value = {
        "zero": 0.0,
        "below_low": math.nextafter(low, 0),
        "low": low,
        "above_low": math.nextafter(low, 1),
        "below_high": math.nextafter(high, 0),
        "high": high,
        "above_high": math.nextafter(high, 1),
        "one": 1.0,
    }[position]
    settings = dual_settings()
    adapters = {
        "generation": ControlledCuRe(value),
        "manipulation": MockAdapter("manipulation", value=value),
    }
    with TestClient(
        create_app(settings, adapters), client=("127.0.0.1", 50000)
    ) as client:
        response = client.post(
            ENDPOINT,
            headers=headers,
            files=request_parts(fields={"models": kind.upper()}),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    result = body[kind]
    assert result["rawScore"] == {"score": value}
    assert result["status"] == "SUCCEEDED"
    assert result["error"] is result["errorCode"] is None
    if value < low:
        assert result["decision"] == absent
        assert result["decisionLabel"] == absent_label
    elif value >= high:
        assert result["decision"] == suspected
        assert result["decisionLabel"] == suspected_label
    else:
        assert result["decision"] == "INCONCLUSIVE"
        assert result["decisionLabel"] == "판단 불가"
        assert result["displayScore"] is None
        assert result["reasons"] == []
    if value < low or value >= high:
        assert result["displayScore"] == math.floor(value * 100 + 0.5)
    assert (result["localization"] is None) == (kind == "generation")
    assert body["manipulation" if kind == "generation" else "generation"] is None


def test_default_inconclusive_is_not_model_failure(headers):
    with TestClient(
        create_app(
            dual_settings(),
            {
                "generation": ControlledCuRe(0.01),
                "manipulation": MockAdapter("manipulation", value=0.4),
            },
        ),
        client=("127.0.0.1", 50000),
    ) as client:
        body = client.post(ENDPOINT, files=request_parts(), headers=headers).json()
    assert body["status"] == "COMPLETED"
    for kind in ("generation", "manipulation"):
        assert body[kind]["decisionLabel"] == "판단 불가"
        assert body[kind]["displayScore"] is None
    assert body["manipulation"]["localization"] is not None


@pytest.mark.parametrize("failed_kind", ["generation", "manipulation"])
def test_partial_failure_preserves_inconclusive_and_label(headers, failed_kind):
    adapters = {
        "generation": ControlledCuRe(
            0.01, error="MODEL_TIMEOUT" if failed_kind == "generation" else None
        ),
        "manipulation": MockAdapter(
            "manipulation",
            value=0.4,
            failure="MODEL_TIMEOUT" if failed_kind == "manipulation" else None,
        ),
    }
    with TestClient(
        create_app(dual_settings(), adapters), client=("127.0.0.1", 50000)
    ) as client:
        body = client.post(ENDPOINT, files=request_parts(), headers=headers).json()
    assert body["status"] == "PARTIAL_FAILED"
    failed = body[failed_kind]
    assert failed["status"] == "FAILED"
    for field in (
        "decision",
        "decisionLabel",
        "rawScore",
        "displayScore",
        "localization",
    ):
        assert failed[field] is None
    assert failed["errorCode"] == failed["error"]["code"] == "MODEL_TIMEOUT"
    success = body["manipulation" if failed_kind == "generation" else "generation"]
    assert success["status"] == "SUCCEEDED"
    assert success["decisionLabel"] == "판단 불가"


@pytest.mark.parametrize(
    "field",
    [
        "generation_hold_low",
        "generation_hold_high",
        "manipulation_hold_low",
        "manipulation_hold_high",
    ],
)
@pytest.mark.parametrize("invalid", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_model_bounds_rejected(field, invalid):
    with pytest.raises(ValueError):
        replace(dual_settings(), **{field: invalid})


@pytest.mark.parametrize("kind", ["generation", "manipulation"])
def test_reversed_or_empty_interval_rejected(kind):
    for low, high in ((0.5, 0.4), (0.5, 0.5)):
        with pytest.raises(ValueError):
            replace(
                dual_settings(), **{f"{kind}_hold_low": low, f"{kind}_hold_high": high}
            )


def test_file_settings_and_policy_version_bind_model_bounds(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "mode": "CURE_TRUFOR",
                "generation_hold_low": 0.000003,
                "manipulation_hold_high": 0.8,
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.from_file(path)
    assert settings.hold_enabled
    assert settings.generation_hold_low == 0.000003
    assert settings.manipulation_hold_high == 0.8
    assert settings.policy_version != dual_settings().policy_version
    assert cure_settings().hold_enabled and dual_settings().hold_enabled
    assert cure_settings().generation_hold_low == dual_settings().generation_hold_low


def test_distinct_custom_bounds_are_used_over_shared_mock_bounds(headers):
    settings = replace(
        dual_settings(),
        generation_hold_high=0.4,
        manipulation_hold_high=0.8,
        hold_low=0.49,
        hold_high=0.51,
    )
    with TestClient(
        create_app(
            settings,
            {
                "generation": ControlledCuRe(0.5),
                "manipulation": MockAdapter("manipulation", value=0.5),
            },
        ),
        client=("127.0.0.1", 50000),
    ) as client:
        body = client.post(ENDPOINT, files=request_parts(), headers=headers).json()
    assert body["generation"]["decisionLabel"] == "AI 생성 의심"
    assert body["manipulation"]["decisionLabel"] == "판단 불가"


@pytest.mark.parametrize("configured", [False, True])
def test_dual_cli_uses_pilot_defaults_and_custom_config(
    monkeypatch, tmp_path, configured
):
    from image_analysis.__main__ import main

    args = ["image_analysis", "--mode", "cure-trufor"]
    if configured:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"generation_hold_high": 0.03, "manipulation_hold_high": 0.8}),
            encoding="utf-8",
        )
        args += ["--config", str(path)]
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setenv("DUNDEUNI_CURE_ROOT", str(tmp_path))
    monkeypatch.setenv("DUNDEUNI_TRUFOR_ROOT", str(tmp_path))
    monkeypatch.delenv("DUNDEUNI_AI_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(
        "image_analysis.cure.CureAdapter", lambda root: ControlledCuRe()
    )
    monkeypatch.setattr(
        "image_analysis.trufor.TruForAdapter", lambda root: MockAdapter("manipulation")
    )
    captured = []
    monkeypatch.setattr(
        "uvicorn.run", lambda app, **kwargs: captured.append(app.state.service.settings)
    )
    main()
    settings = captured[0]
    assert settings.mode == "CURE_TRUFOR" and settings.hold_enabled
    assert settings.generation_hold_low == 0.000004
    assert settings.manipulation_hold_low == 0.12
    assert settings.generation_hold_high == (0.03 if configured else 0.02)
    assert settings.manipulation_hold_high == (0.8 if configured else 0.70)
    assert settings.model_timeout_seconds == 120
    assert settings.response_reserve_seconds == 1
