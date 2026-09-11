"""Idempotent, fail-closed one-time relocation of a file or directory.

Used to migrate a store from an old location to a new one exactly once, without a window in
which the secret exists at two paths. It refuses a cross-filesystem move rather than falling
back to copy+unlink, which would briefly expose the secret at a second path with default
permissions and is not atomic.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

from credbox.errors import CredBoxError

__all__ = ["relocate_once"]


def relocate_once(*, old: Path, new: Path) -> bool:
    """Move ``old`` to ``new`` atomically, exactly once, and report whether this call did it.
    ``old`` and ``new`` are keyword-only: they are same-type ``Path``s and this is a destructive
    replace, so a positional transposition would reverse the move -- the keywords forbid it.

    Returns ``True`` when ``old`` existed and was moved onto ``new`` (replacing ``new`` if it
    was present); ``False`` when ``old`` does not exist -- already relocated or never there --
    so a second call is a safe no-op. The move is ``os.replace`` (atomic within a filesystem).

    Raises:
        CredBoxError: ``old`` and ``new`` are on different filesystems (``EXDEV``) -- credbox
            refuses to copy+unlink, which would briefly expose the secret at a second path;
            relocate within one filesystem instead. Also raised for any other move failure.
    """
    try:
        if not old.exists():
            return False
        new.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old, new)
    except OSError as err:
        # exists()/mkdir()/replace all inside the try so a permission or space failure preparing
        # the move surfaces as the documented CredBoxError, not a raw OSError past the contract.
        if err.errno == errno.EXDEV:
            raise CredBoxError(
                f"cannot relocate {old} to {new}: different filesystems (EXDEV); "
                f"relocate within one filesystem"
            ) from err
        raise CredBoxError(f"could not relocate {old} to {new}: {err}") from err
    return True
