"""Packaging invariants: the version is single-sourced, the type marker ships, and the console
scripts / extras are declared."""

from __future__ import annotations

from importlib import metadata, resources

import credbox


def test_version_matches_distribution_metadata() -> None:
    # __version__ is read from the installed distribution metadata (see __init__), so it can never
    # drift from what pip resolved; this pins that invariant.
    assert credbox.__version__ == metadata.version("credbox")


def test_py_typed_marker_is_present() -> None:
    # PEP 561: without this marker, a consumer's type checker ignores credbox entirely.
    assert resources.files("credbox").joinpath("py.typed").is_file()


def test_console_scripts_are_declared() -> None:
    scripts = {ep.name: ep.value for ep in metadata.entry_points(group="console_scripts")}
    assert scripts.get("credbox") == "credbox.cli:main"
    assert scripts.get("git-credential-credbox") == "credbox.gitcredential:main"


def test_optional_extras_are_declared() -> None:
    extras = metadata.metadata("credbox").get_all("Provides-Extra") or []
    for extra in ("keyring", "crypto", "all"):
        assert extra in extras
