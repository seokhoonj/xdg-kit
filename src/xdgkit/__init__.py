"""Secure XDG-style application storage for Python: paths, credentials, permissions, and
runtime files.

The common surface -- directories and secret resolution -- is re-exported here:

    from xdgkit import config_dir, data_dir, state_dir, cache_dir, runtime_dir
    from xdgkit import Credentials, secret, require

Deeper pieces stay in their modules so the import says what it reaches for:

    from xdgkit.backends import FileBackend, KeyringBackend
    from xdgkit.scrub import scrub_secrets, scrub_exception
    from xdgkit.locking import FileLock, single_instance
"""

from __future__ import annotations

from xdgkit.credentials import (
    Credentials,
    require,
    secret,
    secret_names,
    set_secret,
    unset_secret,
)
from xdgkit.errors import (
    CredentialsError,
    InsecureStorageError,
    InvalidAppNameError,
    XdgkitError,
)
from xdgkit.paths import cache_dir, config_dir, data_dir, state_dir
from xdgkit.runtime import runtime_dir

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "config_dir",
    "data_dir",
    "state_dir",
    "cache_dir",
    "runtime_dir",
    "Credentials",
    "secret",
    "require",
    "set_secret",
    "unset_secret",
    "secret_names",
    "XdgkitError",
    "CredentialsError",
    "InsecureStorageError",
    "InvalidAppNameError",
]
