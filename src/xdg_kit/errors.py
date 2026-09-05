"""Domain exception hierarchy for xdg_kit.

Every error xdg-kit raises on purpose derives from ``XdgKitError``, so a caller can handle
this package's failures with one ``except`` without catching unrelated bugs. A malformed
*argument* (an app name that is not a safe directory segment) is a caller mistake rather
than a runtime condition, so ``InvalidAppNameError`` is *also* a ``ValueError`` -- it joins
this hierarchy yet an ``except ValueError`` still catches it.
"""

from __future__ import annotations

__all__ = [
    "XdgKitError",
    "CredentialsError",
    "InsecureStorageError",
    "InvalidAppNameError",
]


class XdgKitError(Exception):
    """Base for every error xdg-kit raises deliberately."""


class InvalidAppNameError(XdgKitError, ValueError):
    """An app name is not a safe directory segment (empty, a path separator, ``..``, or
    leading/trailing punctuation). It subclasses ``ValueError`` -- a bad literal name is a
    caller mistake -- while still joining the ``XdgKitError`` hierarchy, so a consumer can
    catch it either way and a CLI can single it out as a usage error."""


class CredentialsError(XdgKitError):
    """A credentials store is present but unusable: unreadable, not JSON, not a JSON
    object, or a keyring backend that failed. Its message carries the path or the
    underlying cause."""


class InsecureStorageError(XdgKitError):
    """A directory or file that must be private is not: it exists but is owned by
    another user, is a symlink, or carries permissions that expose it to group or
    others. Raised rather than silently trusting it, because a secret written there
    would leak."""
