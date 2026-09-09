"""Tests for the credbox CLI, focused on the leak-surface discipline (§13): only get --reveal
writes a raw secret to stdout; everything else is masked/content-free, and no path prints a
traceback."""

from __future__ import annotations

import pytest

from credbox.backends.file import FileBackend
from credbox.cli import main

SECRET = "sk_live_0123456789abcdef"


def test_set_then_masked_get(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["set", "myapp", "api_key", "--value", SECRET]) == 0
    capsys.readouterr()
    assert main(["get", "myapp", "api_key"]) == 0
    out = capsys.readouterr().out.strip()
    assert out != SECRET
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
    assert "LEAKY_XYZ" not in captured.err
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
