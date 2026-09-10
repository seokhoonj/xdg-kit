"""The leak-safe store codec: ``parse_store`` / ``serialize_store``.

A *returning-frame* pair. Each decodes or encodes the store map INSIDE a function that
RETURNS, so a content-bearing exception (``UnicodeDecodeError.object``, ``JSONDecodeError.doc``)
is caught here and turned into a content-free ``StoreFault`` -- it never escapes to a raise
site that could keep the secret bytes alive on ``__context__`` or in traceback frame-locals.

Catches are NARROW on purpose: only the specific decode/parse errors map to a fault. A
``MemoryError``, ``KeyboardInterrupt``, ``SystemExit``, or a genuine bug propagates -- the
codec never swallows it behind a fault. The caller (``FileBackend``) turns a ``StoreFault``
into a ``CredentialsError`` built from the enum/ints only, in a frame where no secret local
is bound.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

__all__ = ["StoreFaultKind", "StoreFault", "parse_store", "serialize_store"]


class StoreFaultKind(Enum):
    """A content-free reason the store could not be parsed or serialized -- the enum member
    only, never ``str(err)`` or any file content."""

    NOT_UTF8 = "not_utf8"
    NOT_JSON = "not_json"
    NOT_OBJECT = "not_object"               # top-level JSON is not an object
    NOT_STRING_VALUE = "not_string_value"   # a value in the object is not a str (tampered store)
    NESTING = "nesting"                     # RecursionError while parsing
    NOT_ENCODABLE = "not_encodable"         # serialize side: lone-surrogate UnicodeEncodeError


@dataclass(frozen=True, slots=True)
class StoreFault:
    """A disjoint-sum failure of the codec: the kind, plus an optional JSON position (ints
    only, never file content)."""

    kind: StoreFaultKind
    lineno: int | None = None
    colno: int | None = None


def parse_store(store_bytes: bytes) -> dict[str, str] | StoreFault:
    """Decode UTF-8 and parse JSON inside this returning frame, returning the store map
    ``{name: secret}`` or a content-free ``StoreFault``.

    Narrow catches only: ``UnicodeDecodeError`` -> ``NOT_UTF8``; ``json.JSONDecodeError`` ->
    ``NOT_JSON`` (keeping the int ``lineno``/``colno``); a bare ``ValueError`` -> ``NOT_JSON``
    (``json.loads`` raises a plain ``ValueError`` -- not ``JSONDecodeError`` -- for a number
    literal past ``sys.get_int_max_str_digits()``; catching it here keeps a tampered store's raw
    bytes off the escaping traceback frame); ``RecursionError`` -> ``NESTING``. A parsed top level
    that is not a ``dict`` -> ``NOT_OBJECT``; any value that is not a ``str`` ->
    ``NOT_STRING_VALUE``, so a tampered ``{"k": {...}}`` never flows into ``Secret(str)``. Anything
    else -- ``MemoryError``, ``KeyboardInterrupt`` -- propagates.
    """
    try:
        text = store_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return StoreFault(StoreFaultKind.NOT_UTF8)
    try:
        try:
            parsed = json.loads(text)
        except RecursionError:
            return StoreFault(StoreFaultKind.NESTING)
        except json.JSONDecodeError as err:
            return StoreFault(StoreFaultKind.NOT_JSON, lineno=err.lineno, colno=err.colno)
        except ValueError:
            # json.loads raises a bare ValueError (not JSONDecodeError) for a number literal
            # exceeding the interpreter's integer-string-conversion limit; fold it here too.
            return StoreFault(StoreFaultKind.NOT_JSON)
    finally:
        del text
    if not isinstance(parsed, dict):
        return StoreFault(StoreFaultKind.NOT_OBJECT)
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return StoreFault(StoreFaultKind.NOT_STRING_VALUE)
    return parsed


def serialize_store(secret_value_by_name: dict[str, str]) -> bytes | StoreFault:
    """Serialize the store map to UTF-8 JSON bytes inside this returning frame.

    Narrow catch only: a lone-surrogate ``UnicodeEncodeError`` (the whole store) ->
    ``NOT_ENCODABLE``, never raised out. ``ensure_ascii=False`` is required so a lone
    surrogate surfaces as an encode error here rather than round-tripping as ``\\udXXX``.
    Inputs are already ``str`` values, so ``json.dumps`` cannot hit a non-str ``TypeError``.
    """
    try:
        text = json.dumps(secret_value_by_name, ensure_ascii=False)
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return StoreFault(StoreFaultKind.NOT_ENCODABLE)
