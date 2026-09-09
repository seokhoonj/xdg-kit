"""Tests for the backend factories' find-spec gate and the core/extras import separation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from credbox.backends.factory import (
    default_backend,
    encrypted_backend,
    file_backend,
    keyring_backend,
)
from credbox.backends.file import FileBackend
from credbox.errors import MissingExtraError
from credbox.secret import Secret

_SRC = str(Path(__file__).resolve().parent.parent / "src")


def test_file_backend_factory_returns_a_file_backend() -> None:
    assert isinstance(file_backend(), FileBackend)
    assert isinstance(default_backend(), FileBackend)


def test_keyring_factory_returns_a_backend_when_present() -> None:
    # keyring is installed in the dev env, so the gate passes and a backend is returned.
    backend = keyring_backend(fallback=file_backend())
    assert type(backend).__name__ == "KeyringBackend"


def _simulate_absent(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    """Make the factory's find-spec gate see ``missing`` as not installed."""
    import importlib.util

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args: object, **kwargs: object):
        if name == missing:
            return None
        return real_find_spec(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("credbox.backends.factory.importlib.util.find_spec", fake_find_spec)


def test_keyring_factory_reports_missing_extra_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _simulate_absent(monkeypatch, "keyring")
    with pytest.raises(MissingExtraError) as excinfo:
        keyring_backend()
    assert excinfo.value.extra == "keyring"
    assert excinfo.value.dist == "credbox[keyring]"


def test_crypt_factory_reports_missing_extra_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _simulate_absent(monkeypatch, "cryptography")
    with pytest.raises(MissingExtraError) as excinfo:
        encrypted_backend(passphrase=Secret("pw"))
    assert excinfo.value.extra == "crypto"
    assert excinfo.value.dist == "credbox[crypto]"


def test_missing_extra_error_is_also_an_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _simulate_absent(monkeypatch, "keyring")
    with pytest.raises(ImportError):
        keyring_backend()   # dual-catch: MissingExtraError subclasses ImportError


def test_encrypted_factory_returns_a_backend_when_cryptography_present() -> None:
    backend = encrypted_backend(passphrase=Secret("pw"))
    assert type(backend).__name__ == "EncryptedFileBackend"


def test_core_import_never_pulls_an_extra(tmp_path: Path) -> None:
    # Run in a fresh interpreter: importing credbox and doing a core FileBackend round-trip must
    # not import `keyring` or `cryptography` into sys.modules.
    code = (
        "import sys\n"
        "import credbox\n"
        "from credbox.backends.file import FileBackend\n"
        "b = FileBackend()\n"
        "b.set('sepapp', 'k', value='v')\n"
        "assert b.get('sepapp', 'k').reveal() == 'v'\n"
        "assert 'keyring' not in sys.modules, 'keyring was imported by the core'\n"
        "assert 'cryptography' not in sys.modules, 'cryptography was imported by the core'\n"
        "print('separation-ok')\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": _SRC,
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert "separation-ok" in result.stdout
