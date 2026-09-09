"""The OS keyring backend ([keyring] extra), with a file ``fallback`` for headless machines.

When the OS keyring has no backend (cron, containers, servers) the operation is delegated to
``fallback`` in full and a one-time, content-free warning is printed so the user knows their
secrets are in the file, not the keyring. When the keyring works it is authoritative, and a
successful write/delete also clears any stale plaintext copy from the fallback.

**Leak contract (the P1 fix).** A keyring call can raise a third-party exception whose ``str()``
embeds a secret. Every such exception is caught *inside* a returning-frame helper
(``_try_keyring_*``) and never escapes; the ``CredentialsError`` a caller sees is built from safe
fields only (``app``, ``name``, a fixed phrase) and raised where no exception is in flight, so
both ``__cause__`` AND ``__context__`` are ``None`` (a bare ``raise ... from None`` would leave
the secret-bearing exception on ``__context__``). The warn-once message is content-free too.

One direction cannot be fully closed: a value written to the file fallback *while the keyring is
down* is not migrated into the keyring on recovery. If on recovery the keyring holds no entry for
that name, ``get`` consults the file and returns it; but if the keyring still holds an older value,
that older value shadows the newer file value (the keyring is authoritative on a conflict).
Re-set the key while the keyring is reachable.
"""

from __future__ import annotations

import sys

from credbox.backends.file import _normalize_secret_value
from credbox.backends.protocol import SecretBackend
from credbox.errors import CredentialsError, NoKeyringError
from credbox.secret import Secret

__all__ = ["KeyringBackend"]

_warned_keyring_fallback = False


class KeyringBackend:
    """Secrets in the OS keyring (service = ``app``, username = ``name``), with a file
    ``fallback`` for machines where no keyring backend exists."""

    def __init__(self, *, fallback: SecretBackend | None = None) -> None:
        self._fallback = fallback

    def __repr__(self) -> str:
        fallback = type(self._fallback).__name__ if self._fallback is not None else None
        return f"KeyringBackend(fallback={fallback})"

    def get(self, app: str, name: str) -> Secret | None:
        """Return the keyring value for ``name`` as a ``Secret``, or ``None`` when set nowhere.
        Falls back to the file when the keyring is unavailable (warning once), and when the
        keyring is reachable but empty (so a value written to the file while the keyring was down
        stays readable after recovery).

        Raises:
            NoKeyringError: no keyring backend exists and no fallback is configured.
            CredentialsError: the keyring errored and no fallback is configured, or a consulted
                fallback file is present but malformed.
        """
        status, raw = _try_keyring_get(app, name)
        if status != "ok":
            return self._fallback_get(app, name, structural=(status == "no_backend"))
        cleaned = _normalize_secret_value(raw)
        if cleaned is not None:
            return Secret(cleaned)
        if self._fallback is not None:
            return self._fallback.get(app, name)
        return None

    def set(self, app: str, name: str, *, value: str | Secret) -> None:
        """Store ``value`` in the keyring; a successful write also clears any stale plaintext
        copy from the fallback file. Falls back to the file (warning once) when the keyring is
        unavailable.

        Raises:
            NoKeyringError / CredentialsError: the keyring is unavailable and no fallback is
                configured; or the keyring write succeeded but a stale file copy could not be
                cleared.
        """
        raw = value.reveal() if isinstance(value, Secret) else value
        status = _try_keyring_set(app, name, raw)
        if status != "ok":
            self._fallback_set(app, name, raw, structural=(status == "no_backend"))
            return
        if self._fallback is not None:
            try:
                self._fallback.unset(app, name)
            except CredentialsError as err:
                raise CredentialsError(
                    f"stored {app}/{name} in the keyring, but a stale plaintext copy may remain "
                    f"in the file store and could not be cleared"
                ) from err

    def unset(self, app: str, name: str) -> None:
        """Remove ``name`` from the keyring and from any fallback file copy; an idempotent no-op
        when absent. Fails closed: a keyring present but erroring on delete raises rather than
        silently reporting a delete that may not have happened.

        Raises:
            NoKeyringError: no keyring backend exists and no fallback is configured.
            CredentialsError: the keyring is present but the delete failed; or the delete
                succeeded but a stale file copy could not be cleared.
        """
        status = _try_keyring_delete(app, name)
        if status == "no_backend":
            if self._fallback is not None:
                _warn_keyring_fallback_once()
                self._fallback.unset(app, name)
                return
            raise NoKeyringError(
                f"no OS keyring backend available for {app}/{name} and no fallback is configured"
            )
        if status == "failed":
            # Keyring present but the delete genuinely failed: do NOT report success while the
            # secret may still be retrievable. Content-free -- no in-flight exception here.
            raise CredentialsError(f"could not delete {app}/{name} from the keyring")
        if self._fallback is not None:
            try:
                self._fallback.unset(app, name)
            except CredentialsError as err:
                raise CredentialsError(
                    f"deleted {app}/{name} from the keyring, but a stale plaintext copy may "
                    f"remain in the file store and could not be cleared"
                ) from err

    def names(self, app: str) -> list[str]:
        """The fallback file's stored key names, sorted. The OS keyring cannot enumerate its own
        keys, so a key stored solely in the keyring is not listed.

        Raises:
            CredentialsError: the fallback file is present but malformed.
        """
        return self._fallback.names(app) if self._fallback is not None else []

    def _fallback_get(self, app: str, name: str, *, structural: bool) -> Secret | None:
        if self._fallback is not None:
            _warn_keyring_fallback_once()
            return self._fallback.get(app, name)
        raise self._unavailable_error(app, name, structural=structural)

    def _fallback_set(self, app: str, name: str, raw: str, *, structural: bool) -> None:
        if self._fallback is not None:
            _warn_keyring_fallback_once()
            self._fallback.set(app, name, value=raw)
            return
        raise self._unavailable_error(app, name, structural=structural)

    def _unavailable_error(self, app: str, name: str, *, structural: bool) -> CredentialsError:
        """A content-free error for the no-fallback case, raised where no third-party exception
        is in flight so ``__cause__`` and ``__context__`` are both ``None``."""
        if structural:
            return NoKeyringError(
                f"no OS keyring backend available for {app}/{name} and no fallback is configured"
            )
        return CredentialsError(
            f"keyring unavailable for {app}/{name} and no fallback is configured"
        )


