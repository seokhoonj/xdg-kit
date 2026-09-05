"""The runtime directory: XDG_RUNTIME_DIR when set, a secured temp fallback when not."""

from __future__ import annotations

import os
import tempfile

import pytest

from xdg_kit.runtime import runtime_dir

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


def test_uses_xdg_runtime_dir_when_set(tmp_path):
    assert runtime_dir("nw", create=False) == tmp_path / "runtime" / "nw"


def test_create_makes_the_directory(tmp_path):
    path = runtime_dir("nw")
    assert path.is_dir()


@posix_only
def test_created_dir_is_0700(tmp_path):
    path = runtime_dir("nw")
    assert (path.stat().st_mode & 0o777) == 0o700


def test_create_false_has_no_side_effect(tmp_path):
    path = runtime_dir("ghost", create=False)
    assert not path.exists()


@posix_only
def test_falls_back_to_temp_when_runtime_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    # gettempdir() caches its result, so patch it directly rather than TMPDIR
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmp))
    path = runtime_dir("nw")
    assert path.is_dir()
    assert path == fake_tmp / f"xdg-kit-{os.getuid()}" / "nw"
    assert (path.stat().st_mode & 0o777) == 0o700
    assert (path.parent.stat().st_mode & 0o777) == 0o700   # per-uid root is private too
