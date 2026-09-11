"""Tests for the credbox CLI, focused on the leak-surface discipline: only get --reveal
writes a raw secret to stdout; everything else is masked/content-free, and no path prints a
traceback."""

from __future__ import annotations

import io

import pytest

from credbox.backends.file import FileBackend
from credbox.cli import main
from credbox.secret import mask_secret

SECRET = "sk_live_0123456789abcdef"


class _Tty(io.StringIO):
    """A stdin stand-in that reports as an interactive terminal (so `set` prompts via getpass)."""

    def isatty(self) -> bool:
        return True


def test_set_then_masked_get(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["set", "myapp", "api_key", "--value", SECRET]) == 0
    capsys.readouterr()
    assert main(["get", "myapp", "api_key"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == mask_secret(SECRET)   # exactly the mask, not merely "not the secret"
    assert SECRET not in out


def test_get_reveal_writes_raw_to_stdout_and_nothing_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["set", "myapp", "api_key", "--value", SECRET])
    capsys.readouterr()
    assert main(["get", "myapp", "api_key", "--reveal"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == SECRET
    assert SECRET not in captured.err


def test_get_missing_reports_on_stderr_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "myapp", "absent"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not set" in captured.err


def test_set_empty_value_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["set", "myapp", "k", "--value", "   "]) == 1
    assert "empty value" in capsys.readouterr().err


def test_list_prints_names(capsys: pytest.CaptureFixture[str]) -> None:
    main(["set", "myapp", "a", "--value", "1"])
    main(["set", "myapp", "b", "--value", "2"])
    capsys.readouterr()
    assert main(["list", "myapp"]) == 0
    assert capsys.readouterr().out.split() == ["a", "b"]


def test_unset_removes_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    main(["set", "myapp", "k", "--value", "v"])
    capsys.readouterr()
    assert main(["unset", "myapp", "k"]) == 0
    capsys.readouterr()
    assert main(["get", "myapp", "k"]) == 1


def test_invalid_app_name_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "bad/app", "k"]) == 2
    assert "error" in capsys.readouterr().err


def test_malformed_store_get_prints_no_secret_and_no_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["set", "myapp", "k", "--value", "v"])   # create the app dir
    path = FileBackend().path("myapp")
    path.write_bytes(b"{not json LEAKY_XYZ")
    capsys.readouterr()
    rc = main(["get", "myapp", "k"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "LEAKY_XYZ" not in captured.out + captured.err   # neither stream carries the file bytes
    assert "Traceback" not in captured.err


def test_missing_keyring_extra_prints_pip_hint(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        "credbox.backends.factory.importlib.util.find_spec",
        lambda name, *a, **k: None if name == "keyring" else real(name, *a, **k),
    )
    rc = main(["get", "myapp", "k", "--keyring"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "pip install credbox[keyring]" in captured.err
    assert "Traceback" not in captured.err


def test_path_and_dirs_print_resolved_locations(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["path", "myapp"]) == 0
    assert str(FileBackend().path("myapp")) == capsys.readouterr().out.strip()
    assert main(["dirs", "myapp"]) == 0
    dirs_out = capsys.readouterr().out
    for kind in ("config", "data", "state", "cache", "runtime"):
        assert kind in dirs_out


def test_doctor_warns_on_a_group_readable_credentials_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import os
    import stat

    if os.name != "posix":
        pytest.skip("POSIX mode bits only")
    main(["set", "myapp", "k", "--value", "v"])
    capsys.readouterr()
    path = FileBackend().path("myapp")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)   # 0640: group-readable
    assert main(["doctor", "myapp"]) == 1   # insecure found -> nonzero, so CI can gate on it
    captured = capsys.readouterr()
    assert "chmod 600" in captured.err
    assert "checked 1" in captured.out


def test_doctor_all_secure_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    main(["set", "myapp", "k", "--value", "v"])   # written 0600 in a 0700 dir
    capsys.readouterr()
    assert main(["doctor", "myapp"]) == 0
    assert "checked 1" in capsys.readouterr().out


def test_doctor_with_no_apps_reports_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0
    assert "checked 0" in capsys.readouterr().out


def test_doctor_discovers_and_checks_an_encrypted_only_store(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An app with only a credentials.enc (no credentials.json) must still be discovered and have
    # its permissions checked -- otherwise an encrypted-store-only user gets a false clean bill.
    # doctor only stat()s the file, never decrypts, so the test needs no passphrase or crypto extra.
    import os
    import stat

    if os.name != "posix":
        pytest.skip("POSIX mode bits only")
    from credbox import permissions
    from credbox.backends._store import ENCRYPTED_FILE
    from credbox.paths import config_dir

    monkeypatch.setattr(permissions, "_warned_permissive_paths", set())
    enc = config_dir("encapp") / ENCRYPTED_FILE
    enc.parent.mkdir(parents=True, exist_ok=True)
    enc.write_bytes(b"\x00opaque-ciphertext")   # doctor never decrypts it
    os.chmod(enc, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)   # 0640: group-readable
    capsys.readouterr()
    assert main(["doctor"]) == 1   # discovered via credentials.enc, flagged insecure
    captured = capsys.readouterr()
    assert "chmod 600" in captured.err
    assert "checked 1" in captured.out


def test_get_resolve_consults_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("API_KEY", "from-the-environment")
    assert main(["get", "myapp", "API_KEY", "--resolve", "--reveal"]) == 0
    assert capsys.readouterr().out.strip() == "from-the-environment"


def test_set_reads_the_value_from_a_pipe_when_stdin_is_not_a_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The argv-safe scripted path: a non-TTY stdin supplies the value directly (no --value, so the
    # secret never lands in the process argument list), without any getpass echo warning.
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-piped-value\n"))   # a plain StringIO isatty()==False
    assert main(["set", "myapp", "k"]) == 0
    capsys.readouterr()
    assert main(["get", "myapp", "k", "--reveal"]) == 0
    assert capsys.readouterr().out.strip() == "sk-piped-value"


def test_set_without_value_and_empty_noninteractive_stdin_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))   # non-TTY, nothing to read
    assert main(["set", "myapp", "k"]) == 2
    assert "no value on stdin" in capsys.readouterr().err


def test_keyboard_interrupt_at_prompt_exits_130_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _Tty())   # force the interactive prompt path

    def _interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("credbox.cli.getpass.getpass", _interrupt)
    assert main(["set", "myapp", "k"]) == 130
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_unexpected_exception_is_content_free_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An unexpected failure must be caught by the terminal guard: exit 1, a content-free stderr
    # line, and no traceback (a prompted `value` local must not reach a locals-dumping excepthook).
    monkeypatch.setattr("sys.stdin", _Tty())   # force the interactive prompt path

    def _boom(_prompt: str) -> str:
        raise RuntimeError("unexpected failure carrying sk_live_0123456789abcdef")

    monkeypatch.setattr("credbox.cli.getpass.getpass", _boom)
    assert main(["set", "myapp", "k"]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.err + captured.out
    assert "Traceback" not in captured.err
