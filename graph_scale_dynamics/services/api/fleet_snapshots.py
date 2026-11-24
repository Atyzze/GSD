from __future__ import annotations

import psutil
import threading
import time
from datetime import datetime, timezone

from graph_scale_dynamics import PROJECT_ROOT
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.operations.compute_ecology import memory_floor_verdict, room_reading
from graph_scale_dynamics.operations.volatile_storage import ram_backed_scratch_bytes
from graph_scale_dynamics.services.api.host import _note_swallowed, _service_process_sample


ROOT = PROJECT_ROOT


_PG_STORAGE_SAMPLE_LOCK = threading.Lock()
_PG_STORAGE_SAMPLE: tuple[float, int, int, int, int] | None = None
_PG_IO_DETAIL_SAMPLE: tuple[float, dict[str, int]] | None = None
_PG_TABLE_CHURN_SAMPLE: tuple[float, dict[str, tuple[int, int, int, int, int, int]]] | None = None


_EXECUTION_COUNT_CACHE: dict[str, object] = {"at": 0.0, "value": {}}
_EXECUTION_COUNT_SECONDS = ticks(8)


def _execution_counts(repo) -> dict:
    now = time.monotonic()
    if now - float(_EXECUTION_COUNT_CACHE["at"]) < _EXECUTION_COUNT_SECONDS:
        return dict(_EXECUTION_COUNT_CACHE["value"])  # type: ignore[arg-type]
    try:
        value = {str(row["campaign_id"]): {"simulation_executions": int(row["executions"] or 0)}
                 for row in repo.conn.execute(
                     "SELECT j.campaign_id, COUNT(*) AS executions FROM attempts a "
                     "JOIN jobs j ON j.job_id=a.job_id WHERE j.kind='simulate' GROUP BY j.campaign_id")}
    except Exception as exc:
        _note_swallowed("_execution_counts", exc)
        return dict(_EXECUTION_COUNT_CACHE["value"])  # type: ignore[arg-type]
    _EXECUTION_COUNT_CACHE["at"] = now
    _EXECUTION_COUNT_CACHE["value"] = value
    return dict(value)


def _analysis_runnable_snapshot(repo: Repo, campaign_id: str, analysis_version: str) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        raw = repo.conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE status='queued' AND (next_attempt_utc IS NULL OR next_attempt_utc<=?)) claimable,"
            "COUNT(*) FILTER (WHERE status='queued' AND next_attempt_utc>?) deferred,"
            "COUNT(*) FILTER (WHERE status='leased') leased,"
            "COUNT(*) FILTER (WHERE status='queued' AND COALESCE(error_class,'') LIKE 'memory%') memory_deferred "
            "FROM analysis_queue WHERE campaign_id=? AND analysis_version=?",
            (now, now, str(campaign_id), str(analysis_version)),
        ).fetchone()
        rebuild = repo.conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE status='queued' AND (next_attempt_utc IS NULL OR next_attempt_utc<=?)) claimable,"
            "COUNT(*) FILTER (WHERE status='queued' AND next_attempt_utc>?) deferred,"
            "COUNT(*) FILTER (WHERE status='leased') leased "
            "FROM candidate_evidence_rebuilds WHERE campaign_id=? AND analysis_version=?",
            (now, now, str(campaign_id), str(analysis_version)),
        ).fetchone()
        return {
            "claimable": int(raw["claimable"] or 0) + int(rebuild["claimable"] or 0),
            "deferred": int(raw["deferred"] or 0) + int(rebuild["deferred"] or 0),
            "leased": int(raw["leased"] or 0) + int(rebuild["leased"] or 0),
            "memory_deferred": int(raw["memory_deferred"] or 0),
        }
    except Exception as exc:
        _note_swallowed("_analysis_runnable_snapshot", exc)
        return {"claimable": 0, "deferred": 0, "leased": 0, "memory_deferred": 0}


