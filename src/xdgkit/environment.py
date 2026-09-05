"""Reading values from the environment with one consistent rule: a blank or
whitespace-only value counts as *absent*.

xdgkit resolves both directories (an ``$XDG_CONFIG_HOME`` or a per-app override) and
secrets (a ``GEMINI_API_KEY``) from the environment before falling back to a file. In
every case an empty string must read as "not set" rather than as an explicit empty
value, so that an exported-but-blank variable falls through to the default instead of
overriding it with nothing. Centralised here so directories and secrets treat the
environment identically.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "env_value",
    "absolute_override",
]


def env_value(name: str) -> str | None:
    """Return ``os.environ[name]`` stripped of surrounding whitespace, or ``None`` when
    the variable is unset, empty, or whitespace-only."""
    value = os.environ.get(name, "").strip()
    return value or None


def absolute_override(name: str) -> Path | None:
    """Return the environment value ``name`` as an absolute path (``~`` expanded), or
    ``None`` when it is unset, blank, relative, or a ``~user`` whose home cannot be
    resolved.

    A relative value is rejected on purpose: the XDG spec says a relative base "must be
    ignored", and a relative override would resolve against the current working
    directory, silently splitting a cron run (cwd ``/``) from an interactive run
    (cwd ``~``). Never raises -- an advisory override must not crash the resolver."""
    raw = env_value(name)
    if raw is None:
        return None
    try:
        path = Path(raw).expanduser()
    except RuntimeError:
        return None
    return path if path.is_absolute() else None
