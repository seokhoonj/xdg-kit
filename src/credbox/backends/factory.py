"""Factories for the backends, with a find-spec gate for the optional extras.

The zero-dep core reaches an extra backend ONLY through these factories: ``find_spec`` FIRST
(does the distribution exist, without executing it), then the real import OUTSIDE any ``except``,
so "absent" (an actionable ``pip install`` message via ``MissingExtraError``) and
"installed-but-buggy" (the genuine ``ImportError`` propagates) never blur.
"""

from __future__ import annotations

import importlib.util

from credbox.backends.file import FileBackend
from credbox.backends.protocol import SecretBackend
from credbox.errors import MissingExtraError
from credbox.secret import Secret

__all__ = ["file_backend", "keyring_backend", "encrypted_backend", "default_backend"]


def file_backend() -> SecretBackend:
    """The zero-dep plaintext file backend."""
    return FileBackend()


def keyring_backend(*, fallback: SecretBackend | None = None) -> SecretBackend:
    """The OS keyring backend, with an optional file ``fallback``.

    Raises:
        MissingExtraError: the ``keyring`` distribution is not installed (install
            ``credbox[keyring]``).
    """
    if importlib.util.find_spec("keyring") is None:
        raise MissingExtraError(extra="keyring", dist="credbox[keyring]")
    # Execute the keyring package here, outside any except, so a broken-but-installed keyring fails
    # loudly at construction -- where no secret is in flight -- rather than being caught later in a
    # per-operation helper, misclassified as "no backend", and silently downgraded to the plaintext
    # fallback at runtime.
    import keyring  # noqa: F401

    from credbox.backends.keyring import KeyringBackend
    return KeyringBackend(fallback=fallback)


def encrypted_backend(*, passphrase: Secret) -> SecretBackend:
    """The encrypted file backend, keyed by ``passphrase``.

    Raises:
        MissingExtraError: the ``cryptography`` distribution is not installed (install
            ``credbox[crypto]``).
    """
    if importlib.util.find_spec("cryptography") is None:
        raise MissingExtraError(extra="crypto", dist="credbox[crypto]")
    from credbox.backends.encrypted import EncryptedFileBackend  # outside any except
    return EncryptedFileBackend(passphrase=passphrase)


def default_backend(*, use_keyring: bool = False) -> SecretBackend:
    """The backend a plain ``Credentials(app)`` uses: a ``FileBackend`` by default, or a
    ``KeyringBackend`` with a ``FileBackend`` fallback when ``use_keyring=True``. Never composes
    encrypted over plaintext (that chain is structurally unrepresentable -- encrypted is
    terminal)."""
    if use_keyring:
        return keyring_backend(fallback=file_backend())
    return file_backend()
