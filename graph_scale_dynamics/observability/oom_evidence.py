from __future__ import annotations

import os
import time
from pathlib import Path

OOM_EVIDENCE_CONTRACT = "gsd-oom-evidence-2"
OOM_CLASS = "oom_killed"
SIGKILL_RETURNCODE = -9
KMSG_RECORDS = 20000
CGROUP_ROOT = Path("/sys/fs/cgroup")
VMSTAT = Path("/proc/vmstat")
KMSG = "/dev/kmsg"


def now_usec() -> int:
    return int(time.clock_gettime(time.CLOCK_MONOTONIC) * 1_000_000)


def _counter(path: Path | None, key: str = "oom_kill") -> int | None:
    if path is None:
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition(" ")
            if name == key:
                return int(value.strip())
    except (OSError, ValueError):
        return None
    return None


def _cgroup_path(pid: int | None) -> str | None:
    if pid is None:
        return None
    try:
        lines = Path(f"/proc/{int(pid)}/cgroup").read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    for line in lines:
        hierarchy, _, rest = line.partition(":")
        controllers, _, relative = rest.partition(":")
        if hierarchy == "0" and controllers == "":
            return relative
    return None


def _cgroup_events(pid: int | None) -> Path | None:
    relative = _cgroup_path(pid)
    if relative is None:
        return None
    events = CGROUP_ROOT / relative.lstrip("/") / "memory.events"
    return events if events.is_file() else None


def _own_cgroup(pid: int | None, events: Path | None) -> bool:
    if pid is None or events is None or _cgroup_path(os.getpid()) == _cgroup_path(pid):
        return False
    try:
        procs = {int(value) for value in (events.parent / "cgroup.procs").read_text(encoding="utf-8").split()}
    except (OSError, ValueError):
        return False
    return procs <= {int(pid)}


def counters(pid: int | None) -> dict:
    events = _cgroup_events(pid)
    return {"contract": OOM_EVIDENCE_CONTRACT, "started_usec": now_usec(),
            "cgroup_events": str(events) if events else None, "own_cgroup": _own_cgroup(pid, events),
            "cgroup": _counter(events), "host": _counter(VMSTAT), "read_usec": now_usec()}


def refresh(before: dict | None) -> None:
    if not before:
        return
    events = before.get("cgroup_events")
    before.update(cgroup=_counter(Path(events)) if events else None, host=_counter(VMSTAT), read_usec=now_usec())


def kernel_record(pid: int, since_usec: int | None = None) -> str | None:
    try:
        fd = os.open(KMSG, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    marks = (f"Killed process {int(pid)} ", f"pid={int(pid)},")
    found = None
    try:
        for _ in range(KMSG_RECORDS):
            try:
                record = os.read(fd, 8192)
            except BlockingIOError:
                break
            except OSError:
                continue
            if not record:
                break
            text = record.decode("utf-8", errors="replace")
            header, _, message = text.partition(";")
            fields = header.split(",")
            try:
                stamped = int(fields[2])
            except (IndexError, ValueError):
                continue
            if since_usec is not None and stamped < int(since_usec):
                continue
            lowered = message.lower()
            if any(mark in message for mark in marks) and ("oom" in lowered or "out of memory" in lowered):
                found = message.strip()[:300]
    finally:
        os.close(fd)
    return found


def judge(before: dict | None, *, pid: int | None, returncode: int | None, ended_on_its_own: bool,
          peak_rss_bytes: int = 0, reservation_bytes: int = 0) -> dict | None:
    if returncode != SIGKILL_RETURNCODE or not ended_on_its_own:
        return None
    before = before or {}
    events = before.get("cgroup_events")
    after = {"cgroup": _counter(Path(events)) if events else None, "host": _counter(VMSTAT)}
    rose = {name: after[name] - before[name] for name in ("cgroup", "host")
            if isinstance(before.get(name), int) and isinstance(after[name], int) and after[name] > before[name]}
    readable = any(isinstance(before.get(name), int) and isinstance(after[name], int) for name in ("cgroup", "host"))
    own = bool(before.get("own_cgroup")) and "cgroup" in rose
    record = kernel_record(pid, before.get("started_usec")) if pid is not None else None
    over = bool(reservation_bytes and int(peak_rss_bytes or 0) > int(reservation_bytes))
    peak = over and (bool(rose) or not readable)
    oom = bool(record or own or peak)
    return {"contract": OOM_EVIDENCE_CONTRACT, "oom": oom, "counters_rose": rose,
            "own_cgroup": bool(before.get("own_cgroup")), "kernel_record": record, "counters_readable": readable,
            "peak_rss_bytes": int(peak_rss_bytes or 0),
            "reservation_bytes": int(reservation_bytes or 0), "peak_over_reservation": over,
            "window_usec": ([before.get("started_usec"), before.get("read_usec")]
                            if before.get("started_usec") is not None else None),
            "decided_by": ("kernel record" if record else "its own cgroup's counter" if own
                           else "peak over reservation" if peak else "none")}


def attempt_class(fallback: str, verdict: dict | None) -> str:
    return OOM_CLASS if verdict and verdict.get("oom") else fallback


__all__ = ["OOM_CLASS", "OOM_EVIDENCE_CONTRACT", "attempt_class", "counters", "judge", "kernel_record", "refresh"]
