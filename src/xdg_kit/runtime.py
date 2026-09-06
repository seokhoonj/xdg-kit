"""The session-scoped runtime directory: sockets, PID files, and locks.

``XDG_RUNTIME_DIR`` is the one XDG base directory with *no* specified default. The spec
says: "If ``$XDG_RUNTIME_DIR`` is not set applications should fall back to a replacement
directory with similar capabilities and print a warning message", and requires that the
directory "MUST be owned by the user ... its permissions MUST be 0700". On Linux a login
session sets it (typically ``/run/user/<uid>``), but headless contexts this ecosystem
runs in -- cron, containers, macOS, Windows -- often leave it unset.

So ``runtime_dir`` implements exactly that mandated fallback: when the variable is unset it
uses a per-user directory under the system temp dir, keyed to the uid so a shared
``/tmp`` cannot be hijacked, and -- unlike the other ``*_dir`` functions -- it *creates and
secures* the directory (mode 0700, owner-verified) before returning it, since a socket or
lock placed in a world-writable temp dir must not be exposed. It stays quiet rather than
printing a warning on every run, because in this ecosystem the fallback is the normal path,
not an anomaly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from xdg_kit.environment import absolute_override
from xdg_kit.paths import app_dir_segment
from xdg_kit.permissions import ensure_private_dir

__all__ = ["runtime_dir"]


def runtime_dir(app: str, *, create: bool = True) -> Path:
    """Return the directory for ``app``'s session runtime files.

    ``$XDG_RUNTIME_DIR/<app>`` when the variable is set to an absolute path; otherwise a
    uid-keyed directory under the system temp dir. With ``create=True`` (the default) the
    directory is created if absent and verified to be a real directory owned by this user
    with mode 0700 -- so a socket or lock file written inside it is reachable only by its
    owner. With ``create=False`` the path is computed and returned without touching the
    filesystem (for display), and no security guarantee is made.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment.
        InsecureStorageError: ``create`` and a directory on the path exists but is a symlink
            or owned by another user (a hijack attempt in a shared temp directory).
        XdgKitError: ``create`` and the directory could not be created.
    """
    segment = app_dir_segment(app)
    base = absolute_override("XDG_RUNTIME_DIR")
    if base is not None:
        path = base / segment
        return ensure_private_dir(path) if create else path
    path = _fallback_runtime_root() / segment
    if not create:
        return path
    ensure_private_dir(path.parent)              # secure the per-user temp root first
    return ensure_private_dir(path)


def _fallback_runtime_root() -> Path:
    """The per-user root under the system temp dir used when ``XDG_RUNTIME_DIR`` is unset:
    ``<tempdir>/xdg-kit-<uid>`` on POSIX (the uid keeps a shared ``/tmp`` from being
    hijacked), ``<tempdir>/xdg-kit`` elsewhere (Windows temp is already per-user)."""
    system_temp_dir = Path(tempfile.gettempdir())
    if os.name == "posix":
        return system_temp_dir / f"xdg-kit-{os.getuid()}"
    return system_temp_dir / "xdg-kit"
