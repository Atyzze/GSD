from __future__ import annotations

import os
import signal
import time
from pathlib import Path

REAPER_CONTRACT = "gsd-startup-reaper-1"

NAMESPACE_PREFIXES = ("gsd-", "rrv2-")
SCRATCH_ROOTS = ("/dev/shm",)
DATABASE_MARKERS = ("postgres-runtime", "postgres-temp-tablespace")
MIN_STALE_AGE_SECONDS = 900.0
CHILD_KIND_ENV = "GSD_CHILD_KIND"
CHILD_ROOT_ENV = "GSD_PROJECT_ROOT"
TERMINATE_GRACE_SECONDS = 5.0


def _proc_env(pid: int) -> dict[str, str]:
    try:
        raw = Path("/proc", str(pid), "environ").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    for item in raw.split("\0"):
        key, sep, value = item.partition("=")
        if sep:
            out[key] = value
    return out


def _proc_cmdline(pid: int) -> str:
    try:
        raw = Path("/proc", str(pid), "cmdline").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return " ".join(part for part in raw.split("\0") if part)


def _pids() -> list[int]:
    try:
        return [int(name) for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return []


def _dir_bytes(path: Path, *, max_seconds: float = 3.0) -> int:
    total = 0
    started = time.monotonic()
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
        if time.monotonic() - started > max_seconds:
            break
    return total


def paths_in_use(prefixes: tuple[str, ...] = NAMESPACE_PREFIXES) -> set[str]:
    in_use: set[str] = set()
    for pid in _pids():
        for source in (Path("/proc", str(pid), "fd"), None):
            try:
                if source is None:
                    text = Path("/proc", str(pid), "maps").read_text(encoding="utf-8", errors="replace")
                    targets = [line.split(" ", 5)[-1].strip() for line in text.splitlines() if "/" in line]
                else:
                    targets = []
                    for entry in os.listdir(source):
                        try:
                            targets.append(os.readlink(source / entry))
                        except OSError:
                            continue
            except OSError:
                continue
            for target in targets:
                for root in SCRATCH_ROOTS:
                    if target.startswith(root + "/"):
                        name = target[len(root) + 1:].split("/", 1)[0]
                        if name.startswith(prefixes):
                            in_use.add(os.path.join(root, name))
        try:
            cwd = os.readlink(Path("/proc", str(pid), "cwd"))
        except OSError:
            cwd = ""
        for root in SCRATCH_ROOTS:
            if cwd.startswith(root + "/"):
                name = cwd[len(root) + 1:].split("/", 1)[0]
                if name.startswith(prefixes):
                    in_use.add(os.path.join(root, name))
    return in_use


def database_is_running() -> bool:
    for pid in _pids():
        cmd = _proc_cmdline(pid)
        if "/postgresql/" in cmd or cmd.startswith("postgres") or " postgres " in f" {cmd} ":
            return True
    return False


def database_owned_namespaces() -> set[str]:
    owned: set[str] = set()
    for pid in _pids():
        cmd = _proc_cmdline(pid)
        if not ("/postgresql/" in cmd or cmd.startswith("postgres") or " postgres " in f" {cmd} "):
            continue
        parts = cmd.split()
        pgdata = None
        for index, part in enumerate(parts):
            if part == "-D" and index + 1 < len(parts):
                pgdata = parts[index + 1]
            elif part.startswith("-D") and len(part) > 2:
                pgdata = part[2:]
        if not pgdata:
            continue
        tblspc = Path(pgdata) / "pg_tblspc"
        try:
            links = list(tblspc.iterdir())
        except OSError:
            continue
        for link in links:
            try:
                target = os.readlink(link)
            except OSError:
                continue
            for root in SCRATCH_ROOTS:
                if target.startswith(root + "/"):
                    name = target[len(root) + 1:].split("/", 1)[0]
                    if name.startswith(NAMESPACE_PREFIXES):
                        owned.add(os.path.join(root, name))
    return owned


def survey_namespaces(keep: str | None = None, *, min_age_seconds: float = MIN_STALE_AGE_SECONDS) -> dict:
    in_use = paths_in_use()
    database_live = database_is_running()
    database_owned = database_owned_namespaces() if database_live else set()
    now = time.time()
    keep_resolved = str(Path(keep).resolve()) if keep else None
    entries = []
    for root in SCRATCH_ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.is_dir() or not path.name.startswith(NAMESPACE_PREFIXES):
                continue
            resolved = str(path.resolve())
            has_database = any((path / marker).exists() for marker in DATABASE_MARKERS)
            try:
                age = now - max(path.stat().st_mtime,
                                max((child.stat().st_mtime for child in path.iterdir()), default=0.0))
            except OSError:
                age = 0.0
            if keep_resolved and resolved == keep_resolved:
                status = "current"
            elif resolved in in_use or str(path) in in_use:
                status = "in_use"
            elif has_database and database_live and (
                    not database_owned or resolved in database_owned or str(path) in database_owned):
                status = "database"
            elif age < float(min_age_seconds):
                status = "young"
            else:
                status = "stale"
            entries.append({"path": str(path), "bytes": _dir_bytes(path),
                            "status": status, "age_seconds": round(age, 1),
                            "has_database_dirs": has_database})
    return {"contract": REAPER_CONTRACT,
            "namespaces": sorted(entries, key=lambda e: -e["bytes"]),
            "stale_bytes": sum(e["bytes"] for e in entries if e["status"] == "stale"),
            "total_bytes": sum(e["bytes"] for e in entries),
            "kept": keep_resolved}


def survey_orphan_children(project_root: Path | None = None) -> list[dict]:
    root = str(Path(project_root).resolve()) if project_root else None
    out = []
    for pid in _pids():
        env = _proc_env(pid)
        kind = env.get(CHILD_KIND_ENV)
        cmd = _proc_cmdline(pid)
        if not (bool(kind) or ".services.worker.child" in cmd or ".services.analyzer.child" in cmd):
            continue
        owner = env.get(CHILD_ROOT_ENV) or env.get("PYTHONPATH", "").split(os.pathsep)[0]
        if root and (not owner or str(Path(owner).resolve()) != root):
            continue
        out.append({"pid": pid, "kind": kind or "child", "n": env.get("GSD_CHILD_N"), "project_root": owner,
                    "cmdline": cmd[:200]})
    return out


def fleet_children_running(project_root: Path) -> bool:
    return bool(survey_orphan_children(project_root))


def stop_fleet_children(project_root: Path, *, log=print) -> list[dict]:
    killed = []
    for child in survey_orphan_children(project_root):
        try:
            os.killpg(int(child["pid"]), signal.SIGKILL)
        except ProcessLookupError:
            continue
        except OSError:
            try:
                os.kill(int(child["pid"]), signal.SIGKILL)
            except OSError:
                continue
        killed.append(child)
    deadline = time.monotonic() + 1.0
    while killed and time.monotonic() < deadline and any(Path("/proc", str(c["pid"])).exists() for c in killed):
        time.sleep(0.05)
    if killed:
        log(f"shutdown: {len(killed)} engine child(ren) did not stop when asked and were killed: "
            + ", ".join(f"{c['kind']} N={c.get('n') or '?'} pid {c['pid']}" for c in killed))
    return killed


def reap_orphan_children(project_root: Path | None = None, *, dry_run: bool = False,
                         log=print) -> dict:
    orphans = survey_orphan_children(project_root)
    if not orphans:
        return {"contract": REAPER_CONTRACT, "orphans": [], "terminated": [], "killed": []}
    log(f"child reaper: {len(orphans)} orphaned fleet child process(es) from a previous run")
    if dry_run:
        return {"contract": REAPER_CONTRACT, "orphans": orphans, "terminated": [], "killed": [],
                "dry_run": True}
    terminated, killed = [], []
    for entry in orphans:
        try:
            os.kill(entry["pid"], signal.SIGTERM)
            terminated.append(entry["pid"])
        except OSError:
            continue
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not any(Path("/proc", str(pid)).exists() for pid in terminated):
            break
        time.sleep(0.25)
    for pid in terminated:
        if Path("/proc", str(pid)).exists():
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except OSError:
                continue
    log(f"child reaper: terminated {len(terminated)}, force-killed {len(killed)}")
    return {"contract": REAPER_CONTRACT, "orphans": orphans,
            "terminated": terminated, "killed": killed}


def sweep(project_root: Path | None = None, *, keep: str | None = None, children: bool = True,
          dry_run: bool = False, log=print) -> dict:
    result: dict = {"contract": REAPER_CONTRACT,
                    "sampled_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if children:
        result["children"] = reap_orphan_children(project_root, dry_run=dry_run, log=log)
    return result
