"""Single-instance locking: one holder at a time, released on exit."""

from __future__ import annotations

import os

import pytest

from xdgkit.errors import InvalidAppNameError
from xdgkit.locking import FileLock, single_instance

posix_only = pytest.mark.skipif(os.name != "posix", reason="advisory file locks")


def test_single_instance_acquires():
    with single_instance("nw", "poll") as acquired:
        assert acquired is True


@posix_only
def test_second_holder_is_refused_while_held():
    first = FileLock("nw", "poll")
    assert first.acquire() is True
    try:
        second = FileLock("nw", "poll")
        assert second.acquire() is False   # first still holds it
    finally:
        first.release()


@posix_only
def test_lock_is_reusable_after_release():
    lock = FileLock("nw", "poll")
    assert lock.acquire() is True
    lock.release()
    again = FileLock("nw", "poll")
    assert again.acquire() is True
    again.release()


def test_context_manager_releases():
    with FileLock("nw", "poll") as lock:
        assert lock.acquired is True
    assert lock.acquired is False


def test_acquire_is_idempotent_while_held():
    lock = FileLock("nw", "poll")
    assert lock.acquire() is True
    assert lock.acquire() is True   # still held, no error
    lock.release()


def test_lock_name_traversal_rejected():
    with pytest.raises(InvalidAppNameError):
        FileLock("nw", "../escape")   # a crafted name must not place the .lock outside runtime_dir


def test_lock_bad_app_rejected():
    with pytest.raises(InvalidAppNameError):
        FileLock("../evil", "poll")
