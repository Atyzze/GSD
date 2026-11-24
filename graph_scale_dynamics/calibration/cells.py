from __future__ import annotations

import math
import os
import platform
import time
from pathlib import Path

from graph_scale_dynamics.calibration.contract import CHANNEL_VALUE_KEYS, CHANNELS

STATUS_OK = "ok"
STATUS_FAILED = "failed"


def cell_key(family: str, parameter, seed: int) -> str:
    return f"{family}:{parameter}:{int(seed)}"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def suite_families(names=None) -> list[dict]:
    from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES
    from graph_scale_dynamics.measurements.calibration import CALIBRATION_FAMILIES

    by_name = {f["name"]: f for f in CALIBRATION_FAMILIES}
    selected = list(names) if names else list(SUITE_FAMILIES)
    missing = [n for n in selected if n not in by_name]
    if missing:
        raise KeyError(f"unknown calibration families: {missing}")
    return [by_name[n] for n in selected]


def family_ladder(family: dict, max_nodes: int | None = None) -> list[dict]:
    from graph_scale_dynamics.calibration.contract import MAX_NODES
    from graph_scale_dynamics.measurements.calibration import family_rung_size

    ceiling = MAX_NODES if max_nodes is None else min(int(max_nodes), MAX_NODES)
    rungs = []
    for parameter in family["ladder"]:
        n = int(family_rung_size(family, parameter))
        if n > ceiling:
            continue
        rungs.append({"parameter": parameter, "n": n})
    return rungs


def extension_ladder(family: dict) -> list[dict]:
    from graph_scale_dynamics.calibration.contract import LADDER_EXTENSIONS, MAX_NODES
    from graph_scale_dynamics.measurements.calibration import family_rung_size

    rungs = [{"parameter": p, "n": int(family_rung_size(family, p)), "extension": True}
             for p in LADDER_EXTENSIONS.get(family["name"], ())]
    return [r for r in rungs if r["n"] <= MAX_NODES]


def plan_extension_cells(families: list[dict], *, seeds: int) -> list[dict]:
    plan = [{"key": cell_key(f["name"], r["parameter"], s), "family": f["name"],
             "parameter": r["parameter"], "n": r["n"], "seed": int(s), "extension": True}
            for f in families for r in extension_ladder(f) for s in range(int(seeds))]
    plan.sort(key=lambda c: (c["n"], c["family"], c["seed"]))
    return plan


def plan_cells(families: list[dict], *, seeds: int, max_nodes: int | None = None) -> list[dict]:
    plan = []
    for family in families:
        for rung in family_ladder(family, max_nodes):
            for seed in range(int(seeds)):
                plan.append({"key": cell_key(family["name"], rung["parameter"], seed),
                             "family": family["name"], "parameter": rung["parameter"],
                             "n": rung["n"], "seed": int(seed)})
    plan.sort(key=lambda c: (c["n"], c["family"], c["seed"]))
    return plan


def graph_varies_per_seed(family: dict) -> bool:
    return bool(family.get("graph_varies_per_seed")) and callable(family.get("build_seeded"))


def build_graph(family: dict, parameter, seed: int):
    if graph_varies_per_seed(family):
        return family["build_seeded"](parameter, int(seed))
    return family["build"](parameter)


