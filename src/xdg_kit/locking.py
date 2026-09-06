"""A best-effort single-instance lock, so two runs of the same job do not overlap.

Overlapping runs -- a cron job and a manual one, or two crons -- can double-spend a paid
API, deliver duplicates, and race on shared state. A ``FileLock`` holds an exclusive
advisory lock on a file in ``runtime_dir(app)`` (where the XDG spec says locks belong) for
as long as it is held, and reports whether it was acquired, so a caller can skip a run
already in progress rather than pile on.

Built on ``fcntl.flock`` (POSIX) and ``msvcrt.locking`` (Windows) via ``_oslock`` -- both
released by the OS automatically when the process exits, even on a crash, so there is no
stale lock to clean up. On a platform with neither, it is a no-op that always acquires.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

from xdg_kit._oslock import lock_exclusive, unlock
from xdg_kit.errors import XdgKitError
from xdg_kit.paths import app_dir_segment
from xdg_kit.runtime import runtime_dir

__all__ = [
    "FileLock",
    "single_instance",
]


class FileLock:
    """An exclusive, non-blocking advisory lock named ``name`` for ``app``, held on a file
    in ``runtime_dir(app)``. Acquire it, check ``acquired``, and release it -- or use it as
    a context manager. Re-acquiring or releasing when not held is safe."""

    acquired: bool   # whether this lock is currently held (public: callers read it)

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

    def __repr__(self) -> str:
        return f"FileLock(app={self._app!r}, name={self._name!r}, acquired={self.acquired})"

    def acquire(self) -> bool:
        """Try to take the lock without blocking. Returns ``True`` if taken, ``False`` if
        another process already holds it. Idempotent while held.

        Raises:
            XdgKitError: the lock file could not be opened, or (propagated from
                ``runtime_dir``) the runtime directory could not be created.
            InsecureStorageError: the runtime directory exists but is unsafe (propagated
                from ``runtime_dir``).
        """
        if self.acquired:
            return True
        path = runtime_dir(self._app) / f"{self._name}.lock"
        try:
            handle = path.open("a+")   # a+ suits both flock and msvcrt; never truncates a holder's file
        except OSError as err:
            raise XdgKitError(f"could not open lock file {path}: {err}") from err
        if not lock_exclusive(handle, blocking=False):
            handle.close()
            return False   # another process holds it
        self._handle = handle
        self.acquired = True
        return True

    def release(self) -> None:
        """Release the lock and close its file. A no-op when not held."""
        handle = self._handle
        if handle is not None:
            try:
                unlock(handle)
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
        XdgKitError / InsecureStorageError: propagated from ``runtime_dir``.
    """
    lock = FileLock(app, name)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        lock.release()
