"""Tests for the idempotent, fail-closed one-time relocation helper."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from credbox.errors import CredBoxError
from credbox.relocation import relocate_once


def test_relocate_moves_source_and_reports_true(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    old.write_text("payload")
    new = tmp_path / "sub" / "new.json"
    assert relocate_once(old, new) is True
    assert not old.exists()
    assert new.read_text() == "payload"


def test_relocate_missing_source_reports_false(tmp_path: Path) -> None:
    assert relocate_once(tmp_path / "absent", tmp_path / "new") is False


def test_relocate_is_idempotent_on_second_call(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.write_text("x")
    new = tmp_path / "new"
    assert relocate_once(old, new) is True
    assert relocate_once(old, new) is False   # already relocated -> no-op


def test_relocate_replaces_an_existing_target(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.write_text("fresh")
    new = tmp_path / "new"
    new.write_text("stale")
    assert relocate_once(old, new) is True
    assert new.read_text() == "fresh"


def test_relocate_across_filesystems_raises_rather_than_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    old.write_text("secret")
    new = tmp_path / "new"

    def _exdev(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

    monkeypatch.setattr("credbox.relocation.os.replace", _exdev)
    with pytest.raises(CredBoxError):
        relocate_once(old, new)
    assert old.exists()   # never copy+unlinked
