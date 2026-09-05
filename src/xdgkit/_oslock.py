"""One cross-platform exclusive file-lock primitive, shared by the two callers that need
it: ``locking.FileLock`` (a non-blocking single-instance guard) and ``backends`` (a
blocking serializer around a store's read-modify-write).

Built on ``fcntl.flock`` (POSIX) and ``msvcrt.locking`` (Windows) -- both released by the
OS automatically when the process exits, even on a crash, so there is no stale lock to
clean up. On a platform with neither, locking is a no-op that always "succeeds", leaving
the caller's own in-process guard as the only serialization.

The caller owns the lock file (where it lives, how it is opened); this module only takes
and releases the lock on an already-open handle.
"""

from __future__ import annotations

from typing import IO

try:
    import fcntl
except ImportError:   # non-POSIX
    fcntl = None      # type: ignore[assignment]

try:
    import msvcrt
except ImportError:   # non-Windows
    msvcrt = None     # type: ignore[assignment]

__all__ = [
    "lock_exclusive",
    "unlock",
]


def lock_exclusive(handle: IO[str], *, blocking: bool) -> bool:
    """Take an exclusive lock on ``handle``. With ``blocking=True`` wait until it is free;
    with ``blocking=False`` return ``False`` at once when another holder has it. Returns
    ``True`` once the lock is held -- always ``True`` where no OS primitive exists."""
    if fcntl is not None:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle, flags)
        except OSError:
            return False
        return True
    if msvcrt is not None:
        handle.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            msvcrt.locking(handle.fileno(), mode, 1)
        except OSError:
            return False
        return True
    return True


def unlock(handle: IO[str]) -> None:
    """Release the lock taken by ``lock_exclusive`` on ``handle``; a no-op where no OS
    primitive exists."""
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_UN)
    elif msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
