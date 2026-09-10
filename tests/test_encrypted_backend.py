"""Tests for the [crypto] encrypted backend: roundtrip, fail-closed decryption, AAD-bound header,
and nonce freshness. Requires the ``cryptography`` extra (installed in the dev env)."""

from __future__ import annotations

import inspect
import json

import pytest

from credbox.backends.encrypted import EncryptedFileBackend
from credbox.errors import DecryptionError
from credbox.secret import Secret

SECRET = "sk_live_TOPSECRET_0123456789"
PASSPHRASE = Secret("correct horse battery staple")
_HEADER_LEN_BYTES = 4
_NONCE_LEN = 12


def _backend(passphrase: Secret = PASSPHRASE) -> EncryptedFileBackend:
    return EncryptedFileBackend(passphrase=passphrase)


def test_set_then_get_roundtrips_a_secret() -> None:
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)
    got = backend.get("myapp", "api_key")
    assert isinstance(got, Secret)
    assert got.reveal() == SECRET


def test_value_persists_across_backend_instances() -> None:
    _backend().set("myapp", "api_key", value=SECRET)
    got = _backend().get("myapp", "api_key")   # a fresh instance, same passphrase
    assert got is not None and got.reveal() == SECRET


def test_unset_and_names() -> None:
    backend = _backend()
    backend.set("myapp", "a", value="va")
    backend.set("myapp", "b", value="vb")
    assert backend.names("myapp") == ["a", "b"]
    backend.unset("myapp", "a")
    assert backend.names("myapp") == ["b"]
    backend.unset("myapp", "a")   # idempotent


def test_wrong_passphrase_fails_closed_content_free() -> None:
    _backend(Secret("right-passphrase")).set("myapp", "api_key", value=SECRET)
    with pytest.raises(DecryptionError) as excinfo:
        _backend(Secret("wrong-passphrase")).get("myapp", "api_key")
    err = excinfo.value
    assert SECRET not in str(err)
    assert err.__cause__ is None       # the InvalidTag never rides along
    assert err.__context__ is None     # ... on either link


def test_tampered_ciphertext_fails_closed() -> None:
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)
    path = backend.path("myapp")
    blob = bytearray(path.read_bytes())
    blob[-1] ^= 0x01   # flip a ciphertext/tag bit
    path.write_bytes(bytes(blob))
    with pytest.raises(DecryptionError):
        _backend().get("myapp", "api_key")


def test_tampered_header_fails_via_aad_binding() -> None:
    # A *semantically inert* header change (a benign extra JSON member, header re-parsed fine and
    # KDF params untouched) must still fail -- only the AES-GCM tag over the AAD can catch it. A
    # test that flipped a random header byte could pass without any AAD binding.
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)
    path = backend.path("myapp")
    blob = path.read_bytes()
    header_len = int.from_bytes(blob[:_HEADER_LEN_BYTES], "big")
    header = json.loads(blob[_HEADER_LEN_BYTES:_HEADER_LEN_BYTES + header_len])
    rest = blob[_HEADER_LEN_BYTES + header_len:]        # nonce || ciphertext, left unchanged
    header["benign_extra"] = "inert"                    # parses fine, KDF params unchanged
    new_header = json.dumps(header, sort_keys=True).encode("utf-8")
    tampered = len(new_header).to_bytes(_HEADER_LEN_BYTES, "big") + new_header + rest
    path.write_bytes(tampered)
    with pytest.raises(DecryptionError):
        _backend().get("myapp", "api_key")


@pytest.mark.parametrize(
    "blob",
    [b"", b"\x00\x00\x00\x10short", b"not a credbox encrypted blob at all", b"\xff" * 64],
    ids=["empty", "truncated-header", "garbage-text", "garbage-bytes"],
)
def test_garbage_or_truncated_blob_fails_closed_content_free(blob: bytes) -> None:
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)
    backend.path("myapp").write_bytes(blob)
    with pytest.raises(DecryptionError) as excinfo:
        _backend().get("myapp", "api_key")
    err = excinfo.value
    assert SECRET not in str(err)
    assert err.__cause__ is None
    assert err.__context__ is None


def test_recursion_error_in_the_header_parse_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A tampered header whose JSON nests thousands of levels raises RecursionError in json.loads;
    # it must be folded into a content-free DecryptionError, not escape as a traceback whose frames
    # retain passphrase/blob. Mock-forced rather than building the crashing input.
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("header nests too deep")

    monkeypatch.setattr("credbox.backends.encrypted.json.loads", _raise)
    with pytest.raises(DecryptionError):
        _backend().get("myapp", "api_key")


