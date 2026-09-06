"""Secret scrubbing: redact values from text and exception chains without ever raising."""

from __future__ import annotations

from xdg_kit.scrub import REDACTION, scrub_exception, scrub_secrets


def test_scrub_replaces_each_secret():
    text = "auth with sk-abc and sk-def"
    out = scrub_secrets(text, ["sk-abc", "sk-def"])
    assert "sk-abc" not in out and "sk-def" not in out
    assert out.count(REDACTION) == 2


def test_scrub_ignores_empty_secrets():
    assert scrub_secrets("hello", ["", "   ", None]) == "hello"   # type: ignore[list-item]


def test_scrub_prefix_secret_does_not_leak_suffix():
    # "abc" is a prefix of "abcdef"; longest-first replacement must not leave "def" behind
    assert scrub_secrets("abcdef", ["abc", "abcdef"]) == "***"


def test_scrub_secrets_survives_non_iterable():
    assert scrub_secrets("boom", None) == "boom"   # type: ignore[arg-type]  # never raises


def test_scrub_exception_cleans_args():
    err = ValueError("key sk-secret rejected")
    scrub_exception(err, ["sk-secret"])
    assert "sk-secret" not in str(err)
    assert REDACTION in str(err)


def test_scrub_exception_walks_cause_chain():
    root = ValueError("inner sk-secret")
    try:
        try:
            raise root
        except ValueError as inner:
            raise RuntimeError("outer sk-secret") from inner
    except RuntimeError as err:
        scrub_exception(err, ["sk-secret"])
        assert "sk-secret" not in str(err)
        assert err.__cause__ is not None
        assert "sk-secret" not in str(err.__cause__)


def test_scrub_exception_cleans_url_attribute():
    err = ConnectionError("failed")
    err.url = "https://api/v1?key=sk-secret"   # type: ignore[attr-defined]
    scrub_exception(err, ["sk-secret"])
    assert "sk-secret" not in err.url   # type: ignore[attr-defined]


def test_scrub_exception_survives_raising_property():
    class Nasty(Exception):
        @property
        def url(self):
            raise RuntimeError("property blows up")

    err = Nasty("sk-secret in message")
    # must not raise, and must still scrub args
    scrub_exception(err, ["sk-secret"])
    assert "sk-secret" not in str(err)


def test_scrub_exception_handles_self_referential_cause():
    err = ValueError("sk-secret")
    err.__cause__ = err   # pathological cycle must not loop forever
    scrub_exception(err, ["sk-secret"])
    assert "sk-secret" not in str(err)


def test_scrub_exception_preserves_non_string_args():
    sentinel = object()
    err = Exception("token sk-secret", 404, sentinel)
    scrub_exception(err, ["sk-secret"])
    assert "sk-secret" not in err.args[0]
    assert err.args[1] == 404          # non-string args untouched
    assert err.args[2] is sentinel


def test_scrub_exception_survives_non_iterable_secrets():
    err = ValueError("sk-secret")
    result = scrub_exception(err, None)   # type: ignore[arg-type]  # must not raise
    assert result is err


def test_scrub_survives_secrets_iterator_that_raises_mid_iteration():
    # a secrets iterator can yield one value and then raise while an error is already being
    # handled; both entry points must swallow that and never propagate on the error path
    def secrets_then_boom():
        yield "sk-secret"
        raise RuntimeError("iterator blew up mid-iteration")

    assert scrub_secrets("has sk-secret", secrets_then_boom()) == "has sk-secret"
    err = ValueError("sk-secret here")
    assert scrub_exception(err, secrets_then_boom()) is err


def test_scrub_exception_walks_context_chain():
    # an implicit __context__ (a raise inside an except, without `from`) is a separate edge
    # from __cause__ and must also be scrubbed
    try:
        try:
            raise ValueError("inner sk-secret")
        except ValueError:
            raise RuntimeError("outer sk-secret")   # noqa: B904 -- implicit __context__ is the point
    except RuntimeError as err:
        scrub_exception(err, ["sk-secret"])
        assert err.__context__ is not None
        assert "sk-secret" not in str(err)
        assert "sk-secret" not in str(err.__context__)
