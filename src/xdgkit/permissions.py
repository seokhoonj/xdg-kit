"""POSIX permission and ownership checks for the files and directories that hold
secrets.

A secret is only as private as the file it sits in. Two guards live here:

- ``warn_if_group_or_world_readable`` -- an advisory, warn-once nudge when a credentials
  file is readable beyond its owner (it should be mode 0600). It never raises: the read
  that prompted it already succeeded, and the point is to tell the user to tighten it.
- ``ensure_private_dir`` -- a hard guarantee that a directory used for private runtime
  files is owned by this user and reachable only by them (mode 0700), refusing a
  hijacked or symlinked path rather than trusting it. This matters for the
  ``XDG_RUNTIME_DIR`` fallback, which may land under a world-writable temp directory.

Both are POSIX-only: Windows does not carry these mode bits, so the checks no-op there.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from xdgkit.errors import InsecureStorageError, XdgkitError

__all__ = [
    "PRIVATE_FILE_MODE",
    "PRIVATE_DIR_MODE",
    "warn_if_group_or_world_readable",
    "ensure_private_dir",
    "restrict_dir_to_owner",
]

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700

_warned_permissive_paths: set[str] = set()


def warn_if_group_or_world_readable(path: Path, *, app: str) -> None:
    """Warn once, on stderr, when ``path`` is readable by group or others -- a secret file
    should be mode 0600. POSIX-only and best-effort: a ``stat`` failure is ignored (the
    read that called this already succeeded), and the same path warns at most once per
    process. ``app`` names the program in the message so the warning reads in its voice."""
    if os.name != "posix" or str(path) in _warned_permissive_paths:
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        _warned_permissive_paths.add(str(path))
        print(
            f"{app}: warning: {path} is accessible by group/other; "
            f"restrict it with 'chmod 600'",
            file=sys.stderr,
        )


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` as a directory reachable only by its owner (mode 0700) and return
    it, or -- when it already exists -- verify it is safe to use.

    On POSIX, an existing path must be a real directory (not a symlink), owned by this
    user; a directory we own but that is group/world-accessible is tightened to 0700
    rather than rejected. A path owned by another user, or a symlink, raises
    ``InsecureStorageError`` -- these are the shapes an attacker pre-creates to capture
    another user's secrets in a shared temp directory. A freshly created directory is
    ``chmod``-ed explicitly because ``mkdir``'s mode is masked by the process umask.

    On non-POSIX systems these bits do not apply, so the directory is simply created.

    Raises:
        InsecureStorageError: the path exists but is a symlink, is not a directory, or is
            owned by another user.
        XdgkitError: the directory could not be created (an I/O failure).
    """
    try:
        if os.name != "posix":
            path.mkdir(parents=True, exist_ok=True)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(mode=PRIVATE_DIR_MODE)
        except FileExistsError:
            _verify_private_dir(path)   # may raise InsecureStorageError (not an OSError)
            return path
        os.chmod(path, PRIVATE_DIR_MODE)   # force past the umask on the fresh directory
        return path
    except OSError as err:
        # mkdir/chmod on a read-only or exhausted filesystem raise raw OSError; convert it
        # to the documented XdgkitError so a caller told to `except XdgkitError` is honoured.
        raise XdgkitError(f"could not create private directory {path}: {err}") from err


def restrict_dir_to_owner(path: Path) -> None:
    """Best-effort: ensure ``path`` exists and, on POSIX, is not group/world-accessible
    (tightened to mode 0700 when we own it and it is loose). Unlike ``ensure_private_dir``
    this follows symlinks and never raises for a permission or ownership condition -- it is
    for the *persistent* config directory that holds ``credentials.json``, which a user may
    legitimately symlink into a synced folder, so it must not reject that. The 0600 file
    mode is the real guarantee; this just closes the ``umask 000`` gap where an otherwise
    world-writable enclosing directory would let another local user replace the file.

    A genuine failure to create the directory is left for the write that follows to
    surface (it raises the caller's error type); this stays silent."""
    try:
        if os.name != "posix":
            path.mkdir(parents=True, exist_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(mode=PRIVATE_DIR_MODE)
        except FileExistsError:
            pass
        info = path.stat()   # follow a symlink: a synced-folder target is fine
        if info.st_uid == os.getuid() and (info.st_mode & 0o077):
            os.chmod(path, PRIVATE_DIR_MODE)
    except OSError:
        pass


def _verify_private_dir(path: Path) -> None:
    """Raise ``InsecureStorageError`` unless ``path`` is a real directory owned by this
    user; tighten a directory we own that is group/world-accessible to 0700."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise InsecureStorageError(
            f"{path} is a symlink; refusing to use it for private files"
        )
    if not stat.S_ISDIR(info.st_mode):
        raise InsecureStorageError(f"{path} exists and is not a directory")
    if info.st_uid != os.getuid():
        raise InsecureStorageError(
            f"{path} is owned by uid {info.st_uid}, not this user (uid {os.getuid()})"
        )
    if info.st_mode & 0o077:
        os.chmod(path, PRIVATE_DIR_MODE)   # we own it -- tighten rather than fail
