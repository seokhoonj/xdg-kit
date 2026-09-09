"""The encrypted file backend ([crypt] extra): a single AES-GCM blob keyed by an Argon2id hash
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
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from credbox.atomic import write_bytes_atomic
from credbox.backends.file import _exclusive_store_lock, _normalize_secret_value
from credbox.errors import CredBoxError, CredentialsError, DecryptionError
from credbox.paths import config_dir
from credbox.permissions import PRIVATE_FILE_MODE, restrict_dir_to_owner
from credbox.secret import Secret
from credbox.storecodec import StoreFault, parse_store, serialize_store

__all__ = ["EncryptedFileBackend"]

ENCRYPTED_FILE = "credentials.enc"

_KEY_LEN = 32
_NONCE_LEN = 12
_SALT_LEN = 16
# Write-time Argon2id cost (deliberately expensive -- ~100ms-scale per store open, a feature).
_WRITE_TIME_COST = 3
_WRITE_MEMORY_COST_KIB = 64 * 1024   # 64 MiB
_WRITE_PARALLELISM = 4
# Read-time clamps: a tampered header cannot force a huge Argon2id allocation before the AAD/tag
# check can reject it. A legitimate header's params sit inside these bounds, so clamping is a
# no-op for it; only a tampered header is reshaped (and then fails the tag check anyway).
_MAX_TIME_COST = 16
_MAX_MEMORY_COST_KIB = 1 << 20   # 1 GiB in KiB
_MAX_PARALLELISM = 16


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
        cleaned = _normalize_secret_value(self._load(app).get(name))
        return Secret(cleaned) if cleaned is not None else None

    def set(self, app: str, name: str, *, value: str | Secret) -> None:
        """Store ``value`` under ``name``, re-encrypting the whole store with a fresh nonce under
        the same cross-process lock as the file backend.

        Raises:
            DecryptionError: the existing store could not be decrypted.
            CredentialsError: the store is unreadable, or the write failed.
        """
        raw = value.reveal() if isinstance(value, Secret) else value
        with _exclusive_store_lock(self.path(app)):
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
        with _exclusive_store_lock(self.path(app)):
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
        path = self.path(app)
        try:
            blob = path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as err:
            raise CredentialsError(f"could not read {path}: {err}") from err
        plaintext = _try_decrypt(blob, self._passphrase.reveal())
        del blob
        if plaintext is None:
            # Wrong passphrase or tampering. Raised where no crypto exception is in flight (it
            # died inside _try_decrypt), so DecryptionError has __cause__ AND __context__ None.
            raise DecryptionError(
                f"could not decrypt the store for {app}: wrong passphrase or tampering"
            )
        result = parse_store(plaintext)
        del plaintext
        if isinstance(result, StoreFault):
            raise CredentialsError(f"the decrypted store for {app} is malformed")
        return result

    def _save(self, app: str, store: dict[str, str]) -> None:
        path = self.path(app)
        restrict_dir_to_owner(path.parent)
        encoded = serialize_store(store)
        if isinstance(encoded, StoreFault):
            raise CredentialsError(f"{path} could not be serialized: a value is not encodable")
        blob = _encrypt(encoded, self._passphrase.reveal())
        try:
            write_bytes_atomic(path, blob, mode=PRIVATE_FILE_MODE)
        except CredBoxError as err:
            raise CredentialsError(str(err)) from err


# --- crypto primitives ---------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes, *, time_cost: int, memory_cost: int, lanes: int) -> bytes:
    kdf = Argon2id(
        salt=salt,
        length=_KEY_LEN,
        iterations=time_cost,
        lanes=lanes,
        memory_cost=memory_cost,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt ``plaintext`` into the single-blob layout with a fresh salt and nonce."""
    salt = os.urandom(_SALT_LEN)
    key = _derive_key(
        passphrase, salt,
        time_cost=_WRITE_TIME_COST, memory_cost=_WRITE_MEMORY_COST_KIB, lanes=_WRITE_PARALLELISM,
    )
    header = {
        "v": 1,
        "kdf": "argon2id",
        "t": _WRITE_TIME_COST,
        "m": _WRITE_MEMORY_COST_KIB,
        "p": _WRITE_PARALLELISM,
        "hlen": _KEY_LEN,
        "salt": base64.b64encode(salt).decode("ascii"),
    }
    header_json = json.dumps(header, sort_keys=True).encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, header_json)   # AAD = the whole header
    return len(header_json).to_bytes(4, "big") + header_json + nonce + ciphertext


def _try_decrypt(blob: bytes, passphrase: str) -> bytes | None:
    """Parse the blob, re-derive the key from the header's own (clamped) params, and AES-GCM
    decrypt with the header bound as AAD. Return the plaintext bytes, or ``None`` on ANY failure
    (a malformed blob, wrong passphrase, or tampering). Every crypto/decode exception is caught
    HERE and never escapes, so the caller's ``DecryptionError`` has ``__context__`` ``None``."""
    try:
        header_len = int.from_bytes(blob[:4], "big")
        header_json = blob[4:4 + header_len]
        rest = blob[4 + header_len:]
        nonce = rest[:_NONCE_LEN]
        ciphertext = rest[_NONCE_LEN:]
        if len(header_json) != header_len or len(nonce) != _NONCE_LEN:
            return None
        header = json.loads(header_json)
        if not isinstance(header, dict):
            return None
        if header.get("v") != 1 or header.get("kdf") != "argon2id":
            return None
        salt = base64.b64decode(header["salt"])
        time_cost = _clamp(int(header["t"]), 1, _MAX_TIME_COST)
        memory_cost = _clamp(int(header["m"]), 8 * _MAX_PARALLELISM, _MAX_MEMORY_COST_KIB)
        lanes = _clamp(int(header["p"]), 1, _MAX_PARALLELISM)
        key = _derive_key(passphrase, salt, time_cost=time_cost, memory_cost=memory_cost, lanes=lanes)
        return AESGCM(key).decrypt(nonce, ciphertext, header_json)
    except (InvalidTag, ValueError, KeyError, TypeError, RecursionError,
            json.JSONDecodeError, UnicodeDecodeError):
        # RecursionError: a tampered header whose JSON nests thousands of levels would otherwise
        # escape as a traceback whose frames retain `passphrase`/`blob` (storecodec catches it too).
        return None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))
