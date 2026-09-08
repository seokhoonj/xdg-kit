"""Storage backends: the file store round-trips and validates; the keyring backend
delegates to its fallback when keyring is unusable, is authoritative when it works, and
never leaves a stale plaintext copy behind."""

from __future__ import annotations

import json
import os
import sys
import traceback
import types
from typing import Any

import pytest

from xdg_kit.backends import FileBackend, KeyringBackend, default_backend
from xdg_kit.errors import CredentialsError, XdgKitError

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


# --- FileBackend ---------------------------------------------------------------

def test_file_set_get_round_trip():
    fb = FileBackend()
    fb.set("nw", "GEMINI_API_KEY", value="sk-abc")
    assert fb.get("nw", "GEMINI_API_KEY") == "sk-abc"


def test_file_get_absent_is_none():
    assert FileBackend().get("nw", "MISSING") is None


def test_file_blank_value_reads_as_absent():
    fb = FileBackend()
    fb.set("nw", "K", value="   ")
    assert fb.get("nw", "K") is None


def test_file_names_lists_keys_not_values():
    fb = FileBackend()
    fb.set("nw", "B_KEY", value="2")
    fb.set("nw", "A_KEY", value="1")
    assert fb.names("nw") == ["A_KEY", "B_KEY"]   # sorted


def test_file_unset_is_idempotent():
    fb = FileBackend()
    fb.set("nw", "K", value="v")
    fb.unset("nw", "K")
    fb.unset("nw", "K")   # already gone
    assert fb.get("nw", "K") is None


@posix_only
def test_file_written_0600():
    fb = FileBackend()
    fb.set("nw", "K", value="v")
    assert (fb.path("nw").stat().st_mode & 0o777) == 0o600


@posix_only
def test_file_config_dir_hardened_to_0700():
    fb = FileBackend()
    fb.set("nw", "K", value="v")
    assert (fb.path("nw").parent.stat().st_mode & 0o777) == 0o700


def test_file_malformed_json_raises():
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text("not json")
    with pytest.raises(CredentialsError):
        fb.get("nw", "K")


def test_file_non_object_json_raises():
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text("[1, 2, 3]")
    with pytest.raises(CredentialsError):
        fb.get("nw", "K")


def _contains_secret(value: object, secret: str, seen: set[int] | None = None) -> bool:
    # Whether ``secret`` is reachable inside ``value``, recursing through the shapes a file's
    # content actually takes in _load's locals -- a str (``text``) or a container (``parsed``)
    # -- plus bytes, guarding cycles by id. Other types fall back to ``repr`` (xdg_kit's frame
    # locals are only strings/containers, so no repr-redacting object hides a secret here). We
    # deliberately do NOT recurse arbitrary ``__dict__``: that reaches into framework objects
    # (a MonkeyPatch's stored closures) and false-positives on the test's own machinery.
    seen = set() if seen is None else seen
    if id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, str):
        return secret in value
    if isinstance(value, bytes):
        return secret.encode() in value
    if isinstance(value, dict):
        return any(_contains_secret(k, secret, seen) or _contains_secret(v, secret, seen)
                   for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret(item, secret, seen) for item in value)
    return secret in repr(value)


def _assert_no_secret_leak(exc_info, secret: str) -> None:
    # The secret must be unreachable from the raised exception by every vector a reporter
    # reads: the chained exceptions (__cause__ AND __context__ both None -- the content-bearing
    # original is fully off the chain; `from None` alone leaves __context__ reachable), the
    # str/repr, a formatted traceback, AND the f_locals of every *xdg_kit* frame in the
    # traceback (Sentry captures tb_frame.f_locals). Only library frames are swept: on the read
    # path the file content originates in _load, so a caller's frame never holds it -- but a
    # test's own frame legitimately binds the secret it planted, which is not a library leak.
    err = exc_info.value
    rendered = "".join(traceback.format_exception(type(err), err, exc_info.tb))
    assert err.__cause__ is None
    assert err.__context__ is None
    assert secret not in str(err)
    assert secret not in repr(err)
    assert secret not in rendered
    tb = exc_info.tb
    swept = 0
    while tb is not None:
        frame = tb.tb_frame
        if f"{os.sep}xdg_kit{os.sep}" in frame.f_code.co_filename:
            swept += 1
            for value in list(frame.f_locals.values()):
                assert not _contains_secret(value, secret), \
                    f"secret in {frame.f_code.co_name}() locals"
        tb = tb.tb_next
    assert swept > 0, "swept no xdg_kit frame -- a refactor could make this pass vacuously"


