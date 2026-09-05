"""Packaging invariants: the version is single-sourced and the type marker ships."""

from __future__ import annotations

from importlib import metadata, resources

import xdgkit


def test_version_matches_distribution_metadata():
    # __version__ is hand-written in __init__ and the version lives in pyproject too;
    # this keeps the two from drifting.
    assert xdgkit.__version__ == metadata.version("xdgkit")


def test_py_typed_marker_is_present():
    # PEP 561: without this marker, a consumer's type checker ignores xdgkit entirely.
    assert resources.files("xdgkit").joinpath("py.typed").is_file()