def test_set_on_a_store_written_with_another_passphrase_fails_closed() -> None:
    # set() must read-merge the existing store first, so a wrong passphrase fails closed there
    # rather than silently overwriting the store under a new key (which would strand the old data).
    _backend(Secret("right-passphrase")).set("myapp", "api_key", value=SECRET)
    with pytest.raises(DecryptionError):
        _backend(Secret("wrong-passphrase")).set("myapp", "other", value="v")


def test_unset_on_a_store_written_with_another_passphrase_fails_closed() -> None:
    _backend(Secret("right-passphrase")).set("myapp", "api_key", value=SECRET)
    with pytest.raises(DecryptionError):
        _backend(Secret("wrong-passphrase")).unset("myapp", "api_key")


def test_lone_surrogate_passphrase_roundtrips() -> None:
    # A passphrase holding a lone surrogate (e.g. sourced from an env var via surrogateescape)
    # must encode deterministically via surrogatepass on both write and read, not crash with a
    # UnicodeEncodeError whose frame would carry the passphrase.
    passphrase = Secret("pw-\udc80-\udcff")
    _backend(passphrase).set("myapp", "api_key", value=SECRET)
    got = _backend(passphrase).get("myapp", "api_key")
    assert got is not None and got.reveal() == SECRET


def test_infinite_kdf_param_in_header_fails_closed_not_overflow() -> None:
    # A tampered header param like {"t": 1e999} parses to float('inf'); int(inf) raises
    # OverflowError during key re-derivation, BEFORE the AAD/tag check. It must fold into a
    # content-free DecryptionError, not escape as an OverflowError whose frame retains
    # passphrase/blob.
    backend = _backend()
    backend.set("myapp", "api_key", value=SECRET)
    path = backend.path("myapp")
    blob = path.read_bytes()
    header_len = int.from_bytes(blob[:_HEADER_LEN_BYTES], "big")
    header = json.loads(blob[_HEADER_LEN_BYTES:_HEADER_LEN_BYTES + header_len])
    rest = blob[_HEADER_LEN_BYTES + header_len:]
    header["t"] = 1e999   # -> float('inf'); int(inf) raises OverflowError
    new_header = json.dumps(header, sort_keys=True).encode("utf-8")
    path.write_bytes(len(new_header).to_bytes(_HEADER_LEN_BYTES, "big") + new_header + rest)
    with pytest.raises(DecryptionError) as excinfo:
        _backend().get("myapp", "api_key")
    err = excinfo.value
    assert SECRET not in str(err)
    assert err.__cause__ is None
    assert err.__context__ is None


def test_unsupported_argon2id_build_fails_closed_content_free(monkeypatch: pytest.MonkeyPatch) -> None:
    # On a cryptography/OpenSSL build without Argon2id, the availability probe must raise a
    # content-free CredentialsError BEFORE any passphrase is revealed -- not let UnsupportedAlgorithm
    # escape with the passphrase in frame, and not misclassify it as DecryptionError (tampering).
    from cryptography.exceptions import UnsupportedAlgorithm

    import credbox.backends.encrypted as enc
    from credbox.errors import CredentialsError, DecryptionError

    class _NoArgon2id:
        def __init__(self, *args: object, **kwargs: object) -> None: ...
        def derive(self, *args: object, **kwargs: object) -> bytes:
            raise UnsupportedAlgorithm("this OpenSSL has no argon2id")

    monkeypatch.setattr(enc, "Argon2id", _NoArgon2id)
    monkeypatch.setattr(enc, "_kdf_available", False)   # force the probe to re-run against the mock
    backend = _backend()
    with pytest.raises(CredentialsError) as excinfo:
        backend.get("myapp", "api_key")
    assert not isinstance(excinfo.value, DecryptionError)   # not misreported as tampering
    assert PASSPHRASE.reveal() not in str(excinfo.value)
    with pytest.raises(CredentialsError):
        backend.set("myapp", "api_key", value=SECRET)


def test_each_encryption_uses_a_fresh_nonce() -> None:
    backend = _backend()
    backend.set("myapp", "k", value="v1")
    nonce1 = _nonce_of(backend.path("myapp").read_bytes())
    backend.set("myapp", "k", value="v2")
    nonce2 = _nonce_of(backend.path("myapp").read_bytes())
    assert nonce1 != nonce2


def test_constructor_has_no_fallback_parameter() -> None:
    params = inspect.signature(EncryptedFileBackend.__init__).parameters
    assert "passphrase" in params
    assert "fallback" not in params   # encrypted is terminal; the chain is unrepresentable


def _nonce_of(blob: bytes) -> bytes:
    header_len = int.from_bytes(blob[:_HEADER_LEN_BYTES], "big")
    start = _HEADER_LEN_BYTES + header_len
    return blob[start:start + _NONCE_LEN]
