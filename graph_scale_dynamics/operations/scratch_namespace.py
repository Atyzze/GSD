from __future__ import annotations

import ctypes
import fcntl
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

SCRATCH_NAMESPACE_CONTRACT = "gsd-scratch-namespace-1"
DEFAULT_SIZE = "50%"
MIN_SIZE_BYTES = 1 << 30
READY_TIMEOUT_SECONDS = 10.0
FOLDER_CHECK_SECONDS = max(1, int(os.environ.get("GSD_SCRATCH_FOLDER_CHECK_SECONDS", "30")))
IDLE_GRACE_SECONDS = max(0, int(os.environ.get("GSD_SCRATCH_IDLE_GRACE_SECONDS", "600")))
PARKED_MANIFEST = "PARKED.json"
NOT_PARKED = ("postgres-runtime",)
MS_NOSUID, MS_NODEV, MS_REC, MS_PRIVATE = 2, 4, 16384, 1 << 18


def scratch_dir(root: Path) -> Path:
    return Path(root).resolve() / "var" / "scratch"


def _pidfile(root: Path) -> Path:
    return Path(root).resolve() / "var" / "run" / "scratch-holder.json"


def parked_dir(root: Path) -> Path:
    return Path(root).resolve() / "var" / "scratch_parked"


def _lockfile(root: Path) -> Path:
    return Path(root).resolve() / "var" / "run" / "scratch-holder.lock"


@contextmanager
def _folder_lock(root: Path, *, wait: bool = True):
    path = _lockfile(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def _utc(seconds: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if seconds is None else seconds))


def members_of_my_namespace(proc: str | Path = "/proc") -> list[int]:
    proc, me = Path(proc), os.getpid()
    try:
        mine = os.readlink(proc / "self" / "ns" / "mnt")
        pids = [int(entry.name) for entry in proc.iterdir() if entry.name.isdigit()]
    except OSError:
        return []
    found = []
    for pid in pids:
        if pid == me:
            continue
        try:
            if os.readlink(proc / str(pid) / "ns" / "mnt") == mine:
                found.append(pid)
        except OSError:
            continue
    return found


def park(scratch: Path, parked: Path) -> dict:
    scratch, parked = Path(scratch), Path(parked)
    files = size = dropped = 0
    error = None
    for name in NOT_PARKED:
        if (scratch / name).is_dir():
            dropped += files_in(scratch / name)[0]
            shutil.rmtree(scratch / name, ignore_errors=True)
    for directory, _subdirectories, names in os.walk(scratch):
        for name in names:
            source = Path(directory) / name
            try:
                mode = os.lstat(source).st_mode
                if stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode):
                    source.unlink()
                    dropped += 1
                    continue
                target = parked / source.relative_to(scratch)
                target.parent.mkdir(parents=True, exist_ok=True)
                length = 0 if stat.S_ISLNK(mode) else os.lstat(source).st_size
                shutil.move(str(source), str(target))
                files, size = files + 1, size + length
            except OSError as exc:
                error = f"{type(exc).__name__}: {exc}"
                try:
                    if source.exists() and target.exists():
                        target.unlink()
                except (OSError, NameError):
                    pass
                break
        if error:
            break
    for directory, _subdirectories, _names in sorted(os.walk(scratch), key=lambda item: -len(item[0])):
        if Path(directory) != scratch:
            try:
                os.rmdir(directory)
            except OSError:
                pass
    left = files_in(scratch)[0]
    if files:
        parked.mkdir(parents=True, exist_ok=True)
        manifest = parked / PARKED_MANIFEST
        before = {}
        try:
            before = json.loads(manifest.read_text())
        except (OSError, ValueError):
            pass
        manifest.write_text(json.dumps({"contract": SCRATCH_NAMESPACE_CONTRACT, "parked_utc": _utc(),
                                        "files": files + int(before.get("files") or 0),
                                        "bytes": size + int(before.get("bytes") or 0),
                                        "reading": "an idle scratch's files, moved to disk by its holder before it "
                                                   "ended; the next start of this folder moves them back"}))
    return {"files": files, "bytes": size, "dropped": dropped, "left": left, "error": error}


