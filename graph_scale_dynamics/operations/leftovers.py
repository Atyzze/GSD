from __future__ import annotations

import os
import signal
import time
from pathlib import Path

CONTRACT = "gsd-leftovers-1"
GRACE_SECONDS = 10.0
TILE_BTOP_FLAGS = ("--utf-force", "-u")
TILE_BTOP_CONFIG = "gsd-btop-telemetry-"
HELPERS = {"graph_scale_dynamics.operations.power_sidecar": ("publish", "cpu power publisher"),
           "graph_scale_dynamics.operations.scratch_namespace": ("hold", "scratch holder")}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _status(pid: int) -> dict:
    raw = _read(Path("/proc", str(pid), "status"))
    out = {}
    for line in (raw or b"").decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _argv(pid: int) -> list[str]:
    raw = _read(Path("/proc", str(pid), "cmdline")) or b""
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _tile_btop(pid: int, name: str, argv: list[str]) -> bool:
    if name != "btop":
        return False
    environ = _read(Path("/proc", str(pid), "environ"))
    if environ is not None and any(item.startswith(b"XDG_CONFIG_HOME=") and TILE_BTOP_CONFIG.encode() in item
                                   for item in environ.split(b"\0")):
        return True
    return all(flag in argv[1:] for flag in TILE_BTOP_FLAGS)


def _venv_folder(executable: str) -> str | None:
    head, separator, _ = executable.partition("/.venv/")
    return head if separator and head.startswith("/") else None


POSTGRES_NAMES = ("postgres", "postmaster", "gsd-postgres")


def _named(pid: int, name: str, argv: list[str]) -> tuple[str, str | None] | None:
    text = " ".join(argv)
    for module, (verb, kind) in HELPERS.items():
        if module in argv and verb in argv:
            at = argv.index(verb)
            return kind, (argv[at + 1] if at + 1 < len(argv) else None)
    if name in POSTGRES_NAMES or "unshare" in name:
        for index, arg in enumerate(argv):
            data = argv[index + 1] if arg == "-D" and index + 1 < len(argv) else (arg[2:] if arg.startswith("-D/") else None)
            if data and "/instance/" in data:
                return "postgres", data.split("/instance/", 1)[0]
        return None
    if _tile_btop(pid, name, argv):
        return "the CPU tile's btop", None
    if not (name.startswith("python") or Path(argv[0]).name.startswith("python")):
        return None
    folder = _venv_folder(argv[0])
    ours = "graph_scale_dynamics" in text or "main.py" in text
    if folder and not ours and not _gsd_environment(pid):
        return None
    if folder or "graph_scale_dynamics" in text:
        kind = "fleet supervisor" if "main.py" in text and "run" in argv else "fleet process"
        return kind, folder
    return None


def _gsd_environment(pid: int) -> bool:
    environ = _read(Path("/proc", str(pid), "environ"))
    return environ is not None and any(item.startswith(b"GSD_") for item in environ.split(b"\0"))


