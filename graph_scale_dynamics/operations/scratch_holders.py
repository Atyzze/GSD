from __future__ import annotations

import json
import os
import time
from pathlib import Path

HOLDERS_CONTRACT = "gsd-scratch-holders-1"
HOLDER_MODULE = "graph_scale_dynamics.operations.scratch_namespace"
SCRATCH_SUFFIX = ("var", "scratch")
BREAKDOWN_SECONDS = 2.0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _argv(proc: Path, pid: int) -> list[str]:
    try:
        raw = (proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def holder_folder(argv: list[str]) -> str | None:
    try:
        index = argv.index("-m")
    except ValueError:
        return None
    if argv[index + 1:index + 3] == [HOLDER_MODULE, "hold"] and len(argv) > index + 3:
        return argv[index + 3]
    return None


def _uid(proc: Path, pid: int) -> int | None:
    for line in _read(proc / str(pid) / "status").splitlines():
        if line.startswith("Uid:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _mount_ns(proc: Path, pid: int) -> str | None:
    try:
        return os.readlink(proc / str(pid) / "ns" / "mnt")
    except OSError:
        return None


def _name(proc: Path, pid: int) -> str:
    return _read(proc / str(pid) / "comm").strip() or "?"


def _unescape(field: str) -> str:
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def scratch_mounts(mountinfo: str) -> list[dict]:
    found = []
    for line in mountinfo.splitlines():
        left, _, right = line.partition(" - ")
        fields, fs = left.split(), right.split()
        if len(fields) < 5 or not fs or fs[0] != "tmpfs":
            continue
        mount = _unescape(fields[4])
        if tuple(Path(mount).parts[-2:]) != SCRATCH_SUFFIX:
            continue
        options = dict(opt.partition("=")[::2] for opt in (fs[2] if len(fs) > 2 else "").split(","))
        found.append({"mount": mount, "device": fields[2], "size_option": options.get("size")})
    return found


def _statvfs(path: Path) -> tuple[int | None, int | None]:
    try:
        st = os.statvfs(path)
    except OSError:
        return None, None
    return int(st.f_blocks * st.f_frsize), int((st.f_blocks - st.f_bfree) * st.f_frsize)


def _tree_bytes(path: Path, deadline: float) -> tuple[int, bool]:
    total = 0
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            return total, False
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += int(getattr(st, "st_blocks", 0)) * 512
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
        except OSError:
            continue
    return total, True


def breakdown(scratch: Path, *, seconds: float = BREAKDOWN_SECONDS) -> dict:
    deadline = time.monotonic() + max(0.1, float(seconds))
    entries: dict[str, int] = {}
    complete = True
    try:
        top = sorted(os.scandir(scratch), key=lambda e: e.name)
    except OSError as error:
        return {"entries": {}, "complete": False, "error": f"{type(error).__name__}: {error}"}
    for first in top:
        if first.is_dir(follow_symlinks=False):
            try:
                second = sorted(os.scandir(first.path), key=lambda e: e.name)
            except OSError:
                second = []
            for entry in second:
                if entry.is_dir(follow_symlinks=False):
                    size, done = _tree_bytes(Path(entry.path), deadline)
                else:
                    try:
                        size, done = int(entry.stat(follow_symlinks=False).st_blocks) * 512, True
                    except OSError:
                        size, done = 0, True
                entries[f"{first.name}/{entry.name}"] = size
                complete = complete and done
        else:
            try:
                entries[first.name] = int(first.stat(follow_symlinks=False).st_blocks) * 512
            except OSError:
                pass
        if time.monotonic() > deadline:
            complete = False
            break
    ordered = dict(sorted(entries.items(), key=lambda kv: -kv[1]))
    return {"entries": ordered, "complete": complete}


def discover(*, proc: str | Path = "/proc", uid: int | None = None, breakdown_of: str | Path | None = None) -> list[dict]:
    own = Path(breakdown_of).resolve() if breakdown_of is not None else None
    proc = Path(proc)
    uid = os.getuid() if uid is None else int(uid)
    namespaces: dict[str, list[int]] = {}
    holders: dict[str, list[tuple[int, str]]] = {}
    try:
        pids = sorted(int(entry.name) for entry in proc.iterdir() if entry.name.isdigit())
    except OSError:
        pids = []
    for pid in pids:
        if _uid(proc, pid) != uid:
            continue
        ns = _mount_ns(proc, pid)
        if ns is None:
            continue
        namespaces.setdefault(ns, []).append(pid)
        folder = holder_folder(_argv(proc, pid))
        if folder is not None:
            holders.setdefault(ns, []).append((pid, folder))
    devices: dict[str, dict] = {}
    for ns, members in namespaces.items():
        viewer = (holders.get(ns) or [(members[0], None)])[0][0]
        for mount in scratch_mounts(_read(proc / str(viewer) / "mountinfo")):
            slot = devices.setdefault(mount["device"], {"mount": mount, "namespaces": [], "viewer": viewer, "ns": ns})
            slot["namespaces"].append(ns)
            if holders.get(ns) and not holders.get(slot["ns"]):
                slot.update(viewer=viewer, ns=ns)
    found = []
    for device, slot in devices.items():
        mount = slot["mount"]
        folder = str(Path(mount["mount"]).parent.parent)
        holder_pid = next((pid for ns in slot["namespaces"] for pid, named in holders.get(ns, [])
                           if Path(named) == Path(folder)), None)
        moved_from = None
        if holder_pid is None:
            holder_pid, moved_from = next(((pid, named) for ns in slot["namespaces"]
                                           for pid, named in holders.get(ns, [])), (None, None))
        inside = proc / str(slot["viewer"]) / "root" / mount["mount"].lstrip("/")
        size, used = _statvfs(inside)
        others = sorted({pid for ns in slot["namespaces"] for pid in namespaces[ns] if pid != holder_pid})
        record = {
            "folder": folder, "scratch": mount["mount"], "device": device, "mount_namespace": slot["ns"],
            "holder_pid": holder_pid, "size_bytes": size, "used_bytes": used, "size_option": mount["size_option"],
            "members": [{"pid": pid, "name": _name(proc, pid), "command": " ".join(_argv(proc, pid))[:160]}
                        for pid in others],
        }
        if moved_from is not None:
            record["moved_from"] = moved_from
        record["busy"] = bool(record["members"])
        if own is not None and Path(folder) == own:
            record["breakdown"] = breakdown(inside)
        found.append(record)
    return sorted(found, key=lambda r: -(r.get("used_bytes") or 0))


def _gib(value) -> str:
    return "?" if value is None else f"{value / 2 ** 30:.1f} GiB"


def describe(record: dict) -> str:
    who = (f"holder pid {record['holder_pid']}" if record.get("holder_pid") is not None
           else "no holder (kept alive by the processes inside)")
    inside = ""
    if record.get("members"):
        names = ", ".join(f"{m['name']} {m['pid']}" for m in record["members"][:4])
        more = len(record["members"]) - 4
        inside = f"; busy: {names}" + (f" and {more} more" if more > 0 else "")
    moved = (f" (its holder was started for {record['moved_from']}: the folder was renamed, moved or trashed)"
             if record.get("moved_from") else "")
    return (f"{record['folder']}/var/scratch: {_gib(record.get('used_bytes'))} in use of "
            f"{_gib(record.get('size_bytes'))}, {who}{moved}{inside}{idle_words(record)}")


def idle_words(record: dict) -> str:
    if record.get("busy") or record.get("holder_pid") is None:
        return ""
    try:
        kept = json.loads((Path(record["folder"]) / "var" / "run" / "scratch-holder.json").read_text())
    except (OSError, ValueError, KeyError):
        kept = {}
    if "idle_grace_seconds" not in kept:
        return ""
    grace = int(kept.get("idle_grace_seconds") or 0)
    since = kept.get("idle_since_utc")
    if not grace:
        return "; its idle grace is off (GSD_SCRATCH_IDLE_GRACE_SECONDS=0)"
    if not since:
        return f"; idle, it moves its files to its folder's disk and ends {grace // 60} minutes after it is first seen so"
    import calendar
    try:
        ends = calendar.timegm(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ")) + grace
    except ValueError:
        return ""
    return (f"; idle since {since}, it moves its files to its folder's disk and ends by "
            f"{time.strftime('%H:%M', time.localtime(ends))} local time")


def name_other_folders(keep: str | Path, *, log=print, proc: str | Path = "/proc",
                       found: list[dict] | None = None) -> dict:
    result = {"contract": HOLDERS_CONTRACT, "keep": str(Path(keep).resolve()), "kept": [], "others": [], "lines": []}
    try:
        records = discover(proc=proc) if found is None else found
    except Exception as error:  # noqa: BLE001
        result["lines"].append(f"scratch holders not read: {type(error).__name__}: {error}")
        _emit(log, result["lines"])
        return result
    keep_path = Path(keep).resolve()
    for record in records:
        if Path(record["folder"]) == keep_path:
            result["kept"].append(record)
            continue
        result["others"].append(record)
        result["lines"].append(f"another folder's scratch, {'in use' if record.get('busy') else 'idle'}, left "
                               f"alone (a folder acts only on its own): {describe(record)}")
    _emit(log, result["lines"])
    return result


def _emit(log, lines: list[str]) -> None:
    if log is None:
        return
    for line in lines:
        try:
            log(line)
        except Exception:  # noqa: BLE001
            pass


def committed_bytes(*, exclude: str | Path | None = None, found: list[dict] | None = None) -> int:
    records = discover() if found is None else found
    skip = Path(exclude).resolve() if exclude is not None else None
    return sum(int(r.get("size_bytes") or 0) for r in records
               if skip is None or Path(r["folder"]) != skip)