def test_malformed_json_error_does_not_leak_or_chain_file_content():
    # JSONDecodeError.doc retains the whole parsed text (the secrets); the raised error must
    # fully detach it and echo none of the file content
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text('{"API_KEY": "s3cr3t-value"', encoding="utf-8")  # missing brace
    with pytest.raises(CredentialsError) as exc_info:
        fb.get("nw", "API_KEY")
    _assert_no_secret_leak(exc_info, "s3cr3t-value")


def test_non_utf8_file_error_does_not_leak_or_chain_bytes():
    # UnicodeDecodeError.object carries the raw file bytes (the store content); the raised
    # error must fully detach it and echo none of the bytes
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_bytes(b'{"API_KEY": "s3cr3t\xff\xfe"}')   # invalid UTF-8
    with pytest.raises(CredentialsError) as exc_info:
        fb.get("nw", "API_KEY")
    _assert_no_secret_leak(exc_info, "s3cr3t")


def test_non_object_json_error_does_not_leak_via_frame_locals():
    # the "must contain a JSON object" path holds BOTH the raw text and the parsed value in
    # its frame before raising; a secret-bearing non-object payload must leak through neither
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text('["s3cr3t-in-a-list"]', encoding="utf-8")
    with pytest.raises(CredentialsError) as exc_info:
        fb.get("nw", "K")
    _assert_no_secret_leak(exc_info, "s3cr3t-in-a-list")


def test_deeply_nested_json_does_not_leak_via_frame_locals():
    # a deeply nested payload makes json.loads raise RecursionError, NOT JSONDecodeError -- a
    # non-parse exit that must still map to CredentialsError and clear the file content from
    # the frame (the raw text was live in `text` until the finally)
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text("[" * 100000 + '"s3cr3t-deep"', encoding="utf-8")
    with pytest.raises(CredentialsError) as exc_info:
        fb.get("nw", "API_KEY")
    _assert_no_secret_leak(exc_info, "s3cr3t-deep")


def test_json_decoder_message_is_never_carried_into_the_error(monkeypatch):
    # the raised error is built from the JSON position (lineno/colno), never str(err): so even
    # a (hypothetical) decoder message seeded with file content cannot reach the CredentialsError
    secret = "s3cr3t-in-decoder-msg"

    def raise_with_secret_message(text, *args, **kwargs):
        raise json.JSONDecodeError(secret, "doc", 0)

    monkeypatch.setattr("xdg_kit.backends.json.loads", raise_with_secret_message)
    fb = FileBackend()
    fb.path("nw").parent.mkdir(parents=True, exist_ok=True)
    fb.path("nw").write_text('{"API_KEY": "value"}', encoding="utf-8")
    with pytest.raises(CredentialsError) as exc_info:
        fb.get("nw", "API_KEY")
    _assert_no_secret_leak(exc_info, secret)


def test_leak_detector_is_not_vacuous():
    # negative control: the detector the sweep relies on actually FINDS a secret in the shapes
    # _load's locals take (a bare str, a nested container, bytes) -- so a real frame leak would
    # be caught -- and does not false-positive on a clean value
    secret = "deliberately-retained-secret"
    assert _contains_secret(secret, secret)
    assert _contains_secret({"token": secret}, secret)
    assert _contains_secret(["outer", [secret, "inner"]], secret)
    assert _contains_secret(secret.encode(), secret)
    assert not _contains_secret({"token": "something-else"}, secret)
    assert not _contains_secret(["nothing", "here"], secret)


