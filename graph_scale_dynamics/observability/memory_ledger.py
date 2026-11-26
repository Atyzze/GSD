from __future__ import annotations

import os
import re
import time
from pathlib import Path

LEDGER_CONTRACT = "gsd-memory-ledger-1"

_MEMINFO_KEYS = ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "Shmem",
                 "SReclaimable", "SUnreclaim", "AnonPages", "Mapped", "Unevictable",
                 "KernelStack", "PageTables", "HugePages_Total", "Hugepagesize", "SwapTotal", "SwapFree")


def read_meminfo(path: str = "/proc/meminfo") -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in _MEMINFO_KEYS:
                    parts = rest.split()
                    value = int(parts[0]) if parts else 0
                    if len(parts) > 1 and parts[1] == "kB":
                        value *= 1024
                    out[key] = value
    except OSError:
        pass
    if "HugePages_Total" in out and "Hugepagesize" in out:
        out["HugePages_bytes"] = out["HugePages_Total"] * out["Hugepagesize"]
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def process_pss_bytes(pid: int) -> int | None:
    text = _read(Path("/proc") / str(pid) / "smaps_rollup")
    match = re.search(r"^Pss:\s+(\d+)\s+kB", text, re.M)
    if match:
        return int(match.group(1)) * 1024
    text = _read(Path("/proc") / str(pid) / "status")
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB", text, re.M)
    return int(match.group(1)) * 1024 if match else None


def process_cmdline(pid: int) -> list[str]:
    raw = _read(Path("/proc") / str(pid) / "cmdline")
    return [part for part in raw.split("\0") if part]


def process_parent(pid: int) -> int | None:
    text = _read(Path("/proc") / str(pid) / "status")
    match = re.search(r"^PPid:\s+(\d+)", text, re.M)
    return int(match.group(1)) if match else None


def classify(cmdline: list[str]) -> tuple[str, int | None]:
    joined = " ".join(cmdline)
    if "graph_scale_dynamics.services.worker.child" in joined:
        return "simulation_child", _n_from_args(cmdline)
    if "graph_scale_dynamics.services.analyzer.child" in joined:
        return "analysis_child", _n_from_args(cmdline)
    if "graph_scale_dynamics.services." in joined:
        match = re.search(r"graph_scale_dynamics\.services\.(\w+)", joined)
        return f"service:{match.group(1) if match else 'unknown'}", None
    if "probe_calibration.py" in joined or "pipeline_trial.py" in joined:
        return "calibration", None
    base = os.path.basename(cmdline[0]) if cmdline else ""
    if base in ("postgres", "postmaster") or "/postgresql/" in joined or "postgres:" in joined:
        return "postgres", None
    if "main.py" in joined and " run" in joined:
        return "service:supervisor", None
    return "other", None


def _n_from_args(cmdline: list[str]) -> int | None:
    for part in cmdline[1:]:
        match = re.search(r"[_\-/](?:n|N)(\d{2,8})(?:[_\-.]|$)", part)
        if match:
            return int(match.group(1))
    return None


def child_tags(pid: int) -> tuple[str | None, int | None]:
    raw = _read(Path("/proc") / str(pid) / "environ")
    if not raw:
        return None, None
    kind = n = None
    for item in raw.split("\0"):
        if item.startswith("GSD_CHILD_KIND="):
            kind = item.split("=", 1)[1] or None
        elif item.startswith("GSD_CHILD_N="):
            try:
                n = int(item.split("=", 1)[1])
            except ValueError:
                n = None
    return kind, n


def scratch_breakdown(root: Path | None, *, max_seconds: float = 2.0) -> dict:
    if not root or not Path(root).is_dir():
        return {"root": str(root) if root else None, "available": False, "dirs": {}, "total_bytes": 0}
    root = Path(root)
    started = time.monotonic()
    dirs: dict[str, int] = {}
    truncated = False
    for entry in sorted(root.iterdir()):
        total = 0
        if entry.is_file():
            try:
                total = entry.stat().st_size
            except OSError:
                pass
        else:
            for dirpath, _dirnames, filenames in os.walk(entry):
                for name in filenames:
                    try:
                        total += os.stat(os.path.join(dirpath, name)).st_size
                    except OSError:
                        continue
                if time.monotonic() - started > max_seconds:
                    truncated = True
                    break
        dirs[entry.name] = total
        if truncated:
            break
    return {"root": str(root), "available": True, "dirs": dirs,
            "total_bytes": sum(dirs.values()), "truncated": truncated}