def _governor_capacity_snapshot(repo: Repo, campaign_id: str, scheduler_slots: int) -> dict:
    configured = int(repo.get_flag("compute_total_slots", str(scheduler_slots)) or scheduler_slots)
    exposed_raw = repo.get_flag("compute_active_slots")
    exposed = int(exposed_raw) if exposed_raw not in (None, "") else int(scheduler_slots)
    return {
        "governor_phase": "host_managed",
        "governor_slot_limit": max(0, exposed),
        "scheduler_slot_limit": max(0, int(scheduler_slots)),
        "configured_executor_slots": max(0, configured),
        "safe_max_slots": None,
        "target_slots": None,
        "requested_max_slots": max(0, configured),
        "last_adjustment": None,
        "power_temperature_policy": "observational_only",
        "interpretation": (
            "GSD does not throttle concurrency from CPU package power or temperature; "
            "host CPU/firmware thermal and power management remains authoritative."
        ),
    }


def _postgres_process_tree(repo: Repo) -> tuple[list[int], list[dict]]:
    del repo
    supervisor_path = ROOT / "instance" / "postgres" / "supervisor.pid"
    processes: list[psutil.Process] = []
    try:
        supervisor_pid = int(supervisor_path.read_text(encoding="ascii").strip())
        supervisor = psutil.Process(supervisor_pid)
        processes = supervisor.children(recursive=True)
    except (OSError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
        processes = []

    if not processes:
        root_text = str(ROOT.resolve())
        pgdata_text = str((ROOT / "instance" / "postgres" / "data").resolve())
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                text = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if "postgres" in text.lower() and (pgdata_text in text or root_text in text):
                processes.append(proc)

    def command_text(proc: psutil.Process) -> str:
        try:
            return " ".join(proc.cmdline()).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return ""

    def role(proc: psutil.Process) -> str:
        text = command_text(proc)
        for needle, name in (
            ("checkpointer", "checkpointer"),
            ("background writer", "background writer"),
            ("wal writer", "wal writer"),
            ("walwriter", "wal writer"),
            ("autovacuum", "autovacuum"),
            ("logical replication", "logical replication"),
            ("startup", "startup"),
            ("archiver", "archiver"),
        ):
            if needle in text:
                return name
        if " -d " in f" {text} " or " -d" in text or "postgres -d" in text:
            return "postmaster"
        if "postgres" in text:
            return "client/backend"
        return "namespace child"

    pids: list[int] = []
    counts: dict[str, int] = {}
    for proc in processes:
        try:
            pid = int(proc.pid)
            if pid <= 0 or not proc.is_running():
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        pids.append(pid)
        r = role(proc)
        counts[r] = counts.get(r, 0) + 1
    return sorted(set(pids)), [
        {"role": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (item[0] != "postmaster", item[0]))
    ]


def _database_io_snapshot(repo: Repo) -> dict:
    global _PG_STORAGE_SAMPLE, _PG_IO_DETAIL_SAMPLE, _PG_TABLE_CHURN_SAMPLE
    pids, process_roles = _postgres_process_tree(repo)
    if not pids:
        return {"pids": [], "process_roles": [], "read_bytes_per_second": None,
                "write_bytes_per_second": None, "status": "unavailable"}
    read = write = 0.0
    ready = 0
    for pid in pids:
        sample = _service_process_sample(pid)
        if sample.get("io_rate_ready"):
            ready += 1
            read += float(sample.get("read_bytes_per_second") or 0.0)
            write += float(sample.get("write_bytes_per_second") or 0.0)
    result = {
        "pids": pids,
        "process_roles": process_roles,
        "read_bytes_per_second": round(read, 1) if ready else None,
        "write_bytes_per_second": round(write, 1) if ready else None,
        "status": "measured" if ready else ("warming" if pids else "unavailable"),
    }
    try:
        dbstat = repo.conn.execute(
            "SELECT temp_files,temp_bytes FROM pg_stat_database WHERE datname=current_database()"
        ).fetchone()
        walstat = repo.conn.execute(
            "SELECT wal_bytes,wal_records,wal_fpi FROM pg_stat_wal"
        ).fetchone()
        io_rows = repo.conn.execute(
            "SELECT backend_type,context,object,"
            "COALESCE(SUM((COALESCE(writes,0)+COALESCE(extends,0))*op_bytes),0) bytes "
            "FROM pg_stat_io WHERE object IN ('relation','temp relation') "
            "GROUP BY backend_type,context,object"
        ).fetchall()
        io_bytes: dict[str, int] = {}
        io_detail: dict[str, int] = {}
        for row in io_rows:
            obj = str(row["object"])
            value = int(row["bytes"] or 0)
            io_bytes[obj] = io_bytes.get(obj, 0) + value
            key = "|".join((str(row.get("backend_type") or "unknown"),
                            str(row.get("context") or "unknown"), obj))
            io_detail[key] = value
        temp_bytes = int((dbstat or {}).get("temp_bytes", 0) or 0)
        temp_files = int((dbstat or {}).get("temp_files", 0) or 0)
        wal_bytes = int((walstat or {}).get("wal_bytes", 0) or 0)
        relation_io_bytes = int(io_bytes.get("relation", 0) or 0)
        temp_relation_io_bytes = int(io_bytes.get("temp relation", 0) or 0)
        now = time.monotonic()
        temp_rate = wal_rate = relation_rate = temp_relation_rate = None
        backend_rates: list[dict] = []
        with _PG_STORAGE_SAMPLE_LOCK:
            prior = _PG_STORAGE_SAMPLE
            if prior is not None:
                then, prior_temp, prior_wal, prior_relation, prior_temp_relation = prior
                elapsed = max(1e-6, now - then)
                temp_rate = max(0.0, temp_bytes - prior_temp) / elapsed
                wal_rate = max(0.0, wal_bytes - prior_wal) / elapsed
                relation_rate = max(0.0, relation_io_bytes - prior_relation) / elapsed
                temp_relation_rate = max(0.0, temp_relation_io_bytes - prior_temp_relation) / elapsed
            _PG_STORAGE_SAMPLE = (
                now, temp_bytes, wal_bytes, relation_io_bytes, temp_relation_io_bytes
            )
            detail_prior = _PG_IO_DETAIL_SAMPLE
            if detail_prior is not None:
                detail_then, previous = detail_prior
                detail_elapsed = max(1e-6, now - detail_then)
                for key, value in io_detail.items():
                    delta = max(0, value - int(previous.get(key, value)))
                    if delta <= 0:
                        continue
                    backend_type, context, obj = key.split("|", 2)
                    backend_rates.append({
                        "backend_type": backend_type, "context": context, "object": obj,
                        "bytes_per_second": round(delta / detail_elapsed, 1),
                    })
            _PG_IO_DETAIL_SAMPLE = (now, io_detail)
        backend_rates.sort(key=lambda row: -float(row["bytes_per_second"]))
        temp_setting = repo.conn.execute("SHOW temp_tablespaces").fetchone()
        temp_name = None
        if temp_setting:
            temp_name = next(iter(dict(temp_setting).values()), None)
        temp_location = None
        if temp_name:
            location_row = repo.conn.execute(
                "SELECT pg_tablespace_location(oid) location FROM pg_tablespace WHERE spcname=?",
                (str(temp_name).split(",", 1)[0].strip(),),
            ).fetchone()
            if location_row:
                temp_location = location_row.get("location")
        result["sql_temp"] = {
            "files": temp_files,
            "bytes": temp_bytes,
            "bytes_per_second": None if temp_rate is None else round(temp_rate, 1),
            "tablespace": temp_name,
            "location": temp_location,
            "expected_volatile": bool(temp_location and str(temp_location).startswith("/dev/shm/")),
        }
        result["wal"] = {
            "bytes": wal_bytes,
            "bytes_per_second": None if wal_rate is None else round(wal_rate, 1),
            "records": int((walstat or {}).get("wal_records", 0) or 0),
            "full_page_images": int((walstat or {}).get("wal_fpi", 0) or 0),
            "compression": "on",
        }
        result["relation_io"] = {
            "permanent_bytes": relation_io_bytes,
            "permanent_bytes_per_second": (
                None if relation_rate is None else round(relation_rate, 1)
            ),
            "temp_relation_bytes": temp_relation_io_bytes,
            "temp_relation_bytes_per_second": (
                None if temp_relation_rate is None else round(temp_relation_rate, 1)
            ),
            "source": "pg_stat_io:writes+extends",
            "by_backend": backend_rates[:12],
        }
        table_rows = repo.conn.execute(
            "SELECT relname,n_tup_ins,n_tup_upd,n_tup_hot_upd,n_tup_del,n_dead_tup,autovacuum_count "
            "FROM pg_stat_user_tables"
        ).fetchall()
        current_tables = {
            str(row["relname"]): (
                int(row.get("n_tup_ins") or 0), int(row.get("n_tup_upd") or 0),
                int(row.get("n_tup_hot_upd") or 0), int(row.get("n_tup_del") or 0),
                int(row.get("n_dead_tup") or 0), int(row.get("autovacuum_count") or 0),
            ) for row in table_rows
        }
        churn: list[dict] = []
        with _PG_STORAGE_SAMPLE_LOCK:
            table_prior = _PG_TABLE_CHURN_SAMPLE
            if table_prior is not None:
                table_then, previous_tables = table_prior
                table_elapsed = max(1e-6, now - table_then)
                for table, vals in current_tables.items():
                    previous = previous_tables.get(table)
                    if previous is None:
                        continue
                    ins = max(0, vals[0] - previous[0]); upd = max(0, vals[1] - previous[1])
                    hot = max(0, vals[2] - previous[2]); dele = max(0, vals[3] - previous[3])
                    mutations = ins + upd + dele
                    if mutations <= 0 and vals[4] <= 0:
                        continue
                    churn.append({
                        "table": table,
                        "mutations_per_second": round(mutations / table_elapsed, 2),
                        "inserts_per_second": round(ins / table_elapsed, 2),
                        "updates_per_second": round(upd / table_elapsed, 2),
                        "deletes_per_second": round(dele / table_elapsed, 2),
                        "hot_update_percent": None if upd <= 0 else round(100.0 * hot / upd, 1),
                        "dead_tuples": vals[4],
                        "autovacuum_runs_in_window": max(0, vals[5] - previous[5]),
                    })
            _PG_TABLE_CHURN_SAMPLE = (now, current_tables)
        churn.sort(key=lambda row: (-float(row["mutations_per_second"]), -int(row["dead_tuples"])))
        result["table_churn"] = {"source": "pg_stat_user_tables", "top": churn[:12]}
    except Exception as exc:
        result["storage_counters_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return result


def _scratch_percent_of_host(resources: dict) -> float | None:
    total = int((resources or {}).get("memory_total_bytes") or 0)
    if total <= 0:
        return None
    try:
        used = int(ram_backed_scratch_bytes())
    except Exception as exc:
        _note_swallowed("_scratch_percent_of_host", exc)
        return None
    if used <= 0:
        return None
    return 100.0 * used / total


def _one_worker_per_core(repo, slots: int, physical: int | None, logical: int | None) -> dict | None:
    return ({"physical": physical, "logical": logical}
            if physical and logical and logical > physical and slots <= physical else None)


def _capacity_diagnosis(*, paused: bool, resources: dict, active_slots: int,
                        scheduler_slots: int, runnable_simulations: int,
                        runnable_analyses: int, blocked_simulations: int,
                        deferred_analyses: int, memory_deferred_analyses: int,
                        stranded_nonterminal: int, nonterminal_observed: int,
                        governor: dict, memory_reservation_percent: float = 0.0,
                        cpu_iowait_percent: float | None = None,
                        scratch_percent: float | None = None, admission: dict | None = None,
                        deferred_simulations: int = 0,
                        supply: dict | None = None,
                        one_worker_per_core: dict | None = None, room: dict | None = None) -> tuple[str, str, str]:
    runnable = max(0, int(runnable_simulations)) + max(0, int(runnable_analyses))
    idle = max(0, int(scheduler_slots) - int(active_slots))
    cpu = float(resources.get("cpu_percent") or 0.0)
    iowait = cpu_iowait_percent
    memory = float(resources.get("memory_load_percent") or 0.0)
    host_write = float(resources.get("disk_write_bytes_per_second") or 0.0)
    host_read = float(resources.get("disk_read_bytes_per_second") or 0.0)
    if paused:
        return "OPERATOR_PAUSED", "operator", "Scientific work is paused; unused CPU and slots are intentional."
    if int(active_slots) > int(scheduler_slots):
        return ("SCHEDULER_SNAPSHOT_LAG", "warning",
                "Live leased work exceeds the last scheduler slot snapshot; capacity data are temporarily inconsistent, so no resource bottleneck is inferred from it.")
    if runnable > 0 and iowait is not None and float(iowait) >= 10.0 and (host_write > 0 or host_read > 0):
        return ("DISK_IO_LIMITED", "warning",
                "Runnable scientific work exists while the host spends substantial CPU time waiting on physical I/O; storage latency/stall is limiting useful throughput.")
    memory_pressed = memory_deferred_analyses > 0 or (runnable > 0 and memory >= 90.0)
    if memory_pressed and scratch_percent is not None and scratch_percent >= 25.0:
        said = room_reading(room)
        return ("MEMORY_LIMITED_BY_SCRATCH", "warning",
                f"Volatile scratch holds {scratch_percent:.0f}% of host RAM. tmpfs pages are "
                "not reclaimable, so that memory is unavailable to the fleet "
                "until retention deletes the files. Check that retention is running "
                "before treating this as insufficient RAM." + (f" {said}" if said else ""))
    floor = memory_floor_verdict(admission, waiting=runnable + memory_deferred_analyses, idle=idle,
                                 slots=scheduler_slots, deferred=deferred_simulations,
                                 reservation_percent=memory_reservation_percent, room=room)
    if floor is not None:
        return floor
    if memory_pressed:
        return ("MEMORY_LIMITED", "warning",
                "Runnable scientific work exists, but measured RAM pressure/admission is preventing additional launches.")
    if runnable > 0:
        material_idle = idle >= max(2, int(max(1, scheduler_slots) * 0.25))
        if idle > 0 and material_idle:
            if cpu >= 90.0:
                return ("HOST_CPU_CONTENTION", "warning",
                        "Host CPU is saturated before all configured executor slots are occupied; logical slot underfill is not sufficient evidence of scheduler failure. Inspect GSD/external CPU attribution and per-job CPU demand first.")
            if blocked_simulations > 0:
                return ("SCHEDULER_LIMITED", "warning",
                        "Runnable simulation work exists but campaign/scheduler allocation is withholding a material share of otherwise idle executor capacity.")
            if runnable_simulations == 0 and runnable_analyses > 0:
                return ("WORK_SUPPLY_STARVED", "warning",
                        "Executor capacity is idle with no simulation work queued; "
                        f"the {runnable_analyses} runnable item(s) are analyses, which "
                        "cannot occupy simulation slots. Upstream proposal/admission "
                        "supply, not scheduler admission, is the constraint.")
            return ("SCHEDULER_UNDERFILL", "warning",
                    "Runnable work exists while a material share of configured executor capacity is idle; worker/scheduler admission is underfilling the fleet.")
        if cpu >= 90.0:
            return ("CPU_LIMITED", "normal",
                    "Runnable work is queued, configured executor capacity is substantially occupied, and host CPU is saturated.")
        if one_worker_per_core:
            cores, threads = one_worker_per_core.get("physical"), one_worker_per_core.get("logical")
            return ("ONE_WORKER_PER_CORE", "normal",
                    f"The fleet runs one worker per physical core unless --workers or GSD_MAX_WORKERS asks for "
                    f"more: {scheduler_slots} slots on {cores} physical cores, each running one chain while its second "
                    f"hardware thread stays free, so host CPU reads about half of {threads} threads ({cpu:.1f}%).")
        return ("EXECUTOR_CONCURRENCY_LIMITED", "warning",
                f"Runnable work is queued and configured executor capacity is substantially occupied, but host CPU is only {cpu:.1f}%; configured executor concurrency, not CPU saturation, is the throughput-scale ceiling.")
    if idle > 0 and runnable == 0 and stranded_nonterminal > 0:
        return ("RECOVERY_BLOCKED", "error",
                "Idle compute exists, but one or more nonterminal candidates own no runnable work and require lifecycle reconciliation.")
    if idle > 0 and runnable == 0 and nonterminal_observed > 0:
        because = str((supply or {}).get("reading") or "")
        expected = bool((supply or {}).get("expected"))
        return ("WORK_SUPPLY_STARVED", "normal" if expected and because else "warning",
                "Idle compute exists but no campaign supplies claimable simulation or analysis "
                "work" + (f": {because}." if because else
                          ". No campaign explains it, which is itself the finding."))
    if runnable == 0 and deferred_analyses > 0:
        return ("DEFERRED_WORK", "normal",
                "No work is claimable at this instant; queued analysis is intentionally sleeping until its retry time.")
    return ("CAPACITY_AVAILABLE", "normal",
            "No runnable scientific work is waiting for additional capacity at this instant.")
