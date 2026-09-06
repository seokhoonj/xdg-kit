"""The ``xdg-kit`` command: manage any app's stored secrets and inspect its directories,
from one place with one format.

Instead of remembering each package's own way to store a key, ``xdg-kit set <app> <name>``
writes the same ``credentials.json`` (mode 0600) that every consumer reads. The value is
prompted for without echo when omitted, so it never lands in shell history. ``get`` masks
by default, ``list`` shows names only, and ``doctor`` reports files that are readable
beyond their owner. Everything here operates on xdg-kit's own stores and directories -- it
is not a general-purpose CLI.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from xdg_kit import __version__
from xdg_kit.backends import FileBackend, default_backend
from xdg_kit.credentials import Credentials
from xdg_kit.errors import InvalidAppNameError, XdgKitError
from xdg_kit.paths import app_dir_segment, cache_dir, config_dir, data_dir, state_dir
from xdg_kit.permissions import warn_if_group_or_world_readable
from xdg_kit.runtime import runtime_dir


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``xdg-kit`` console script. Returns a process exit code:
    0 on success, 1 on an ``XdgKitError`` (reported as a one-line message, not a
    traceback), 2 on a usage error (from argparse). ``--version`` (and ``-h``) do not
    return -- argparse prints and raises ``SystemExit(0)`` from ``parse_args``."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        exit_code: int = args.run(args)
        return exit_code
    except InvalidAppNameError as err:
        # an invalid app name is a usage mistake, not a runtime failure
        print(f"xdg-kit: error: {err}", file=sys.stderr)
        return 2
    except XdgKitError as err:
        print(f"xdg-kit: error: {err}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xdg-kit", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"xdg-kit {__version__}",
        help="print the installed version and exit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="store a secret (prompted without echo if omitted)")
    p_set.add_argument("app")
    p_set.add_argument("name")
    p_set.add_argument(
        "--value",
        help="the secret value; omit to be prompted without echo. Passing it here exposes "
        "the secret in the process argument list (/proc, shell history) -- prefer the prompt",
    )
    _add_keyring_flag(p_set)
    p_set.set_defaults(run=_cmd_set)

    p_get = sub.add_parser("get", help="print a stored secret (masked unless --reveal)")
    p_get.add_argument("app")
    p_get.add_argument("name")
    p_get.add_argument("--reveal", action="store_true", help="print the value in full")
    p_get.add_argument(
        "--resolve",
        action="store_true",
        help="also consult the environment variable, not just the stored value",
    )
    _add_keyring_flag(p_get)
    p_get.set_defaults(run=_cmd_get)

    p_list = sub.add_parser("list", help="list stored secret names (never values)")
    p_list.add_argument("app")
    _add_keyring_flag(p_list)
    p_list.set_defaults(run=_cmd_list)

    p_unset = sub.add_parser("unset", help="remove a stored secret")
    p_unset.add_argument("app")
    p_unset.add_argument("name")
    _add_keyring_flag(p_unset)
    p_unset.set_defaults(run=_cmd_unset)

    p_path = sub.add_parser("path", help="print the credentials file path for an app")
    p_path.add_argument("app")
    p_path.set_defaults(run=_cmd_path)

    p_dirs = sub.add_parser("dirs", help="print the XDG directories for an app")
    p_dirs.add_argument("app")
    p_dirs.set_defaults(run=_cmd_dirs)

    p_doctor = sub.add_parser("doctor", help="check credentials file permissions")
    p_doctor.add_argument("app", nargs="*", help="apps to check; default: all under the config dir")
    p_doctor.set_defaults(run=_cmd_doctor)

    return parser


def _add_keyring_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--keyring",
        action="store_true",
        help="use the OS keyring backend (falls back to the file store when unavailable)",
    )


def _credentials(args: argparse.Namespace) -> Credentials:
    return Credentials(args.app, backend=default_backend(use_keyring=args.keyring))


def _cmd_set(args: argparse.Namespace) -> int:
    value = args.value if args.value is not None else getpass.getpass(f"{args.name}: ")
    if not value.strip():
        # A whitespace-only value reads back as absent (every read runs through _clean),
        # so reject it here rather than store it and print a false "stored".
        print("xdg-kit: error: empty value; nothing stored", file=sys.stderr)
        return 1
    _credentials(args).set(args.name, value=value)
    print(f"stored {args.name} for {args.app}")
    return 0


def _cmd_get(args: argparse.Namespace) -> int:
    if args.resolve:
        value = _credentials(args).secret(args.name)   # override(none) > env > this store
    else:
        value = default_backend(use_keyring=args.keyring).get(args.app, args.name)  # this store only
    if value is None:
        print(f"xdg-kit: {args.name} is not set for {args.app}", file=sys.stderr)
        return 1
    print(value if args.reveal else _mask(value))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    for name in _credentials(args).names():
        print(name)
    return 0


def _cmd_unset(args: argparse.Namespace) -> int:
    _credentials(args).unset(args.name)
    print(f"removed {args.name} from {args.app}")
    return 0


def _cmd_path(args: argparse.Namespace) -> int:
    print(FileBackend().path(args.app))
    return 0


def _cmd_dirs(args: argparse.Namespace) -> int:
    print(f"config  {config_dir(args.app)}")
    print(f"data    {data_dir(args.app)}")
    print(f"state   {state_dir(args.app)}")
    print(f"cache   {cache_dir(args.app)}")
    print(f"runtime {runtime_dir(args.app, create=False)}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    apps = args.app or _discover_apps()
    checked = 0
    for app in apps:
        path = FileBackend().path(app)
        if path.exists():
            checked += 1
            warn_if_group_or_world_readable(path, app=app)
            _warn_if_dir_group_or_world_accessible(config_dir(app), app=app)
    print(f"checked {checked} credentials file(s)")
    return 0


def _discover_apps() -> list[str]:
    """App names that have a credentials file under the config base -- the immediate
    subdirectories of ``config_dir``'s parent that contain a ``credentials.json``. A
    subdirectory whose name is not a valid app segment is skipped, so one stray neighbour
    cannot abort the whole sweep."""
    config_base = config_dir("xdg-kit").parent   # the XDG config home itself
    if not config_base.is_dir():
        return []
    discovered_apps = []
    for child in config_base.iterdir():
        if not (child.is_dir() and (child / "credentials.json").is_file()):
            continue
        try:
            app_dir_segment(child.name)
        except InvalidAppNameError:
            continue
        discovered_apps.append(child.name)
    return sorted(discovered_apps)


def _warn_if_dir_group_or_world_accessible(directory: Path, *, app: str) -> None:
    """Warn on stderr when the config directory holding a credentials file is reachable by
    group or others -- it should be mode 0700 so another local user cannot replace the
    file. POSIX-only, best-effort."""
    if os.name != "posix" or not directory.is_dir():
        return
    try:
        mode = directory.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        print(
            f"{app}: warning: {directory} is accessible by group/other; "
            f"restrict it with 'chmod 700'",
            file=sys.stderr,
        )


def _mask(value: str) -> str:
    """A value shown with only its ends visible, e.g. ``sk***ab`` -- enough to tell which
    key it is without printing it."""
    if len(value) <= 8:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


if __name__ == "__main__":
    raise SystemExit(main())
