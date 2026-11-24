from __future__ import annotations

import platform
import time
from pathlib import Path

from graph_scale_dynamics.operations import dev_mode as _dev_mode
from graph_scale_dynamics.calibration import (
    CalibrationGateError, ensure_calibration, load_table, resolve_table, science_fingerprint,
    write_table,
)

__all__ = ["CalibrationGateError", "ensure_probe_calibration", "science_fingerprint",
           "pipeline_trial_stale", "record_pipeline_trial", "table_in_force"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pipeline_trial_stale(document: dict | None, suite_fingerprint: str | None) -> str | None:
    if not isinstance(document, dict):
        return "no calibration table"
    trial = document.get("pipeline_trial")
    if not isinstance(trial, dict) or not trial.get("rows"):
        return "no pipeline trial recorded"
    if str(trial.get("suite_fingerprint")) != str(suite_fingerprint):
        return (f"pipeline trial ran under suite {trial.get('suite_fingerprint')}, "
                f"runtime suite is {suite_fingerprint}")
    if trial.get("host") != platform.node():
        return f"pipeline trial ran on {trial.get('host') or 'another host'}; this pipeline is unverified"
    return None


def record_pipeline_trial(document: dict, section: dict, *, suite_fingerprint: str | None,
                          build_number: int) -> dict:
    document["pipeline_trial"] = dict(section, generated_utc=_now(), host=platform.node(),
                                      suite_fingerprint=suite_fingerprint,
                                      build_number=int(build_number),
                                      science_fingerprint=science_fingerprint())
    return document


def ensure_probe_calibration(var: Path, *, build_number: int, log=print,
                             dev_mode: bool | None = None, root: Path | None = None,
                             workers: int | None = None, profile: str | None = None) -> dict:
    var = Path(var)
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    if dev_mode is None:
        dev_mode = _dev_mode.enabled()
    status = ensure_calibration(root, var, log=log, dev_mode=dev_mode, workers=workers,
                                profile=profile)
    path = Path(status["path"])
    document = load_table(path)
    if document is None:
        raise CalibrationGateError(f"the calibration table at {path} could not be read back after "
                                   "ensure_calibration; it is left as it is")

    reason = pipeline_trial_stale(document, status.get("suite_fingerprint"))
    if reason is not None:
        log(f"calibration gate: {reason}; running the pipeline trial against the release anchors")
        from graph_scale_dynamics.services.calibration_core import run_probes

        probes = run_probes(seeds=2)
        record_pipeline_trial(document, probes, suite_fingerprint=status.get("suite_fingerprint"),
                              build_number=build_number)
        for row in probes["rows"]:
            log(f"calibration gate: [{row['status']:^7}] {row['anchor']}: "
                f"{row['channel']} measured "
                f"{'refused' if row['measured'] is None else format(row['measured'], '.4f')} "
                f"(theory {row['theory']:.4f}, tol {row['tolerance']})")
        status["ran_pipeline_trial"] = True
    else:
        log("calibration gate: pipeline trial current for this suite and host")
        status["ran_pipeline_trial"] = False
    if status["ran_pipeline_trial"]:
        write_table(document, path)

    trial = document.get("pipeline_trial") or {}
    status["pipeline_passed"] = bool(trial.get("pipeline_passed"))
    status["probes_passed"] = status["pipeline_passed"]
    if not status["pipeline_passed"]:
        failures = "; ".join(trial.get("stage_failures") or ["unknown failure"])
        message = (f"pipeline trial FAILED against known anchors: {failures}. A runtime whose "
                   "instruments cannot read known targets must not collect data.")
        if not dev_mode:
            raise CalibrationGateError(message)
        log(f"calibration gate: {message}")
        log("calibration gate: GSD_DEV_MODE=1 downgrades this refusal to a warning; nothing "
            "collected under it is certifiable")
    log(f"calibration gate: table {path} in force"
        f"{'' if status.get('authoritative') else ' (NOT authoritative)'}; "
        f"verdict {status.get('verdict')}; {status.get('reused', 0)} cells reused, "
        f"{status.get('computed', 0)} computed")
    return status


def table_in_force(root: Path, var: Path) -> tuple[Path, dict | None, str]:
    return resolve_table(Path(root), Path(var))
