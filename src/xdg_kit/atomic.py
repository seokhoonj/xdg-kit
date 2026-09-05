"""Atomic file writes: write a temp file in the target directory, fsync it, then rename
it over the target.

A rename on the same filesystem is atomic, so a crash or a concurrent reader never sees
a half-written file, and the fsync before the rename means a crash *after* the rename
cannot leave the target pointing at unflushed bytes. The temp file is created 0600 by
``mkstemp`` and its mode is set explicitly before the rename, so a secret is never briefly
world-readable between create and ``chmod``. Two overlapping writers get distinct temp
paths, so neither corrupts the other.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from xdg_kit.errors import XdgKitError

__all__ = [
    "write_bytes_atomic",
    "write_text_atomic",
]


def write_bytes_atomic(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically, leaving it mode ``mode`` (0600 by default,
    the right mode for a secret). Creates the parent directory if needed.

    Raises:
        XdgKitError: the write failed (an I/O error); the partial temp file is removed
            first so a failed write never leaves debris beside the target.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), mode)   # POSIX: pin the mode before any bytes land
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())   # durable before the rename
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
    except OSError as err:
        raise XdgKitError(f"could not write {path}: {err}") from err


def write_text_atomic(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write ``text`` (UTF-8) to ``path`` atomically, leaving it mode ``mode``.

    Raises:
        XdgKitError: the write failed (propagated from ``write_bytes_atomic``).
    """
    write_bytes_atomic(path, text.encode("utf-8"), mode=mode)
