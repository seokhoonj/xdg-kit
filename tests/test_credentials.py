"""The four-tier resolution: override > env > shared store > app store."""

from __future__ import annotations

import pytest

from xdg_kit.backends import FileBackend
from xdg_kit.credentials import Credentials, get_secret, require_secret, secret_names, set_secret
from xdg_kit.errors import CredentialsError, InvalidAppNameError


def test_override_beats_everything(monkeypatch):
    monkeypatch.setenv("K", "from-env")
    creds = Credentials("nw")
    creds.set("K", value="from-app")
    assert creds.secret("K", override="explicit") == "explicit"


def test_env_beats_stores(monkeypatch):
    monkeypatch.setenv("K", "from-env")
    creds = Credentials("nw")
    creds.set("K", value="from-app")
    assert creds.secret("K") == "from-env"


def test_shared_store_beats_app_store():
    FileBackend().set("auth", "EXAMPLE_API_KEY", value="shared-key")
    FileBackend().set("nw", "EXAMPLE_API_KEY", value="app-key")
    creds = Credentials("nw", shared=["auth"])
    assert creds.secret("EXAMPLE_API_KEY") == "shared-key"


def test_falls_through_to_app_store_when_shared_absent():
    FileBackend().set("nw", "OPENDART_KEY", value="app-only")
    creds = Credentials("nw", shared=["auth"])
    assert creds.secret("OPENDART_KEY") == "app-only"


def test_secret_none_when_unset_everywhere():
    assert Credentials("nw").secret("NOPE") is None


def test_blank_override_falls_through(monkeypatch):
    monkeypatch.setenv("K", "from-env")
    assert Credentials("nw").secret("K", override="   ") == "from-env"


def test_require_raises_when_unset():
    with pytest.raises(CredentialsError):
        Credentials("nw").require("NOPE")


def test_require_returns_value(monkeypatch):
    monkeypatch.setenv("K", "v")
    assert Credentials("nw").require("K") == "v"


def test_set_writes_to_own_store_only():
    creds = Credentials("nw", shared=["auth"])
    creds.set("K", value="v")
    assert FileBackend().get("nw", "K") == "v"
    assert FileBackend().get("auth", "K") is None   # never the shared store


def test_module_level_helpers(monkeypatch):
    set_secret("nw", "K", value="v")
    assert get_secret("nw", "K") == "v"
    assert secret_names("nw") == ["K"]
    assert require_secret("nw", "K") == "v"


def test_invalid_app_or_shared_name_rejected():
    with pytest.raises(InvalidAppNameError):
        Credentials("../evil")
    with pytest.raises(InvalidAppNameError):
        Credentials("nw", shared=["../evil"])


def test_repr_is_secret_safe():
    creds = Credentials("nw", shared=["auth"])
    creds.set("K", value="super-secret-value")
    text = repr(creds)
    assert "nw" in text and "auth" in text and "FileBackend" in text
    assert "super-secret-value" not in text