def restore(parked: Path, scratch: Path) -> dict:
    parked, scratch = Path(parked), Path(scratch)
    files = size = 0
    error = None
    if not parked.is_dir():
        return {"files": 0, "bytes": 0, "left": 0, "error": None}
    for directory, _subdirectories, names in os.walk(parked):
        for name in names:
            source = Path(directory) / name
            relative = source.relative_to(parked)
            if str(relative) == PARKED_MANIFEST:
                continue
            target = scratch / relative
            try:
                if target.exists() or target.is_symlink():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                length = 0 if source.is_symlink() else source.stat().st_size
                shutil.move(str(source), str(target))
                files, size = files + 1, size + length
            except OSError as exc:
                error = f"{type(exc).__name__}: {exc}"
                try:
                    if target.exists() and source.exists():
                        target.unlink()
                except OSError:
                    pass
                break
        if error:
            break
    left = sum(1 for d, _s, names in os.walk(parked) for n in names
               if not (Path(d) == parked and n == PARKED_MANIFEST))
    if not left:
        shutil.rmtree(parked, ignore_errors=True)
    return {"files": files, "bytes": size, "left": left, "error": error}


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _mount(source, target, fstype, flags: int, data) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encode = (lambda value: None if value is None else str(value).encode())
    if libc.mount(encode(source), encode(target), encode(fstype), ctypes.c_ulong(flags), encode(data)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"mount {fstype or ''} on {target}: {os.strerror(error)}")


def mounted_here(root: Path) -> bool:
    target = str(scratch_dir(root))
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            before, _, after = line.partition(" - ")
            fields = before.split()
            if len(fields) > 4 and fields[4].replace("\\040", " ") == target and after.split()[:1] == ["tmpfs"]:
                return True
    except OSError:
        return False
    return False


def _is_holder_of(pid: int, root: Path, proc: str | Path = "/proc") -> bool:
    try:
        command = (Path(proc) / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    if __name__.encode() not in command:
        return False
    if str(Path(root).resolve()).encode() in command:
        return True
    from graph_scale_dynamics.operations.scratch_holders import scratch_mounts
    try:
        mounts = scratch_mounts((Path(proc) / str(pid) / "mountinfo").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return any(Path(m["mount"]) == scratch_dir(Path(root).resolve()) for m in mounts)


def holder_pid(root: Path) -> int | None:
    try:
        record = json.loads(_pidfile(root).read_text())
        pid = int(record["pid"])
        if record.get("boot_id") == _boot_id() and _is_holder_of(pid, root):
            return pid
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        from graph_scale_dynamics.operations.scratch_holders import discover
        wanted = Path(root).resolve()
        for record in discover():
            pid = record.get("holder_pid")
            if pid is not None and Path(record["folder"]) == wanted and _is_holder_of(int(pid), root):
                return int(pid)
    except Exception:  # noqa: BLE001
        return None
    return None


def _mem_total_bytes() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    raise OSError("no MemTotal in /proc/meminfo")


def size_bytes(requested: str, total: int) -> int:
    text = str(requested).strip().lower()
    if not text:
        raise ValueError("an empty scratch size")
    if text.endswith("%"):
        return int(total * float(text[:-1]) / 100.0)
    scale = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}
    if text[-1] in scale:
        return int(float(text[:-1]) * scale[text[-1]])
    return int(float(text))


def planned_size(root: Path) -> dict:
    from graph_scale_dynamics.operations.scratch_holders import committed_bytes
    from graph_scale_dynamics.scheduling.memory import host_available_floor_bytes

    total = _mem_total_bytes()
    requested = os.environ.get("GSD_SCRATCH_SIZE", DEFAULT_SIZE).strip() or DEFAULT_SIZE
    asked = size_bytes(requested, total)
    others = committed_bytes(exclude=root)
    floor = host_available_floor_bytes(total)
    room = max(0, total - floor - others)
    size = min(asked, room)
    return {"size_bytes": int(size), "asked": requested, "asked_bytes": int(asked), "others_bytes": int(others),
            "floor_bytes": int(floor), "total_bytes": int(total), "capped": size < asked}


def _hold(root: Path) -> int:
    from graph_scale_dynamics.operations.process_ownership import folder_identity
    root = Path(root).resolve()
    target = scratch_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    identity = folder_identity(root)
    uid, gid = os.getuid(), os.getgid()
    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)
    Path("/proc/self/setgroups").write_text("deny")
    Path("/proc/self/uid_map").write_text(f"{uid} {uid} 1")
    Path("/proc/self/gid_map").write_text(f"{gid} {gid} 1")
    _mount(None, "/", None, MS_REC | MS_PRIVATE, None)
    size = os.environ.get("GSD_SCRATCH_SIZE", DEFAULT_SIZE).strip() or DEFAULT_SIZE
    _mount("tmpfs", target, "tmpfs", MS_NOSUID | MS_NODEV, f"size={size},mode=0700")
    pidfile = _pidfile(root)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    record = {"contract": SCRATCH_NAMESPACE_CONTRACT, "pid": os.getpid(), "root": str(root), "scratch": str(target),
              "size": size, "boot_id": _boot_id(), "started_utc": _utc(), "idle_grace_seconds": IDLE_GRACE_SECONDS,
              "idle_since_utc": None}

    def write(**changes) -> None:
        record.update(changes)
        partial = pidfile.with_suffix(".partial")
        partial.write_text(json.dumps(record))
        partial.replace(pidfile)

    write()
    stopping = []
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda *_: stopping.append(True))
    signal.signal(signal.SIGALRM, lambda *_: None)
    idle_since = None
    while not stopping and folder_identity(root) == identity:
        signal.alarm(FOLDER_CHECK_SECONDS)
        signal.pause()
        if stopping or not IDLE_GRACE_SECONDS:
            continue
        with _folder_lock(root, wait=False) as locked:
            members = members_of_my_namespace() if locked else [None]
            if members:
                if idle_since is not None:
                    idle_since = None
                    write(idle_since_utc=None)
                continue
            if idle_since is None:
                idle_since = time.time()
                write(idle_since_utc=_utc(idle_since))
                continue
            if time.time() - idle_since < IDLE_GRACE_SECONDS:
                continue
            moved = park(target, parked_dir(root))
            print(json.dumps({"event": "scratch_parked", "utc": _utc(), "idle_since_utc": _utc(idle_since), **moved}),
                  flush=True)
            if moved["left"]:
                idle_since = time.time()
                write(idle_since_utc=_utc(idle_since), last_park_error=moved["error"])
                continue
            try:
                pidfile.unlink()
            except OSError:
                pass
            break
    signal.alarm(0)
    return 0


