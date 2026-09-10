"""The ``git-credential-credbox`` adapter: speak git's credential protocol over stdin/stdout,
backed by a credbox store.

git invokes ``git-credential-credbox <get|store|erase>`` and writes ``key=value`` lines to stdin,
terminated by a blank line. The mapping is: the git ``host`` is the credbox ``app``, the git
``username`` is the credbox secret ``name``, and the password is the secret value.

Leak-surface discipline: on ``get`` the only thing written to stdout is the credential
reply (``username=...\npassword=...``); on any error nothing is written to stdout (git treats an
empty reply as "no credential") and a content-free note goes to stderr -- never the secret, never
a traceback.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from credbox.backends import default_backend
from credbox.credentials import Credentials
from credbox.errors import CredBoxError, InvalidAppNameError
from credbox.paths import app_dir_segment


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``git-credential-credbox`` console script. Always returns 0 -- git
    reads the credential (if any) from stdout; an error is a content-free stderr note and an empty
    stdout, which git reads as "no credential"."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    operation = arguments[0] if arguments else ""
    fields = _read_fields(sys.stdin)
    try:
        if operation == "get":
            _do_get(fields)
        elif operation == "store":
            _do_store(fields)
        elif operation == "erase":
            _do_erase(fields)
        # any other operation: git ignores unknown helpers' output -- do nothing.
    except InvalidAppNameError:
        return 0   # the host does not map to a valid store name -> no credential, quietly
    except CredBoxError:
        # content-free: nothing on stdout (git prompts), a generic note on stderr, no traceback.
        print("credbox: git-credential error", file=sys.stderr)
    return 0


def _do_get(fields: dict[str, str]) -> None:
    app = _app_of(fields)
    if app is None:
        return
    # Read the STORE ONLY (host-scoped) -- NOT Credentials.secret(), whose environment tier is
    # global and host-unscoped: git supplies the username, so a crafted URL
    # `https://SOME_ENV_VAR@evil.com/` would otherwise resolve `SOME_ENV_VAR` from os.environ and
    # hand that value to git as the password *for evil.com* -- a remote exfiltration of any env var.
    # A credential this helper serves must come from a store keyed to the requesting host.
    backend = default_backend()
    username = fields.get("username")
    if username:
        value = backend.get(app, username)
        if value is not None:
            _write_reply(sys.stdout, username=username, password=value.reveal())
        return
    # First contact without a username: use the sole stored name if exactly one exists. Under a
    # keyring backend, names() lists only the fallback file, so a keyring-only store may yield
    # nothing here (a defined empty reply -> git prompts), which is documented, not a break.
    names = backend.names(app)
    if len(names) == 1:
        value = backend.get(app, names[0])
        if value is not None:
            _write_reply(sys.stdout, username=names[0], password=value.reveal())


def _do_store(fields: dict[str, str]) -> None:
    app = _app_of(fields)
    username = fields.get("username")
    password = fields.get("password", "")
    if app is None or not username or not password.strip():
        return
    Credentials(app).set(username, value=password)


def _do_erase(fields: dict[str, str]) -> None:
    app = _app_of(fields)
    username = fields.get("username")
    if app is None or not username:
        return
    Credentials(app).unset(username)


def _app_of(fields: dict[str, str]) -> str | None:
    """The credbox app for this request: the git ``host``, validated as a store segment. Returns
    ``None`` when there is no host or it is not a usable segment (so ``get`` yields no credential
    rather than erroring)."""
    host = fields.get("host")
    if not host:
        return None
    try:
        return app_dir_segment(host)
    except InvalidAppNameError:
        return None


def _read_fields(stream: TextIO) -> dict[str, str]:
    """Parse the git credential ``key=value`` lines from ``stream`` until a blank line or EOF."""
    fields: dict[str, str] = {}
    for raw_line in stream:
        line = raw_line.rstrip("\n")
        if line == "":
            break
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value
    return fields


def _write_reply(stream: TextIO, *, username: str, password: str) -> None:
    """Write the git credential reply (the one deliberate raw-secret-to-stdout path) and nothing
    else."""
    stream.write(f"username={username}\n")
    stream.write(f"password={password}\n")
    stream.write("\n")
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
