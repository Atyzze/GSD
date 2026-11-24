from __future__ import annotations

from graph_scale_dynamics.domain.cadence import TICK_SECONDS, ticks
from tests.support.engines import require_rust_engine
from graph_scale_dynamics.services.api import fleet_snapshots as api_fleet_snapshots


def test_the_engines_and_the_fleet_share_one_tick():
    from graph_scale_dynamics.engine.engine import STOP_CHECK_SECONDS
    assert STOP_CHECK_SECONDS == TICK_SECONDS == 4.0
    gsd_engine_rs = require_rust_engine()
    assert gsd_engine_rs.STOP_CHECK_SECONDS == TICK_SECONDS


def _default_poll(module) -> float:
    import argparse
    captured = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, args=None, namespace=None):
        for action in self._actions:
            if "--poll" in action.option_strings:
                captured["poll"] = action.default
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        module.main([]) if module.main.__code__.co_argcount else module.main()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = real
    return float(captured["poll"])


def test_every_named_interval_is_a_whole_number_of_ticks():
    import main
    from graph_scale_dynamics.artifact_store import resume_state
    from graph_scale_dynamics.operations import volatile_storage
    from graph_scale_dynamics.scheduling import concurrency, memory
    from graph_scale_dynamics.operations import quiet_report
    from graph_scale_dynamics.services.api import campaign_manager
    from graph_scale_dynamics.services.api import main as api_main
    from graph_scale_dynamics.services.worker import main as worker
    from graph_scale_dynamics.services.controller import main as controller
    from graph_scale_dynamics.services.maintenance import main as maintenance
    from graph_scale_dynamics.services.proposer import main as proposer
    from graph_scale_dynamics.services.executor import main as executor
    from graph_scale_dynamics.services.telemetry import main as telemetry
    from graph_scale_dynamics.operations import power_sidecar
    from graph_scale_dynamics.observability import log
    intervals = {
        "a stopped child's grace": resume_state.STOP_GRACE_SECONDS,
        "the prediction cache": memory.PREDICTION_PROFILE_CACHE_SECONDS,
        "the measured-peaks cache": memory.MEASURED_PEAKS_CACHE_SECONDS,
        "the scratch-usage cache": volatile_storage._SCRATCH_USAGE_SECONDS,
        "the ramp's tick": main.RAMP_TICK_SECONDS,
        "the ramp's hold between steps": concurrency.STEP_HOLD_SECONDS,
        "a simulation lease": float(worker.SIM_LEASE_SECONDS),
        "a simulation lease's renewal": float(worker.SIM_LEASE_RENEW_SECONDS),
        "the dashboard overview cache": api_main.DASHBOARD_OVERVIEW_TTL_SECONDS,
        "the paused dashboard overview cache": api_main.DASHBOARD_OVERVIEW_TTL_PAUSED_SECONDS,
        "the landscape cache": api_main.DASHBOARD_LANDSCAPE_TTL_SECONDS,
        "the heavy dashboard sections' cache": api_main.DASHBOARD_HEAVY_TTL_SECONDS,
        "the execution-count cache": api_fleet_snapshots._EXECUTION_COUNT_SECONDS,
        "the Campaigns overview cache": campaign_manager._ACTIVE_TTL,
        "a quiet report's drain timeout": quiet_report.DRAIN_TIMEOUT_SECONDS,
        "a quiet report's cycle timeout": quiet_report.REPORT_TIMEOUT_SECONDS,
        "the controller's idle rest ceiling": controller.IDLE_REST_CEILING_SECONDS,
        "the checkpoint sweep's rest after work": maintenance.CHECKPOINT_SWEEP_FLOOR_SECONDS,
        "the checkpoint sweep's idle rest ceiling": maintenance.CHECKPOINT_SWEEP_CEILING_SECONDS,
        "the CPU power publication": power_sidecar.PUBLISH_INTERVAL_SECONDS,
        "the service log flush": log._DEFAULT_FLUSH_SECONDS,
        **{f"the {name} service's idle poll": _default_poll(module)
           for name, module in (("controller", controller), ("maintenance", maintenance),
                                ("proposer", proposer), ("executor", executor),
                                ("telemetry", telemetry))},
    }
    off = {name: seconds for name, seconds in intervals.items() if seconds <= 0 or seconds % TICK_SECONDS}
    assert not off, f"not a whole number of {TICK_SECONDS:g} s ticks: {off}"
    assert resume_state.STOP_GRACE_SECONDS == ticks(30), (
        "a stopped seed is given the time its save takes: 19 s for the largest, densest state of 65,536 nodes, 38 s "
        "with its last whole chunk beside it, where the 8 s before 840 ended 5 of 14 seeds of study 172 unsaved")
    assert resume_state.STOP_GRACE_SECONDS < float(worker.SIM_LEASE_SECONDS), "and its lease outlasts that wait"
