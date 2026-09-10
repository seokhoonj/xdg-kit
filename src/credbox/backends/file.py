"""The zero-dep file backend: a flat ``name -> secret`` JSON map in ``credentials.json`` under
``config_dir(app)``, written atomically at mode 0600 in a directory tightened to 0700.

It is the reliable base everywhere -- no OS session, no network, portable across machines, the
same headless as on a desktop -- and it is TERMINAL: it has no fallback. Reads route through the
leak-safe ``_storecodec`` (a malformed file yields a content-free ``StoreFault``, never an
exception carrying the file's bytes); writes serialize the whole read-modify-write under a
cross-process lock so concurrent writers do not lose each other's keys.
"""

from __future__ import annotations

from pathlib import Path

from credbox._storecodec import StoreFault, StoreFaultKind, parse_store, serialize_store
from credbox.atomic import write_bytes_atomic
from credbox.backends._store import exclusive_store_lock, normalize_secret_value
from credbox.errors import CredBoxError, CredentialsError
from credbox.paths import config_dir
from credbox.permissions import (
    PRIVATE_FILE_MODE,
    warn_if_group_or_world_readable,
)
from credbox.secret import Secret

__all__ = ["FileBackend"]

CREDENTIALS_FILE = "credentials.json"


class FileBackend:
    """Secrets in ``credentials.json`` (a flat JSON object) under ``config_dir(app)``, written
    atomically at mode 0600 in a directory tightened to 0700. Terminal -- no fallback."""

    def path(self, app: str) -> Path:
        """The credentials file for ``app``: ``credentials.json`` in ``config_dir(app)``."""
        return config_dir(app) / CREDENTIALS_FILE

    def get(self, app: str, name: str) -> Secret | None:
        """Return the value stored under ``name`` as a ``Secret``, or ``None`` when the file or
        key is absent (or the value is blank). Warns once if the file is readable beyond its
        owner.

        Raises:
            CredentialsError: the file exists but is unreadable, not UTF-8, not JSON, not a JSON
                object, or holds a non-string value -- built from the fault kind and JSON
                position only, never the file's content.
        """
        cleaned = normalize_secret_value(self._load(app).get(name))
        return Secret(cleaned) if cleaned is not None else None

    def set(self, app: str, name: str, *, value: str | Secret) -> None:
        """Store ``value`` (a ``str`` or ``Secret``) under ``name`` at mode 0600 in a 0700
        directory. The whole read-modify-write is serialized -- across threads and, wherever the
        OS file lock can be taken, across processes -- so concurrent writers do not lose keys.

        Raises:
            CredentialsError: the existing file is unreadable or malformed, or the write failed.
        """
        raw = value.reveal() if isinstance(value, Secret) else value
        with exclusive_store_lock(self.path(app)):
            secret_value_by_name = self._load(app)
            secret_value_by_name[name] = raw
            self._save(app, secret_value_by_name)

    def unset(self, app: str, name: str) -> None:
        """Remove ``name`` if present; an idempotent no-op when the file or key is absent. The
        read-modify-write is serialized (see ``set``).

        Raises:
            CredentialsError: the existing file is unreadable or malformed, or the write failed.
        """
        with exclusive_store_lock(self.path(app)):
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

    def _load(self, app: str) -> dict[str, str]:
        """Parse ``credentials.json`` into a ``name -> secret`` map, or ``{}`` when absent. A
        malformed file becomes a content-free ``CredentialsError`` via ``_storecodec`` -- the raw
        bytes die in ``parse_store``'s returning frame and are not bound at this raise site."""
        path = self.path(app)
        try:
            store_bytes = path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as err:
            # An I/O error carries no file content; keep the errno detail.
            raise CredentialsError(f"could not read {path}: {err}") from err
        warn_if_group_or_world_readable(path, app=app)
        result = parse_store(store_bytes)
        del store_bytes   # drop this frame's copy of the raw bytes before any raise
        if isinstance(result, StoreFault):
            raise _fault_error(path, result)
        return result

    def _save(self, app: str, secret_value_by_name: dict[str, str]) -> None:
        """Serialize the map and write it back to ``credentials.json`` atomically at mode 0600.
        The config directory was already hardened to 0700 by ``exclusive_store_lock``, which wraps
        every ``set``/``unset`` -- so this method does not repeat that.

        The plaintext map is a live frame-local here (the caller handed it to us to store); the
        *raised* ``CredentialsError`` carries only the path/errno, never a value -- the object-
        level guarantee, not a claim that no plaintext exists in the frame (see _storecodec)."""
        path = self.path(app)
        encoded = serialize_store(secret_value_by_name)
        if isinstance(encoded, StoreFault):
            raise CredentialsError(f"{path} could not be serialized: a value is not encodable")
        try:
            write_bytes_atomic(path, encoded, mode=PRIVATE_FILE_MODE)
        except CredBoxError as err:
            raise CredentialsError(str(err)) from err


def _fault_error(path: Path, fault: StoreFault) -> CredentialsError:
    """A content-free ``CredentialsError`` describing a ``StoreFault`` -- built from the enum
    and the integer JSON position only, in a frame where no secret local is bound."""
    kind = fault.kind
    if kind is StoreFaultKind.NOT_UTF8:
        detail = "not valid UTF-8"
    elif kind is StoreFaultKind.NOT_JSON:
        detail = f"not valid JSON (line {fault.lineno}, column {fault.colno})"
    elif kind is StoreFaultKind.NOT_OBJECT:
        detail = "not a JSON object of name to value"
    elif kind is StoreFaultKind.NOT_STRING_VALUE:
        detail = "a stored value is not a string"
    else:
        detail = "malformed"
    return CredentialsError(f"{path} is {detail}")