def measure_cell(family_name: str, parameter, seed: int, *, cell_fingerprint: str,
                 science_fingerprint: str) -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements.estimators import _measure_graph

    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

    family = suite_families([family_name])[0]
    started = time.monotonic()
    record = {
        "family": family_name, "parameter": parameter, "seed": int(seed), "analysis": ANALYSIS_VERSION,
        "cell_fingerprint": cell_fingerprint, "science_fingerprint": science_fingerprint,
        "graph_varies_per_seed": graph_varies_per_seed(family),
        "computed_utc": _utc(), "host": platform.node(),
    }
    try:
        n, edges = build_graph(family, parameter, seed)
        record["n"] = int(n)
        result, _curves = _measure_graph(n, edges, np.random.default_rng(int(seed)),
                                         measure_geometry=True)
        channels = {}
        for channel in CHANNELS:
            entry = result.get(channel)
            value_key = CHANNEL_VALUE_KEYS[channel]
            if isinstance(entry, dict) and entry.get("valid") and _finite(entry.get(value_key)):
                se = entry.get("se")
                channels[channel] = {"valid": True, "value": float(entry[value_key]),
                                     "se": (float(se) if _finite(se) else None),
                                     "reason": None, "refusal": None}
                if _finite(entry.get("measured_se")):
                    channels[channel]["measured_se"] = float(entry["measured_se"])
            else:
                reason = entry.get("reason") if isinstance(entry, dict) else "channel absent"
                refusal = entry.get("refusal") if isinstance(entry, dict) else None
                channels[channel] = {"valid": False, "value": None, "se": None,
                                     "reason": str(reason) if reason else "refused",
                                     "refusal": str(refusal) if refusal else None}
        record["channels"] = channels
        record["component"] = int(result.get("component") or 0)
        reach = result.get("half_volume_radius")
        record["half_volume_radius"] = float(reach) if _finite(reach) else None
        record["status"] = STATUS_OK
        from graph_scale_dynamics.calibration.margins import MARGINS_CONTRACT, margins
        try:
            record["d_s_margins"] = margins(result.get("d_s"), _curves)
        except Exception as exc:  # noqa: BLE001
            record["d_s_margins"] = {"contract": MARGINS_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
        from graph_scale_dynamics.calibration import structure
        if structure.wanted(family, seed):
            record["structure"] = structure.measure(n, edges)
        from graph_scale_dynamics.calibration import start_reading
        if start_reading.wanted(family_name, int(n), seed):
            record["start"] = start_reading.measure(n, edges, seed)
    except Exception as exc:
        record["status"] = STATUS_FAILED
        record["error"] = f"{type(exc).__name__}: {exc}"
        record.setdefault("channels", {})
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    try:
        import resource
        record["peak_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except (ImportError, OSError, ValueError):
        pass
    return record


def measure_the_start_beside(cell: dict) -> dict:
    from graph_scale_dynamics.calibration import start_reading

    family = suite_families([str(cell["family"])])[0]
    try:
        n, edges = build_graph(family, cell["parameter"], cell["seed"])
        block = start_reading.measure(n, edges, cell["seed"])
    except Exception as exc:  # noqa: BLE001
        block = {"contract": start_reading.CONTRACT, "fingerprint": start_reading.fingerprint(),
                 "error": f"{type(exc).__name__}: {exc}"}
    return dict(cell, start=dict(block, measured_beside_utc=_utc()))


def _worker_measure(task: dict) -> dict:
    if isinstance(task.get("its_probes_are_current"), dict):
        return measure_the_start_beside(task["its_probes_are_current"])
    return measure_cell(task["family"], task["parameter"], task["seed"],
                        cell_fingerprint=task["cell_fingerprint"],
                        science_fingerprint=task["science_fingerprint"])


def _worker_init() -> None:
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(name, "1")


CELL_OOM_SCORE_ADJ = 500
_PR_SET_PDEATHSIG = 1


def _cell_process_setup(parent_pid: int | None) -> None:
    try:
        Path("/proc/self/oom_score_adj").write_text(str(CELL_OOM_SCORE_ADJ))
    except OSError:
        pass
    try:
        import ctypes
        import signal
        ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
    except (OSError, AttributeError, ValueError):
        pass
    if parent_pid is not None and os.getppid() != int(parent_pid):
        os._exit(0)


def _cell_process_main(task: dict, conn) -> None:
    _cell_process_setup(task.get("parent_pid"))
    _worker_init()
    try:
        cell = _worker_measure(task)
    except BaseException as exc:  # noqa: BLE001
        cell = {"family": task.get("family"), "parameter": task.get("parameter"), "seed": task.get("seed"),
                "n": task.get("n"), "status": STATUS_FAILED, "error": f"{type(exc).__name__}: {exc}",
                "channels": {}}
    try:
        conn.send(cell)
    finally:
        conn.close()
