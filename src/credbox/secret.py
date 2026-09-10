"""The ``Secret`` value type and the canonical ``mask_secret`` display helper.

A ``Secret`` wraps a credential value so it never lands in a log by accident: ``str`` and
``repr`` render a mask, equality is constant-time, and the type is unhashable so it cannot
become a dict or cache key. Call ``.reveal()`` to obtain the raw value at the point of use.

``mask_secret`` is the single canonical mask used by ``Secret``'s ``__str__``/``__repr__``
and by the CLI -- there is no second, divergent masking routine.
"""

from __future__ import annotations

import hmac

__all__ = ["Secret", "mask_secret"]


def mask_secret(value: str, *, edge: int = 4) -> str:
    """Return a display-safe rendering of ``value`` that reveals at most its two edges.

    Reveals ``value[:edge] + "..." + value[-edge:]`` ONLY when ``edge > 0`` and
    ``len(value) >= 4 * edge``; otherwise returns ``"***"`` (neither edge shown). The
    ``edge > 0`` half is not optional: with ``edge == 0`` the ``4 * edge`` test is always
    true and ``value[-0:]`` is ``value[0:]`` -- the whole secret. The ``4 * edge`` floor
    keeps a short value from revealing most of itself (a 9-char value at ``edge=4`` would
    otherwise show 8 of 9 chars).
    """
    if edge <= 0 or len(value) < 4 * edge:
        return "***"
    return f"{value[:edge]}...{value[-edge:]}"


class Secret:
    """A wrapped credential value that resists accidental disclosure.

    ``str``/``repr`` render ``mask_secret`` of the value; equality is constant-time against
    another ``Secret``; the type is unhashable (it cannot become a dict or cache key, so a
    secret never lands in one silently). Use ``reveal()`` to obtain the raw ``str`` at the
    point of use.
    """

    # Defining __eq__ below (without __hash__) makes Secret unhashable: Python sets
    # __hash__ to None at class creation, so a secret can never become a dict/cache key.
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Secret value must be str, not {type(value).__name__}")
        self._value = value

    def reveal(self) -> str:
        """Return the raw secret value."""
        return self._value

    def __str__(self) -> str:
        return mask_secret(self._value)

    def __repr__(self) -> str:
        return f"Secret({mask_secret(self._value)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        # Encode to bytes first: hmac.compare_digest raises TypeError on a non-ASCII str. Use
        # errors="surrogatepass" so a value holding a lone surrogate (e.g. a secret sourced from an
        # env var via surrogateescape) encodes to deterministic bytes rather than raising a
        # UnicodeEncodeError whose .object/.args would carry the raw secret out of this frame.
        return hmac.compare_digest(
            self._value.encode("utf-8", "surrogatepass"),
            other._value.encode("utf-8", "surrogatepass"),
        )