def test_file_concurrent_set_no_lost_update():
    """Concurrent set() of distinct keys into the same store must not lose updates: the
    load->modify->save critical section is serialized, so every writer's key survives.
    Without a lock, all writers read the same empty snapshot and overwrite one another,
    leaving only one key."""
    import threading

    fb = FileBackend()
    n = 50
    start = threading.Barrier(n)   # release all writers at once to force overlap
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            start.wait()
            fb.set("nw", f"KEY_{i:03d}", value=f"v{i}")
        except BaseException as err:   # pragma: no cover - surfaced via the assert below
            errors.append(err)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert fb.names("nw") == [f"KEY_{i:03d}" for i in range(n)]
    for i in range(n):
        assert fb.get("nw", f"KEY_{i:03d}") == f"v{i}"   # each key kept its own value


def _process_set_worker(key: str, value: str) -> None:
    """Set one key in the shared store from a separate process -- so the sibling ``.lock``
    OS lock, not the per-process thread lock, is what serializes the read-modify-write."""
    from xdg_kit.backends import FileBackend

    FileBackend().set("nw", key, value=value)


@posix_only
def test_file_concurrent_process_set_no_lost_update():
    """Distinct keys set by separate PROCESSES must all survive. The thread-only test cannot
    reach this path: its threading.Lock serializes before the OS lock is ever contended, so
    only a cross-process run actually exercises the flock serialization the fix relies on."""
    import multiprocessing as mp

    n = 20
    ctx = mp.get_context("fork")   # fork so children inherit the test's XDG_CONFIG_HOME
    procs = [
        ctx.Process(target=_process_set_worker, args=(f"KEY_{i:03d}", f"v{i}"))
        for i in range(n)
    ]
    for process in procs:
        process.start()
    for process in procs:
        process.join(timeout=30)
    for process in procs:
        if process.is_alive():
            process.terminate()   # never orphan a hung child still holding the flock
            process.join()

    assert all(process.exitcode == 0 for process in procs)
    fb = FileBackend()
    assert fb.names("nw") == [f"KEY_{i:03d}" for i in range(n)]
    for i in range(n):
        assert fb.get("nw", f"KEY_{i:03d}") == f"v{i}"


def _process_unset_worker(key: str) -> None:
    """Unset one key in the shared store from a separate process -- exercises the sibling
    ``.lock`` OS lock on the unset read-modify-write, not the per-process thread lock."""
    from xdg_kit.backends import FileBackend

    FileBackend().unset("nw", key)


@posix_only
def test_file_concurrent_process_set_and_unset_keeps_expected_keys():
    """The cross-process set test cannot see a missing lock on unset: seed keys, then from
    separate PROCESSES concurrently add new keys and remove the seeded ones. The store must
    end with exactly the new keys -- proving unset takes the same OS lock set does."""
    import multiprocessing as mp

    n = 20
    fb = FileBackend()
    for i in range(n):
        fb.set("nw", f"OLD_{i:03d}", value=f"o{i}")   # seed keys the deleters will remove

    ctx = mp.get_context("fork")   # fork so children inherit the test's XDG_CONFIG_HOME
    setters = [ctx.Process(target=_process_set_worker, args=(f"NEW_{i:03d}", f"n{i}")) for i in range(n)]
    unsetters = [ctx.Process(target=_process_unset_worker, args=(f"OLD_{i:03d}",)) for i in range(n)]
    procs = setters + unsetters
    for process in procs:
        process.start()
    for process in procs:
        process.join(timeout=30)
    for process in procs:
        if process.is_alive():
            process.terminate()   # never orphan a hung child still holding the flock
            process.join()

    assert all(process.exitcode == 0 for process in procs)
    assert FileBackend().names("nw") == [f"NEW_{i:03d}" for i in range(n)]


