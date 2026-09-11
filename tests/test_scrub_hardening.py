"""Tests for the scrub hardening: URL-encoded forms, transport request/response URLs,
PEP 678 notes, and the never-raise contract against a property that raises."""

from __future__ import annotations

from urllib.parse import quote, quote_plus

from credbox.scrub import REDACTION, scrub_exception, scrub_secrets

SECRET = "s3cr3t/p@ss word"


def test_scrub_secrets_redacts_url_encoded_forms() -> None:
    text = f"raw={SECRET} quoted={quote(SECRET)} plus={quote_plus(SECRET)}"
    scrubbed = scrub_secrets(text, [SECRET])
    assert SECRET not in scrubbed
    assert quote(SECRET) not in scrubbed
    assert quote_plus(SECRET) not in scrubbed
    assert scrubbed.count(REDACTION) >= 3


class _UrlHolder:
    def __init__(self, url: str) -> None:
        self.url = url


def test_scrub_exception_scrubs_request_and_response_url() -> None:
    err = ValueError(f"failed with {SECRET}")
    err.request = _UrlHolder(f"https://api/?key={quote_plus(SECRET)}")  # type: ignore[attr-defined]
    err.response = _UrlHolder(f"https://api/redir?key={SECRET}")  # type: ignore[attr-defined]
    scrub_exception(err, [SECRET])
    assert SECRET not in str(err.args)
    assert SECRET not in err.request.url  # type: ignore[attr-defined]
    assert quote_plus(SECRET) not in err.request.url  # type: ignore[attr-defined]
    assert SECRET not in err.response.url  # type: ignore[attr-defined]


def test_scrub_exception_scrubs_pep678_notes() -> None:
    err = ValueError("boom")
    err.add_note(f"context: {SECRET}")
    scrub_exception(err, [SECRET])
    assert all(SECRET not in note for note in err.__notes__)


class _RaisingUrl:
    @property
    def url(self) -> str:
        raise RuntimeError("url is unset")  # an httpx-style property that raises when unset


def test_scrub_exception_survives_a_url_property_that_raises() -> None:
    # The raising url lives on err.request (the owner walk), distinct from test_scrub.py's
    # raising url on the exception node itself.
    err = ValueError(f"failed {SECRET}")
    err.request = _RaisingUrl()  # type: ignore[attr-defined]
    result = scrub_exception(err, [SECRET])  # must not raise
    assert result is err
    assert SECRET not in str(err.args)


def test_scrub_secrets_rejects_a_bytes_arg_instead_of_silently_passing_through() -> None:
    # A bytes `secrets` is Iterable[int], so without the eager guard it would match no str item,
    # redact nothing, and return the secret-bearing log verbatim -- a silent no-op on a leak guard.
    # It must raise loudly (and BEFORE the never-raises body swallows it) so the misuse surfaces.
    import pytest

    log = f"leaking {SECRET}"
    for binary in (SECRET.encode(), bytearray(SECRET.encode()), memoryview(SECRET.encode())):
        with pytest.raises(TypeError):
            scrub_secrets(log, binary)   # type: ignore[arg-type]  # the point: binary is refused


def test_scrub_exception_rejects_a_bytes_arg_without_rendering_the_in_flight_secret() -> None:
    import pytest

    # Called inside an except block (the realistic scrub_exception site). The guard's `from None`
    # sets __suppress_context__ so the in-flight, secret-bearing exception is not RENDERED in the
    # TypeError's traceback. (Python still records __context__ as an object link -- `from None` does
    # NOT detach it -- so we assert the suppression flag, never `__context__ is None`.)
    try:
        raise RuntimeError(f"in-flight {SECRET}")
    except RuntimeError:
        with pytest.raises(TypeError) as excinfo:
            scrub_exception(ValueError(f"leaking {SECRET}"), SECRET.encode())   # type: ignore[arg-type]
    assert excinfo.value.__suppress_context__ is True
