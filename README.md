**English** | [한국어](README.ko.md)

# xdg-kit

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

## Install

```sh
pip install xdg-kit            # file store, zero runtime dependencies
pip install "xdg-kit[keyring]" # add the optional OS keyring backend
```

Check it worked:

```sh
xdg-kit --version
```

Requires Python 3.11+.

## Directories

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

## Secrets

```python
from xdg_kit import Credentials, secret, require, set_secret, unset_secret, secret_names

# Resolution order: override > environment > shared stores > this app's store.
creds = Credentials("myapp", shared=["auth"])
key = creds.require("API_KEY")         # env $API_KEY, then auth's store, then myapp's; raises if unset
maybe = creds.secret("API_KEY")        # same, but returns None instead of raising
creds.set("API_KEY", value="sk-...")   # writes myapp's own store (value is keyword-only)
creds.unset("API_KEY")                 # removes it from myapp's store (no-op if absent)
creds.names()                          # ["API_KEY", ...] -- names only, never values

# One-shot module-level convenience (each constructs a Credentials internally):
secret("myapp", "API_KEY")                       # -> str | None
require("myapp", "API_KEY")                      # -> str, raises CredentialsError if unset
set_secret("myapp", "API_KEY", value="sk-...")   # value is keyword-only
unset_secret("myapp", "API_KEY")                 # remove from this app's store (no-op if absent)
secret_names("myapp")                            # -> list[str]
```

The **shared store** is how a key common to several apps stops being duplicated: store it
once under a shared app (say `"auth"`), and every consumer resolves it with
`shared=["auth"]`. A key specific to one app stays in that app's own store.

## The `xdg-kit` command

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

## Keyring

The file store is the default because it is reliable everywhere — headless servers, cron,
containers, and multiple machines. The OS keyring is opt-in:

```python
from xdg_kit.backends import FileBackend, KeyringBackend, default_backend
from xdg_kit import Credentials

backend = KeyringBackend(fallback=FileBackend())   # keyring on a desktop, file on a server
creds = Credentials("myapp", backend=backend)
# or: default_backend(use_keyring=True) -- the same thing
```

When no keyring backend is present, the operation falls back to the file store
automatically and a one-time warning is printed, so a user who opted into the keyring
learns their secrets are in the file instead. When the keyring works it is authoritative,
and a successful `set` / `unset` also clears any stale plaintext copy from the file, so
opting into the keyring never leaves a file copy behind. One direction cannot be closed: a
value written to the file while the keyring is *down* is not migrated back into the keyring
on recovery, so rotate a key while the keyring is reachable (or clear the stale keyring
entry) to avoid an older keyring value shadowing it.

## Redacting secrets from logs

```python
from xdg_kit.scrub import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # scrubs the whole __cause__/__context__ chain
```

`scrub_exception` never raises and rewrites each exception's `args` and a string `url`
attribute; for an exception with a custom `__str__`, also pass the rendered log line
through `scrub_secrets`.

## Single-instance locking

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

## Public API reference

| Import | What it is |
|--------|------------|
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` (`xdg_kit`) | XDG directory for an app (a `Path`). |
| `runtime_dir(app, *, create=True)` (`xdg_kit`) | Secured session runtime directory. |
| `Credentials(app, *, shared=(), backend=None)` (`xdg_kit`) | The four-tier secret resolver: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `secret` / `require` / `set_secret` / `unset_secret` / `secret_names` (`xdg_kit`) | Module-level one-shot convenience over `Credentials`. |
| `SecretBackend` / `FileBackend` / `KeyringBackend` / `default_backend` (`xdg_kit.backends`) | The storage seam and its two implementations. |
| `scrub_secrets` / `scrub_exception` (`xdg_kit.scrub`) | Redact secret values from text and exception chains. |
| `FileLock` / `single_instance` (`xdg_kit.locking`) | Single-instance advisory locking in `runtime_dir`. |
| `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` (`xdg_kit.permissions`) | Directory/file permission guarantees and checks. |
| `write_bytes_atomic` / `write_text_atomic` (`xdg_kit.atomic`) | Atomic 0600 writes. |
| `env_value` / `absolute_override` (`xdg_kit.environment`) | Read an env value (blank = absent) / an absolute-path override. |
| `app_dir_segment` (`xdg_kit.paths`) | Validate an app name as a safe path segment. |
| `XdgKitError` / `CredentialsError` / `InsecureStorageError` / `InvalidAppNameError` (`xdg_kit`) | The exception hierarchy. |

## For library authors

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

## License

MIT
