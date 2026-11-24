from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

EVIDENCE_SOURCES_CONTRACT = "gsd-evidence-sources-1"
RUNTIME_IMPORTS_PREFIX = "runtime_imports:"
SUPERVISOR_LOG_NAME = "supervisor.log"

TRACKED_MODULE_PREFIXES = ("graph_scale_dynamics", "tools", "main")


def _main_module_name() -> str | None:
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    name = getattr(spec, "name", None)
    if isinstance(name, str) and name.split(".", 1)[0] in TRACKED_MODULE_PREFIXES:
        return name
    return None


def runtime_import_snapshot(modules=None) -> list[str]:
    names = list(sys.modules.keys()) if modules is None else list(modules)
    if modules is None:
        entry = _main_module_name()
        if entry:
            names.append(entry)
    out = []
    for name in names:
        head = name.split(".", 1)[0]
        if head in TRACKED_MODULE_PREFIXES:
            out.append(name)
    return sorted(set(out))


def runtime_import_digest(names) -> str:
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()[:16]


def runtime_import_record(service: str, names=None) -> dict:
    names = runtime_import_snapshot() if names is None else sorted(set(names))
    return {
        "service": str(service),
        "pid": os.getpid(),
        "argv0": os.path.basename(sys.argv[0]) if sys.argv else "",
        "modules": names,
        "digest": runtime_import_digest(names),
        "sampled_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def runtime_imports_payload(repo, extra_records=()) -> dict:
    records = []
    try:
        rows = repo.conn.execute(
            "SELECT key,value FROM control WHERE key LIKE ?",
            (RUNTIME_IMPORTS_PREFIX + "%",),
        ).fetchall()
    except Exception as exc:
        return {"contract": EVIDENCE_SOURCES_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
    for row in rows:
        try:
            record = json.loads(row["value"])
        except (TypeError, ValueError):
            continue
        record.setdefault("service", str(row["key"])[len(RUNTIME_IMPORTS_PREFIX):])
        records.append(record)
    records.extend(dict(r) for r in extra_records)
    union: dict[str, list[str]] = {}
    for record in records:
        for module in record.get("modules") or ():
            union.setdefault(module, []).append(record.get("service", "?"))
    return {
        "contract": EVIDENCE_SOURCES_CONTRACT,
        "services": sorted(records, key=lambda r: (str(r.get("service")), int(r.get("pid") or 0))),
        "module_union": {m: sorted(set(s)) for m, s in sorted(union.items())},
        "module_count": len(union),
    }


def _percentiles(values: list[float]) -> dict:
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"count": 0, "median": None, "p90": None, "mean": None}
    def pick(q: float) -> float:
        idx = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
        return values[idx]
    return {
        "count": len(values),
        "median": round(pick(0.5), 4),
        "p90": round(pick(0.9), 4),
        "mean": round(sum(values) / len(values), 4),
    }


def performance_payload(repo, campaign_id: str, *, window_hours: float = 24.0) -> dict:
    try:
        sim_rows = repo.conn.execute(
            "SELECT j.n n, a.wall_seconds wall, a.user_cpu_seconds ucpu, a.system_cpu_seconds scpu, "
            "a.peak_pss_bytes pss, a.peak_rss_bytes rss, a.finished_utc finished "
            "FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=? AND j.kind='simulate' AND a.exit_code=0 AND a.finished_utc IS NOT NULL",
            (str(campaign_id),),
        ).fetchall()
        ana_rows = repo.conn.execute(
            "SELECT q.n n, a.wall_seconds wall, a.peak_pss_bytes pss, a.peak_rss_bytes rss, "
            "a.finished_utc finished "
            "FROM analysis_attempts a JOIN analysis_queue q "
            "ON q.campaign_id=a.campaign_id AND q.input_artifact=a.input_artifact "
            "AND q.analysis_version=a.analysis_version "
            "WHERE a.campaign_id=? AND a.exit_code=0 AND a.finished_utc IS NOT NULL",
            (str(campaign_id),),
        ).fetchall()
        telemetry = repo.conn.execute(
            "SELECT sampled_utc, cpu_percent, memory_used_bytes, active_simulations, active_analyses "
            "FROM resource_telemetry WHERE phase='runtime' "
            "ORDER BY sample_id DESC LIMIT 900",
        ).fetchall()
    except Exception as exc:
        return {"contract": EVIDENCE_SOURCES_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}

    def by_n(rows, fields):
        groups: dict[int, dict[str, list]] = {}
        for row in rows:
            n = int(row["n"] or 0)
            slot = groups.setdefault(n, {f: [] for f in fields})
            for f in fields:
                value = row[f]
                if value is not None:
                    slot[f].append(float(value))
        return {
            str(n): {f: _percentiles(vals) for f, vals in slots.items()} | {"completed": len(slots[fields[0]])}
            for n, slots in sorted(groups.items())
        }

    def within_window(rows):
        cutoff = time.time() - window_hours * 3600.0
        kept = []
        for row in rows:
            stamp = str(row["finished"] or "")
            try:
                epoch = time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            except ValueError:
                continue
            if epoch >= cutoff:
                kept.append(row)
        return kept

    def hourly(rows):
        buckets: dict[str, int] = {}
        for row in within_window(rows):
            stamp = str(row["finished"] or "")
            buckets[stamp[:13] + ":00Z"] = buckets.get(stamp[:13] + ":00Z", 0) + 1
        return dict(sorted(buckets.items()))

    sim_hourly = hourly(sim_rows)
    ana_hourly = hourly(ana_rows)
    finished = sorted(str(r["finished"])[:19]
                      for r in within_window(sim_rows) + within_window(ana_rows)
                      if r["finished"])
    span_hours = None
    if len(finished) >= 2:
        try:
            first = time.mktime(time.strptime(finished[0], "%Y-%m-%dT%H:%M:%S"))
            last = time.mktime(time.strptime(finished[-1], "%Y-%m-%dT%H:%M:%S"))
            span_hours = round(max(0.0, last - first) / 3600.0, 2)
        except ValueError:
            span_hours = None
    effective_window_hours = min(window_hours, span_hours) if span_hours is not None else window_hours
    hours = max(1.0 / 60.0, effective_window_hours)
    occupancy = [
        {"utc": str(t["sampled_utc"]), "cpu_percent": t["cpu_percent"],
         "memory_used_bytes": t["memory_used_bytes"],
         "active_simulations": t["active_simulations"], "active_analyses": t["active_analyses"]}
        for t in reversed(list(telemetry))
    ]
    return {
        "contract": EVIDENCE_SOURCES_CONTRACT,
        "campaign_id": str(campaign_id),
        "window_hours": window_hours,
        "work_span_hours": span_hours,
        "effective_window_hours": round(effective_window_hours, 2),
        "window_note": (
            "effective_window_hours is the span of completed work when the campaign "
            "is younger than window_hours; per-hour rates and any comparison to a "
            "baseline must use it"
        ),
        "simulation": {
            "completed_total": len(sim_rows),
            "completed_per_hour_window": round(sum(sim_hourly.values()) / hours, 3),
            "hourly": sim_hourly,
            "by_n": by_n(sim_rows, ("wall", "ucpu", "scpu", "pss", "rss")),
        },
        "analysis": {
            "completed_total": len(ana_rows),
            "completed_per_hour_window": round(sum(ana_hourly.values()) / hours, 3),
            "hourly": ana_hourly,
            "by_n": by_n(ana_rows, ("wall", "pss", "rss")),
        },
        "occupancy_series": occupancy,
        "occupancy_samples": len(occupancy),
    }


def schema_payload(repo) -> dict:
    try:
        columns = repo.conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default, ordinal_position "
            "FROM information_schema.columns WHERE table_schema='public' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        indexes = repo.conn.execute(
            "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' "
            "ORDER BY tablename, indexname"
        ).fetchall()
        constraints = repo.conn.execute(
            "SELECT conrelid::regclass::text table_name, conname, pg_get_constraintdef(oid) definition "
            "FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1,2"
        ).fetchall()
        migrations = []
        try:
            migrations = [dict(r) for r in repo.conn.execute(
                "SELECT * FROM schema_migrations ORDER BY 1").fetchall()]
        except Exception:
            pass
    except Exception as exc:
        return {"contract": EVIDENCE_SOURCES_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
    tables: dict[str, dict] = {}
    for row in columns:
        table = tables.setdefault(str(row["table_name"]), {"columns": [], "indexes": [], "constraints": []})
        table["columns"].append({
            "name": row["column_name"], "type": row["data_type"],
            "nullable": row["is_nullable"] == "YES", "default": row["column_default"],
        })
    for row in indexes:
        tables.setdefault(str(row["tablename"]), {"columns": [], "indexes": [], "constraints": []})
        tables[str(row["tablename"])]["indexes"].append({"name": row["indexname"], "definition": row["indexdef"]})
    for row in constraints:
        name = str(row["table_name"]).strip('"')
        tables.setdefault(name, {"columns": [], "indexes": [], "constraints": []})
        tables[name]["constraints"].append({"name": row["conname"], "definition": row["definition"]})
    return {
        "contract": EVIDENCE_SOURCES_CONTRACT,
        "table_count": len(tables),
        "tables": tables,
        "migrations_applied": migrations,
    }


def stranded_payload(repo, campaign_id: str, candidate_ids, *, limit: int = 40) -> dict:
    out = {"contract": EVIDENCE_SOURCES_CONTRACT, "campaign_id": str(campaign_id), "candidates": []}
    try:
        out["deferred_analyses"] = [dict(r) for r in repo.conn.execute(
            "SELECT candidate_id,n,status,attempts,next_attempt_utc,error_class,error,"
            "memory_reservation_bytes,updated_utc FROM analysis_queue "
            "WHERE campaign_id=? AND status='queued' AND next_attempt_utc IS NOT NULL "
            "ORDER BY next_attempt_utc LIMIT 200", (str(campaign_id),)).fetchall()]
        out["memory_admission_refusals_recent"] = [dict(r) for r in repo.conn.execute(
            "SELECT event_id,created_utc,payload_json FROM events WHERE topic='memory_admission_refused' "
            "ORDER BY event_id DESC LIMIT 100").fetchall()]
    except Exception as exc:
        out["analysis_lane_error"] = f"{type(exc).__name__}: {exc}"
    for candidate_id in list(candidate_ids)[:limit]:
        entry = {"candidate_id": str(candidate_id)}
        try:
            entry["engine_decisions"] = repo.engine_decisions(str(campaign_id), str(candidate_id))
        except Exception as exc:
            entry["decisions_error"] = f"{type(exc).__name__}: {exc}"
        try:
            entry["state_history"] = [dict(r) for r in repo.candidate_state_history(str(campaign_id), str(candidate_id))]
        except Exception as exc:
            entry["state_history_error"] = f"{type(exc).__name__}: {exc}"
        try:
            entry["jobs"] = [dict(r) for r in repo.conn.execute(
                "SELECT job_id,kind,stage,n,seed,status,attempts,lease_owner,lease_expires_utc,"
                "requested_by,created_utc,updated_utc,error FROM jobs "
                "WHERE campaign_id=? AND candidate_id=? ORDER BY created_utc",
                (str(campaign_id), str(candidate_id))).fetchall()]
            entry["analysis_queue"] = [dict(r) for r in repo.conn.execute(
                "SELECT * FROM analysis_queue WHERE campaign_id=? AND candidate_id=? ORDER BY 1",
                (str(campaign_id), str(candidate_id))).fetchall()]
        except Exception as exc:
            entry["jobs_error"] = f"{type(exc).__name__}: {exc}"
        out["candidates"].append(entry)
    return out


def supervisor_log_path(var: Path) -> Path:
    return Path(var) / "log" / SUPERVISOR_LOG_NAME


def supervisor_log_tail(var: Path, *, lines: int = 2000) -> str:
    path = supervisor_log_path(var)
    previous = path.with_suffix(path.suffix + ".1")
    if not path.is_file() and not previous.is_file():
        return f"no supervisor log at {path}; the supervisor tees its stdout there\n"
    collected: list[str] = []
    for source in (previous, path):
        if not source.is_file():
            continue
        try:
            with open(source, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                block = min(size, max(65536, lines * 200))
                handle.seek(size - block)
                collected.extend(handle.read().decode("utf-8", "replace").splitlines())
        except OSError as exc:
            return f"supervisor log unreadable: {exc}\n"
    return "\n".join(collected[-lines:]) + "\n"


class TeeStdout:
    def __init__(self, stream, path: Path, *, max_bytes: int | None = None):
        from graph_scale_dynamics.observability.console_log import LineTee, for_path
        self.stream = stream
        self.path = Path(path)
        self.log = for_path(self.path)
        if max_bytes is not None:
            self.log.max_bytes = int(max_bytes)
        self._lines = LineTee(self.log)

    def write(self, text):
        self.stream.write(text)
        try:
            self._lines.feed(text if isinstance(text, str) else bytes(text).decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self):
        self.stream.flush()

    def fileno(self):
        return self.stream.fileno()

    def isatty(self):
        return self.stream.isatty()

    def __getattr__(self, name):
        return getattr(self.stream, name)
