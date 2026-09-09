"""Removing secret values from text before it is logged or surfaced.

A provider often echoes the API key back inside an error message or a request URL, so an
unscrubbed exception can leak the very secret it failed to use into a log or a terminal.
``scrub_secrets`` replaces each known secret value -- and its URL-encoded forms -- in a string
with ``***``; ``scrub_exception`` walks an exception and its ``__cause__`` / ``__context__``
chain and scrubs each node's ``args``, its transport URLs (``url``, ``request.url``,
``response.url``), and its ``__notes__`` in place. Both are best-effort: they run on the error
path, where a second failure would mask the first, so any *ordinary* exception while inspecting a
node is swallowed. The one carve-out is ``MemoryError`` (and ``KeyboardInterrupt`` / ``SystemExit``,
which are not ``Exception`` and propagate anyway): it is re-raised rather than swallowed, because
swallowing it would return the still-unscrubbed, secret-bearing text as the function's result --
a worse leak than the bare ``MemoryError``, whose own ``str`` carries no secret. The caller
supplies the secret *values* to redact; this module never reads a store.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import quote, quote_plus

__all__ = [
    "scrub_secrets",
    "scrub_exception",
]

REDACTION = "***"


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Return ``text`` with every non-empty value in ``secrets`` -- and each value's
    URL-encoded (``quote`` / ``quote_plus``) forms -- replaced by ``***``.

    Longer targets are replaced first, so a secret that is a prefix of another (or of its own
    encoded form) does not leave a tail exposed. Best-effort and never raises: a non-iterable
    ``secrets`` leaves ``text`` unchanged."""
    try:
        secret_values = [value for value in secrets if isinstance(value, str) and value]
    except MemoryError:
        raise   # never swallow OOM into a return of the still-unscrubbed text (see module docstring)
    except Exception:
        # a non-iterable or mid-iteration-raising `secrets` must not raise on the error path
        return text
    result = text
    for target in _redaction_targets(secret_values):
        result = result.replace(target, REDACTION)
    return result


def scrub_exception(err: BaseException, secrets: Iterable[str]) -> BaseException:
    """Scrub every secret in ``secrets`` from ``err`` and its ``__cause__`` / ``__context__``
    chain, in place, and return ``err``. Best-effort: any failure while inspecting a node is
    swallowed, so this never raises on the error path.

    Per node it rewrites ``args``, the transport URLs (``url``, ``request.url``,
    ``response.url`` -- each ``getattr``-guarded, since httpx spells them as properties that
    raise when unset), and ``__notes__`` (PEP 678). It does **not** guarantee ``str(err)`` is
    clean for an exception with a custom ``__str__`` that renders something other than these,
    so also pass the rendered log line through ``scrub_secrets`` before emitting it."""
    try:
        secret_values = [value for value in secrets if isinstance(value, str) and value]
    except MemoryError:
        raise   # never swallow OOM into a return of the still-unscrubbed error (see module docstring)
    except Exception:
        return err   # a non-iterable or raising `secrets` must not mask the original error
    if not secret_values:
        return err
    seen: set[int] = set()
    stack: list[BaseException | None] = [err]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        _scrub_node(node, secret_values)
        for attr in ("__cause__", "__context__"):
            try:
                stack.append(getattr(node, attr, None))
            except Exception:
                pass   # a custom exception's attribute access may raise; never on the error path
    return err


def _redaction_targets(secret_values: list[str]) -> list[str]:
    """Every string that must be redacted -- each secret plus its ``quote``/``quote_plus``
    forms -- deduplicated and ordered longest-first so no target's replacement uncovers
    another's tail."""
    targets: set[str] = set()
    for value in secret_values:
        targets.add(value)
        try:
            targets.add(quote(value))
            targets.add(quote_plus(value))
        except Exception:
            pass   # an exotic value that will not URL-encode: the raw form is still redacted
    return sorted(targets, key=len, reverse=True)


def _scrub_node(node: BaseException, secret_values: list[str]) -> None:
    """Scrub ``node.args``, its transport URLs, and its ``__notes__``, each guarded
    independently so a property that raises cannot abort the walk."""
    try:
        args = node.args
        if args:
            node.args = tuple(
                scrub_secrets(arg, secret_values) if isinstance(arg, str) else arg for arg in args
            )
    except MemoryError:
        raise   # never swallow OOM into leaving `args` unscrubbed on the node
    except Exception:
        pass   # a custom .args accessor may raise; the never-raise contract wins here
    _scrub_url_attr(node, secret_values)
    for owner_name in ("request", "response"):
        try:
            owner = getattr(node, owner_name, None)
        except Exception:
            owner = None
        if owner is not None:
            _scrub_url_attr(owner, secret_values)
    try:
        notes = getattr(node, "__notes__", None)
        if isinstance(notes, list):
            node.__notes__ = [
                scrub_secrets(note, secret_values) if isinstance(note, str) else note
                for note in notes
            ]
    except MemoryError:
        raise   # never swallow OOM into leaving `__notes__` unscrubbed on the node
    except Exception:
        pass   # a custom __notes__ may not be assignable; never on the error path


def _scrub_url_attr(obj: object, secret_values: list[str]) -> None:
    """Scrub a string ``url`` attribute on ``obj`` in place, fully guarded -- reading ``url``
    (an httpx property) can itself raise when unset, and a non-string ``url`` (an httpx URL
    object) is left alone."""
    try:
        url = getattr(obj, "url", None)
    except Exception:
        return   # a property that raises when unset
    if isinstance(url, str):
        try:
            obj.url = scrub_secrets(url, secret_values)  # type: ignore[attr-defined]
        except MemoryError:
            raise   # never swallow OOM into leaving the URL unscrubbed on the node
        except Exception:
            pass   # a read-only or custom url property: cannot rewrite it, and must not raise
