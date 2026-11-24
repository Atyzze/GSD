from __future__ import annotations

import argparse
import os
import time


from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.observability.ladder_history import LadderRecorder
from graph_scale_dynamics.observability.host_resources import (cpu_percent_sampled, stop_btop_sidecar,
                                                                 system_resources)
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.observability.resource_telemetry import (
    RESOURCE_TELEMETRY_CONTRACT, cpu_frequency_mhz, interval_energy_j,
    process_cpu_seconds, gsd_cpu_percent, sample_quality,
)
from graph_scale_dynamics.observability.telemetry_aggregation import TelemetryAggregator
from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.domain.version import BUILD_NUMBER, environment_fingerprint, runtime_fingerprint


def _active_work(repo: Repo, campaign_id: str) -> tuple[list[dict], int, int]:
    simulations = [dict(row) for row in repo.conn.execute(
        "SELECT campaign_id,job_id,candidate_id,kind,stage,n,seed,lease_owner,lease_generation,requested_by FROM jobs "
        "WHERE status='leased' ORDER BY campaign_id,job_id"
    ).fetchall()]
    analyses = [dict(row) for row in repo.conn.execute(
        "SELECT campaign_id,input_artifact,candidate_id,n,seed,lease_owner,producer_job FROM analysis_queue "
        "WHERE analysis_version=? AND status='leased' ORDER BY campaign_id,input_artifact",
        (ANALYSIS_VERSION,),
    ).fetchall()]
    auxiliary = [dict(row) for row in repo.conn.execute(
        "SELECT campaign_id,auxiliary_attempt_id,candidate_id,work_kind,worker,child_pid,status "
        "FROM auxiliary_attempts WHERE status IN ('submitted','running') "
        "ORDER BY campaign_id,auxiliary_attempt_id"
    ).fetchall()]
    work: list[dict] = []
    for row in simulations:
        work.append({
            "type": "simulation", "work_id": row.get("job_id"),
            "campaign_id": row.get("campaign_id"), "candidate_id": row.get("candidate_id"), "n": row.get("n"),
            "seed": row.get("seed"), "owner": row.get("lease_owner"),
            "stage": row.get("stage"), "requested_by": row.get("requested_by"),
            "lease_generation": row.get("lease_generation"),
        })
    for row in analyses:
        work.append({
            "type": "analysis", "work_id": row.get("input_artifact"),
            "campaign_id": row.get("campaign_id"), "candidate_id": row.get("candidate_id"), "n": row.get("n"),
            "seed": row.get("seed"), "owner": row.get("lease_owner"),
            "producer_job": row.get("producer_job"),
        })
    for row in auxiliary:
        work.append({
            "type": str(row.get("work_kind") or "auxiliary"),
            "work_id": row.get("auxiliary_attempt_id"),
            "campaign_id": row.get("campaign_id"),
            "candidate_id": row.get("candidate_id"),
            "n": None, "seed": None,
            "owner": row.get("worker") or (f"pid:{row.get('child_pid')}" if row.get("child_pid") else None),
            "status": row.get("status"),
        })
    return work, len(simulations), len(analyses)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--var", default="var")
    parser.add_argument("--poll", type=float, default=ticks(1))
    parser.add_argument("--baseline-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    poll = max(0.5, float(args.poll))
    baseline_seconds = max(0.0, float(args.baseline_seconds))
    repo = Repo(args.db)
    service = f"telemetry-{os.getpid()}"
    log = Log(args.var, service)
    aggregator = TelemetryAggregator()
    started = time.monotonic()
    previous_at: float | None = None
    previous_watts: float | None = None
    previous_gsd_cpu: float | None = None
    cpu_percent_sampled()
    log.write("start", contract=RESOURCE_TELEMETRY_CONTRACT, poll_seconds=poll,
              baseline_seconds=baseline_seconds)
    ladder = LadderRecorder()
    try:
        while True:
            now_mono = time.monotonic()
            elapsed = None if previous_at is None else max(0.0, now_mono - previous_at)
            resources = system_resources()
            work, simulations, analyses = _active_work(repo, args.campaign)
            since_start = max(0.0, now_mono - started)
            phase = "baseline" if since_start < baseline_seconds else (
                "runtime" if work else "idle"
            )

            gsd_cpu_total = process_cpu_seconds()
            gsd_pct = gsd_cpu_percent(previous_gsd_cpu, gsd_cpu_total, elapsed)
            host_pct_raw = resources.get("cpu_percent")
            host_pct = None if host_pct_raw is None else float(host_pct_raw)
            external_pct = None
            if host_pct is not None and gsd_pct is not None:
                external_pct = max(0.0, min(100.0, host_pct - gsd_pct))

            watts_raw = resources.get("cpu_power_watts")
            watts = None if watts_raw is None else float(watts_raw)
            energy = interval_energy_j(previous_watts, watts, elapsed)
            quality = sample_quality(
                watts=watts, phase=phase,
                external_cpu_percent_estimate=external_pct,
            )
            power_thermal_disabled = os.environ.get("GSD_DISABLE_POWER_TELEMETRY", "").strip().lower() in {"1", "true", "yes", "on"}
            source = {
                "power_source": resources.get("cpu_power_source"),
                "power_detail": resources.get("cpu_power_detail"),
                "temperature_source": resources.get("cpu_temperature_source"),
                "temperature_path": resources.get("cpu_temperature_path"),
                "power_thermal_mode": "operator_disabled" if power_thermal_disabled else "auto",
                "gsd_cpu_accounting": "process-cmdline-delta-v1",
                "external_cpu_estimate": "host_cpu_percent_minus_gsd_process_cpu_percent",
            }
            active_slot_raw = repo.get_flag("compute_active_slots")
            active_slot_limit = None if active_slot_raw in (None, "") else int(active_slot_raw)
            governor_phase = repo.get_flag("resource_governor_phase") or ("baseline" if phase == "baseline" else "unmanaged")
            calibration_raw = repo.get_flag("resource_calibration_id")
            calibration_id = None if calibration_raw in (None, "") else int(calibration_raw)
            durable_row = aggregator.add({
                "campaign_id": args.campaign,
                "telemetry_contract": RESOURCE_TELEMETRY_CONTRACT,
                "build_number": BUILD_NUMBER,
                "runtime_fingerprint": runtime_fingerprint(),
                "environment_fingerprint": environment_fingerprint(),
                "sampled_utc": utc_now(),
                "phase": phase,
                "interval_seconds": elapsed,
                "cpu_percent": host_pct,
                "gsd_cpu_percent": gsd_pct,
                "external_cpu_percent_estimate": external_pct,
                "cpu_package_watts": watts,
                "cpu_power_limit_watts": resources.get("cpu_power_limit_watts"),
                "cpu_temperature_celsius": resources.get("cpu_temperature_celsius"),
                "cpu_frequency_mhz": cpu_frequency_mhz(),
                "memory_total_bytes": resources.get("memory_total_bytes"),
                "memory_used_bytes": resources.get("memory_used_bytes"),
                "memory_free_bytes": resources.get("memory_free_bytes"),
                "memory_bandwidth": resources.get("memory_bandwidth"),
                "active_simulations": simulations,
                "active_analyses": analyses,
                "active_work": work,
                "quality": quality,
                "source": source,
                "interval_energy_j": energy,
                "active_slot_limit": active_slot_limit,
                "governor_phase": governor_phase,
                "calibration_id": calibration_id,
            })
            if durable_row is not None:
                repo.record_resource_telemetry(durable_row)
            if phase == "baseline" or quality not in {"clean", "baseline_observation"}:
                log.write("sample", phase=phase, watts=watts, cpu_percent=host_pct,
                          gsd_cpu_percent=gsd_pct, external_cpu_percent=external_pct,
                          active_simulations=simulations, active_analyses=analyses,
                          quality=quality)
            repo.heartbeat(service, {
                "contract": RESOURCE_TELEMETRY_CONTRACT,
                "phase": phase,
                "watts": watts,
                "quality": quality,
                "active_simulations": simulations,
                "active_analyses": analyses,
            })
            previous_at = now_mono
            previous_watts = watts
            previous_gsd_cpu = gsd_cpu_total
            try:
                ladder.maybe_record(repo, args.campaign, now_mono)
            except Exception as exc:
                try:
                    repo.conn.rollback_if_open()
                except Exception:
                    pass
                log.write("ladder_snapshot_failed", error=str(exc)[:200])
            if not repo.fleet_has_work(ANALYSIS_VERSION) and phase != "baseline":
                tail = aggregator.drain()
                if tail is not None:
                    repo.record_resource_telemetry(tail)
                log.write("exit", reason="fleet has no remaining work")
                return 0
            time.sleep(poll)
    finally:
        try:
            tail = aggregator.drain()
            if tail is not None:
                repo.record_resource_telemetry(tail)
        except Exception:
            pass
        try:
            stop_btop_sidecar()
        finally:
            log.close()
            repo.close()


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
