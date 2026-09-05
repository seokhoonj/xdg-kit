"""A best-effort single-instance lock, so two runs of the same job do not overlap.

Overlapping runs -- a cron job and a manual one, or two crons -- can double-spend a paid
API, deliver duplicates, and race on shared state. A ``FileLock`` holds an exclusive
advisory lock on a file in ``runtime_dir(app)`` (where the XDG spec says locks belong) for
as long as it is held, and reports whether it was acquired, so a caller can skip a run
already in progress rather than pile on.

Built on ``fcntl.flock`` (POSIX) and ``msvcrt.locking`` (Windows) -- both released by the OS
automatically when the process exits, even on a crash, so there is no stale lock to clean
up. On a platform with neither, it is a no-op that always acquires.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

from xdgkit.paths import app_dir_segment
from xdgkit.runtime import runtime_dir

try:
    import fcntl
except ImportError:   # non-POSIX
    fcntl = None      # type: ignore[assignment]

try:
    import msvcrt
except ImportError:   # non-Windows
    msvcrt = None     # type: ignore[assignment]

__all__ = [
    "FileLock",
    "single_instance",
]


class FileLock:
    """An exclusive, non-blocking advisory lock named ``name`` for ``app``, held on a file
    in ``runtime_dir(app)``. Acquire it, check ``acquired``, and release it -- or use it as
    a context manager. Re-acquiring or releasing when not held is safe."""

    def __init__(self, app: str, name: str) -> None:
        """Bind to an ``app`` and a lock ``name``. Both are validated as safe path segments
        here (fail-fast), so a crafted ``name`` such as ``"../escape"`` cannot place the
        ``.lock`` file outside the runtime directory.

        Raises:
            InvalidAppNameError: ``app`` or ``name`` is not a valid directory segment.
        """
        self._app = app_dir_segment(app)
        self._name = app_dir_segment(name)
        self._handle: IO[str] | None = None
        self.acquired = False

    def acquire(self) -> bool:
        """Try to take the lock without blocking. Returns ``True`` if taken, ``False`` if
        another process already holds it. Idempotent while held.

        Raises:
            XdgkitError / InsecureStorageError: the runtime directory could not be created
                or secured (propagated from ``runtime_dir``).
        """
        if self.acquired:
            return True
        path = runtime_dir(self._app) / f"{self._name}.lock"
        if _is_windows() and msvcrt is not None:
            handle = path.open("a+")   # no truncate: leave a holder's region undisturbed
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            except OSError:
                handle.close()
                return False
            self._handle = handle
            self.acquired = True
            return True
        if fcntl is not None:
            handle = path.open("w")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            except OSError:
                handle.close()
                return False
            self._handle = handle
            self.acquired = True
            return True
        self.acquired = True   # no advisory lock available on this platform
        return True

    def release(self) -> None:
        """Release the lock and close its file. A no-op when not held."""
        handle = self._handle
        if handle is not None:
            try:
                if _is_windows() and msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
                elif fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            finally:
                handle.close()
                self._handle = None
        self.acquired = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


@contextmanager
def single_instance(app: str, name: str) -> Iterator[bool]:
    """Hold a ``FileLock`` for the block and yield whether it was acquired -- ``True`` to
    proceed, ``False`` when another process already holds it (the caller should skip its
    run). Convenience over ``FileLock``.

    Raises:
        InvalidAppNameError: ``app`` or ``name`` is not a valid directory segment.
        XdgkitError / InsecureStorageError: propagated from ``runtime_dir``.
    """
    lock = FileLock(app, name)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        lock.release()


def _is_windows() -> bool:
    return os.name == "nt"
