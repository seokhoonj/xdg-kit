"""Tests for layout selection, including the import-safety guarantee (a malformed
``CREDBOX_LAYOUT`` must not raise)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from credbox import layout as layout_mod
from credbox.layout import default_layout, set_default_layout


@pytest.fixture(autouse=True)
def _reset_override() -> Iterator[None]:
    """Each test starts with no process-wide override set."""
    saved = layout_mod._override
    layout_mod._override = None
    yield
    layout_mod._override = saved


def test_default_is_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDBOX_LAYOUT", raising=False)
    assert default_layout() == "xdg"


def test_env_selects_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_LAYOUT", "native")
    assert default_layout() == "native"


def test_env_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_LAYOUT", "NATIVE")
    assert default_layout() == "native"


def test_malformed_env_does_not_raise_and_defaults_to_xdg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDBOX_LAYOUT", "banana")
    assert default_layout() == "xdg"


def test_malformed_env_falls_through_to_set_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_LAYOUT", "banana")
    set_default_layout("native")
    assert default_layout() == "native"


def test_set_default_layout_is_used_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDBOX_LAYOUT", raising=False)
    set_default_layout("native")
    assert default_layout() == "native"


def test_valid_env_overrides_set_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDBOX_LAYOUT", "xdg")
    set_default_layout("native")
    assert default_layout() == "xdg"


def test_set_default_layout_rejects_an_unknown_value() -> None:
    from credbox.errors import CredBoxError, InvalidLayoutError

    # The rejection is InvalidLayoutError -- a (CredBoxError, ValueError) subclass -- so it is
    # caught by BOTH the package-wide `except CredBoxError` surface (errors.py's contract: "every
    # error credbox raises on purpose derives from CredBoxError") and a plain `except ValueError`.
    with pytest.raises(InvalidLayoutError):
        set_default_layout("cloud")  # type: ignore[arg-type]
    with pytest.raises(CredBoxError):
        set_default_layout("cloud")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        set_default_layout("cloud")  # type: ignore[arg-type]
