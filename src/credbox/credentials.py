"""Resolving a secret for an application across four tiers, in a fixed order.

A ``Credentials`` is bound to an app and, optionally, to one or more *shared* stores it also
consults. ``secret(name)`` resolves in this order, first hit wins:

1. an explicit ``override`` the caller passed (e.g. an ``api_key=`` argument in code),
2. the environment variable ``name`` (``EXAMPLE_API_KEY``),
3. each shared store, in order (another app's ``credentials.json``, consulted by name),
4. this app's own store.

The shared-store tier is what lets a key common to several apps live in one place: store it once
under a shared app (say ``"auth"``) and a consumer resolves it with
``Credentials("myapp", shared=["auth"])`` -- env still wins, then the ``auth`` store, then
``myapp``'s own.

``Credentials`` is a configured FACADE: it binds ``(app, shared)`` and a single chosen
``SecretBackend`` and *orders the resolution tiers*, delegating every store touch to the backend.
It does not compose a fallback chain itself -- keyring-over-file composition lives in the backend
(see ``backends``). Every resolved value is returned as a ``Secret``, never a raw ``str``.
"""

from __future__ import annotations

from collections.abc import Sequence

from credbox.backends import SecretBackend, default_backend
from credbox.environment import env_value
from credbox.errors import BlankSecretError, CredentialsError
from credbox.paths import app_dir_segment
from credbox.secret import Secret

__all__ = ["Credentials"]


class Credentials:
    """An app's secret resolver: bound to one app, optionally consulting shared stores, backed by
    one ``SecretBackend`` (a ``FileBackend`` by default)."""

    def __init__(
        self,
        app: str,
        *,
        shared: Sequence[str] = (),
        backend: SecretBackend | None = None,
    ) -> None:
        """Bind to ``app``. ``shared`` names other apps whose stores are consulted before
        ``app``'s own (e.g. ``["auth"]`` for a key common to several apps). ``backend`` selects
        the store; the default is a ``FileBackend`` (call ``default_backend(use_keyring=True)`` or
        a factory for the keyring/encrypted backends).

        Raises:
            InvalidAppNameError: ``app`` or any ``shared`` name is not a valid directory segment.
        """
        self._app = app_dir_segment(app)
        self._shared = tuple(app_dir_segment(name) for name in shared)
        self._backend = backend if backend is not None else default_backend()

    def __repr__(self) -> str:
        # Secret-safe: the app, the shared-store order, and the backend type only -- no value.
        return (
            f"Credentials(app={self._app!r}, shared={list(self._shared)!r}, "
            f"backend={type(self._backend).__name__})"
        )

    def secret(self, name: str, *, override: str | Secret | None = None) -> Secret | None:
        """Resolve ``name`` across the four tiers (override > env > shared > app) as a ``Secret``,
        or ``None`` when unset everywhere. A blank value at any tier is treated as absent.

        Raises:
            CredentialsError: a consulted store is present but unreadable or malformed.
            DecryptionError: with an encrypted backend, a store could not be decrypted (a wrong
                passphrase or tampering) -- a sibling of ``CredentialsError`` under ``CredBoxError``,
                so catch ``CredBoxError`` to cover both, or ``DecryptionError`` to single it out.
        """
        if override is not None:
            raw = override.reveal() if isinstance(override, Secret) else override
            cleaned = raw.strip()
            if cleaned:
                return Secret(cleaned)
        from_env = env_value(name)
        if from_env is not None:
            return Secret(from_env)
        for store in self._shared:
            value = self._backend.get(store, name)
            if value is not None:
                return value
        return self._backend.get(self._app, name)

    def require(self, name: str, *, override: str | Secret | None = None) -> Secret:
        """Like ``secret`` but raise when the secret is unset everywhere -- for a key the caller
        cannot proceed without. The error is content-free (it names ``name`` and the app, never a
        value).

        Raises:
            CredentialsError: ``name`` resolves to nothing across all tiers, or a consulted store
                is malformed.
            DecryptionError: with an encrypted backend, a store could not be decrypted (catch
                ``CredBoxError`` to cover both, or ``DecryptionError`` to single it out).
        """
        value = self.secret(name, override=override)
        if value is None:
            raise CredentialsError(
                f"required secret {name!r} is not set for {self._app}: set the {name} "
                f"environment variable, or store it with 'credbox set {self._app} {name}'"
            )
        return value

    def set(self, name: str, *, value: str | Secret) -> None:
        """Store ``value`` (a ``str`` or ``Secret``) under ``name`` in this app's own store
        (never a shared one). ``value`` is keyword-only so it cannot be swapped with ``name``.

        Surrounding whitespace is stripped before storing, so the stored file holds exactly what
        ``secret`` returns (resolution strips every tier, so a pasted key's trailing newline never
        survives a read).

        Raises:
            BlankSecretError: ``value`` is empty or whitespace-only -- a blank would list under
                ``names`` yet resolve to ``None``, so it is refused to keep set and get consistent.
                A subclass of both ``CredBoxError`` and ``ValueError``.
            CredentialsError: the store could not be written.
            DecryptionError: with an encrypted backend, the existing store had to be read to
                merge the new value and could not be decrypted (a wrong passphrase or tampering).
        """
        raw = value.reveal() if isinstance(value, Secret) else value
        raw = raw.strip()
        if not raw:
            raise BlankSecretError(f"refusing to store a blank value for {name!r}")
        self._backend.set(self._app, name, value=raw)

    def unset(self, name: str) -> None:
        """Remove ``name`` from this app's own store; a no-op when absent.

        Raises:
            CredentialsError: the store could not be written.
            DecryptionError: with an encrypted backend, the existing store had to be read to
                remove the name and could not be decrypted (a wrong passphrase or tampering).
        """
        self._backend.unset(self._app, name)

    def names(self) -> list[str]:
        """The secret names stored in this app's own store, sorted -- never the values. With a
        keyring backend this lists only the file-fallback names (the OS keyring cannot enumerate
        its keys).

        Raises:
            CredentialsError: the store is present but malformed.
            DecryptionError: with an encrypted backend, the store could not be decrypted (catch
                ``CredBoxError`` to cover both, or ``DecryptionError`` to single it out).
        """
        return self._backend.names(self._app)
