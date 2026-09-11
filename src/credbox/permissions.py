"""POSIX permission and ownership checks for the files and directories that hold secrets.

A secret is only as private as the file it sits in. The guards here:

- ``warn_if_group_or_world_readable`` -- an advisory, warn-once nudge when a credentials file
  is readable beyond its owner (it should be mode 0600). It never raises: the read that
  prompted it already succeeded, and the point is to tell the user to tighten it.
- ``ensure_private_dir`` -- a hard guarantee that a directory used for private files is owned
  by this user and reachable only by them (mode 0700), refusing a hijacked or symlinked path
  rather than trusting it. This matters for the ``XDG_RUNTIME_DIR`` fallback under a
  world-writable temp directory.
- ``ensure_dir`` -- the general "make this directory exist" primitive, with an optional
  ``private=True`` that delegates to ``ensure_private_dir``.
- ``restrict_dir_to_owner`` -- best-effort tightening of the persistent config directory.

All the mode-bit checks are POSIX-only: Windows does not carry these bits, so they no-op there
and access follows the per-user directory ACL instead (documented; credbox makes no 0600/0700
guarantee on NTFS).
"""

from __future__ import annotations

import os
import stat
import sys
import threading
from pathlib import Path

from credbox.errors import CredBoxError, InsecureStorageError

__all__ = [
    "PRIVATE_FILE_MODE",
    "PRIVATE_DIR_MODE",
    "warn_if_group_or_world_readable",
    "warn_if_group_or_world_accessible",
    "ensure_dir",
    "ensure_private_dir",
    "restrict_dir_to_owner",
]

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700

_warned_permissive_paths: set[str] = set()
_warn_lock = threading.Lock()


def warn_if_group_or_world_readable(path: Path, *, app: str) -> bool:
    """Return whether the credentials *file* ``path`` is readable by group or others (insecure -- a
    secret file should be mode 0600), warning once per path. See ``_warn_if_permissive`` for the
    shared contract (POSIX-only, best-effort, warn-once, return reflects the live state)."""
    if os.name != "posix":
        return False
    return _warn_if_permissive(path, app=app, chmod="600")


def warn_if_group_or_world_accessible(directory: Path, *, app: str) -> bool:
    """Return whether the config *directory* holding a credentials file is reachable by group or
    others (insecure -- it should be mode 0700), warning once per path. The directory sibling of
    ``warn_if_group_or_world_readable``: same POSIX-only, best-effort, warn-once contract, so the
    ``& 0o077`` policy lives in one place instead of being re-authored by each caller."""
    if os.name != "posix" or not directory.is_dir():
        return False
    return _warn_if_permissive(directory, app=app, chmod="700")


def _warn_if_permissive(path: Path, *, app: str, chmod: str) -> bool:
    """Shared core of the two warn-if-* guards. Return whether ``path`` is accessible beyond its
    owner (``& 0o077``), printing a ``chmod <chmod>`` nudge the first time each path is seen. The
    RETURN reflects the actual permission state on every call (so a caller like ``doctor`` can key
    an exit code off it), independent of the once-per-path print. A ``stat`` failure returns
    ``False``. ``app`` names the program so the warning reads in its voice."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if not mode & 0o077:
        return False   # safe path: the common case takes no lock, so reads never serialize
    # Insecure. Record-and-print under the lock so two threads seeing the same permissive path
    # cannot both print, but return True regardless of whether this call was the one that printed.
    key = str(path)
    with _warn_lock:
        already_warned = key in _warned_permissive_paths
        _warned_permissive_paths.add(key)
    if not already_warned:
        # A file/dir path is not a secret value; the warning names it so the user can fix it.
        print(
            f"{app}: warning: {path} is accessible by group/other; restrict it with 'chmod {chmod}'",
            file=sys.stderr,
        )
    return True


def ensure_dir(path: Path, *, private: bool = False) -> Path:
    """Create ``path`` (and its parents) if absent and return it.

    With ``private=True`` this delegates to ``ensure_private_dir`` -- the directory is created
    mode 0700 and, if it already exists, verified to be a real directory owned by this user
    (a symlink or another user's directory raises ``InsecureStorageError``). With
    ``private=False`` (the default) it is an ordinary ``mkdir(parents=True, exist_ok=True)``.

    Raises:
        InsecureStorageError: ``private`` and the existing path is a symlink, not a directory,
            or owned by another user.
        CredBoxError: the directory could not be created (an I/O failure).
    """
    if private:
        return ensure_private_dir(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise CredBoxError(f"could not create directory {path}: {err}") from err
    return path


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` as a directory reachable only by its owner (mode 0700) and return it,
    or -- when it already exists -- verify it is safe to use.

    On POSIX, an existing path must be a real directory (not a symlink), owned by this user; a
    directory we own but that is group/world-accessible is tightened to 0700 rather than
    rejected. A path owned by another user, or a symlink, raises ``InsecureStorageError`` --
    the shapes an attacker pre-creates to capture another user's secrets in a shared temp
    directory. A freshly created directory is ``chmod``-ed explicitly because ``mkdir``'s mode
    is masked by the process umask. On non-POSIX systems these bits do not apply, so the
    directory is simply created.

    Raises:
        InsecureStorageError: the path exists but is a symlink, is not a directory, or is
            owned by another user.
        CredBoxError: the directory could not be created (an I/O failure).
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
        raise CredBoxError(f"could not create private directory {path}: {err}") from err


def restrict_dir_to_owner(path: Path) -> None:
    """Best-effort: ensure ``path`` exists and, on POSIX, is not group/world-accessible
    (tightened to mode 0700 when we own it and it is loose). Unlike ``ensure_private_dir`` this
    follows symlinks and never raises for a permission or ownership condition -- it is for the
    *persistent* config directory that holds ``credentials.json``, which a user may legitimately
    symlink into a synced folder, so it must not reject that. The 0600 file mode is the real
    guarantee; this just closes the ``umask 000`` gap where an otherwise world-writable
    enclosing directory would let another local user replace the file.

    A genuine failure to create the directory is left for the write that follows to surface
    (it raises the caller's error type); this stays silent."""
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
    """Raise ``InsecureStorageError`` unless ``path`` is a real directory owned by this user;
    tighten a directory we own that is group/world-accessible to 0700."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise InsecureStorageError(f"{path} is a symlink; refusing to use it for private files")
    if not stat.S_ISDIR(info.st_mode):
        raise InsecureStorageError(f"{path} exists and is not a directory")
    if info.st_uid != os.getuid():
        raise InsecureStorageError(
            f"{path} is owned by uid {info.st_uid}, not this user (uid {os.getuid()})"
        )
    if info.st_mode & 0o077:
        # Bounded TOCTOU: this chmod follows symlinks and runs after the lstat above, so a swap
        # of `path` for a symlink in between would retarget it. The window is closed in practice
        # for the runtime fallback -- its parent is a 0700 directory we own under the sticky-bit
        # system temp dir, where another user cannot rename our directory away.
        os.chmod(path, PRIVATE_DIR_MODE)   # we own it -- tighten rather than fail
