"""Removing secret values from text before it is logged or surfaced.

A provider often echoes the API key back inside an error message or a request URL, so an
unscrubbed exception can leak the very secret it failed to use into a log or a terminal.
``scrub_secrets`` replaces each known secret value in a string with ``***``;
``scrub_exception`` walks an exception and its ``__cause__`` / ``__context__`` chain and
scrubs each one's ``args`` (and a transport error's URL) in place. Both are best-effort and
never raise -- they run on the error path, where a second failure would mask the first.
The caller supplies the secret *values* to redact; this module never reads a store.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = [
    "scrub_secrets",
    "scrub_exception",
]

REDACTION = "***"


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Return ``text`` with every non-empty value in ``secrets`` replaced by ``***``.

    Longer secrets are replaced first, so a secret that is a prefix of another does not
    leave the other's tail exposed. Best-effort and never raises: a non-iterable ``secrets``
    leaves ``text`` unchanged (matching ``scrub_exception``)."""
    try:
        values = sorted(
            (value for value in secrets if isinstance(value, str) and value),
            key=len,
            reverse=True,
        )
    except Exception:
        return text
    result = text
    for value in values:
        result = result.replace(value, REDACTION)
    return result


def scrub_exception(err: BaseException, secrets: Iterable[str]) -> BaseException:
    """Scrub every secret in ``secrets`` from ``err`` and its ``__cause__`` / ``__context__``
    chain, in place, and return ``err``. Best-effort: any failure while inspecting a node
    is swallowed, so this never raises on the error path.

    This rewrites each node's ``args`` and a string ``url`` attribute. It does **not**
    guarantee ``str(err)`` is clean for an exception with a custom ``__str__`` / ``__repr__``
    that renders something other than ``args`` (e.g. a transport error rendering
    ``request.url`` or a ``.filename``), so also pass the rendered log line through
    ``scrub_secrets`` before emitting it."""
    try:
        values = [value for value in secrets if isinstance(value, str) and value]
    except Exception:
        return err   # a non-iterable or raising `secrets` must not mask the original error
    if not values:
        return err
    seen: set[int] = set()
    stack: list[BaseException | None] = [err]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        _scrub_node(node, values)
        for attr in ("__cause__", "__context__"):
            try:
                stack.append(getattr(node, attr, None))
            except Exception:
                pass
    return err


def _scrub_node(node: BaseException, values: list[str]) -> None:
    """Scrub ``node.args`` and a transport error's ``url``, each guarded independently so a
    property that raises (httpx spells ``url`` as one) cannot abort the walk."""
    try:
        args = node.args
        if args:
            node.args = tuple(
                scrub_secrets(arg, values) if isinstance(arg, str) else arg for arg in args
            )
    except Exception:
        pass
    try:
        url = getattr(node, "url", None)
        if isinstance(url, str):
            node.url = scrub_secrets(url, values)   # type: ignore[attr-defined]
    except Exception:
        pass
