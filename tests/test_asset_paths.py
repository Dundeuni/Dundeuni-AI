"""Portable asset settings must not fall back to a developer's machine."""

from pathlib import Path

import pytest

from image_analysis.cure import resolve_cure_root


def test_explicit_asset_path_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("DUNDEUNI_CURE_ROOT", str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"
    assert resolve_cure_root(explicit) == explicit.resolve()


def test_asset_path_uses_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DUNDEUNI_CURE_ROOT", str(tmp_path))
    assert resolve_cure_root() == tmp_path.resolve()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_asset_setting_fails_clearly(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DUNDEUNI_CURE_ROOT", raising=False)
    else:
        monkeypatch.setenv("DUNDEUNI_CURE_ROOT", value)
    with pytest.raises(ValueError, match="DUNDEUNI_CURE_ROOT"):
        resolve_cure_root()


@pytest.mark.parametrize("explicit", [False, True])
def test_single_cli_uses_configured_root(monkeypatch, tmp_path, explicit):
    from image_analysis.__main__ import main

    args = ["image_analysis", "--mode", "cure"]
    environment_root = tmp_path / "environment"
    expected = environment_root
    monkeypatch.setenv("DUNDEUNI_CURE_ROOT", str(environment_root))
    if explicit:
        expected = tmp_path / "argument"
        args += ["--cure-root", str(expected)]
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.delenv("DUNDEUNI_AI_SERVICE_TOKEN", raising=False)
    roots = []
    monkeypatch.setattr(
        "image_analysis.cure.CureAdapter", lambda root: roots.append(root)
    )
    monkeypatch.setattr("image_analysis.__main__.create_app", lambda *a, **kw: None)
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    main()
    assert roots == [Path(expected)]


def test_single_cli_without_root_stops_before_loading(monkeypatch, capsys):
    from image_analysis.__main__ import main

    monkeypatch.setattr("sys.argv", ["image_analysis", "--mode", "cure"])
    monkeypatch.delenv("DUNDEUNI_CURE_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "DUNDEUNI_CURE_ROOT" in capsys.readouterr().err