def ensure_holder(root: Path) -> int:
    pid = holder_pid(root)
    if pid is not None:
        return pid
    root = Path(root).resolve()
    plan = planned_size(root)
    if plan["capped"] and plan["size_bytes"] < min(MIN_SIZE_BYTES, plan["asked_bytes"]):
        gib = 1 << 30
        raise RuntimeError(
            f"no room for this folder's scratch: other folders' scratch may grow to "
            f"{plan['others_bytes'] / gib:.1f} GiB of this host's {plan['total_bytes'] / gib:.1f} GiB, and the "
            f"floor keeps {plan['floor_bytes'] / gib:.1f} GiB; `python3 tools/scratch_holders.py` names them")
    log = root / "var" / "log" / "scratch-holder.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    package_root = str(Path(__file__).resolve().parents[2])
    path = os.pathsep.join(dict.fromkeys([package_root, str(root)]))
    with open(log, "ab") as out:
        process = subprocess.Popen([sys.executable, "-m", __name__, "hold", str(root)], cwd=str(root),
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True,
                                   close_fds=True, env=dict(os.environ, PYTHONPATH=path,
                                                            GSD_SCRATCH_SIZE=str(plan["size_bytes"])))
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        pid = holder_pid(root)
        if pid == process.pid:
            return pid
        if process.poll() is not None:
            break
        time.sleep(0.05)
    tail = log.read_text(errors="replace")[-400:] if log.exists() else ""
    raise RuntimeError(f"the scratch holder did not start (exit {process.poll()}): {tail.strip()}")


def thread_count() -> int:
    try:
        return len(os.listdir("/proc/self/task"))
    except OSError:
        return 1


def _join(pid: int) -> None:
    cwd = os.getcwd()
    with open(f"/proc/{pid}/ns/user") as user_ns, open(f"/proc/{pid}/ns/mnt") as mount_ns:
        os.setns(user_ns.fileno(), os.CLONE_NEWUSER)
        os.setns(mount_ns.fileno(), os.CLONE_NEWNS)
    os.chdir(cwd)


