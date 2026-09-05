"""The cross-platform exclusive file-lock primitive: it excludes a second holder, waits
when told to block, and degrades to a no-op where the platform offers no lock."""

from __future__ import annotations

import os

import pytest

from xdg_kit import _oslock
from xdg_kit._oslock import lock_exclusive, unlock

posix_only = pytest.mark.skipif(os.name != "posix", reason="advisory file locks")


@posix_only
def test_non_blocking_second_holder_refused(tmp_path):
    path = tmp_path / "x.lock"
    first = path.open("a+")
    second = path.open("a+")
    try:
        assert lock_exclusive(first, blocking=False) is True
        assert lock_exclusive(second, blocking=False) is False   # first still holds it
        unlock(first)
        assert lock_exclusive(second, blocking=False) is True    # free now
        unlock(second)
    finally:
        first.close()
        second.close()


@posix_only
def test_blocking_acquires_when_free(tmp_path):
    """An uncontended blocking acquire returns held at once (does not exercise the wait)."""
    path = tmp_path / "x.lock"
    first = path.open("a+")
    second = path.open("a+")
    try:
        assert lock_exclusive(first, blocking=True) is True
        unlock(first)
        assert lock_exclusive(second, blocking=True) is True
        unlock(second)
    finally:
        first.close()
        second.close()


@posix_only
def test_blocking_waits_until_holder_releases(tmp_path):
    """blocking=True must genuinely WAIT for a foreign holder, not return False: while a
    child process holds the lock the parent's blocking acquire stays pending, and completes
    only once the child releases."""
    import multiprocessing as mp
    import threading

    path = tmp_path / "x.lock"
    ctx = mp.get_context("fork")
    holding = ctx.Event()   # set once the child holds the lock
    release = ctx.Event()   # parent asks the child to let go

    def child() -> None:
        handle = path.open("a+")
        lock_exclusive(handle, blocking=False)
        holding.set()
        release.wait(timeout=10)
        unlock(handle)
        handle.close()

    proc = ctx.Process(target=child)
    proc.start()
    try:
        assert holding.wait(timeout=5)   # child now holds the lock
        parent = path.open("a+")
        acquired = threading.Event()

        def block() -> None:
            lock_exclusive(parent, blocking=True)   # must wait here while the child holds it
            acquired.set()

        waiter = threading.Thread(target=block)
        waiter.start()
        assert not acquired.wait(timeout=0.5)   # still blocked -- the lock is held elsewhere
        release.set()                            # let the child release
        assert acquired.wait(timeout=5)          # the blocking acquire now completes
        waiter.join()
        unlock(parent)
        parent.close()
    finally:
        release.set()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join()


def test_windows_blocking_retries_on_deadlock_timeout(monkeypatch, tmp_path):
    """The Windows path: msvcrt.locking(LK_LOCK) raises EDEADLOCK after its bounded wait, so
    lock_exclusive must re-issue it until it succeeds -- that is what makes blocking=True a
    real wait rather than a one-shot that gives up at ~10s."""
    import errno

    calls = {"n": 0}

    class FakeMsvcrt:
        LK_LOCK = 0
        LK_NBLCK = 1
        LK_UNLCK = 2

        def locking(self, fileno: int, mode: int, nbytes: int) -> None:
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError(errno.EDEADLOCK, "lock timed out")   # two timeouts, then held
            return None

    monkeypatch.setattr(_oslock, "fcntl", None)
    monkeypatch.setattr(_oslock, "msvcrt", FakeMsvcrt())
    handle = (tmp_path / "x.lock").open("a+")
    try:
        assert lock_exclusive(handle, blocking=True) is True
        assert calls["n"] == 3   # retried through both timeouts before acquiring
    finally:
        handle.close()


def test_windows_blocking_gives_up_on_non_timeout_error(monkeypatch, tmp_path):
    """A non-timeout error (e.g. EACCES) is real: do NOT retry, return False so blocking does
    not silently spin on a permanent failure."""
    import errno

    class FakeMsvcrt:
        LK_LOCK = 0
        LK_NBLCK = 1
        LK_UNLCK = 2

        def locking(self, fileno: int, mode: int, nbytes: int) -> None:
            raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(_oslock, "fcntl", None)
    monkeypatch.setattr(_oslock, "msvcrt", FakeMsvcrt())
    handle = (tmp_path / "x.lock").open("a+")
    try:
        assert lock_exclusive(handle, blocking=True) is False
    finally:
        handle.close()


def test_no_primitive_platform_is_a_no_op(monkeypatch, tmp_path):
    """Where neither fcntl nor msvcrt exists, locking must not fail -- it succeeds as a no-op
    so the caller's own in-process guard is the only serialization."""
    monkeypatch.setattr(_oslock, "fcntl", None)
    monkeypatch.setattr(_oslock, "msvcrt", None)
    handle = (tmp_path / "x.lock").open("a+")
    try:
        assert lock_exclusive(handle, blocking=False) is True
        assert lock_exclusive(handle, blocking=True) is True
        unlock(handle)   # no-op, must not raise
    finally:
        handle.close()
