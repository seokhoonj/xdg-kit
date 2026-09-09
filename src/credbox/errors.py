"""Domain exception hierarchy for credbox.

Every error credbox raises on purpose derives from ``CredBoxError``, so a caller can handle
this package's failures with a single ``except`` without catching unrelated bugs. Each leaf
states its bases explicitly: ``InvalidAppNameError`` is also a ``ValueError`` (a bad literal
name is a caller mistake) and ``MissingExtraError`` is also an ``ImportError`` (a missing
optional dependency), so an ``except ValueError`` / ``except ImportError`` still catches them.
"""

from __future__ import annotations

__all__ = [
    "CredBoxError",
    "CredentialsError",
    "NoKeyringError",
    "InsecureStorageError",
    "InvalidAppNameError",
    "DecryptionError",
    "MissingExtraError",
]


class CredBoxError(Exception):
    """Base for every error credbox raises deliberately."""


class CredentialsError(CredBoxError):
    """The credential store is unusable: present but malformed (unreadable, not JSON, not a
    JSON object, a non-string value), or the backend it needs is absent. Built from safe
    fields only (a path, an errno, a content-free kind) -- never from a secret value, and
    never chained to an exception whose text could embed one."""


class NoKeyringError(CredentialsError):
    """No OS keyring backend is available at all -- an environment fact, not a store fault.
    A ``CredentialsError`` subtype so a broad ``except CredentialsError`` still catches it."""


class InsecureStorageError(CredBoxError):
    """A path that must be private is not: it is owned by another user, is a symlink, or is
    readable by group/others. Raised rather than trusting it, because a secret written there
    would leak."""


class InvalidAppNameError(CredBoxError, ValueError):
    """An app name fails the charset rule (non-empty, a leading alphanumeric, then only
    ``[A-Za-z0-9._-]``). Also a ``ValueError`` -- a bad literal name is a caller mistake --
    so an ``except ValueError`` still catches it and the CLI can single it out as a usage
    error (exit 2)."""


class DecryptionError(CredBoxError):
    """[crypto] The encrypted store could not be decrypted: a wrong passphrase or tampering
    (an AES-GCM tag failure). Content-free by construction -- raised from a returning frame
    so that both ``__cause__`` and ``__context__`` are ``None`` and the underlying
    ``InvalidTag`` never rides along."""


class MissingExtraError(CredBoxError, ImportError):
    """An optional feature was requested but its extra is not installed. Also an
    ``ImportError`` for dual-catch. Carries ``.extra`` (e.g. ``"keyring"``) and ``.dist``
    (e.g. ``"credbox[keyring]"``) so the CLI can print an actionable ``pip install`` hint."""

    def __init__(self, *, extra: str, dist: str) -> None:
        self.extra = extra
        self.dist = dist
        super().__init__(f"optional feature {extra!r} is not installed; install {dist!r}")
