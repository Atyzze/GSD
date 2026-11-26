from __future__ import annotations

import json
import os

CONTRACT = "gsd-study-hours-1"
PARTS = ("A", "N", "D", "system")
NAMES = {"A": "the blind draw", "N": "the focus's neighbours, seeds and seeded laws", "D": "the depth seeker",
         "system": "the system's own use beside the science"}
CONTROLS = "campaign-standing-controls"
GIB = 1024 ** 3


def part_of(spec: dict) -> str | None:
    if str((spec or {}).get("name") or "") == CONTROLS:
        return None
    design = (spec or {}).get("study_design") or {}
    group, kind = design.get("group"), design.get("kind")
    if group in ("A", "N", "D"):
        return str(group)
    if kind == "blind":
        return "A"
    if kind == "seed":
        return "N"
    return None


def worker_seconds(repo) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sql in ("SELECT j.campaign_id campaign_id, COALESCE(SUM(a.wall_seconds),0) core, "
                "COALESCE(SUM(COALESCE(a.peak_rss_bytes,0)*a.wall_seconds),0) bytes "
                "FROM jobs j JOIN attempts a ON a.job_id=j.job_id WHERE a.wall_seconds IS NOT NULL "
                "GROUP BY j.campaign_id",
                "SELECT campaign_id, COALESCE(SUM(wall_seconds),0) core, "
                "COALESCE(SUM(COALESCE(peak_rss_bytes,0)*wall_seconds),0) bytes "
                "FROM analysis_attempts WHERE wall_seconds IS NOT NULL GROUP BY campaign_id"):
        for row in repo.conn.execute(sql).fetchall():
            seen = out.setdefault(str(row["campaign_id"]), {"core_seconds": 0.0, "byte_seconds": 0.0})
            seen["core_seconds"] += float(row["core"] or 0.0)
            seen["byte_seconds"] += float(row["bytes"] or 0.0)
    return out


def host_seconds(repo, cores: int) -> dict | None:
    row = repo.conn.execute(
        "SELECT COALESCE(SUM(interval_seconds*cpu_percent/100.0),0) cpu, "
        "COALESCE(SUM(interval_seconds*memory_used_bytes),0) mem, COALESCE(SUM(interval_seconds),0) span, "
        "MIN(sampled_utc) since, MAX(sampled_utc) until FROM resource_telemetry "
        "WHERE interval_seconds IS NOT NULL AND interval_seconds>0").fetchone()
    if row is None or not float(row["span"] or 0.0):
        return None
    return {"core_seconds": float(row["cpu"] or 0.0) * int(cores), "byte_seconds": float(row["mem"] or 0.0),
            "seconds": float(row["span"]), "since": row["since"], "until": row["until"]}


def hours(repo, campaign_ids=None, *, cores: int | None = None) -> dict:
    cores = int(cores or os.cpu_count() or 1)
    wanted = None if campaign_ids is None else {str(c) for c in campaign_ids}
    work = worker_seconds(repo)
    core = {part: 0.0 for part in PARTS}
    memory = {part: 0.0 for part in PARTS}
    for row in repo.conn.execute("SELECT campaign_id,spec_json FROM campaigns").fetchall():
        cid = str(row["campaign_id"])
        if wanted is not None and cid not in wanted:
            continue
        try:
            spec = json.loads(row["spec_json"] or "{}")
        except (TypeError, ValueError):
            spec = {}
        part = part_of(spec if isinstance(spec, dict) else {})
        if part is None:
            continue
        core[part] += (work.get(cid) or {}).get("core_seconds", 0.0)
        memory[part] += (work.get(cid) or {}).get("byte_seconds", 0.0)
    host = host_seconds(repo, cores)
    science_core, science_memory = sum(core.values()), sum(memory.values())
    core["system"] = max(0.0, host["core_seconds"] - science_core) if host else 0.0
    memory["system"] = max(0.0, host["byte_seconds"] - science_memory) if host else 0.0
    return {"contract": CONTRACT, "parts": list(PARTS), "names": NAMES, "host_cores": cores,
            "host_read": host is not None, "since": (host or {}).get("since"), "until": (host or {}).get("until"),
            "core_hours": {part: round(core[part] / 3600.0, 3) for part in PARTS}
            | {"total": round(sum(core.values()) / 3600.0, 3)},
            "memory_gib_hours": {part: round(memory[part] / GIB / 3600.0, 3) for part in PARTS}
            | {"total": round(sum(memory.values()) / GIB / 3600.0, 3)}}


__all__ = ["CONTRACT", "NAMES", "PARTS", "host_seconds", "hours", "part_of", "worker_seconds"]
