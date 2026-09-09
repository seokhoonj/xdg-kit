"""Tests for environment reading and app-name env-var folding."""

from __future__ import annotations

from pathlib import Path

import pytest

from credbox.environment import (
    colliding_env_var_prefixes,
    env_value,
    env_var_prefix,
    read_absolute_path_override,
)


def test_env_value_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDBOX_TEST_VAR", raising=False)
    assert env_value("CREDBOX_TEST_VAR") is None


def test_env_value_treats_blank_and_whitespace_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_TEST_VAR", "   ")
    assert env_value("CREDBOX_TEST_VAR") is None


def test_env_value_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_TEST_VAR", "  hello  ")
    assert env_value("CREDBOX_TEST_VAR") == "hello"


def test_absolute_override_returns_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREDBOX_TEST_DIR", str(tmp_path))
    assert read_absolute_path_override("CREDBOX_TEST_DIR") == tmp_path


def test_absolute_override_ignores_a_relative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_TEST_DIR", "relative/dir")
    assert read_absolute_path_override("CREDBOX_TEST_DIR") is None


def test_absolute_override_expands_a_leading_tilde(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CREDBOX_TEST_DIR", "~/sub")
    assert read_absolute_path_override("CREDBOX_TEST_DIR") == tmp_path / "sub"


def test_env_var_prefix_folds_and_uppercases() -> None:
    assert env_var_prefix("my-app") == "MY_APP"
    assert env_var_prefix("a.b_c") == "A_B_C"
    assert env_var_prefix("plain") == "PLAIN"


def test_colliding_env_var_prefixes_reports_only_collisions() -> None:
    result = colliding_env_var_prefixes(["a-b", "a.b", "a_b", "solo"])
    assert result == {"A_B": ["a-b", "a.b", "a_b"]}
