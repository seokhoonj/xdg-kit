"""Where a secret is physically stored, behind one small interface.

``SecretBackend`` is the seam: given an app and a secret name, read, write, remove, or
list. Two implementations ship:

- ``FileBackend`` (the default) -- a flat ``name -> value`` JSON map in
  ``credentials.json`` under ``config_dir(app)``, written atomically at mode 0600 in a
  directory tightened to 0700. It is the reliable base everywhere: no OS session, no
  network, portable across machines, and it works the same headless as on a desktop.
- ``KeyringBackend`` (opt-in) -- the OS secure store, via the ``keyring`` package. Because
  a login keyring has no backend in headless contexts (cron, containers, servers), it
  takes a ``fallback`` (normally a ``FileBackend``) and delegates the whole operation to it
  whenever ``keyring`` is missing or non-functional -- warning once so the user learns
  their secrets are in the file, not the keyring they asked for. When ``keyring`` *is*
  functional it is authoritative, and a successful write/delete also clears any stale
  plaintext copy from the fallback, so opting into the keyring does not leave (or later
  resurrect) a file copy.

The store an app reads is chosen by *name* (``config_dir(app)``), so one app can read
another's store -- that is how a shared store lets a common key live in one place (see
``credentials``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Protocol

from xdgkit.atomic import write_text_atomic
from xdgkit.errors import CredentialsError, XdgkitError
from xdgkit.paths import config_dir
from xdgkit.permissions import (
    PRIVATE_FILE_MODE,
    restrict_dir_to_owner,
    warn_if_group_or_world_readable,
)

__all__ = [
    "SecretBackend",
    "FileBackend",
    "KeyringBackend",
    "default_backend",
]

CREDENTIALS_FILE = "credentials.json"

_warned_keyring_fallback = False


class SecretBackend(Protocol):
    """The store interface every backend implements. ``get`` returns the stored value or
    ``None`` when the store or key is absent; ``set`` and ``unset`` mutate it; ``names``
    lists the stored keys (never their values). ``value`` is keyword-only so it can never
    be swapped with ``name`` positionally -- a swap would store the secret *as a key
    name*."""

    def get(self, app: str, name: str) -> str | None: ...
    def set(self, app: str, name: str, *, value: str) -> None: ...
    def unset(self, app: str, name: str) -> None: ...
    def names(self, app: str) -> list[str]: ...


class FileBackend:
    """Secrets in ``credentials.json`` (a flat JSON object) under ``config_dir(app)``,
    written atomically at mode 0600 in a directory tightened to 0700."""

    def path(self, app: str) -> Path:
        """The credentials file for ``app``: ``credentials.json`` in ``config_dir(app)``."""
        return config_dir(app) / CREDENTIALS_FILE

    def get(self, app: str, name: str) -> str | None:
        """Return the value stored under ``name``, or ``None`` when the file or key is
        absent (or the value is not a non-empty string). Warns once if the file is
        readable beyond its owner.

        Raises:
            CredentialsError: the file exists but is unreadable, not JSON, or not a JSON
                object.
        """
        return _clean(self._load(app).get(name))

    def set(self, app: str, name: str, *, value: str) -> None:
        """Store ``value`` under ``name``, creating or updating the file at mode 0600 in a
        0700 directory.

        Raises:
            CredentialsError: the existing file is unreadable or malformed, or the write
                failed.
        """
        secret_value_by_name = self._load(app)
        secret_value_by_name[name] = value
        self._save(app, secret_value_by_name)

    def unset(self, app: str, name: str) -> None:
        """Remove ``name`` from the file if present; a no-op when the file or key is
        absent.

        Raises:
            CredentialsError: the existing file is unreadable or malformed, or the write
                failed.
        """
        secret_value_by_name = self._load(app)
        if name in secret_value_by_name:
            del secret_value_by_name[name]
            self._save(app, secret_value_by_name)

    def names(self, app: str) -> list[str]:
        """The stored key names, sorted -- never the values.

        Raises:
            CredentialsError: the file exists but is unreadable or malformed.
        """
        return sorted(self._load(app))

    def _load(self, app: str) -> dict[str, object]:
        """Parse ``credentials.json`` into a name -> value dict, or ``{}`` when the file is
        absent. Warns once when a present file is group/world-readable."""
        path = self.path(app)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError) as err:
            # UnicodeDecodeError is a ValueError, not an OSError, so name it explicitly or
            # a non-UTF-8 file escapes this boundary as a bare traceback.
            raise CredentialsError(f"could not read {path}: {err}") from err
        warn_if_group_or_world_readable(path, app=app)
        try:
            secret_value_by_name = json.loads(text)
        except json.JSONDecodeError as err:
            raise CredentialsError(f"{path} is not valid JSON: {err}") from err
        if not isinstance(secret_value_by_name, dict):
            raise CredentialsError(f"{path} must contain a JSON object of name to value")
        return secret_value_by_name

    def _save(self, app: str, secret_value_by_name: dict[str, object]) -> None:
        """Write the map back to ``credentials.json`` atomically at mode 0600, in a config
        directory hardened to 0700 first. Converts the atomic layer's ``XdgkitError`` to
        ``CredentialsError`` to honour the ``set``/``unset`` contract."""
        path = self.path(app)
        restrict_dir_to_owner(path.parent)
        text = json.dumps(secret_value_by_name, indent=2, sort_keys=True) + "\n"
        try:
            write_text_atomic(path, text, mode=PRIVATE_FILE_MODE)
        except XdgkitError as err:
            raise CredentialsError(str(err)) from err


class KeyringBackend:
    """Secrets in the OS keyring (service = ``app``, username = ``name``), via the
    ``keyring`` package, with a file ``fallback`` for headless machines where no keyring
    backend exists.

    When ``keyring`` is missing or raises (no backend, a locked store), the operation is
    delegated to ``fallback`` in full and a one-time warning is printed so the user knows
    their secrets are in the file, not the keyring. When ``keyring`` works it is the sole
    source, and a successful ``set``/``unset`` also clears any file copy so opting into the
    keyring never leaves plaintext behind. ``keyring`` provides no way to enumerate a
    service's keys, so ``names`` reports only what the ``fallback`` holds -- keys stored
    solely in the OS keyring are not listable.

    One direction cannot be closed: a value written to the file fallback *while the keyring
    is down* is not migrated into the keyring on recovery. If the keyring still holds an
    older value for that name, it will shadow the newer file value once it comes back (the
    keyring is authoritative). Rotate a key while the keyring is reachable, or clear the
    stale keyring entry, to avoid a superseded secret reappearing.
    """

    def __init__(self, *, fallback: SecretBackend | None = None) -> None:
        self._fallback = fallback

    def get(self, app: str, name: str) -> str | None:
        try:
            import keyring
            value = keyring.get_password(app, name)
        except Exception as err:   # missing package or any keyring backend failure
            return self._fallback_get(app, name, err)
        return _clean(value)

    def set(self, app: str, name: str, *, value: str) -> None:
        try:
            import keyring
            keyring.set_password(app, name, value)
        except Exception as err:
            self._fallback_set(app, name, value, err)
            return
        # keyring is authoritative: drop any stale plaintext copy from the fallback file.
        if self._fallback is not None:
            self._fallback.unset(app, name)

    def unset(self, app: str, name: str) -> None:
        try:
            import keyring
            import keyring.errors
        except ImportError as err:
            self._fallback_unset(app, name, err)
            return
        try:
            keyring.delete_password(app, name)
        except keyring.errors.PasswordDeleteError:
            pass   # key already absent -- unset is idempotent
        except keyring.errors.NoKeyringError as err:
            self._fallback_unset(app, name, err)   # no backend at all -> the file owns it
            return
        except keyring.errors.KeyringError as err:
            # keyring is present but the delete genuinely failed (a locked store, an I/O
            # error): do NOT report success and silently fall back while the secret may
            # still be retrievable from the keyring -- surface it.
            raise CredentialsError(
                f"could not delete {app}/{name} from the keyring: {err}"
            ) from err
        # deletion succeeded (or the key was absent): also clear any file copy so a later
        # keyring outage cannot resurrect it.
        if self._fallback is not None:
            self._fallback.unset(app, name)

    def names(self, app: str) -> list[str]:
        # keyring cannot enumerate; report only the fallback's file-stored names.
        return self._fallback.names(app) if self._fallback is not None else []

    def _fallback_get(self, app: str, name: str, err: Exception) -> str | None:
        if self._fallback is not None:
            _warn_keyring_fallback_once(err)
            return self._fallback.get(app, name)
        raise CredentialsError(f"keyring unavailable for {app}/{name}: {err}") from err

    def _fallback_set(self, app: str, name: str, value: str, err: Exception) -> None:
        if self._fallback is not None:
            _warn_keyring_fallback_once(err)
            self._fallback.set(app, name, value=value)
            return
        raise CredentialsError(f"keyring unavailable for {app}/{name}: {err}") from err

    def _fallback_unset(self, app: str, name: str, err: Exception) -> None:
        if self._fallback is not None:
            _warn_keyring_fallback_once(err)
            self._fallback.unset(app, name)
            return
        raise CredentialsError(f"keyring unavailable for {app}/{name}: {err}") from err


def default_backend(*, use_keyring: bool = False) -> SecretBackend:
    """The backend a plain ``Credentials(app)`` uses: a ``FileBackend`` by default, or a
    ``KeyringBackend`` with a ``FileBackend`` fallback when ``use_keyring=True`` opts into
    the OS keyring."""
    if use_keyring:
        return KeyringBackend(fallback=FileBackend())
    return FileBackend()


def _warn_keyring_fallback_once(err: Exception) -> None:
    """Warn once, on stderr, that the OS keyring is unavailable and secrets are going to
    the file backend instead -- so a user who opted into the keyring is not silently
    downgraded to a plaintext file without knowing."""
    global _warned_keyring_fallback
    if _warned_keyring_fallback:
        return
    _warned_keyring_fallback = True
    print(
        f"xdgkit: warning: OS keyring unavailable ({err}); using the file backend "
        f"(credentials.json, mode 0600) instead",
        file=sys.stderr,
    )


def _clean(value: object) -> str | None:
    """A stored value normalised to a non-empty string, or ``None`` -- so a blank entry
    reads as absent and falls through to the next resolution tier."""
    return value.strip() if isinstance(value, str) and value.strip() else None
