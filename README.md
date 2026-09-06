# xdg-kit

[![check](https://github.com/seokhoonj/xdg-kit/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/xdg-kit/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/xdg-kit)](https://pypi.org/project/xdg-kit/)
[![Python](https://img.shields.io/pypi/pyversions/xdg-kit)](https://pypi.org/project/xdg-kit/)
[![License](https://img.shields.io/pypi/l/xdg-kit)](https://github.com/seokhoonj/xdg-kit/blob/main/LICENSE)

**English** | [한국어](README.ko.md)

Secure XDG-style application storage for Python: paths, credentials, permissions, and
runtime files.

One small, dependency-free foundation for the two things every command-line app has to do
on disk — **find where its files live** and **resolve its secrets** — done once, the same
way, on every OS.

- **Directories** follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)
  (`config` / `data` / `state` / `cache` / `runtime`), using the `~/.config` layout on
  every platform — the same convention git follows — so paths are identical across
  machines and no platform library is needed.
- **Secrets** resolve in a fixed order — an explicit value, then the environment, then a
  shared store, then the app's own store — so a key common to several apps can live in
  **one** place instead of being copied into each.
- **Storage** is a plain `credentials.json` at mode 0600 in a 0700 directory by default
  (reliable headless and across machines); the OS keyring is an opt-in backend with
  automatic file fallback.

## 1. Install

```sh
pip install xdg-kit            # file store, zero runtime dependencies
pip install "xdg-kit[keyring]" # add the optional OS keyring backend
```

Check it worked:

```sh
xdg-kit --version
```

Requires Python 3.11+.

## 2. Directories

```python
from xdg_kit import config_dir, data_dir, state_dir, cache_dir, runtime_dir

config_dir("myapp")   # ~/.config/myapp        (or $XDG_CONFIG_HOME/...)
data_dir("myapp")     # ~/.local/share/myapp   (or $XDG_DATA_HOME/...)
state_dir("myapp")    # ~/.local/state/myapp   (or $XDG_STATE_HOME/...)
cache_dir("myapp")    # ~/.cache/myapp         (or $XDG_CACHE_HOME/...)
runtime_dir("myapp")  # $XDG_RUNTIME_DIR/myapp, else a secured 0700 temp dir
```

The app name is validated as a single path segment, so a crafted name can never escape its
base. `data_dir` and `state_dir` also honour a per-app `<APP>_DATA_DIR` / `<APP>_STATE_DIR`
environment override (an absolute path used as-is), so a large archive can be relocated to
another volume without editing anything. `runtime_dir` is the one XDG directory with no
specified default; when `XDG_RUNTIME_DIR` is unset (cron, containers, macOS, Windows) it
creates and secures a private uid-keyed directory under the system temp dir, as the spec
directs, and returns it (pass `create=False` to compute the path without creating it).

## 3. Secrets

```python
from xdg_kit import Credentials, get_secret, require_secret, set_secret, unset_secret, secret_names

# Resolution order: override > environment > shared stores > this app's store
creds = Credentials("myapp", shared=["auth"])
key = creds.require("API_KEY")         # env $API_KEY, then auth's store, then myapp's; raises if unset
maybe = creds.secret("API_KEY")        # same, but returns None instead of raising
creds.set("API_KEY", value="sk-...")   # writes myapp's own store (value is keyword-only)
creds.unset("API_KEY")                 # removes it from myapp's store (no-op if absent)
creds.names()                          # ["API_KEY", ...] -- names only, never values

# One-shot module-level convenience (each constructs a Credentials internally):
get_secret("myapp", "API_KEY")                   # -> str | None
require_secret("myapp", "API_KEY")               # -> str, raises CredentialsError if unset
set_secret("myapp", "API_KEY", value="sk-...")   # value is keyword-only
unset_secret("myapp", "API_KEY")                 # remove from this app's store (no-op if absent)
secret_names("myapp")                            # -> list[str]
```

The **shared store** is how a key common to several apps stops being duplicated: store it
once under a shared app (say `"auth"`), and every consumer resolves it with
`shared=["auth"]`. A key specific to one app stays in that app's own store.

## 4. The `xdg-kit` command

Manage any app's secrets from one place, in one format — no need to learn each package's
own way to store a key:

```sh
xdg-kit set myapp API_KEY               # prompts without echo; writes credentials.json (0600)
xdg-kit set myapp API_KEY --value sk-…  # or pass it directly (exposes it in argv; prefer the prompt)
xdg-kit list myapp                      # names only, never values
xdg-kit get myapp API_KEY               # masked (sk***ef); reads the stored value only
xdg-kit get myapp API_KEY --reveal      # print in full
xdg-kit get myapp API_KEY --resolve     # also consult the environment variable, not just the stored value
xdg-kit unset myapp API_KEY
xdg-kit path myapp                      # print the credentials.json path
xdg-kit dirs myapp                      # print all five directories
xdg-kit doctor                          # check every app's credentials file/dir permissions
xdg-kit doctor myapp other-app          # check only the named apps
```

`set`, `get`, `list`, and `unset` accept `--keyring` to operate on the OS keyring backend
(with automatic file fallback). Exit codes: `0` success, `1` a runtime error, `2` a usage
error (an invalid app name).

## 5. Keyring

Secrets — passwords, tokens, API keys — can live in one of two places:

- **File store** (the default) — a `credentials.json` in the app's folder. Works reliably
  everywhere, but stores the value in plaintext.
- **OS keyring** (opt-in) — the OS-provided encrypted vault (macOS Keychain, GNOME Keyring,
  etc.). More secure, but unavailable where no keyring exists or it is locked: headless
  servers, cron jobs, containers.

The file store is the default because it works everywhere. To use the keyring, turn it on
explicitly:

```python
from xdg_kit.backends import FileBackend, KeyringBackend, default_backend
from xdg_kit import Credentials

backend = KeyringBackend(fallback=FileBackend())   # keyring when available, else the file
creds = Credentials("myapp", backend=backend)
# or: default_backend(use_keyring=True) -- the same thing
```

With the keyring turned on, xdg-kit behaves like this:

- **Normally (keyring reachable)**: the value is stored in the keyring, and the keyring holds
  authority over it — if the file also has the same key, the keyring value wins. A successful
  `set` / `unset` also clears any stale plaintext copy from the file, so switching to the
  keyring never leaves a file copy behind.
- **When the keyring can't be used (not installed, locked, or absent on a server)**: the
  operation falls back to the file store automatically, and a one-time warning is printed, so
  a user who turned the keyring on learns the value went to the file instead.

**One caveat** — this reconciliation runs only one way, keyring → file; the
reverse (file → keyring) is not automatic: a value written to the file while the keyring
was unavailable is *not* migrated back into the keyring once it
recovers. So if the keyring still holds an older value for that key, a read hits the keyring
first and that older value shadows the newer one in the file. The reliable fix is to
**re-set the key while the keyring is reachable** — the new value then goes straight into the
keyring and the stale file copy is cleared. Do *not* try to fix it by deleting the keyring
entry with `xdg-kit unset --keyring`: while the keyring is reachable that also deletes the
newer file copy, losing the value.

## 6. Redacting secrets from logs

An API often echoes your key back inside an error message or a request URL, so logging an
unscrubbed exception can leak the very secret it failed with into a log file or your terminal.
These helpers replace known secret values with `***` before anything is logged or surfaced.

```python
from xdg_kit.scrub import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # scrubs the whole __cause__/__context__ chain
```

`scrub_exception` never raises and rewrites each exception's `args` and a string `url`
attribute; for an exception with a custom `__str__`, also pass the rendered log line
through `scrub_secrets`.

## 7. Single-instance locking

Stop a job from overlapping with another copy of itself — two cron runs, or a cron run and a
manual one. Such runs redo the same work, produce duplicate output (double sends,
duplicate rows), and race on shared state (two writers corrupting one file); a `FileLock`
lets the later run detect that one is already in progress and skip rather than pile on.

```python
from xdg_kit.locking import FileLock, single_instance

with single_instance("myapp", "poll") as acquired:
    if not acquired:
        return   # another run holds the lock; skip rather than pile on
    ...

lock = FileLock("myapp", "poll")   # or hold it explicitly
if lock.acquire():
    try:
        ...
    finally:
        lock.release()
```

The lock lives in `runtime_dir` and is released by the OS when the process exits, even on a
crash.

## 8. Public API reference

| Import | What it is |
|--------|------------|
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` (`xdg_kit`) | XDG directory for an app (a `Path`). |
| `runtime_dir(app, *, create=True)` (`xdg_kit`) | Secured session runtime directory. |
| `Credentials(app, *, shared=(), backend=None)` (`xdg_kit`) | The four-tier secret resolver: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `get_secret` / `require_secret` / `set_secret` / `unset_secret` / `secret_names` (`xdg_kit`) | Module-level one-shot convenience over `Credentials`. |
| `SecretBackend` / `FileBackend` / `KeyringBackend` / `default_backend` (`xdg_kit.backends`) | The storage seam and its two implementations. |
| `scrub_secrets` / `scrub_exception` (`xdg_kit.scrub`) | Redact secret values from text and exception chains. |
| `FileLock` / `single_instance` (`xdg_kit.locking`) | Single-instance advisory locking in `runtime_dir`. |
| `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` (`xdg_kit.permissions`) | Directory/file permission guarantees and checks. |
| `write_bytes_atomic` / `write_text_atomic` (`xdg_kit.atomic`) | Atomic 0600 writes. |
| `env_value` / `absolute_override` (`xdg_kit.environment`) | Read an env value (blank = absent) / an absolute-path override. |
| `app_dir_segment` (`xdg_kit.paths`) | Validate an app name as a safe path segment. |
| `XdgKitError` / `CredentialsError` / `InsecureStorageError` / `InvalidAppNameError` (`xdg_kit`) | The exception hierarchy. |

## 9. For library authors

`xdg-kit` provides only the base layer — directories, secret resolution, permissions,
atomic writes, locking, and scrubbing. Your package keeps its own domain configuration
(accounts, routes, topics) and reaches for xdg-kit underneath:

```python
from xdg_kit import config_dir, Credentials

def credentials_path():
    return config_dir("yourapp") / "credentials.json"

def api_key() -> str:
    return Credentials("yourapp").require("YOURAPP_API_KEY")
```

## 10. License

MIT
