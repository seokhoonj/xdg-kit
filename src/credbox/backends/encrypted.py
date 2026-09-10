"""The encrypted file backend ([crypto] extra): a single AES-GCM blob keyed by an Argon2id hash
of a passphrase.

TERMINAL -- there is no fallback: a decrypt failure (wrong passphrase or tampering) FAILS CLOSED
with a content-free ``DecryptionError``, never a plaintext downgrade. The store is ONE atomically
written file so a header and ciphertext cannot desync:

    header_len(4, big-endian) || header(JSON) || nonce(12) || ciphertext_and_tag

The header carries all KDF params and is bound as the AES-GCM associated data (AAD), so params or
version cannot be downgraded unauthenticated. The key is re-derived from the header's own params
on read (after clamping them, so a tampered header cannot force a huge Argon2id allocation before
the tag check can reject it). A fresh nonce is drawn per encryption and never reused with a key.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path

from cryptography.exceptions import InternalError, InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from credbox._storecodec import StoreFault, parse_store, serialize_store
from credbox.atomic import write_bytes_atomic
from credbox.backends._store import exclusive_store_lock, normalize_secret_value
from credbox.errors import CredBoxError, CredentialsError, DecryptionError
from credbox.paths import config_dir
from credbox.permissions import PRIVATE_FILE_MODE
from credbox.secret import Secret

__all__ = ["EncryptedFileBackend"]

ENCRYPTED_FILE = "credentials.enc"

_KEY_LEN = 32
_NONCE_LEN = 12
_SALT_LEN = 16
# Write-time Argon2id cost (deliberately expensive -- ~100ms-scale per store open, a feature).
_WRITE_TIME_COST = 3
_WRITE_MEMORY_COST_KIB = 64 * 1024   # 64 MiB
_WRITE_LANES = 4
# Read-time clamps: a tampered header cannot force a huge Argon2id allocation before the AAD/tag
# check can reject it. A legitimate header's params sit inside these bounds, so clamping is a
# no-op for it; only a tampered header is reshaped (and then fails the tag check anyway).
_MAX_TIME_COST = 16
_MAX_MEMORY_COST_KIB = 4 * _WRITE_MEMORY_COST_KIB   # 256 MiB -- bounds a tampered-header alloc close
_MAX_LANES = 16                                     #   to the legitimate write cost, still a no-op for it


class EncryptedFileBackend:
    """Secrets in a single AES-GCM-encrypted blob under ``config_dir(app)``, keyed by an Argon2id
    hash of ``passphrase``. Terminal -- no fallback; a decrypt failure fails closed."""

    def __init__(self, *, passphrase: Secret) -> None:
        self._passphrase = passphrase

    def __repr__(self) -> str:
        return "EncryptedFileBackend()"   # never render the passphrase

    def path(self, app: str) -> Path:
        """The encrypted store file for ``app``: ``credentials.enc`` in ``config_dir(app)``."""
        return config_dir(app) / ENCRYPTED_FILE

    def get(self, app: str, name: str) -> Secret | None:
        """Return the value stored under ``name`` as a ``Secret``, or ``None`` when absent.

        Raises:
            DecryptionError: the store exists but could not be decrypted (wrong passphrase or
                tampering) -- content-free, ``__cause__`` and ``__context__`` both ``None``.
            CredentialsError: the store is unreadable, or decrypts to a malformed map.
        """
        cleaned = normalize_secret_value(self._load(app).get(name))
        return Secret(cleaned) if cleaned is not None else None

    def set(self, app: str, name: str, *, value: str | Secret) -> None:
        """Store ``value`` under ``name``, re-encrypting the whole store with a fresh nonce under
        the same cross-process lock as the file backend.

        Raises:
            DecryptionError: the existing store could not be decrypted.
            CredentialsError: the store is unreadable, or the write failed.
        """
        raw = value.reveal() if isinstance(value, Secret) else value
        with exclusive_store_lock(self.path(app)):
            store = self._load(app)
            store[name] = raw
            self._save(app, store)

    def unset(self, app: str, name: str) -> None:
        """Remove ``name`` if present; an idempotent no-op when absent. Re-encrypts under the
        same lock as ``set``.

        Raises:
            DecryptionError: the existing store could not be decrypted.
            CredentialsError: the store is unreadable, or the write failed.
        """
        with exclusive_store_lock(self.path(app)):
            store = self._load(app)
            if name in store:
                del store[name]
                self._save(app, store)

    def names(self, app: str) -> list[str]:
        """The stored key names, sorted -- never the values.

        Raises:
            DecryptionError / CredentialsError: as for ``get``.
        """
        return sorted(self._load(app))

    def _load(self, app: str) -> dict[str, str]:
        _ensure_kdf_available()   # before any passphrase.reveal(), so an unsupported build is content-free
        path = self.path(app)
        try:
            blob = path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as err:
            raise CredentialsError(f"could not read {path}: {err}") from err
        outcome = _try_decrypt(blob, self._passphrase.reveal(), app)
        del blob
        if outcome is _NEWER_VERSION:
            # A well-formed argon2id header carrying an unrecognized newer version -- written by a
            # newer credbox. Report that distinctly (content-free) instead of misdiagnosing it as a
            # wrong passphrase or tampering, so the user is told to upgrade rather than doubting
            # their passphrase. (The header is pre-tag-check, so someone with write access could
            # choose this message, but both outcomes are content-free -- no secret either way.)
            raise CredentialsError(
                f"the store for {app} was written by a newer credbox; upgrade credbox to read it"
            )
        if not isinstance(outcome, bytes):
            # Wrong passphrase, tampering, or a relocated blob (its bound app did not match). Raised
            # where no crypto exception is in flight (it died inside _try_decrypt), so
            # DecryptionError has __cause__ AND __context__ None.
            raise DecryptionError(
                f"could not decrypt the store for {app}: wrong passphrase or tampering"
            )
        plaintext = outcome
        result = parse_store(plaintext)
        del plaintext
        if isinstance(result, StoreFault):
            raise CredentialsError(f"the decrypted store for {app} is malformed")
        return result

    def _save(self, app: str, store: dict[str, str]) -> None:
        _ensure_kdf_available()   # before any passphrase.reveal(), so an unsupported build is content-free
        path = self.path(app)
        encoded = serialize_store(store)
        if isinstance(encoded, StoreFault):
            raise CredentialsError(f"{path} could not be serialized: a value is not encodable")
        blob = _encrypt(encoded, self._passphrase.reveal(), app)
        try:
            write_bytes_atomic(path, blob, mode=PRIVATE_FILE_MODE)
        except CredBoxError as err:
            raise CredentialsError(str(err)) from err


# --- crypto primitives ---------------------------------------------------------

# Sentinel returned by _try_decrypt for a well-formed header whose version this build does not
# understand -- distinct from None (a decrypt failure) so the caller reports "upgrade credbox".
_NEWER_VERSION: object = object()

_kdf_available = False
_kdf_probe_lock = threading.Lock()


def _ensure_kdf_available() -> None:
    """Confirm this cryptography/OpenSSL build actually provides Argon2id, raising a content-free
    ``CredentialsError`` if not. Probed with a throwaway secret-free input and cached, and called
    BEFORE any passphrase is revealed -- so an unsupported build fails closed here instead of
    letting an ``UnsupportedAlgorithm``/``InternalError`` escape a later ``derive()`` whose frame
    holds the passphrase. Not folded into ``DecryptionError`` (that would misreport a missing
    build capability as a wrong passphrase or tampering)."""
    global _kdf_available
    if _kdf_available:
        return
    with _kdf_probe_lock:
        if _kdf_available:
            return
        try:
            Argon2id(
                salt=b"\x00" * _SALT_LEN, length=_KEY_LEN,
                iterations=1, lanes=1, memory_cost=8,
            ).derive(b"")   # b"": no secret in this frame, so a raise here leaks nothing
        except (UnsupportedAlgorithm, InternalError):
            raise CredentialsError(
                "this cryptography/OpenSSL build does not support Argon2id; "
                "upgrade cryptography (>=44) or its bundled OpenSSL"
            ) from None
        _kdf_available = True


def _derive_key(passphrase: str, salt: bytes, *, time_cost: int, memory_cost: int, lanes: int) -> bytes:
    kdf = Argon2id(
        salt=salt,
        length=_KEY_LEN,
        iterations=time_cost,
        lanes=lanes,
        memory_cost=memory_cost,
    )
    # surrogatepass: a passphrase holding a lone surrogate (e.g. sourced from an env var via
    # surrogateescape) encodes to deterministic bytes instead of raising UnicodeEncodeError, whose
    # .object/.args and this frame's locals (passphrase, plaintext) would otherwise leak the secret.
    try:
        return kdf.derive(passphrase.encode("utf-8", "surrogatepass"))
    except (UnsupportedAlgorithm, InternalError):
        # The availability probe validates Argon2id at tiny params; the REAL derive runs at 64 MiB
        # (write) or up to the clamped 256 MiB / 16 lanes (read), which an OpenSSL build can still
        # reject param-specifically (e.g. no thread support for lanes>1) with these -- not caught by
        # _try_decrypt's tuple, so without this they would escape with `passphrase` in frame. Fold
        # to a content-free CredentialsError, `from None`; NOT DecryptionError (this is a build
        # capability failure, not wrong-passphrase-or-tampering).
        raise CredentialsError(
            "Argon2id key derivation failed in this cryptography/OpenSSL build"
        ) from None


def _encrypt(plaintext: bytes, passphrase: str, app: str) -> bytes:
    """Encrypt ``plaintext`` into the single-blob layout with a fresh salt and nonce. ``app`` is
    written into the header (and thus bound as AAD) so a reader can confirm the blob belongs to
    the store it was found in -- see ``_try_decrypt``."""
    salt = os.urandom(_SALT_LEN)
    key = _derive_key(
        passphrase, salt,
        time_cost=_WRITE_TIME_COST, memory_cost=_WRITE_MEMORY_COST_KIB, lanes=_WRITE_LANES,
    )
    header = {
        "v": 1,
        "kdf": "argon2id",
        "t": _WRITE_TIME_COST,
        "m": _WRITE_MEMORY_COST_KIB,
        "p": _WRITE_LANES,
        "hlen": _KEY_LEN,
        "app": app,
        "salt": base64.b64encode(salt).decode("ascii"),
    }
    header_json = json.dumps(header, sort_keys=True).encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, header_json)   # AAD = the whole header
    return len(header_json).to_bytes(4, "big") + header_json + nonce + ciphertext


def _try_decrypt(blob: bytes, passphrase: str, app: str) -> bytes | None | object:
    """Parse the blob, re-derive the key from the header's own (clamped) params, and AES-GCM
    decrypt with the header bound as AAD. Return the plaintext bytes; ``None`` on any decrypt
    failure (a malformed blob, wrong passphrase, tampering, or a blob bound to a different app);
    or the ``_NEWER_VERSION`` sentinel for a well-formed header whose version is newer than this
    build understands. Every crypto/decode exception is caught HERE and never escapes, so the
    caller's ``DecryptionError`` has ``__context__`` ``None``."""
    try:
        header_len = int.from_bytes(blob[:4], "big")
        header_json = blob[4:4 + header_len]
        rest = blob[4 + header_len:]
        nonce = rest[:_NONCE_LEN]
        ciphertext = rest[_NONCE_LEN:]
        if len(header_json) != header_len or len(nonce) != _NONCE_LEN:
            return None
        header = json.loads(header_json)
        if not isinstance(header, dict) or header.get("kdf") != "argon2id":
            return None
        version = header.get("v")
        if version != 1:
            # A well-formed argon2id header with a recognizably-newer integer version was written
            # by a newer credbox; signal that distinctly. Anything else (v absent, non-int, <1) is
            # malformed and falls through to a normal decrypt failure.
            return _NEWER_VERSION if isinstance(version, int) and version > 1 else None
        salt = base64.b64decode(header["salt"])
        time_cost = _clamp(int(header["t"]), 1, _MAX_TIME_COST)
        memory_cost = _clamp(int(header["m"]), 8 * _MAX_LANES, _MAX_MEMORY_COST_KIB)
        lanes = _clamp(int(header["p"]), 1, _MAX_LANES)
        key = _derive_key(passphrase, salt, time_cost=time_cost, memory_cost=memory_cost, lanes=lanes)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, header_json)
        # App binding: a v1 blob carries its app in the (AAD-authenticated) header. A blob moved
        # from another same-passphrase store decrypts (its own header is the AAD) but its app will
        # not match -- reject it as tampering. A blob without the field (a hypothetical older one)
        # skips the check, so the binding is additive and back-compatible.
        stored_app = header.get("app")
        if stored_app is not None and stored_app != app:
            return None
        return plaintext
    except (InvalidTag, ValueError, KeyError, TypeError, RecursionError, OverflowError,
            json.JSONDecodeError, UnicodeDecodeError):
        # Every way a tampered/garbage header can fault maps to None here, so nothing escapes with
        # `passphrase`/`blob` retained in this frame's traceback. Two non-obvious members:
        # RecursionError -- a header whose JSON nests thousands of levels; OverflowError -- a header
        # param like {"t": 1e999} parses to float('inf'), and int(inf) raises OverflowError (not a
        # ValueError). Only MemoryError/KeyboardInterrupt propagate: an OOM is not a malformed
        # header, so folding it to "wrong passphrase or tampering" would misclassify it, exactly as
        # _storecodec keeps its own catches narrow.
        return None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))
