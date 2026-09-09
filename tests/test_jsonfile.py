"""Tests for the corruption-aware non-secret JSON state reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from credbox.jsonfile import read_json


def test_reads_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"cursor": 42}')
    assert read_json(path) == {"cursor": 42}


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_json(tmp_path / "absent.json") is None


def test_malformed_json_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert read_json(path) is None


def test_non_utf8_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bin.json"
    path.write_bytes(b"\xff\xfe\x00")
    assert read_json(path) is None


def test_a_real_os_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "state.json"
    path.write_text("{}")

    def _boom(*_args: object, **_kwargs: object) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    with pytest.raises(PermissionError):
        read_json(path)