def gsd_folder(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    for folder in (candidate, *candidate.parents):
        if folder == folder.parent:
            break
        if (folder / "main.py").is_file() and (folder / "graph_scale_dynamics").is_dir():
            return str(folder)
    return None


def survey(uid: int | None = None) -> list[dict]:
    uid = os.getuid() if uid is None else int(uid)
    me = os.getpid()
    table: dict[int, dict] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        pid = int(entry)
        status = _status(pid)
        try:
            if int((status.get("Uid") or "-1").split()[0]) != uid:
                continue
        except ValueError:
            continue
        argv = _argv(pid)
        if not argv:
            continue
        table[pid] = {"pid": pid, "ppid": int(status.get("PPid") or 0), "name": status.get("Name") or "",
                      "argv": argv, "cwd": _cwd(pid)}
    found: dict[int, dict] = {}
    for pid, row in table.items():
        named = _named(pid, row["name"], row["argv"])
        if named is not None:
            found[pid] = dict(row, kind=named[0], folder=named[1])
    changed = True
    while changed:
        changed = False
        for pid, row in table.items():
            if pid not in found and row["ppid"] in found:
                found[pid] = dict(row, kind=f"child of {row['ppid']}", folder=None)
                changed = True
    def named_folder(pid: int, seen: frozenset = frozenset()) -> str | None:
        row = found.get(pid)
        if row is None or pid in seen:
            return None
        return row["folder"] or named_folder(row["ppid"], seen | {pid})

    out = []
    for pid, row in found.items():
        cwd = row["cwd"] or ""
        deleted = cwd.endswith(" (deleted)")
        cwd_path = cwd[:-len(" (deleted)")] if deleted else cwd
        named = named_folder(pid)
        candidates = [c for c in (named, cwd_path) if c]
        orphan_tile = row["kind"] == "the CPU tile's btop" and row["ppid"] == 1
        if not candidates and not orphan_tile:
            continue
        live = next((found_folder for found_folder in map(gsd_folder, candidates) if found_folder), None)
        basis = [named] if named else [cwd_path]
        if live is None and not orphan_tile and any(
                Path(c).exists() and not (deleted and c == cwd_path) for c in basis if c):
            continue
        candidate = candidates[0] if candidates else None
        replaced = deleted and live is not None and (
            cwd_path == live or (row["kind"] == "postgres" and cwd_path.startswith(live.rstrip("/") + "/instance/")))
        out.append({"pid": pid, "ppid": row["ppid"], "name": row["name"], "kind": row["kind"],
                    "folder": live or candidate, "gone": bool(orphan_tile or live is None or replaced),
                    "command": " ".join(row["argv"])[:300]})
    return sorted(out, key=lambda r: (str(r["folder"]), r["pid"]))


def end(processes: list[dict], *, grace: float = GRACE_SECONDS) -> dict:
    pids = {int(p["pid"]) for p in processes}
    names = {int(p["pid"]): p.get("name") for p in processes}
    parents = {int(p["pid"]): int(p.get("ppid") or 0) for p in processes}
    asked = []
    for pid in sorted(pids):
        postgres = names[pid] in POSTGRES_NAMES
        if postgres and names.get(parents[pid]) in POSTGRES_NAMES and parents[pid] in pids:
            continue
        try:
            os.kill(pid, signal.SIGINT if postgres else signal.SIGTERM)
            asked.append(pid)
        except OSError:
            continue
    deadline = time.monotonic() + float(grace)
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    killed, failed = [], []
    for pid in sorted(pids):
        if not _alive(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except OSError:
            failed.append(pid)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and any(_alive(pid) for pid in killed):
        time.sleep(0.05)
    failed += [pid for pid in killed if _alive(pid)]
    return {"asked": asked, "killed": [pid for pid in killed if pid not in failed], "failed": failed,
            "stopped": sorted(pid for pid in pids if pid not in killed and pid not in failed)}


def _alive(pid: int) -> bool:
    status = _status(pid)
    return bool(status) and not status.get("State", "").startswith("Z")


def at_start(root: Path, *, log=print, uid: int | None = None) -> dict:
    root = str(Path(root).resolve())
    try:
        processes = survey(uid)
    except OSError as exc:
        log(f"leftovers: not surveyed ({type(exc).__name__}: {exc})", flush=True)
        return {"contract": CONTRACT, "gone": [], "others": []}
    gone = [p for p in processes if p["gone"]]
    result: dict = {"contract": CONTRACT, "gone": gone}
    if gone:
        by_folder: dict = {}
        for p in gone:
            by_folder.setdefault(p["folder"] or "(no folder)", []).append(p)
        for folder, rows in by_folder.items():
            log(f"leftovers: {len(rows)} process(es) of {folder}, a folder that is gone, ending them: "
                + ", ".join(f"{p['kind']} pid {p['pid']}" for p in rows[:8]) + (" ..." if len(rows) > 8 else ""),
                flush=True)
        result["ended"] = end(gone)
        if result["ended"]["failed"]:
            log(f"leftovers: could not end pid(s) {result['ended']['failed']}", flush=True)
    others = sorted({p["folder"] for p in processes
                     if not p["gone"] and p["kind"] == "fleet supervisor" and p["folder"] != root})
    for folder in others:
        log(f"leftovers: another fleet runs in {folder}; two fleets share this host's cores, each slower, and "
            "neither changes what the other decides", flush=True)
    result["others"] = others
    return result
