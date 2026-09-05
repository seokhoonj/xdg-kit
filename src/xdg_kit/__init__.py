"""Secure XDG-style application storage for Python: paths, credentials, permissions, and
runtime files.

The common surface -- directories and secret resolution -- is re-exported here:

    from xdg_kit import config_dir, data_dir, state_dir, cache_dir, runtime_dir
    from xdg_kit import Credentials, secret, require

Deeper pieces stay in their modules so the import says what it reaches for:

    from xdg_kit.backends import FileBackend, KeyringBackend
    from xdg_kit.scrub import scrub_secrets, scrub_exception
    from xdg_kit.locking import FileLock, single_instance
"""

from __future__ import annotations

from importlib.metadata import version

from xdg_kit.credentials import (
    Credentials,
    require,
    secret,
    secret_names,
    set_secret,
    unset_secret,
)
from xdg_kit.errors import (
    CredentialsError,
    InsecureStorageError,
    InvalidAppNameError,
    XdgKitError,
)
from xdg_kit.paths import cache_dir, config_dir, data_dir, state_dir
from xdg_kit.runtime import runtime_dir

# Single source of truth is pyproject's version, read from the installed distribution's
# metadata -- so a release bump lives in one place and `xdg-kit --version` can never drift
# from what pip resolved. (An editable install reflects a bump after re-sync; importing
# from an uninstalled source tree raises PackageNotFoundError, which is not a supported use.)
__version__ = version("xdg-kit")

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
    "XdgKitError",
    "CredentialsError",
    "InsecureStorageError",
    "InvalidAppNameError",
]
