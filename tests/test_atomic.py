"""Atomic writes: content lands, mode is honoured, a target is replaced in place."""

from __future__ import annotations

import os

import pytest

from xdg_kit.atomic import write_bytes_atomic, write_text_atomic
from xdg_kit.errors import XdgKitError

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


def test_write_text_creates_file_with_content(tmp_path):
    target = tmp_path / "sub" / "f.json"
    write_text_atomic(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'


@posix_only
def test_default_mode_is_0600(tmp_path):
    target = tmp_path / "secret"
    write_text_atomic(target, "k")
    assert (target.stat().st_mode & 0o777) == 0o600


@posix_only
def test_explicit_mode_is_applied(tmp_path):
    target = tmp_path / "public"
    write_bytes_atomic(target, b"data", mode=0o644)
    assert (target.stat().st_mode & 0o777) == 0o644


def test_replaces_existing_atomically(tmp_path):
    target = tmp_path / "f"
    write_text_atomic(target, "old")
    write_text_atomic(target, "new")
    assert target.read_text() == "new"
    # no temp debris left beside the target
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_failure_wrapped(tmp_path):
    # a path whose parent is a file, not a directory, cannot be written
    parent_is_file = tmp_path / "afile"
    parent_is_file.write_text("x")
    with pytest.raises(XdgKitError):
        write_text_atomic(parent_is_file / "child", "data")


def test_replace_failure_cleans_up_and_leaves_target(tmp_path, monkeypatch):
    target = tmp_path / "f"
    write_text_atomic(target, "old")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr("xdg_kit.atomic.os.replace", boom)
    with pytest.raises(XdgKitError):
        write_text_atomic(target, "new")
    assert target.read_text() == "old"            # original untouched
    assert list(tmp_path.glob("*.tmp")) == []     # no secret-bearing temp debris left


def test_fdopen_failure_wraps_and_cleans_up(tmp_path, monkeypatch):
    # if os.fdopen never adopts the mkstemp fd, the raw fd must be closed (no leak) and the
    # temp file removed; the failure surfaces as XdgKitError
    def boom(fd, *args, **kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr("xdg_kit.atomic.os.fdopen", boom)
    with pytest.raises(XdgKitError):
        write_bytes_atomic(tmp_path / "f", b"data")
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_body_failure_cleans_up_temp(tmp_path, monkeypatch):
    # a failure after the temp file is opened (here fsync, standing in for any mid-write I/O
    # error) must still remove the secret-bearing temp file and surface as XdgKitError
    def boom(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr("xdg_kit.atomic.os.fsync", boom)
    with pytest.raises(XdgKitError):
        write_bytes_atomic(tmp_path / "f", b"secret-data")
    assert list(tmp_path.glob("*.tmp")) == []


@posix_only
def test_fchmod_pins_mode_before_first_write(tmp_path, monkeypatch):
    # the mode must be pinned before any secret bytes land, so the temp file never holds the
    # secret at a mode wider than requested, even briefly
    events: list[str] = []
    real_fchmod = os.fchmod
    real_fdopen = os.fdopen

    def recording_fchmod(fd, mode):
        events.append("fchmod")
        return real_fchmod(fd, mode)

    class _RecordingHandle:
        def __init__(self, handle):
            self._handle = handle

        def write(self, data):
            events.append("write")
            return self._handle.write(data)

        def __getattr__(self, attr):
            return getattr(self._handle, attr)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._handle.__exit__(*exc)

    monkeypatch.setattr("xdg_kit.atomic.os.fchmod", recording_fchmod)
    monkeypatch.setattr("xdg_kit.atomic.os.fdopen", lambda fd, *a, **k: _RecordingHandle(real_fdopen(fd, *a, **k)))
    write_bytes_atomic(tmp_path / "f", b"secret")
    assert events[0] == "fchmod" and events.index("fchmod") < events.index("write")
