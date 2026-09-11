"""Storage layout selection: XDG everywhere (the default) or OS-native locations.

``default_layout()`` resolves **lazily** -- never at import time -- so ``import credbox``
cannot fail on a malformed ``CREDBOX_LAYOUT``. A present-but-malformed value is ignored (it
falls through to any explicit ``set_default_layout``, else ``"xdg"``) and never raises.
"""

from __future__ import annotations

from typing import Literal

from credbox.environment import env_value
from credbox.errors import InvalidLayoutError

__all__ = ["Layout", "default_layout", "set_default_layout"]

Layout = Literal["xdg", "native"]

_override: Layout | None = None


def default_layout() -> Layout:
    """Resolve the active layout, lazily. Precedence: a valid ``CREDBOX_LAYOUT`` env value
    (case-insensitive) > a ``set_default_layout`` value > ``"xdg"``. A present-but-malformed
    ``CREDBOX_LAYOUT`` is ignored (never raises), keeping ``import credbox`` safe."""
    env = env_value("CREDBOX_LAYOUT")
    if env is not None:
        candidate = env.lower()
        if candidate == "xdg":
            return "xdg"
        if candidate == "native":
            return "native"
    if _override is not None:
        return _override
    return "xdg"


def set_default_layout(layout: Layout) -> None:
    """Set the process-wide default layout used when a call passes ``layout=None``. A valid
    ``CREDBOX_LAYOUT`` env value still overrides this."""
    global _override
    if layout not in ("xdg", "native"):
        raise InvalidLayoutError(f"layout must be 'xdg' or 'native', not {layout!r}")
    _override = layout
