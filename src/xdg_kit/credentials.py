"""Resolving a secret for an application across four tiers, in a fixed order.

A ``Credentials`` is bound to an app and, optionally, to one or more *shared* stores it
also consults. ``secret(name)`` resolves in this order, first hit wins:

1. an explicit ``override`` the caller passed (e.g. an ``api_key=`` argument in code),
2. the environment variable ``name`` (``EXAMPLE_API_KEY``),
3. each shared store, in order (another app's ``credentials.json``, consulted by name),
4. this app's own store.

The shared-store tier is what lets a key common to several apps live in one place: store
it once under a shared app (say ``"auth"``) and a consumer resolves it with
``Credentials("myapp", shared=["auth"])`` -- env still wins, then the ``auth`` store, then
``myapp``'s own. A key specific to one app needs no ``shared`` and stays in that app's own
store.

The store tier (file vs OS keyring) is a ``SecretBackend``; ``Credentials`` only orders the
tiers and never touches disk itself. ``FileBackend`` is the default -- see ``backends``.
"""

from __future__ import annotations

from collections.abc import Sequence

from xdg_kit.backends import SecretBackend, default_backend
from xdg_kit.environment import env_value
from xdg_kit.errors import CredentialsError
from xdg_kit.paths import app_dir_segment

__all__ = [
    "Credentials",
    "get_secret",
    "require_secret",
    "set_secret",
    "unset_secret",
    "secret_names",
]


class Credentials:
    """An app's secret resolver: bound to one app, optionally consulting shared stores,
    backed by one ``SecretBackend`` (file by default)."""

    def __init__(
        self,
        app: str,
        *,
        shared: Sequence[str] = (),
        backend: SecretBackend | None = None,
    ) -> None:
        """Bind to ``app``. ``shared`` names other apps whose stores are consulted before
        ``app``'s own (e.g. ``["auth"]`` for a key common to several apps). ``backend``
        selects the store; the default is a ``FileBackend``.

        Raises:
            InvalidAppNameError: ``app`` or any ``shared`` name is not a valid directory
                segment.
        """
        self._app = app_dir_segment(app)
        self._shared = tuple(app_dir_segment(name) for name in shared)
        self._backend = backend if backend is not None else default_backend()

    def __repr__(self) -> str:
        # Secret-safe: shows the app, the shared-store order, and the backend type only --
        # never a resolved value.
        return (
            f"Credentials(app={self._app!r}, shared={list(self._shared)!r}, "
            f"backend={type(self._backend).__name__})"
        )

    def secret(self, name: str, *, override: str | None = None) -> str | None:
        """Resolve ``name`` across the four tiers (override > env > shared > app), or
        ``None`` when unset everywhere. A blank value at any tier is treated as absent and
        falls through.

        Raises:
            CredentialsError: a consulted store is present but unreadable or malformed
                (propagated from the backend).
        """
        if override is not None and override.strip():
            return override.strip()
        from_env = env_value(name)
        if from_env is not None:
            return from_env
        for store in self._shared:
            value = self._backend.get(store, name)
            if value is not None:
                return value
        return self._backend.get(self._app, name)

    def require(self, name: str, *, override: str | None = None) -> str:
        """Like ``secret`` but raise when the secret is unset everywhere -- for a key the
        caller cannot proceed without.

        Raises:
            CredentialsError: ``name`` resolves to nothing across all tiers, or a consulted
                store is malformed.
        """
        value = self.secret(name, override=override)
        if value is None:
            raise CredentialsError(
                f"required secret {name!r} is not set for {self._app}: set the {name} "
                f"environment variable, or store it with 'xdg-kit set {self._app} {name}'"
            )
        return value

    def set(self, name: str, *, value: str) -> None:
        """Store ``value`` under ``name`` in this app's own store (never a shared one).
        ``value`` is keyword-only so it cannot be swapped with ``name``.

        Raises:
            CredentialsError: the store could not be written (propagated from the backend).
        """
        self._backend.set(self._app, name, value=value)

    def unset(self, name: str) -> None:
        """Remove ``name`` from this app's own store; a no-op when absent.

        Raises:
            CredentialsError: the store could not be written (propagated from the backend).
        """
        self._backend.unset(self._app, name)

    def names(self) -> list[str]:
        """The secret names stored in this app's own store, sorted -- never the values.

        With a keyring backend this lists only the file-fallback names: the OS keyring
        cannot enumerate its keys, so a key stored solely in the keyring will not appear.

        Raises:
            CredentialsError: the store is present but malformed (propagated from the
                backend).
        """
        return self._backend.names(self._app)


def get_secret(
    app: str,
    name: str,
    *,
    override: str | None = None,
    shared: Sequence[str] = (),
    backend: SecretBackend | None = None,
) -> str | None:
    """Resolve one secret without holding a ``Credentials`` -- convenience over
    ``Credentials(app, shared=shared, backend=backend).secret(name, override=override)``."""
    return Credentials(app, shared=shared, backend=backend).secret(name, override=override)


def require_secret(
    app: str,
    name: str,
    *,
    override: str | None = None,
    shared: Sequence[str] = (),
    backend: SecretBackend | None = None,
) -> str:
    """Resolve one required secret, raising ``CredentialsError`` when unset -- convenience
    over ``Credentials(...).require(...)``."""
    return Credentials(app, shared=shared, backend=backend).require(name, override=override)


def set_secret(
    app: str,
    name: str,
    *,
    value: str,
    backend: SecretBackend | None = None,
) -> None:
    """Store one secret in ``app``'s own store -- convenience over
    ``Credentials(app, backend=backend).set(name, value=value)``. ``value`` is
    keyword-only so it cannot be swapped with ``name``."""
    Credentials(app, backend=backend).set(name, value=value)


def unset_secret(app: str, name: str, *, backend: SecretBackend | None = None) -> None:
    """Remove one secret from ``app``'s own store -- convenience over
    ``Credentials(app, backend=backend).unset(name)``."""
    Credentials(app, backend=backend).unset(name)


def secret_names(app: str, *, backend: SecretBackend | None = None) -> list[str]:
    """List the secret names in ``app``'s own store -- convenience over
    ``Credentials(app, backend=backend).names()``."""
    return Credentials(app, backend=backend).names()