def tmpfs_usage(mount: str = "/dev/shm") -> dict:
    try:
        st = os.statvfs(mount)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return {"mount": mount, "total_bytes": total, "used_bytes": total - free, "available": True}
    except OSError:
        return {"mount": mount, "available": False, "total_bytes": 0, "used_bytes": 0}


def build_ledger(service_pids: dict[str, list[int]], *, scratch_root: Path | None = None,
                 reservations: dict | None = None, extra_pids: list[int] | None = None,
                 proc_root: str = "/proc") -> dict:
    mem = read_meminfo(os.path.join(proc_root, "meminfo"))
    total = mem.get("MemTotal", 0)

    known: dict[int, str] = {}
    for role, pids in (service_pids or {}).items():
        for pid in pids or ():
            known[int(pid)] = f"service:{role}"
    rows: list[dict] = []
    try:
        all_pids = [int(name) for name in os.listdir(proc_root) if name.isdigit()]
    except OSError:
        all_pids = []
    parents = {pid: process_parent(pid) for pid in all_pids}
    for pid in all_pids:
        cmd = process_cmdline(pid)
        cls, n = classify(cmd)
        if pid in known:
            cls = known[pid]
        if cls in ("simulation_child", "analysis_child") or cls == "other":
            kind, tagged_n = child_tags(pid)
            if kind in ("simulation", "analysis"):
                cls = f"{kind}_child"
                n = tagged_n if tagged_n is not None else n
        if cls == "other":
            parent = parents.get(pid)
            hops = 0
            while parent and hops < 4:
                if parent in known:
                    cls = "child_of:" + known[parent]
                    break
                parent = parents.get(parent)
                hops += 1
        pss = process_pss_bytes(pid)
        if pss is None:
            continue
        rows.append({"pid": pid, "class": cls, "n": n, "pss_bytes": pss})

    def total_for(pred) -> int:
        return sum(r["pss_bytes"] for r in rows if pred(r))

    services = {}
    for r in rows:
        if r["class"].startswith("service:"):
            services[r["class"][8:]] = services.get(r["class"][8:], 0) + r["pss_bytes"]
    sim_by_n: dict[str, dict] = {}
    ana_by_n: dict[str, dict] = {}
    for r in rows:
        bucket = sim_by_n if r["class"] == "simulation_child" else ana_by_n if r["class"] == "analysis_child" else None
        if bucket is None:
            continue
        key = str(r["n"] or "unknown")
        slot = bucket.setdefault(key, {"processes": 0, "pss_bytes": 0})
        slot["processes"] += 1
        slot["pss_bytes"] += r["pss_bytes"]

    simulation = total_for(lambda r: r["class"] == "simulation_child")
    analysis = total_for(lambda r: r["class"] == "analysis_child")
    postgres = total_for(lambda r: r["class"] == "postgres")
    calibration = total_for(lambda r: r["class"] == "calibration")
    service_total = sum(services.values())
    other_children = total_for(lambda r: r["class"].startswith("child_of:"))
    other = total_for(lambda r: r["class"] == "other")

    shm = tmpfs_usage("/dev/shm")
    scratch = scratch_breakdown(scratch_root)
    try:
        from graph_scale_dynamics.operations.startup_reaper import survey_namespaces
        namespaces = survey_namespaces(str(scratch_root) if scratch_root else None)
    except Exception:
        namespaces = None
    scratch_bytes = scratch["total_bytes"] if scratch["available"] else 0
    shmem_total = mem.get("Shmem", 0)
    other_folders = _other_folders_scratch(scratch_root)
    other_folders_bytes = sum(int(r.get("used_bytes") or 0) for r in other_folders)
    other_shmem = max(0, shmem_total - scratch_bytes - other_folders_bytes)
    page_cache = max(0, mem.get("Cached", 0) - shmem_total) + mem.get("Buffers", 0)
    slab = mem.get("SReclaimable", 0) + mem.get("SUnreclaim", 0)
    kernel_other = mem.get("KernelStack", 0) + mem.get("PageTables", 0) + mem.get("HugePages_bytes", 0)
    free = mem.get("MemFree", 0)
    attributed = (service_total + simulation + analysis + postgres + calibration + other_children + other
                  + scratch_bytes + other_folders_bytes + other_shmem + page_cache + slab + kernel_other + free)
    residual = total - attributed

    lines = [
        {"key": "simulation_children", "bytes": simulation, "reclaimable": False,
         "note": f"{sum(v['processes'] for v in sim_by_n.values())} process(es), PSS, by N below"},
        {"key": "analysis_children", "bytes": analysis, "reclaimable": False,
         "note": f"{sum(v['processes'] for v in ana_by_n.values())} process(es), PSS, by N below"},
        {"key": "service_processes", "bytes": service_total, "reclaimable": False, "note": "supervised roles, PSS"},
        {"key": "postgres", "bytes": postgres, "reclaimable": False, "note": "folder-local cluster, PSS"},
        {"key": "calibration", "bytes": calibration, "reclaimable": False, "note": "probe/ladder studies"},
        {"key": "other_service_children", "bytes": other_children, "reclaimable": False,
         "note": "children of supervised roles not recognised as sim/analysis"},
        {"key": "scratch_tmpfs", "bytes": scratch_bytes, "reclaimable": False,
         "note": "volatile scratch; pages are RAM until retention deletes the files"},
        {"key": "other_folders_scratch", "bytes": other_folders_bytes, "reclaimable": False,
         "note": f"{len(other_folders)} other folder(s)' RAM scratch, each in its own namespace; "
                 "tools/scratch_holders.py names them; none is ended from here"},
        {"key": "other_shmem", "bytes": other_shmem, "reclaimable": False,
         "note": "shared memory outside the scratch root (other tmpfs, SysV/POSIX shm)"},
        {"key": "page_cache", "bytes": page_cache, "reclaimable": True, "note": "file cache and buffers; reclaimable"},
        {"key": "kernel_slab", "bytes": slab, "reclaimable": False, "note": "SReclaimable + SUnreclaim"},
        {"key": "kernel_other", "bytes": kernel_other, "reclaimable": False, "note": "stacks, page tables, hugepages"},
        {"key": "other_processes", "bytes": other, "reclaimable": False, "note": "everything not ours, PSS"},
        {"key": "free", "bytes": free, "reclaimable": True, "note": "MemFree"},
        {"key": "residual", "bytes": residual, "reclaimable": False,
         "note": "MemTotal minus everything above; kernel allocations /proc does not attribute"},
    ]
    for line in lines:
        line["percent_of_total"] = round(100.0 * line["bytes"] / total, 1) if total else None

    reservation_view = None
    if reservations:
        sim_res = int(reservations.get("simulation") or 0)
        ana_res = int(reservations.get("analysis") or 0)
        reservation_view = {
            "simulation": {"reserved_bytes": sim_res, "measured_pss_bytes": simulation,
                           "ratio": round(sim_res / simulation, 2) if simulation else None},
            "analysis": {"reserved_bytes": ana_res, "measured_pss_bytes": analysis,
                         "ratio": round(ana_res / analysis, 2) if analysis else None},
            "budget_bytes": int(reservations.get("budget") or 0),
            "admission": reservations.get("admission"),
            "note": "admission keeps the floor available after every running child reaches its reservation; "
                    "a high ratio costs headroom only while children are young",
        }

    return {
        "contract": LEDGER_CONTRACT,
        "sampled_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mem_total_bytes": total,
        "mem_available_bytes": mem.get("MemAvailable", 0),
        "used_by_available_bytes": max(0, total - mem.get("MemAvailable", 0)),
        "lines": lines,
        "attributed_bytes": attributed,
        "residual_bytes": residual,
        "simulation_by_n": dict(sorted(sim_by_n.items(), key=lambda kv: (kv[0] == "unknown", int(kv[0]) if kv[0].isdigit() else 0))),
        "analysis_by_n": dict(sorted(ana_by_n.items(), key=lambda kv: (kv[0] == "unknown", int(kv[0]) if kv[0].isdigit() else 0))),
        "services": services,
        "scratch": scratch,
        "dev_shm": shm,
        "namespaces": namespaces,
        "other_folders_scratch": other_folders,
        "shared_memory_holders": _shared_memory_holders(),
        "reservation_vs_measured": reservation_view,
        "process_count": len(rows),
        "meminfo": mem,
    }


def _other_folders_scratch(scratch_root: Path | None) -> list[dict]:
    try:
        from graph_scale_dynamics.operations.scratch_holders import describe, discover
        found = discover()
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"{type(exc).__name__}: {exc}", "used_bytes": 0}]
    mine = Path(scratch_root).resolve() if scratch_root else None
    out = []
    for record in found:
        if mine is not None and (mine == Path(record["scratch"]) or Path(record["scratch"]) in mine.parents):
            continue
        out.append(dict(record, line=describe(record)))
    return out


def _shared_memory_holders() -> dict:
    try:
        from graph_scale_dynamics.observability.shared_memory import holders
        return holders()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
