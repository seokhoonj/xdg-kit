# credbox

[![check](https://github.com/seokhoonj/credbox/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/credbox/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/credbox)](https://pypi.org/project/credbox/)
[![Python](https://img.shields.io/pypi/pyversions/credbox)](https://pypi.org/project/credbox/)
[![License](https://img.shields.io/pypi/l/credbox)](https://github.com/seokhoonj/credbox/blob/main/LICENSE)

**English** | [한국어](README.ko.md)

A secure, XDG-located **secret store** for Python apps and CLIs — leak-safe by construction.

Every command-line app has to resolve its secrets and find where its files live. credbox does
both, once, the same way on every OS — and treats *not leaking the secret* as the whole job:

- **Leak-safe.** A resolved secret comes back as a `Secret` that masks itself in a log or a
  traceback; you call `.reveal()` to get the raw value only at the point of use. A malformed
  store, a failing OS keyring, or a wrong encryption passphrase raises a **content-free** error —
  the value never rides along on the exception, its `__cause__`/`__context__` chain, or a
  traceback. The CLI and the git helper write a raw secret to stdout only on an explicit reveal.
- **Honest by default.** Storage is a plain `credentials.json` at mode 0600 in a 0700 directory —
  reliable headless and across machines. The OS keyring and an encrypted-file backend are
  **opt-in** upgrades; a missing keyring is an explicit, warned fallback, never a silent downgrade.
- **Zero-dep core.** The default file store pulls in nothing. `keyring` and `cryptography` are
  installed only if you ask for them, and the core's import graph can never reach them.

credbox is a safe re-packaging of the `keyring` ecosystem's ideas — atomic writes, correct
permissions, cross-process locking, XDG paths, and leak-scrubbing wired together as one tested
unit — not a novel vault. Directories follow the
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/).

## 1. Install

```sh
pip install credbox              # file store, zero runtime dependencies
pip install "credbox[keyring]"   # add the optional OS keyring backend
pip install "credbox[crypt]"     # add the optional encrypted-file backend (Argon2id + AES-GCM)
pip install "credbox[all]"       # both
```

Check it worked:

```sh
credbox --version
```

Requires Python 3.11+.

## 2. Quickstart

Store a secret once (prompted, without echo):

```sh
credbox set myapp API_KEY
```

Then read it back in code. `require` resolves it (`$API_KEY`, else `myapp`'s store) and raises if
it is set nowhere; the result is a `Secret`, so it will not land in a log by accident:

```python
from credbox import Credentials

secret = Credentials("myapp").require("API_KEY")   # a Secret, not a str
secret.reveal()                                     # the raw value, at the point of use
print(secret)                                       # 'API_...cdef' — masked, safe to log
```

## 3. Secrets

Secrets (passwords, tokens, API keys) live in **one `credentials.json` per app** —
`config_dir(app)/credentials.json`, e.g. `~/.config/myapp/credentials.json` for `myapp`. That one
file is the app's **store**. Which store is read is decided by the app name, so one app can name
another app's store and read it alongside its own (see **shared store** below).

```python
from credbox import Credentials, Secret

# Resolution order: override > environment > shared stores > this app's store
creds = Credentials("myapp", shared=["auth"])
key   = creds.require("API_KEY")          # env $API_KEY, then auth's store, then myapp's; raises if unset
maybe = creds.secret("API_KEY")           # same, but returns None instead of raising
creds.set("API_KEY", value="sk-...")      # writes myapp's own store (str or Secret; keyword-only)
creds.unset("API_KEY")                    # removes it from myapp's store (no-op if absent)
creds.names()                             # ["API_KEY", ...] — names only, never values

key.reveal()          # -> "sk-..."  the raw string, for passing to an HTTP client
```

`secret` and `require` return a `Secret`; call `.reveal()` for the raw string. A `Secret` renders
masked in `str`/`repr`, compares in constant time, and is unhashable, so it cannot slip into a log
line or become a dict key by accident. `set` accepts a `str` or a `Secret`, refuses a blank value,
and strips surrounding whitespace so a stored key matches what resolution returns.

The **shared store** is how a key common to several apps stops being duplicated: store it once
under a shared app (say `"auth"`), and every consumer resolves it with `shared=["auth"]`. A key
specific to one app stays in that app's own store.

## 4. The `credbox` command

Manage any app's secrets from one place, in one format:

```sh
credbox set myapp API_KEY               # prompts without echo; writes credentials.json (0600)
credbox set myapp API_KEY --value sk-…  # or pass it directly (exposes it in argv; prefer the prompt)
credbox list myapp                      # names only, never values
credbox get myapp API_KEY               # masked (API_…cdef); reads the stored value only
credbox get myapp API_KEY --reveal      # print in full (the only raw-secret-to-stdout path)
credbox get myapp API_KEY --resolve     # also consult the environment variable, not just the store
credbox unset myapp API_KEY
credbox path myapp                      # print the credentials.json path
credbox dirs myapp                      # print all five directories
credbox doctor                          # check every app's credentials file/dir permissions
```

`set`, `get`, `list`, and `unset` accept `--keyring` to operate on the OS keyring backend (with
automatic file fallback). The CLI never prints a traceback: a runtime error becomes a one-line,
content-free message on stderr. Exit codes: `0` success, `1` a command failure, `2` a usage error.

## 5. Backends

Where a secret is physically stored is a `SecretBackend`. `Credentials` uses a `FileBackend` by
default; select another by passing `backend=`:

```python
from credbox import Credentials, Secret
from credbox import default_backend, file_backend, keyring_backend, encrypted_backend

Credentials("myapp")                                                    # file store (default)
Credentials("myapp", backend=default_backend(use_keyring=True))         # keyring over file
Credentials("myapp", backend=keyring_backend(fallback=file_backend()))  # the same, explicit
Credentials("myapp", backend=encrypted_backend(passphrase=Secret("…"))) # encrypted file [crypt]
```

- **File store** (default, zero-dep) — a `credentials.json` in the app's folder. Works reliably
  everywhere; stores the value in plaintext at mode 0600.
- **OS keyring** (`[keyring]`) — the OS-provided vault (macOS Keychain, GNOME Keyring, …). When
  reachable it is authoritative, and a successful `set`/`unset` also clears any stale plaintext
  copy from the fallback file. When *absent* (no backend on a server, cron, a container), every
  operation falls back to the file store with a one-time, content-free warning — so a user who
  turned the keyring on learns the value went to the file, never a silent downgrade. A *present but
  failing* keyring still lets `get`/`set` fall back, but `unset` fails closed rather than report a
  delete that may not have happened. (One caveat: reconciliation runs only keyring → file; a value
  written to the file while the keyring was down is not migrated back, so re-set the key while the
  keyring is reachable.)
- **Encrypted file** (`[crypt]`) — a single AES-GCM blob keyed by an Argon2id hash of a passphrase.
  It is **terminal**: a wrong passphrase or a tampered file fails closed with a content-free
  `DecryptionError`, never a plaintext downgrade. The whole header is authenticated (AES-GCM AAD),
  a fresh nonce is drawn per write, and the deliberately expensive KDF adds ~100 ms-scale latency
  per store open — a feature, not a bug.

The factories gate the optional import: `keyring_backend()` / `encrypted_backend()` raise a
`MissingExtraError` (with a `pip install credbox[…]` hint) when the extra is not installed.

## 6. Git credential helper

credbox can serve credentials to git. Point git at the installed helper:

```sh
git config --global credential.helper credbox
```

git then calls `git-credential-credbox` for `get`/`store`/`erase`, mapping the git `host` to a
credbox app and the git `username` to the secret name. On `get` the helper writes only the
credential reply to stdout; on any error it writes nothing (git prompts) and a content-free note to
stderr — never the secret, never a traceback.

## 7. Directories

```python
from credbox import config_dir, data_dir, state_dir, cache_dir, runtime_dir

config_dir("myapp")   # ~/.config/myapp        (or $XDG_CONFIG_HOME/...)
data_dir("myapp")     # ~/.local/share/myapp   (or $XDG_DATA_HOME/...)
state_dir("myapp")    # ~/.local/state/myapp   (or $XDG_STATE_HOME/...)
cache_dir("myapp")    # ~/.cache/myapp         (or $XDG_CACHE_HOME/...)
runtime_dir("myapp")  # $XDG_RUNTIME_DIR/myapp, else a secured 0700 temp dir
```

The app name is validated as a single path segment, so a crafted name can never escape its base.
`data_dir` and `state_dir` honour a per-app `<PREFIX>_DATA_DIR` / `<PREFIX>_STATE_DIR` override (an
absolute path used as-is), where `<PREFIX>` is `env_var_prefix(app)`. By default paths use the XDG
`~/.config` layout on every OS; pass `layout="native"` for OS-native locations (macOS
`~/Library/Application Support`, Windows `%LOCALAPPDATA%`), or set `CREDBOX_LAYOUT`.

**Windows note:** the 0600/0700 mode bits are POSIX-only. On Windows there is no such mode; credbox
relies on the per-user `%LOCALAPPDATA%` ACL, and does not claim a mode guarantee it cannot deliver
there.

## 8. Redacting secrets from logs

An API often echoes your key back inside an error message or a request URL, so logging an
unscrubbed exception can leak the very secret it failed with. These helpers replace known secret
values — and their URL-encoded forms — with `***` before anything is logged:

```python
from credbox import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # scrubs the whole __cause__/__context__ chain
```

`scrub_exception` never raises and rewrites each exception's `args`, its transport URLs (`url`,
`request.url`, `response.url`), and its PEP 678 `__notes__`. For an exception with a custom
`__str__`, also pass the rendered log line through `scrub_secrets`.

## 9. Single-instance locking

Stop a job from overlapping with another copy of itself — two cron runs, or a cron run and a manual
one — which redo work, produce duplicates, and race on shared state:

```python
from credbox import single_instance, FileLock

with single_instance("myapp", "poll") as acquired:
    if not acquired:
        return   # another run holds the lock; skip rather than pile on
    ...
```

The lock lives in `runtime_dir` and is released by the OS when the process exits, even on a crash.

## 10. Public API reference

### Everyday API (`credbox`)

| Import | What it is |
|--------|------------|
| `Credentials(app, *, shared=(), backend=None)` | The four-tier secret resolver: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `Secret` / `mask_secret` | The leak-safe value type (`.reveal()` for the raw string) and its canonical mask. |
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` / `runtime_dir` | XDG directories for an app. |
| `default_backend` / `file_backend` / `keyring_backend` / `encrypted_backend` | Backend chooser and factories. |
| `SecretBackend` / `FileBackend` | The backend protocol and the zero-dep file backend. |
| `scrub_secrets` / `scrub_exception` | Redact secret values from text and exception chains. |
| `single_instance` / `FileLock` | Single-instance advisory locking in `runtime_dir`. |
| `CredBoxError` / `CredentialsError` / `NoKeyringError` / `InsecureStorageError` / `InvalidAppNameError` / `DecryptionError` / `MissingExtraError` | The exception hierarchy. |
| `__version__` | The installed package version string. |

### Building blocks (for library authors — rarely called directly)

| Import | What it is |
|--------|------------|
| `ensure_dir` / `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` | Directory/file permission guarantees and checks. |
| `write_bytes_atomic` / `write_text_atomic` | Atomic 0600 writes. |
| `read_json` / `relocate_once` | Corruption-aware non-secret state read; idempotent, fail-closed relocation. |
| `env_var_prefix` / `colliding_env_var_prefixes` / `read_absolute_path_override` | App-name env folding and an absolute-path override. |
| `app_dir_segment` / `Layout` / `default_layout` / `set_default_layout` | Validate an app name; select the path layout. |

## 11. License

MIT
