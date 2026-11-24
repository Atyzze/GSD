#!/usr/bin/env python3
from __future__ import annotations

import argparse
import array
import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations.filesystem_endurance import inspect_cow_placement

_FS_IOC_GETFLAGS = 0x80086601
_FS_IOC_SETFLAGS = 0x40086602
_FS_NOCOW_FL = 0x00800000


def _set_nodatacow(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return False
    try:
        buffer = array.array("l", [0])
        fcntl.ioctl(fd, _FS_IOC_GETFLAGS, buffer, True)
        buffer[0] = int(buffer[0]) | _FS_NOCOW_FL
        fcntl.ioctl(fd, _FS_IOC_SETFLAGS, buffer, False)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _server_running() -> bool:
    import tools.postgres_instance as pg
    return pg._server_running()


def _why_busy(pgdata: Path) -> str | None:
    from graph_scale_dynamics.operations.folder_guard import live_fleet, live_serve
    if _server_running():
        return "the managed PostgreSQL server is running (run: python3 tools/postgres_instance.py stop)"
    if (pgdata / "postmaster.pid").exists():
        return (f"{pgdata / 'postmaster.pid'} exists: a postmaster may be running or did not stop cleanly "
                "(start and stop the instance once with tools/postgres_instance.py to clear it)")
    var = ROOT / "var"
    return live_fleet(var) or live_serve(var)


def _lock():
    import tools.postgres_instance as pg
    return pg.bootstrap_lock()


def _pgdata() -> Path:
    import tools.postgres_instance as pg
    return pg.PGDATA


def command_inspect() -> int:
    report = inspect_cow_placement(_pgdata())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def command_migrate(*, assume_yes: bool) -> int:
    with _lock():
        return _migrate(assume_yes=assume_yes)


def _migrate(*, assume_yes: bool) -> int:
    pgdata = _pgdata()
    report = inspect_cow_placement(pgdata)
    if not report.get("copy_on_write_filesystem"):
        print(f"PGDATA is on {report.get('filesystem')!r}; no copy-on-write migration applies")
        return 0
    if report.get("nodatacow"):
        print("PGDATA already carries the nodatacow attribute; nothing to do")
        return 0
    busy = _why_busy(pgdata)
    if busy:
        print(f"refusing to migrate PGDATA: {busy}")
        return 2
    if not (pgdata / "PG_VERSION").is_file():
        print(f"refusing to migrate: {pgdata} does not look like a PostgreSQL cluster")
        return 2

    used = sum(f.stat().st_size for f in pgdata.rglob("*") if f.is_file())
    free = shutil.disk_usage(pgdata.parent).free
    if free < used * 1.1:
        print(f"insufficient free space: cluster is {used / 1e9:.1f} GB, {free / 1e9:.1f} GB free")
        return 2

    staging = pgdata.with_name(pgdata.name + ".nocow-staging")
    retired = pgdata.with_name(pgdata.name + ".cow-retired")
    if staging.exists() or retired.exists():
        print(f"refusing to proceed: {staging} or {retired} already exists; clean them up first")
        return 2

    if not assume_yes:
        print(f"about to copy {used / 1e9:.1f} GB from {pgdata} into a nodatacow directory")
        print("the original is retained as " + str(retired))
        if input("proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("aborted")
            return 1

    staging.mkdir(parents=True)
    if not _set_nodatacow(staging):
        staging.rmdir()
        print("could not set the nodatacow attribute; the filesystem may not support it")
        return 2
    staging.chmod(0o700)

    result = subprocess.run(
        ["cp", "-a", "--reflink=never", str(pgdata) + "/.", str(staging) + "/"],
        check=False,
    )
    if result.returncode:
        print("copy failed; the original cluster is untouched")
        return 2
    busy = _why_busy(pgdata)
    if busy:
        shutil.rmtree(staging, ignore_errors=True)
        print(f"refusing to promote the copy: {busy} started during it; the copy is removed and the original "
              "cluster is untouched")
        return 2

    pgdata.rename(retired)
    staging.rename(pgdata)
    print(f"PGDATA migrated to nodatacow; previous cluster retained at {retired}")
    print("start the cluster, confirm it is healthy, then remove the retained copy")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/gsd_pgdata_cow.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="report copy-on-write placement for PGDATA")
    migrate = sub.add_parser("migrate", help="relocate PGDATA into a nodatacow directory")
    migrate.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)
    if args.command == "inspect":
        return command_inspect()
    return command_migrate(assume_yes=bool(args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
