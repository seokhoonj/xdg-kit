"""Tests for the Credentials facade: four-tier resolution, Secret returns, and content-free
require()."""

from __future__ import annotations

import pytest

from credbox.credentials import Credentials
from credbox.errors import CredentialsError
from credbox.secret import Secret


def test_secret_from_own_store_is_a_secret() -> None:
    creds = Credentials("myapp")
    creds.set("api_key", value="v")
    got = creds.secret("api_key")
    assert isinstance(got, Secret)
    assert got.reveal() == "v"


def test_override_wins_over_store() -> None:
    creds = Credentials("myapp")
    creds.set("api_key", value="stored")
    assert creds.secret("api_key", override="explicit").reveal() == "explicit"  # type: ignore[union-attr]


def test_env_beats_store(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = Credentials("myapp")
    creds.set("API_TOKEN", value="stored")
    monkeypatch.setenv("API_TOKEN", "from_env")
    assert creds.secret("API_TOKEN").reveal() == "from_env"  # type: ignore[union-attr]


def test_shared_store_consulted_before_own() -> None:
    Credentials("auth").set("shared_key", value="from_auth")
    creds = Credentials("myapp", shared=["auth"])
    assert creds.secret("shared_key").reveal() == "from_auth"  # type: ignore[union-attr]


def test_own_store_used_when_not_in_shared() -> None:
    Credentials("myapp").set("own", value="mine")
    creds = Credentials("myapp", shared=["auth"])
    assert creds.secret("own").reveal() == "mine"  # type: ignore[union-attr]


def test_unset_everywhere_returns_none() -> None:
    assert Credentials("myapp").secret("nope") is None


def test_require_raises_when_unset() -> None:
    with pytest.raises(CredentialsError) as excinfo:
        Credentials("myapp").require("nope")
    assert "nope" in str(excinfo.value)   # the name is safe to name; there is no value to leak


def test_set_strips_surrounding_whitespace() -> None:
    creds = Credentials("myapp")
    creds.set("k", value="  spaced  ")
    assert creds.secret("k").reveal() == "spaced"  # type: ignore[union-attr]


def test_set_refuses_a_blank_value() -> None:
    with pytest.raises(ValueError):
        Credentials("myapp").set("k", value="   ")


def test_set_accepts_a_secret() -> None:
    creds = Credentials("myapp")
    creds.set("k", value=Secret("v"))
    assert creds.secret("k").reveal() == "v"  # type: ignore[union-attr]


def test_repr_never_shows_a_value() -> None:
    creds = Credentials("myapp")
    creds.set("k", value="topsecret_value")
    assert "topsecret_value" not in repr(creds)


def test_names_lists_own_store_sorted() -> None:
    creds = Credentials("myapp")
    creds.set("b_key", value="1")
    creds.set("a_key", value="2")
    assert creds.names() == ["a_key", "b_key"]
