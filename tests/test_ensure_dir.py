"""Tests for the general ``ensure_dir`` primitive and its ``private=True`` path."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from credbox.errors import InsecureStorageError
from credbox.permissions import ensure_dir

_POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits only")


def test_ensure_dir_creates_missing_directory_and_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    assert ensure_dir(target) == target
    assert target.is_dir()


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "d"
    ensure_dir(target)
    assert ensure_dir(target) == target   # no raise on second call


@_POSIX_ONLY
def test_ensure_dir_private_creates_0700(tmp_path: Path) -> None:
    target = tmp_path / "private"
    ensure_dir(target, private=True)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


@_POSIX_ONLY
def test_ensure_dir_private_rejects_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(InsecureStorageError):
        ensure_dir(link, private=True)
