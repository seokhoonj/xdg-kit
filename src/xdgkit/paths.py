"""XDG base directories for an application, resolved the same way on every OS.

Follows the XDG Base Directory Specification's names and defaults
(https://specifications.freedesktop.org/basedir/latest/): each kind of file gets its own
base directory, taken from the matching ``XDG_*_HOME`` variable when it holds an absolute
path, else the spec's home-relative default. The same layout is used on macOS and Windows
too -- the convention git / ssh / aws already follow there -- so a path is identical
across machines and no platform library is needed.

- ``config_dir(app)`` -- hand-editable configuration and ``credentials.json``.
  (``$XDG_CONFIG_HOME``, else ``~/.config``)
- ``data_dir(app)``   -- durable, hard-to-regenerate data.
  (``$XDG_DATA_HOME``, else ``~/.local/share``)
- ``state_dir(app)``  -- persistent but replaceable run state and logs.
  (``$XDG_STATE_HOME``, else ``~/.local/state``)
- ``cache_dir(app)``  -- discardable cache.
  (``$XDG_CACHE_HOME``, else ``~/.cache``)

``data_dir`` and ``state_dir`` also honour a per-app ``<APP>_DATA_DIR`` / ``<APP>_STATE_DIR``
environment override (an explicit absolute path used as-is), so a large archive or a log
can be relocated to another volume without editing anything. ``config_dir`` has no such
override -- configuration cannot name its own location -- and ``cache_dir`` is not worth
relocating; both are still redirectable through the standard ``XDG_*_HOME`` variables.

The session-scoped ``runtime_dir(app)`` lives in ``runtime.py``, because ``XDG_RUNTIME_DIR``
has no spec default and needs a secured fallback.

An ``app`` is a single directory-name segment (``"myapp"``, ``"my-app"``), validated by
``app_dir_segment`` so it can never escape its base with a separator or ``..``.
"""

from __future__ import annotations

import re
from pathlib import Path

from xdgkit.environment import absolute_override
from xdgkit.errors import InvalidAppNameError, XdgkitError

__all__ = [
    "config_dir",
    "data_dir",
    "state_dir",
    "cache_dir",
    "app_dir_segment",
]

_APP_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def app_dir_segment(app: str) -> str:
    """Return ``app`` unchanged once validated as a safe single path segment, or raise.

    A valid name starts and ends with a letter or digit and contains only letters,
    digits, ``.``, ``_``, and ``-`` between (``"my-app"``, ``"a.b_c"``). This rejects an
    empty name, a path separator, ``.``/``..``, and leading/trailing punctuation, so
    ``config_dir(app)`` can never be steered out of its XDG base by a crafted name.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment (a caller mistake).
            It is a ``ValueError`` too, so an ``except ValueError`` still catches it.
    """
    if not _APP_NAME.fullmatch(app):
        raise InvalidAppNameError(
            f"invalid app name {app!r}: expected a single path segment of letters, "
            f"digits, '.', '_', '-' (e.g. 'my-app')"
        )
    return app


def config_dir(app: str) -> Path:
    """Hand-editable configuration and ``credentials.json`` for ``app``.

    ``$XDG_CONFIG_HOME/<app>`` when that variable is an absolute path, else
    ``~/.config/<app>`` -- the same on every OS.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment.
        XdgkitError: no home directory can be determined and ``XDG_CONFIG_HOME`` is unset
            or not absolute.
    """
    return _xdg_app_dir("XDG_CONFIG_HOME", ".config", app_dir_segment(app))


def data_dir(app: str) -> Path:
    """Durable, hard-to-regenerate data for ``app`` (a database, an archive).

    A ``<APP>_DATA_DIR`` environment override wins, taken as an explicit absolute path
    used as-is (``~`` expanded, no app segment appended). Otherwise ``$XDG_DATA_HOME/<app>``,
    else ``~/.local/share/<app>``.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment.
        XdgkitError: no home directory can be determined and neither the override nor
            ``XDG_DATA_HOME`` gives an absolute path.
    """
    segment = app_dir_segment(app)
    override = absolute_override(_app_env_var(app, "DATA_DIR"))
    if override is not None:
        return override
    return _xdg_app_dir("XDG_DATA_HOME", ".local/share", segment)


def state_dir(app: str) -> Path:
    """Persistent but replaceable run state and logs for ``app`` (watermarks, a log).

    A ``<APP>_STATE_DIR`` environment override wins, used as-is (symmetric with
    ``data_dir``). Otherwise ``$XDG_STATE_HOME/<app>``, else ``~/.local/state/<app>``.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment.
        XdgkitError: no home directory can be determined and neither the override nor
            ``XDG_STATE_HOME`` gives an absolute path.
    """
    segment = app_dir_segment(app)
    override = absolute_override(_app_env_var(app, "STATE_DIR"))
    if override is not None:
        return override
    return _xdg_app_dir("XDG_STATE_HOME", ".local/state", segment)


def cache_dir(app: str) -> Path:
    """Discardable cache for ``app`` -- safe to delete between runs.

    ``$XDG_CACHE_HOME/<app>`` when absolute, else ``~/.cache/<app>``.

    Raises:
        InvalidAppNameError: ``app`` is not a valid directory segment.
        XdgkitError: no home directory can be determined and ``XDG_CACHE_HOME`` is unset
            or not absolute.
    """
    return _xdg_app_dir("XDG_CACHE_HOME", ".cache", app_dir_segment(app))


# --- private resolvers ---------------------------------------------------------

def _xdg_app_dir(env_name: str, home_subpath: str, segment: str) -> Path:
    """``$<env_name>/<segment>`` when the variable is an absolute path, else
    ``~/<home_subpath>/<segment>`` (the XDG spec's own home-relative fallback). A blank,
    relative, or unresolvable value is ignored per the spec.

    Raises:
        XdgkitError: no absolute env value and no home directory can be determined --
            converted from the ``RuntimeError`` ``Path.home`` raises, so it stays inside
            xdgkit's error surface."""
    root = absolute_override(env_name)
    if root is not None:
        return root / segment
    try:
        home = Path.home()
    except RuntimeError as err:
        raise XdgkitError(
            f"cannot locate ~/{home_subpath}/{segment}: no home directory "
            f"(set HOME, or set {env_name} to an absolute path)"
        ) from err
    return home / home_subpath / segment


def _app_env_var(app: str, suffix: str) -> str:
    """The per-app override variable name: the app upper-cased with every non-alphanumeric
    character folded to ``_``, then ``_<suffix>`` (``my-app`` -> ``MY_APP`` ->
    ``MY_APP_DATA_DIR``).

    The fold is lossy: ``a.b``, ``a-b``, and ``a_b`` all map to ``A_B``, so distinct app
    names that differ only in punctuation share one override variable. Harmless for the
    hyphen/underscore-free names that are the norm, but a caller relying on the override
    for two such near-twins should pick names that do not collide."""
    stem = re.sub(r"[^A-Za-z0-9]", "_", app).upper()
    return f"{stem}_{suffix}"
