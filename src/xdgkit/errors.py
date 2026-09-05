"""Domain exception hierarchy for xdgkit.

Every error xdgkit raises on purpose derives from ``XdgkitError``, so a caller can handle
this package's failures with one ``except`` without catching unrelated bugs. A malformed
*argument* (an app name that is not a safe directory segment) is a caller mistake rather
than a runtime condition, so ``InvalidAppNameError`` is *also* a ``ValueError`` -- it joins
this hierarchy yet an ``except ValueError`` still catches it.
"""

from __future__ import annotations

__all__ = [
    "XdgkitError",
    "CredentialsError",
    "InsecureStorageError",
    "InvalidAppNameError",
]


class XdgkitError(Exception):
    """Base for every error xdgkit raises deliberately."""


class InvalidAppNameError(XdgkitError, ValueError):
    """An app name is not a safe directory segment (empty, a path separator, ``..``, or
    leading/trailing punctuation). It subclasses ``ValueError`` -- a bad literal name is a
    caller mistake -- while still joining the ``XdgkitError`` hierarchy, so a consumer can
    catch it either way and a CLI can single it out as a usage error."""


class CredentialsError(XdgkitError):
    """A credentials store is present but unusable: unreadable, not JSON, not a JSON
    object, or a keyring backend that failed. Its message carries the path or the
    underlying cause."""


class InsecureStorageError(XdgkitError):
    """A directory or file that must be private is not: it exists but is owned by
    another user, is a symlink, or carries permissions that expose it to group or
    others. Raised rather than silently trusting it, because a secret written there
    would leak."""
