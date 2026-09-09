"""credbox -- a secure, XDG-located secret store for apps and CLIs.

Honest plaintext mode-0600 default, with opt-in keyring and encrypted upgrades. This module
is NAME DEFINITION ONLY: it re-exports the common public surface and does no import-time work
and never imports an optional extra (``keyring``/``cryptography``).
"""

from __future__ import annotations

from credbox.errors import (
    CredBoxError,
    CredentialsError,
    DecryptionError,
    InsecureStorageError,
    InvalidAppNameError,
    MissingExtraError,
    NoKeyringError,
)
from credbox.secret import Secret, mask_secret

__all__ = [
    # errors
    "CredBoxError",
    "CredentialsError",
    "NoKeyringError",
    "InsecureStorageError",
    "InvalidAppNameError",
    "DecryptionError",
    "MissingExtraError",
    # value type
    "Secret",
    "mask_secret",
]