# --- returning-frame keyring calls (the third-party exception dies here) --------
#
# Each helper catches every keyring exception INSIDE its own frame and returns a status string,
# so the exception never reaches a caller frame. That is what lets KeyringBackend raise a
# content-free CredentialsError with __context__ == None: at the raise site there is no exception
# in flight to become the implicit context.


def _try_keyring_get(app: str, name: str) -> tuple[str, str | None]:
    """Return ``("ok", value)``, ``("no_backend", None)``, or ``("failed", None)``."""
    try:
        import keyring
        import keyring.errors
    except ImportError:
        return "no_backend", None
    try:
        return "ok", keyring.get_password(app, name)
    except keyring.errors.NoKeyringError:
        return "no_backend", None
    except Exception:
        return "failed", None


def _try_keyring_set(app: str, name: str, raw: str) -> str:
    """Return ``"ok"``, ``"no_backend"``, or ``"failed"``."""
    try:
        import keyring
        import keyring.errors
    except ImportError:
        return "no_backend"
    try:
        keyring.set_password(app, name, raw)
        return "ok"
    except keyring.errors.NoKeyringError:
        return "no_backend"
    except Exception:
        return "failed"


def _try_keyring_delete(app: str, name: str) -> str:
    """Return ``"deleted"`` (including an already-absent key), ``"no_backend"``, or ``"failed"``."""
    try:
        import keyring
        import keyring.errors
    except ImportError:
        return "no_backend"
    try:
        keyring.delete_password(app, name)
        return "deleted"
    except keyring.errors.PasswordDeleteError:
        return "deleted"   # already absent -- unset is idempotent
    except keyring.errors.NoKeyringError:
        return "no_backend"
    except Exception:
        return "failed"


def _warn_keyring_fallback_once() -> None:
    """Warn once, on stderr, that the OS keyring is unavailable and secrets are going to the file
    backend instead. Content-free: it never interpolates the third-party error, whose text could
    embed a secret."""
    global _warned_keyring_fallback
    if _warned_keyring_fallback:
        return
    _warned_keyring_fallback = True
    print(
        "credbox: warning: OS keyring unavailable; using the file backend "
        "(credentials.json, mode 0600) instead",
        file=sys.stderr,
    )
