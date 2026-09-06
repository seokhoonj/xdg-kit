"""Packaging invariants: the version is single-sourced and the type marker ships."""

from __future__ import annotations

from importlib import metadata, resources

import xdg_kit


def test_version_matches_distribution_metadata():
    # __version__ is read from the installed distribution metadata (see __init__), so it can
    # never drift from what pip resolved; this pins that invariant.
    assert xdg_kit.__version__ == metadata.version("xdg-kit")


def test_py_typed_marker_is_present():
    # PEP 561: without this marker, a consumer's type checker ignores xdg-kit entirely.
    assert resources.files("xdg_kit").joinpath("py.typed").is_file()
