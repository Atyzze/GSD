from __future__ import annotations

import os
import re
from pathlib import Path

HOLDERS_CONTRACT = "gsd-shared-memory-holders-1"
MIN_BYTES = 64 * 1024 * 1024


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def tmpfs_mounts(mountinfo: str | None = None) -> list[dict]:
    text = mountinfo if mountinfo is not None else _read(Path("/proc/self/mountinfo"))
    seen, out = set(), []
    for line in text.splitlines():
        left, _, right = line.partition(" - ")
        fields, fs = left.split(), right.split()
        if len(fields) < 5 or not fs or fs[0] != "tmpfs":
            continue
        mount = fields[4].replace("\\040", " ")
        if mount in seen:
            continue
        seen.add(mount)
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        out.append({"mount": mount, "used_bytes": int(used), "size_bytes": int(st.f_blocks * st.f_frsize),
                    "device": fields[2]})
    return sorted(out, key=lambda m: -m["used_bytes"])


def _postgres_data_dir(pid: int, cmdline: list[str]) -> str | None:
    if "-D" in cmdline[:-1]:
        return cmdline[cmdline.index("-D") + 1]
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def shmem_processes(proc: str = "/proc", *, min_bytes: int = MIN_BYTES) -> list[dict]:
    groups: dict[str, dict] = {}
    for entry in Path(proc).iterdir():
        if not entry.name.isdigit():
            continue
        status = _read(entry / "status")
        match = re.search(r"^RssShmem:\s+(\d+)\s+kB", status, re.M)
        if not match:
            continue
        shmem = int(match.group(1)) * 1024
        if shmem < max(1, int(min_bytes)):
            continue
        cmdline = [p for p in _read(entry / "cmdline").split("\0") if p]
        name = os.path.basename(cmdline[0]) if cmdline else (re.search(r"^Name:\s+(\S+)", status, re.M) or [None, "?"])[1]
        joined = " ".join(cmdline)
        if name in ("postgres", "postmaster") or joined.startswith("postgres:"):
            key = f"postgres cluster {_postgres_data_dir(int(entry.name), cmdline) or '?'}"
        else:
            key = joined[:160] or name
        slot = groups.setdefault(key, {"holder": key, "shmem_bytes": 0, "processes": 0, "pids": []})
        slot["shmem_bytes"] = max(slot["shmem_bytes"], shmem)
        slot["processes"] += 1
        if len(slot["pids"]) < 5:
            slot["pids"].append(int(entry.name))
    return sorted(groups.values(), key=lambda g: -g["shmem_bytes"])


def sysv_segments(path: str = "/proc/sysvipc/shm") -> dict:
    text = _read(Path(path))
    lines = text.splitlines()
    if not lines:
        return {"segments": 0, "size_bytes": 0, "rss_bytes": 0}
    header = lines[0].split()
    count = size = rss = 0
    for line in lines[1:]:
        values = dict(zip(header, line.split(), strict=False))
        try:
            size += int(values.get("size", 0))
            rss += int(values.get("rss", values.get("size", 0)))
            count += 1
        except ValueError:
            continue
    return {"segments": count, "size_bytes": size, "rss_bytes": rss}


def _meminfo_shmem(path: str = "/proc/meminfo") -> int | None:
    match = re.search(r"^Shmem:\s+(\d+)\s+kB", _read(Path(path)), re.M)
    return int(match.group(1)) * 1024 if match else None


def holders(exclude_mounts: tuple[str, ...] = ()) -> dict:
    try:
        all_mounts = tmpfs_mounts()
    except Exception as exc:  # noqa: BLE001
        all_mounts = [{"error": f"{type(exc).__name__}: {exc}"}]
    try:
        from graph_scale_dynamics.operations.scratch_holders import discover
        scratch = discover()
    except Exception as exc:  # noqa: BLE001
        scratch = [{"error": f"{type(exc).__name__}: {exc}"}]
    scratch_devices = {s.get("device") for s in scratch if s.get("device")}
    mounts = [m for m in all_mounts if "error" in m or m.get("device") not in scratch_devices]
    try:
        every_process = shmem_processes(min_bytes=1)
    except Exception as exc:  # noqa: BLE001
        every_process = [{"error": f"{type(exc).__name__}: {exc}"}]
    sysv = sysv_segments()
    shmem = _meminfo_shmem()
    named = (sum(int(m.get("used_bytes") or 0) for m in mounts)
             + sum(int(s.get("used_bytes") or 0) for s in scratch)
             + int(sysv.get("rss_bytes") or 0)
             + sum(int(p.get("shmem_bytes") or 0) for p in every_process))
    share = (min(1.0, named / shmem) if shmem else None)
    listed_mounts = [m for m in mounts if "error" in m or (m["used_bytes"] >= MIN_BYTES
                     and not any(m["mount"] == x for x in exclude_mounts))]
    listed_processes = [p for p in every_process if "error" in p or p["shmem_bytes"] >= MIN_BYTES][:15]
    return {"contract": HOLDERS_CONTRACT, "shmem_bytes": shmem, "named_bytes": named,
            "named_share": None if share is None else round(share, 4),
            "scratch": scratch, "tmpfs_mounts": listed_mounts, "sysv": sysv, "processes": listed_processes,
            "note": "processes that map a tmpfs file are counted with the tmpfs and with the process, so the "
                    "named total can pass Shmem; the share is capped at 100%"}


def summary_lines(found: dict, limit: int = 6) -> list[str]:
    def gib(b):
        return f"{b / 2**30:.1f} GiB"
    lines = []
    if found.get("shmem_bytes") is not None:
        share = found.get("named_share")
        named = min(found.get("named_bytes") or 0, found["shmem_bytes"])
        lines.append(f"Shmem {gib(found['shmem_bytes'])}: {gib(named)}"
                     + (f" ({100 * share:.0f}%)" if share is not None else "") + " named below"
                     + (f"; {gib(found['shmem_bytes'] - named)} unnamed (kernel buffers, such as a GPU's, "
                        "belong to no process)" if share is not None and share < 0.95 else ""))
    try:
        from graph_scale_dynamics.operations.scratch_holders import describe
    except Exception:  # noqa: BLE001
        describe = None
    for s in (found.get("scratch") or [])[:limit]:
        if "error" in s:
            lines.append(f"folder scratches not read: {s['error']}")
        elif describe is not None:
            lines.append("scratch " + describe(s))
    lines += [f"tmpfs {m['mount']}: {gib(m['used_bytes'])} in files" for m in found.get("tmpfs_mounts") or []
              if "used_bytes" in m][:limit]
    sysv = found.get("sysv") or {}
    if (sysv.get("rss_bytes") or 0) >= MIN_BYTES:
        lines.append(f"SysV shared memory: {gib(sysv['rss_bytes'])} resident in {sysv.get('segments')} segment(s)")
    lines += [f"{p['holder']}: {gib(p['shmem_bytes'])} shared ({p['processes']} process(es))"
              for p in found.get("processes") or [] if "shmem_bytes" in p][:limit]
    return lines
