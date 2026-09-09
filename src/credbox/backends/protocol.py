"""The ``SecretBackend`` protocol: the seam every store implementation satisfies.

A backend answers, for an ``(app, name)`` pair: read (``get``), write (``set``), remove
(``unset``), or list the names (``names``). ``get`` returns a ``Secret`` (never a raw ``str``),
so a resolved value cannot land in a log by accident; ``set`` accepts a ``str`` or a ``Secret``.
``value`` is keyword-only so it can never be swapped with ``name`` positionally -- a swap would
store the secret *as a key name*.
"""

from __future__ import annotations

from typing import Protocol

from credbox.secret import Secret

__all__ = ["SecretBackend"]


class SecretBackend(Protocol):
    """The store interface every backend implements.

    ``get`` returns the stored value as a ``Secret``, or ``None`` when the store or key is
    absent (a whitespace-only stored value reads back as absent). ``set``/``unset`` mutate the
    store; ``names`` lists the stored keys, never their values. When the store is present but
    unusable a method raises a ``CredBoxError`` -- a ``CredentialsError`` for an unreadable or
    malformed store (or an absent required backend), or a ``DecryptionError`` from the encrypted
    backend when the store cannot be decrypted; a caller that wants to cover every backend
    catches the ``CredBoxError`` base, since ``DecryptionError`` is a sibling of
    ``CredentialsError``, not a subtype. ``unset`` on a missing name is an idempotent no-op, not
    an error.
    """

    def get(self, app: str, name: str) -> Secret | None: ...
    def set(self, app: str, name: str, *, value: str | Secret) -> None: ...
    def unset(self, app: str, name: str) -> None: ...
    def names(self, app: str) -> list[str]: ...
