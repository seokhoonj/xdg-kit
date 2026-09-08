"""Atomic writes: content lands, mode is honoured, a target is replaced in place."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from xdg_kit.atomic import write_bytes_atomic, write_text_atomic
from xdg_kit.errors import XdgKitError

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


def test_write_text_creates_file_with_content(tmp_path):
    target = tmp_path / "sub" / "f.json"
    write_text_atomic(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'


def test_non_encodable_text_raises_before_write(tmp_path):
    # a lone surrogate is not encodable as UTF-8; write_text_atomic surfaces the caller
    # error as UnicodeEncodeError (not wrapped as XdgKitError) before touching the disk
    target = tmp_path / "f"
    with pytest.raises(UnicodeEncodeError):
        write_text_atomic(target, "\ud800")
    assert not target.exists()   # the failure happens before any filesystem operation


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


def test_cleanup_unlink_failure_does_not_mask_original_error(tmp_path, monkeypatch):
    # if os.replace fails AND the best-effort temp cleanup also fails, the ORIGINAL write
    # error must still surface (wrapped as XdgKitError) -- the cleanup error must not mask it
    target = tmp_path / "f"
    real_unlink = Path.unlink

    def boom_replace(src, dst):
        raise OSError(errno.EIO, "replace failed")

    def boom_unlink(self, *args, **kwargs):
        if self.suffix == ".tmp":               # only the temp file's cleanup fails
            raise OSError(errno.EACCES, "unlink failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr("xdg_kit.atomic.os.replace", boom_replace)
    monkeypatch.setattr("xdg_kit.atomic.Path.unlink", boom_unlink)
    with pytest.raises(XdgKitError) as exc_info:
        write_bytes_atomic(target, b"data")
    # the wrapped cause is the replace failure (EIO), not the cleanup unlink failure (EACCES)
    assert isinstance(exc_info.value.__cause__, OSError)
    assert exc_info.value.__cause__.errno == errno.EIO


def test_write_succeeds_without_fchmod(tmp_path, monkeypatch):
    # on a platform without os.fchmod (e.g. Windows), the mode is simply not pinned via
    # fchmod; the write must still complete and land the content
    target = tmp_path / "f"
    monkeypatch.delattr("xdg_kit.atomic.os.fchmod", raising=False)
    write_bytes_atomic(target, b"data", mode=0o600)
    assert target.read_bytes() == b"data"


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


def _track_directory_fds(monkeypatch, dir_fds: set[int]) -> None:
    """Wrap ``os.open`` so every directory opened by the atomic writer lands in ``dir_fds``.

    The patch is global -- ``tempfile._os is os``, so ``tempfile.mkstemp``'s own file open
    is intercepted too -- but the ``os.path.isdir(path)`` filter records only directory
    descriptors, and the writer opens a directory only in ``_fsync_dir`` (after the rename,
    once the file's own fd is already closed). So a fd later reused for the directory is
    never mistaken for the file: the file fsync runs while ``dir_fds`` is still empty."""
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if os.path.isdir(path):
            dir_fds.add(fd)
        return fd

    monkeypatch.setattr("xdg_kit.atomic.os.open", recording_open)


@posix_only
def test_directory_is_fsynced_after_replace(tmp_path, monkeypatch):
    # the containing directory must be fsync'd after the rename so the rename itself is
    # durable across a crash, not only the file contents
    target = tmp_path / "sub" / "f"
    dir_fds: set[int] = set()
    fsynced_dir_fds: list[int] = []
    real_fsync = os.fsync
    _track_directory_fds(monkeypatch, dir_fds)

    def recording_fsync(fd):
        if fd in dir_fds:
            fsynced_dir_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr("xdg_kit.atomic.os.fsync", recording_fsync)
    write_bytes_atomic(target, b"data")
    assert target.read_bytes() == b"data"
    assert fsynced_dir_fds, "containing directory was not fsync'd after the rename"


@posix_only
def test_directory_fsync_real_error_propagates_leaving_target(tmp_path, monkeypatch):
    # a genuine durability failure (EIO) on the directory fsync must surface as XdgKitError:
    # swallowing it would report a non-durable write as done. The target is already replaced
    # (the rename completed before the dir fsync), so the write is durable-uncertain, not lost.
    target = tmp_path / "f"
    dir_fds: set[int] = set()
    real_fsync = os.fsync
    _track_directory_fds(monkeypatch, dir_fds)

    def failing_fsync(fd):
        if fd in dir_fds:               # fail only the directory fsync; the file fsync ran first
            raise OSError(errno.EIO, "I/O error")
        return real_fsync(fd)

    monkeypatch.setattr("xdg_kit.atomic.os.fsync", failing_fsync)
    with pytest.raises(XdgKitError):
        write_bytes_atomic(target, b"data")
    assert target.read_bytes() == b"data"   # atomicity holds: the new bytes are in place


@posix_only
def test_directory_fsync_unsupported_is_ignored(tmp_path, monkeypatch):
    # a filesystem that cannot fsync a directory (EINVAL) must not fail the write -- the
    # rename already succeeded and the platform offers no stronger guarantee
    target = tmp_path / "f"
    dir_fds: set[int] = set()
    fsync_fired = False
    real_fsync = os.fsync
    _track_directory_fds(monkeypatch, dir_fds)

    def einval_fsync(fd):
        nonlocal fsync_fired
        if fd in dir_fds:
            fsync_fired = True
            raise OSError(errno.EINVAL, "invalid argument")
        return real_fsync(fd)

    monkeypatch.setattr("xdg_kit.atomic.os.fsync", einval_fsync)
    write_bytes_atomic(target, b"data")   # must not raise
    assert fsync_fired, "the injected EINVAL branch never ran -- the test is vacuous"
    assert target.read_bytes() == b"data"


@posix_only
def test_directory_open_error_propagates(tmp_path, monkeypatch):
    # a real error opening the directory for fsync (EACCES here; also EMFILE, EIO) is NOT a
    # "platform cannot fsync dirs" case -- it must surface, symmetric with the fsync branch,
    # rather than silently report a possibly-non-durable write as done
    target = tmp_path / "f"
    open_fired = False
    real_open = os.open

    def refusing_open(path, flags, *args, **kwargs):
        nonlocal open_fired
        if os.path.isdir(path):
            open_fired = True
            raise OSError(errno.EACCES, "cannot open directory")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("xdg_kit.atomic.os.open", refusing_open)
    with pytest.raises(XdgKitError):
        write_bytes_atomic(target, b"data")
    assert open_fired, "the injected directory-open failure never ran -- the test is vacuous"
    assert target.read_bytes() == b"data"   # atomicity holds even though the sync was refused


@posix_only
def test_directory_open_unsupported_is_ignored(tmp_path, monkeypatch):
    # symmetric with the fsync branch: an "unsupported" errno on the directory *open*
    # (EINVAL) is tolerated, so the write succeeds. This is defensive symmetry -- in practice
    # a real "cannot fsync a directory" surfaces at the fsync, not the open -- so the branch
    # is exercised here by injection rather than by a real filesystem.
    target = tmp_path / "f"
    open_fired = False
    real_open = os.open

    def unsupported_open(path, flags, *args, **kwargs):
        nonlocal open_fired
        if os.path.isdir(path):
            open_fired = True
            raise OSError(errno.EINVAL, "invalid argument")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("xdg_kit.atomic.os.open", unsupported_open)
    write_bytes_atomic(target, b"data")   # must not raise
    assert open_fired, "the injected directory-open EINVAL branch never ran -- the test is vacuous"
    assert target.read_bytes() == b"data"


def test_non_posix_skips_directory_fsync(tmp_path, monkeypatch):
    # on a non-POSIX platform there is no directory fsync; the writer must not even attempt
    # to open the directory, and the write still succeeds. `_IS_POSIX` is flipped (not the
    # shared `os.name`, which would break pathlib elsewhere in the run), so this runs on any OS.
    target = tmp_path / "f"
    opened_dirs: list[str] = []
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):
        if os.path.isdir(path):
            opened_dirs.append(str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("xdg_kit.atomic._IS_POSIX", False)
    monkeypatch.setattr("xdg_kit.atomic.os.open", recording_open)
    write_bytes_atomic(target, b"data")
    assert target.read_bytes() == b"data"
    assert opened_dirs == [], "a non-POSIX write must not open the directory for fsync"
