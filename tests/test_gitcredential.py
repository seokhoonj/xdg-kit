"""Tests for the git-credential adapter: the (app, name) -> Secret mapping, the username-less
first-contact lookup, and the stdout discipline (only a get reply, nothing on error)."""

from __future__ import annotations

import io

import pytest

from credbox.credentials import Credentials
from credbox.gitcredential import main


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    stdin_text: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    rc = main([operation])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_get_with_username_returns_the_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    Credentials("github.com").set("alice", value="ghp_secret123")
    rc, out, _ = _run(monkeypatch, capsys, "get", "host=github.com\nusername=alice\n\n")
    assert rc == 0
    assert "username=alice" in out
    assert "password=ghp_secret123" in out


def test_get_without_username_uses_the_sole_stored_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    Credentials("github.com").set("only_user", value="ghp_x")
    _rc, out, _ = _run(monkeypatch, capsys, "get", "host=github.com\n\n")
    assert "username=only_user" in out
    assert "password=ghp_x" in out


def test_get_without_username_and_many_names_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    Credentials("github.com").set("a", value="1")
    Credentials("github.com").set("b", value="2")
    _rc, out, _ = _run(monkeypatch, capsys, "get", "host=github.com\n\n")
    assert out == ""   # ambiguous -> no credential, git prompts


def test_get_unknown_credential_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, _ = _run(monkeypatch, capsys, "get", "host=github.com\nusername=nobody\n\n")
    assert rc == 0
    assert out == ""


def test_store_then_get_roundtrips(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, capsys, "store", "host=gitlab.com\nusername=bob\npassword=pw123\n\n")
    _rc, out, _ = _run(monkeypatch, capsys, "get", "host=gitlab.com\nusername=bob\n\n")
    assert "password=pw123" in out


def test_erase_removes_the_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    Credentials("gitlab.com").set("bob", value="pw")
    _run(monkeypatch, capsys, "erase", "host=gitlab.com\nusername=bob\n\n")
    _rc, out, _ = _run(monkeypatch, capsys, "get", "host=gitlab.com\nusername=bob\n\n")
    assert out == ""


def test_unusable_host_yields_no_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _run(monkeypatch, capsys, "get", "host=bad/host\nusername=x\n\n")
    assert rc == 0
    assert out == ""
    assert "bad/host" not in out
