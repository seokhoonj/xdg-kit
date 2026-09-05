"""The xdgkit command: store, read (masked), list, remove, inspect, and check."""

from __future__ import annotations

import pytest

from xdgkit import __version__
from xdgkit.backends import FileBackend
from xdgkit.cli import main


def test_set_with_value_stores(capsys):
    assert main(["set", "nw", "K", "--value", "sk-abcdef"]) == 0
    assert FileBackend().get("nw", "K") == "sk-abcdef"
    assert "stored K for nw" in capsys.readouterr().out


def test_version_flag_prints_and_exits_zero(capsys):
    """`xdgkit --version` prints the version at the top level and exits 0 -- not shoved
    behind a required subcommand (argparse's version action raises SystemExit)."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"xdgkit {__version__}"


def test_set_empty_value_is_refused(capsys):
    assert main(["set", "nw", "K", "--value", ""]) == 1
    assert "empty value" in capsys.readouterr().err


def test_get_masks_by_default(capsys):
    main(["set", "nw", "K", "--value", "sk-abcdef"])
    capsys.readouterr()
    assert main(["get", "nw", "K"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "sk***ef"                 # exact mask, not the whole secret
    assert "sk-abcdef" not in out


def test_get_reveal_prints_full(capsys):
    main(["set", "nw", "K", "--value", "sk-abcdef"])
    capsys.readouterr()
    main(["get", "nw", "K", "--reveal"])
    assert capsys.readouterr().out.strip() == "sk-abcdef"


def test_get_reads_store_not_env(monkeypatch, capsys):
    main(["set", "nw", "K", "--value", "stored"])
    monkeypatch.setenv("K", "from-env")
    capsys.readouterr()
    main(["get", "nw", "K", "--reveal"])
    assert capsys.readouterr().out.strip() == "stored"   # the store it manages, not env


def test_get_resolve_walks_env(monkeypatch, capsys):
    main(["set", "nw", "K", "--value", "stored"])
    monkeypatch.setenv("K", "from-env")
    capsys.readouterr()
    main(["get", "nw", "K", "--reveal", "--resolve"])
    assert capsys.readouterr().out.strip() == "from-env"   # env wins in full resolution


def test_get_missing_returns_1(capsys):
    assert main(["get", "nw", "MISSING"]) == 1


def test_list_shows_names(capsys):
    main(["set", "nw", "A", "--value", "1"])
    main(["set", "nw", "B", "--value", "2"])
    capsys.readouterr()
    main(["list", "nw"])
    assert capsys.readouterr().out.split() == ["A", "B"]


def test_unset_removes(capsys):
    main(["set", "nw", "K", "--value", "v"])
    assert main(["unset", "nw", "K"]) == 0
    assert FileBackend().get("nw", "K") is None


def test_path_prints_credentials_file(capsys):
    main(["path", "nw"])
    assert capsys.readouterr().out.strip().endswith("nw/credentials.json")


def test_dirs_prints_five_kinds(capsys):
    main(["dirs", "nw"])
    out = capsys.readouterr().out
    for kind in ("config", "data", "state", "cache", "runtime"):
        assert kind in out


def test_doctor_reports_count(capsys):
    main(["set", "nw", "K", "--value", "v"])
    capsys.readouterr()
    assert main(["doctor", "nw"]) == 0
    assert "checked 1" in capsys.readouterr().out


def test_bad_app_name_is_usage_error(capsys):
    assert main(["path", "../evil"]) == 2
    assert "error" in capsys.readouterr().err
