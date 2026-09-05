"""Directory resolution: XDG variables, home fallback, per-app overrides, and the
app-name guard against path traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

from xdg_kit.paths import app_dir_segment, cache_dir, config_dir, data_dir, state_dir


def test_config_dir_uses_xdg_config_home(tmp_path):
    assert config_dir("newswatcher") == tmp_path / "config" / "newswatcher"


def test_each_kind_has_its_own_base(tmp_path):
    assert data_dir("nw") == tmp_path / "data" / "nw"
    assert state_dir("nw") == tmp_path / "state" / "nw"
    assert cache_dir("nw") == tmp_path / "cache" / "nw"


def test_falls_back_to_home_when_xdg_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config_dir("nw") == tmp_path / "home" / ".config" / "nw"


def test_relative_xdg_value_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")   # spec: a relative base is ignored
    assert config_dir("nw") == tmp_path / "home" / ".config" / "nw"


def test_per_app_data_dir_override_wins_and_is_used_as_is(monkeypatch, tmp_path):
    elsewhere = tmp_path / "big-disk" / "archive"
    monkeypatch.setenv("NW_DATA_DIR", str(elsewhere))
    assert data_dir("nw") == elsewhere   # no app segment appended


def test_override_env_var_folds_punctuation(monkeypatch, tmp_path):
    elsewhere = tmp_path / "vol"
    monkeypatch.setenv("OPENDART_CLIENT_DATA_DIR", str(elsewhere))
    assert data_dir("opendart-client") == elsewhere


def test_config_dir_has_no_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NW_CONFIG_DIR", str(tmp_path / "ignored"))
    assert config_dir("nw") == tmp_path / "config" / "nw"


@pytest.mark.parametrize("good", ["nw", "newswatcher", "opendart-client", "kis-trader", "a.b_c"])
def test_valid_app_names_pass(good):
    assert app_dir_segment(good) == good


@pytest.mark.parametrize("bad", ["", ".", "..", "../etc", "a/b", "a\\b", "/abs", "-lead", "trail-", "sp ace"])
def test_traversal_and_junk_names_rejected(bad):
    with pytest.raises(ValueError):
        app_dir_segment(bad)


def test_bad_app_name_rejected_by_dir_functions(bad="../../etc"):
    with pytest.raises(ValueError):
        config_dir(bad)


def test_absolute_xdg_value_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    assert data_dir("nw") == tmp_path / "xdgdata" / "nw"
    assert isinstance(config_dir("nw"), Path)