def test_file_concurrent_set_and_unset_keeps_expected_keys():
    """The same lock governs unset: concurrently setting new keys while unsetting seeded ones
    must leave exactly the surviving set -- no set clobbering a delete or vice versa."""
    import threading

    fb = FileBackend()
    n = 30
    for i in range(n):
        fb.set("nw", f"OLD_{i:03d}", value=f"o{i}")   # seed keys the deleters will remove

    start = threading.Barrier(2 * n)
    errors: list[BaseException] = []

    def setter(i: int) -> None:
        try:
            start.wait()
            fb.set("nw", f"NEW_{i:03d}", value=f"n{i}")
        except BaseException as err:   # pragma: no cover - surfaced via the assert below
            errors.append(err)

    def unsetter(i: int) -> None:
        try:
            start.wait()
            fb.unset("nw", f"OLD_{i:03d}")
        except BaseException as err:   # pragma: no cover - surfaced via the assert below
            errors.append(err)

    threads = [threading.Thread(target=setter, args=(i,)) for i in range(n)]
    threads += [threading.Thread(target=unsetter, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert fb.names("nw") == [f"NEW_{i:03d}" for i in range(n)]   # all olds gone, all news kept


def test_file_set_write_failure_raises_credentials_error(monkeypatch):
    """The atomic layer raises XdgKitError; FileBackend.set must honour its documented
    CredentialsError contract by converting it."""
    def boom(*args, **kwargs):
        raise XdgKitError("disk full")

    monkeypatch.setattr("xdg_kit.backends.write_text_atomic", boom)
    with pytest.raises(CredentialsError):
        FileBackend().set("nw", "K", value="v")


# --- KeyringBackend ------------------------------------------------------------

@pytest.fixture
def working_keyring(monkeypatch):
    """A dict-backed stand-in for the keyring package, so the keyring path is exercised
    without an OS backend."""
    store: dict[tuple[str, str], str] = {}
    _install_fake_keyring(monkeypatch, store)
    return store


class _KeyringError(Exception):
    pass


class _NoKeyringError(_KeyringError):
    pass


class _PasswordDeleteError(_KeyringError):
    pass


def _install_fake_keyring(monkeypatch, store, *, delete_error=None):
    """Install a dict-backed stand-in for the keyring package (with the real error
    taxonomy) so the keyring path is exercised without an OS backend. ``delete_error``, if
    given, is raised by ``delete_password`` to simulate a locked/failed store."""
    mod: Any = types.ModuleType("keyring")
    errmod: Any = types.ModuleType("keyring.errors")

    def delete(service, name):
        if delete_error is not None:
            raise delete_error
        if (service, name) not in store:
            raise _PasswordDeleteError()
        del store[(service, name)]

    errmod.KeyringError = _KeyringError
    errmod.NoKeyringError = _NoKeyringError
    errmod.PasswordDeleteError = _PasswordDeleteError
    mod.errors = errmod
    mod.get_password = lambda service, name: store.get((service, name))
    mod.set_password = lambda s, n, v: store.__setitem__((s, n), v)
    mod.delete_password = delete
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errmod)


def test_keyring_is_authoritative_when_working(working_keyring):
    kb = KeyringBackend(fallback=FileBackend())
    kb.set("nw", "K", value="from-keyring")
    assert kb.get("nw", "K") == "from-keyring"
    assert working_keyring[("nw", "K")] == "from-keyring"


def test_keyring_value_wins_over_conflicting_fallback(working_keyring):
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    working_keyring[("nw", "K")] = "keyring-val"   # seed keyring directly
    fb.set("nw", "K", value="file-val")            # a conflicting file copy
    assert kb.get("nw", "K") == "keyring-val"       # keyring is authoritative


def test_keyring_miss_consults_fallback_so_outage_written_value_survives(working_keyring):
    # A value written to the file while the keyring was down must stay readable once the
    # keyring recovers empty: get() consults the fallback on a clean keyring miss rather than
    # hiding it. The keyring holds no conflicting entry here, so it stays authoritative.
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    fb.set("nw", "K", value="written-during-outage")   # keyring empty, file has the value
    assert kb.get("nw", "K") == "written-during-outage"


def test_keyring_set_clears_stale_file_copy(working_keyring):
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    fb.set("nw", "K", value="old-plaintext")
    kb.set("nw", "K", value="new-keyring")
    assert fb.get("nw", "K") is None            # plaintext copy removed
    assert working_keyring[("nw", "K")] == "new-keyring"


def test_keyring_set_success_but_file_cleanup_failure_reports_partial_success(working_keyring, monkeypatch):
    # keyring write succeeded; if clearing the stale file copy then fails, the error must say
    # the secret IS stored in the keyring (partial success), not read as a total failure
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)

    def boom(app, name):
        raise CredentialsError("file is malformed")

    monkeypatch.setattr(fb, "unset", boom)
    with pytest.raises(CredentialsError, match="stored .* in the keyring"):
        kb.set("nw", "K", value="v")
    assert working_keyring[("nw", "K")] == "v"   # the authoritative keyring write did happen


