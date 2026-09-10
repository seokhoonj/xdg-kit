"""Tests for the keyring backend, driven by a fake ``keyring`` module injected into
``sys.modules`` (the real one is optional and not installed here).

The headline test is the P1 leak regression: a keyring call that raises an exception whose text
embeds the secret must produce a content-free ``CredentialsError`` with BOTH ``__cause__`` and
``__context__`` ``None`` -- the third-party exception must not survive on the exception graph.
"""

from __future__ import annotations

import sys
import types

import pytest

from credbox.backends.file import FileBackend
from credbox.backends.keyring import KeyringBackend
from credbox.errors import CredentialsError, NoKeyringError
from credbox.secret import Secret

SECRET = "sk_live_TOPSECRET_0123456789"


def _install_fake_keyring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    get=lambda service, username: None,
    set_=lambda service, username, password: None,
    delete=lambda service, username: None,
) -> types.ModuleType:
    """Install a fake ``keyring`` (+ ``keyring.errors``) into sys.modules and return it."""
    errors = types.ModuleType("keyring.errors")

    class KeyringError(Exception):
        pass

    class NoKeyringErr(KeyringError):
        pass

    class PasswordDeleteError(KeyringError):
        pass

    errors.KeyringError = KeyringError  # type: ignore[attr-defined]
    errors.NoKeyringError = NoKeyringErr  # type: ignore[attr-defined]
    errors.PasswordDeleteError = PasswordDeleteError  # type: ignore[attr-defined]

    keyring = types.ModuleType("keyring")
    keyring.errors = errors  # type: ignore[attr-defined]
    keyring.get_password = get  # type: ignore[attr-defined]
    keyring.set_password = set_  # type: ignore[attr-defined]
    keyring.delete_password = delete  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    return keyring


def _graph_contains(err: BaseException, needle: str) -> bool:
    seen: set[int] = set()
    stack: list[BaseException | None] = [err]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if needle in str(node) or needle in repr(node.args):
            return True
        stack.append(node.__cause__)
        stack.append(node.__context__)
    return False


def test_keyring_error_embedding_the_secret_never_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(service: str, username: str) -> str:
        raise RuntimeError(f"backend failed while handling value {SECRET}")

    _install_fake_keyring(monkeypatch, get=boom)
    backend = KeyringBackend()   # no fallback -> must raise
    with pytest.raises(CredentialsError) as excinfo:
        backend.get("app", "name")
    err = excinfo.value
    assert SECRET not in str(err)
    assert err.__cause__ is None        # chain broken
    assert err.__context__ is None      # the P1 fix: not left on __context__ either
    assert not _graph_contains(err, SECRET)


def test_no_backend_without_fallback_raises_nokeyringerror(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = _install_fake_keyring(monkeypatch)

    def no_backend(service: str, username: str) -> str:
        raise keyring.errors.NoKeyringError("no backend on this host")

    monkeypatch.setattr(keyring, "get_password", no_backend)
    with pytest.raises(NoKeyringError) as excinfo:
        KeyringBackend().get("app", "name")
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_falls_back_to_file_when_no_keyring_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # The LEGITIMATE fallback: no OS keyring backend exists at all (headless). This is the only
    # case that consults the file.
    keyring = _install_fake_keyring(monkeypatch)

    def no_backend(service: str, username: str) -> str:
        raise keyring.errors.NoKeyringError("no backend on this host")

    monkeypatch.setattr(keyring, "get_password", no_backend)
    fallback = FileBackend()
    fallback.set("app", "name", value=SECRET)
    got = KeyringBackend(fallback=fallback).get("app", "name")
    assert isinstance(got, Secret)
    assert got.reveal() == SECRET


def test_get_fails_closed_on_a_keyring_error_even_with_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A present-but-erroring keyring must NOT silently serve the (stale/attacker-planted) file
    # value in place of the authoritative keyring value.
    def boom(service: str, username: str) -> str:
        raise RuntimeError("keyring is locked")

    _install_fake_keyring(monkeypatch, get=boom)
    fallback = FileBackend()
    fallback.set("app", "name", value="stale_value")
    with pytest.raises(CredentialsError):
        KeyringBackend(fallback=fallback).get("app", "name")


def test_set_fails_closed_on_a_keyring_error_and_writes_no_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A keyring write error must NOT downgrade to a plaintext file write (which would report
    # success while the keyring's old value keeps shadowing this write on recovery).
    def boom(service: str, username: str, password: str) -> None:
        raise RuntimeError("keyring is locked")

    _install_fake_keyring(monkeypatch, set_=boom)
    fallback = FileBackend()
    with pytest.raises(CredentialsError):
        KeyringBackend(fallback=fallback).set("app", "name", value=SECRET)
    assert fallback.get("app", "name") is None   # nothing was written to the fallback


def test_keyring_hit_returns_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_keyring(monkeypatch, get=lambda service, username: SECRET)
    got = KeyringBackend().get("app", "name")
    assert isinstance(got, Secret)
    assert got.reveal() == SECRET


def test_set_clears_a_stale_fallback_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], str] = {}
    _install_fake_keyring(
        monkeypatch, set_=lambda service, username, password: stored.__setitem__((service, username), password)
    )
    fallback = FileBackend()
    fallback.set("app", "name", value="stale_plaintext")
    KeyringBackend(fallback=fallback).set("app", "name", value=SECRET)
    assert stored[("app", "name")] == SECRET
    assert fallback.get("app", "name") is None   # stale file copy cleared


def test_unset_fails_closed_when_keyring_delete_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = _install_fake_keyring(monkeypatch)

    def boom(service: str, username: str) -> None:
        raise keyring.errors.KeyringError("store is locked")

    monkeypatch.setattr(keyring, "delete_password", boom)
    with pytest.raises(CredentialsError):
        KeyringBackend().unset("app", "name")


def test_names_reports_only_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_keyring(monkeypatch)
    fallback = FileBackend()
    fallback.set("app", "k", value="v")
    assert KeyringBackend(fallback=fallback).names("app") == ["k"]


def test_set_and_unset_fall_back_to_file_when_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The write-side of the headless fallback (the normal path on cron/container/server hosts):
    # with no OS keyring, set/unset delegate to the file store and warn exactly once.
    keyring = _install_fake_keyring(monkeypatch)

    def no_backend(*args: object, **kwargs: object) -> str:
        raise keyring.errors.NoKeyringError("no backend on this host")

    monkeypatch.setattr(keyring, "set_password", no_backend)
    monkeypatch.setattr(keyring, "get_password", no_backend)
    monkeypatch.setattr(keyring, "delete_password", no_backend)
    fallback = FileBackend()
    backend = KeyringBackend(fallback=fallback)

    backend.set("app", "name", value=SECRET)
    backend.set("app", "other", value="second")   # same process -> still one warning
    assert fallback.get("app", "name").reveal() == SECRET   # type: ignore[union-attr]
    assert backend.get("app", "name").reveal() == SECRET    # type: ignore[union-attr]

    backend.unset("app", "name")
    assert fallback.get("app", "name") is None

    err = capsys.readouterr().err
    assert err.count("OS keyring unavailable") == 1
    assert SECRET not in err