def enter(root: Path, *, create: bool = True, name_others: bool = False) -> dict:
    root = Path(root).resolve()
    result = {"contract": SCRATCH_NAMESPACE_CONTRACT, "scratch": str(scratch_dir(root)), "inside": False}
    if os.environ.get("GSD_VOLATILE_DIR", "").strip():
        return result | {"reason": "GSD_VOLATILE_DIR is set explicitly"}
    if name_others:
        from graph_scale_dynamics.operations.scratch_holders import name_other_folders
        named = name_other_folders(root, log=lambda line: print(f"scratch: {line}", flush=True))
        result |= {"other_folders": len(named["others"])}
    try:
        with _folder_lock(root):
            if not mounted_here(root):
                if not (hasattr(os, "setns") and hasattr(os, "unshare")):
                    return result | {"reason": "this Python has no os.setns (3.12 or later is needed)"}
                pid = ensure_holder(root) if create else holder_pid(root)
                if pid is None:
                    return result | {"reason": "no scratch holder is running"}
                threads = thread_count()
                if threads > 1:
                    return result | {"reason": f"this process already runs {threads} threads, and a threaded "
                                               "process cannot join; join before importing anything that starts "
                                               "threads (numpy does)"}
                _join(pid)
            if mounted_here(root):
                os.environ["GSD_VOLATILE_DIR"] = str(scratch_dir(root))
                if parked_dir(root).is_dir():
                    back = restore(parked_dir(root), scratch_dir(root))
                    result |= {"restored": back}
                return result | {"inside": True}
            return result | {"reason": "joined, but var/scratch is not a tmpfs here"}
    except (OSError, RuntimeError, ValueError) as error:
        return result | {"reason": f"{type(error).__name__}: {error}"}


def refusal(result: dict) -> str | None:
    reason = str(result.get("reason") or "")
    if result.get("inside") or "no room for this folder's scratch" not in reason:
        return None
    if os.environ.get("GSD_ALLOW_PERSISTENT_SCRATCH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    here = Path(str(result.get("scratch") or "")).parent.parent
    try:
        from graph_scale_dynamics.operations.scratch_holders import describe, discover
        others = [describe(record) for record in discover() if Path(record["folder"]) != here]
    except Exception as error:
        others = [f"(the other folders' scratches could not be read: {type(error).__name__}: {error})"]
    return "\n".join([
        f"refusing to start: no room for this folder's RAM scratch ({reason.partition(': ')[2] or reason}).",
        *(f"  {line}" for line in others),
        "This folder ends no other folder's scratch. A fleet that stops with its scratch empty ends its holder "
        "itself; a holder that no process has joined for "
        f"{_minutes(IDLE_GRACE_SECONDS)} moves its files to its folder's disk and ends (each line above says when). "
        "A holder started by an earlier build ends only when its folder is deleted, or with `kill <pid>` once "
        "nothing in it is needed. Then start again."])


def files_in(path: Path) -> tuple[int, int]:
    count = size = 0
    for directory, _subdirectories, names in os.walk(path):
        for name in names:
            try:
                size += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                continue
            count += 1
    return count, size


def release_when_empty(root: Path) -> dict:
    pid = holder_pid(root)
    if pid is None:
        return {"held": False}
    if not mounted_here(root):
        return {"held": True, "pid": pid, "ended": False, "seen": False}
    files, size = files_in(scratch_dir(root))
    if files:
        return {"held": True, "pid": pid, "ended": False, "seen": True, "files": files, "bytes": size}
    stop_holder(root)
    return {"held": True, "pid": pid, "ended": True, "seen": True, "files": 0, "bytes": 0}


def release_line(result: dict) -> str | None:
    if not result.get("held"):
        return None
    pid = result["pid"]
    if result.get("ended"):
        return (f"scratch: empty, so its holder (pid {pid}) ended and its RAM is free for another folder; "
                "the next start here mounts it again")
    if not result.get("seen"):
        return (f"scratch: kept, holder pid {pid}: this process could not look inside it; another folder's start "
                f"counts its full size until this folder is deleted or `kill {pid}` ends it")
    return (f"scratch: kept, {result['files']:,} file(s), {result['bytes'] / (1 << 30):.2f} GiB, a checkpoint perhaps "
            f"their only copy; holder pid {pid}: if no process of this folder joins it again within "
            f"{_minutes(IDLE_GRACE_SECONDS)}, the holder moves them to var/scratch_parked on this folder's disk and "
            f"ends, and the next start here moves them back")


def _minutes(seconds: int) -> str:
    return f"{seconds // 60} minutes" if seconds >= 120 else f"{seconds} seconds"


def stop_holder(root: Path) -> bool:
    pid = holder_pid(root)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    return True


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "hold":
        raise SystemExit(_hold(Path(sys.argv[2])))
    print("usage: python -m graph_scale_dynamics.operations.scratch_namespace hold <folder>", file=sys.stderr)
    raise SystemExit(2)