def test_keyring_unset_clears_file_copy_so_no_resurrection(working_keyring):
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    fb.set("nw", "K", value="plaintext")
    working_keyring[("nw", "K")] = "in-keyring"
    kb.unset("nw", "K")
    assert fb.get("nw", "K") is None
    assert ("nw", "K") not in working_keyring


def test_keyring_unset_idempotent_when_working(working_keyring):
    kb = KeyringBackend(fallback=FileBackend())
    kb.set("nw", "K", value="v")
    kb.unset("nw", "K")
    kb.unset("nw", "K")
    assert kb.get("nw", "K") is None


def test_keyring_unset_hard_failure_raises_not_false_success(monkeypatch):
    """A delete that fails for a real reason (a locked store) must NOT report success and
    silently fall back while the secret is still retrievable from the keyring."""
    store: dict[tuple[str, str], str] = {}
    _install_fake_keyring(monkeypatch, store, delete_error=_KeyringError("store is locked"))
    store[("nw", "K")] = "still-here"
    kb = KeyringBackend(fallback=FileBackend())
    with pytest.raises(CredentialsError):
        kb.unset("nw", "K")
    assert kb.get("nw", "K") == "still-here"   # not silently "removed"


def test_keyring_falls_back_when_unavailable(monkeypatch, capsys):
    """When keyring raises (no backend), the whole operation goes to the fallback file,
    with a one-time stderr warning about the downgrade."""
    mod: Any = types.ModuleType("keyring")

    def boom(*args, **kwargs):
        raise RuntimeError("no keyring backend")

    mod.get_password = boom
    mod.set_password = boom
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setattr("xdg_kit.backends._warned_keyring_fallback", False)
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    kb.set("nw", "K", value="to-file")
    assert fb.get("nw", "K") == "to-file"       # landed in the file
    assert kb.get("nw", "K") == "to-file"       # read back via fallback
    assert "keyring unavailable" in capsys.readouterr().err


def test_keyring_without_fallback_raises_when_unavailable(monkeypatch):
    mod: Any = types.ModuleType("keyring")

    def boom(*args, **kwargs):
        raise RuntimeError("no keyring backend")

    mod.get_password = boom
    monkeypatch.setitem(sys.modules, "keyring", mod)
    with pytest.raises(CredentialsError):
        KeyringBackend().get("nw", "K")


def test_keyring_names_reports_fallback_only(working_keyring):
    fb = FileBackend()
    fb.set("nw", "FILE_KEY", value="v")
    kb = KeyringBackend(fallback=fb)
    working_keyring[("nw", "KR_KEY")] = "v"    # only in keyring; not listable
    assert kb.names("nw") == ["FILE_KEY"]


def test_default_backend_is_file():
    assert isinstance(default_backend(), FileBackend)


def test_default_backend_keyring_is_keyring():
    assert isinstance(default_backend(use_keyring=True), KeyringBackend)


def test_keyring_import_absent_falls_back_for_all_ops_and_warns_once(monkeypatch, capsys):
    """When the keyring package cannot even be imported, get/set/unset all route to the file
    fallback (exercising unset's ImportError branch) and the downgrade warning prints once."""
    monkeypatch.setitem(sys.modules, "keyring", None)   # `import keyring` -> ImportError
    monkeypatch.setattr("xdg_kit.backends._warned_keyring_fallback", False)
    fb = FileBackend()
    kb = KeyringBackend(fallback=fb)
    kb.set("nw", "K", value="v")            # -> file
    assert kb.get("nw", "K") == "v"         # <- file
    kb.unset("nw", "K")                     # -> file (ImportError branch of unset)
    assert kb.get("nw", "K") is None
    assert fb.get("nw", "K") is None
    assert capsys.readouterr().err.count("keyring unavailable") == 1   # warn-once holds
