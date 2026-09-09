"""credbox -- a secure, XDG-located secret store for apps and CLIs.

Honest plaintext mode-0600 default, with opt-in keyring and encrypted upgrades. This module
is NAME DEFINITION ONLY: it re-exports the common public surface and does no import-time work
and never imports an optional extra (``keyring``/``cryptography``).
"""

from __future__ import annotations

from credbox.environment import (
    colliding_env_var_prefixes,
    env_var_prefix,
    read_absolute_path_override,
)
from credbox.errors import (
    CredBoxError,
    CredentialsError,
    DecryptionError,
    InsecureStorageError,
    InvalidAppNameError,
    MissingExtraError,
    NoKeyringError,
)
from credbox.layout import Layout, default_layout, set_default_layout
from credbox.paths import app_dir_segment, cache_dir, config_dir, data_dir, state_dir
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
    # paths & layout
    "config_dir",
    "data_dir",
    "state_dir",
    "cache_dir",
    "app_dir_segment",
    "Layout",
    "default_layout",
    "set_default_layout",
    # environment
    "env_var_prefix",
    "colliding_env_var_prefixes",
    "read_absolute_path_override",
]
