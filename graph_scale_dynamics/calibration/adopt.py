from __future__ import annotations

from graph_scale_dynamics.calibration import cells as CELLS
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import table as T


DEEP_SAMPLE_TO = 4096


def sample_cells(document: dict, per_family: int, *, deep_to: int | None = DEEP_SAMPLE_TO) -> list[tuple[str, dict]]:
    by_family: dict[str, list[tuple[str, dict]]] = {}
    for key, cell in (document.get("cells") or {}).items():
        if cell.get("status") != "ok" or not isinstance(cell.get("n"), int):
            continue
        by_family.setdefault(str(cell.get("family")), []).append((key, cell))
    picked = []
    for family in sorted(by_family):
        rows = sorted(by_family[family], key=lambda item: (item[1]["n"], item[1].get("seed", 0)))
        chosen = rows[:per_family]
        if deep_to is not None:
            deep = [row for row in rows if row[1]["n"] <= deep_to]
            if deep:
                largest = max(row[1]["n"] for row in deep)
                top = min((row for row in deep if row[1]["n"] == largest), key=lambda row: row[1].get("seed", 0))
                if top not in chosen:
                    chosen.append(top)
        picked.extend(chosen)
    return picked


def spot_check(document: dict, *, per_family: int = 1, tolerance: float = 1e-9, repeat: int = 2,
               deep_to: int | None = None) -> dict:
    picked = sample_cells(document, max(1, int(per_family)), deep_to=deep_to)
    science = FP.science_fingerprint()
    report = {"sampled": len(picked), "moved": [], "worst_deviation": 0.0, "worst_host_spread": 0.0}
    for key, cell in picked:
        family = str(cell.get("family"))
        fingerprint = FP.cell_fingerprint(family, None)
        runs = [CELLS.measure_cell(family, cell.get("parameter"), int(cell.get("seed") or 0),
                                   cell_fingerprint=fingerprint, science_fingerprint=science)
                for _ in range(max(1, int(repeat)))]
        problems, deviation, spread = compare(cell, runs, tolerance)
        report["worst_deviation"] = max(report["worst_deviation"], deviation)
        report["worst_host_spread"] = max(report["worst_host_spread"], spread)
        if problems:
            report["moved"].append({"cell": key, "family": family, "problems": problems})
    return report


def relative(a: float, b: float) -> float:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale


def compare(stored: dict, runs: list[dict], tolerance: float) -> tuple[list[str], float, float]:
    problems: list[str] = []
    fresh = runs[0]
    worst_deviation = 0.0
    worst_spread = 0.0
    stored_channels = stored.get("channels") or {}
    fresh_channels = fresh.get("channels") or {}
    if fresh.get("status") != "ok":
        return [f"re-measurement failed: {fresh.get('error') or fresh.get('status')}"], 0.0, 0.0
    if int(stored.get("n") or -1) != int(fresh.get("n") or -2):
        problems.append(f"n changed: {stored.get('n')} -> {fresh.get('n')}")
    was_reach, reach = stored.get("half_volume_radius"), fresh.get("half_volume_radius")
    if (was_reach is None) != (reach is None) or (reach is not None and relative(float(was_reach), float(reach)) > tolerance):
        problems.append(f"half_volume_radius: {was_reach!r} -> {reach!r}")
    for channel in sorted(set(stored_channels) | set(fresh_channels)):
        was = stored_channels.get(channel) or {}
        now = fresh_channels.get(channel) or {}
        if bool(was.get("valid")) != bool(now.get("valid")):
            problems.append(f"{channel}: validity {was.get('valid')} -> {now.get('valid')}")
            continue
        if not was.get("valid"):
            continue
        for field in ("value", "se"):
            old_value, new_value = was.get(field), now.get(field)
            if old_value is None or new_value is None:
                if old_value is not new_value:
                    problems.append(f"{channel}: {field} {old_value!r} -> {new_value!r}")
                continue
            deviation = relative(float(old_value), float(new_value))
            worst_deviation = max(worst_deviation, deviation)
            spread = 0.0
            for other in runs[1:]:
                repeat_value = ((other.get("channels") or {}).get(channel) or {}).get(field)
                if repeat_value is not None:
                    spread = max(spread, relative(float(new_value), float(repeat_value)))
            worst_spread = max(worst_spread, spread)
            if deviation > tolerance and deviation > spread:
                problems.append(
                    f"{channel}: {field} {old_value!r} -> {new_value!r} "
                    f"(relative {deviation:.2e}, this host's run-to-run spread {spread:.2e})")
    return problems, worst_deviation, worst_spread


def restamp_current(document: dict, science: str) -> tuple[int, int]:
    from collections import Counter
    cells = list((document.get("cells") or {}).values())
    usual = {}
    for family, _count in Counter((str(c.get("family")), str(c.get("cell_fingerprint"))) for c in cells).most_common():
        usual.setdefault(family[0], family[1])
    restamped = kept = 0
    analysis = FP.analysis_version(None)
    for cell in cells:
        family = str(cell.get("family"))
        if str(cell.get("cell_fingerprint")) != usual.get(family) or cell.get("analysis") != analysis:
            kept += 1
            continue
        cell["cell_fingerprint"] = FP.cell_fingerprint(family, None)
        cell["science_fingerprint"] = science
        restamped += 1
    return restamped, kept


def verify_and_adopt(document: dict, *, sample: int = 2, tolerance: float = 1e-9,
                     repeat: int = 2, reason: str = "") -> dict:
    current = FP.estimator_fingerprint(None)
    report = {"adopted": False, "refused": [], "sampled": 0, "stale_cells": 0,
              "worst_deviation": 0.0, "worst_host_spread": 0.0,
              "table_fingerprint": document.get("estimator_fingerprint"),
              "runtime_fingerprint": current, "notices": []}
    science = FP.science_fingerprint()
    stale = [key for key, cell in (document.get("cells") or {}).items()
             if cell.get("cell_fingerprint") != FP.cell_fingerprint(str(cell.get("family")), None)
             or cell.get("science_fingerprint") != science]
    report["stale_cells"] = len(stale)
    if not stale and document.get("estimator_fingerprint") == current:
        report["notices"].append("every cell already matches this runtime; nothing to adopt")
        return report
    picked = sample_cells(document, max(1, int(sample)))
    if not picked:
        report["notices"].append("no usable cells to verify against")
        return report
    report["sampled"] = len(picked)
    for key, cell in picked:
        family = str(cell.get("family"))
        fingerprint = FP.cell_fingerprint(family, None)
        runs = [CELLS.measure_cell(family, cell.get("parameter"), int(cell.get("seed") or 0),
                                   cell_fingerprint=fingerprint, science_fingerprint=science)
                for _ in range(max(1, int(repeat)))]
        problems, deviation, spread = compare(cell, runs, tolerance)
        report["worst_deviation"] = max(report["worst_deviation"], deviation)
        report["worst_host_spread"] = max(report["worst_host_spread"], spread)
        if problems:
            report["refused"].append({"cell": key, "problems": problems})
    if report["refused"]:
        report["notices"].append(
            f"{len(report['refused'])} of {len(picked)} sampled cell(s) moved: the edit was "
            "not value-neutral and the table is genuinely stale")
        return report
    restamped, kept = restamp_current(document, science)
    report["restamped"], report["kept_stale"] = restamped, kept
    T.mark_adopted(document, source=(reason or f"estimator fingerprint "
                                     f"{report['table_fingerprint']} -> {current}"),
                   notices=[
        f"{len(picked)} cell(s) re-measured; worst deviation {report['worst_deviation']:.2e} "
        f"against tolerance {tolerance:.0e}, worst run-to-run spread on this host "
        f"{report['worst_host_spread']:.2e}; remaining cells re-stamped, not re-run",
        f"sample is the cheapest cells per family and its largest up to {DEEP_SAMPLE_TO:,} nodes: a change "
        "biting only above that would not have been caught by it",
    ])
    document["estimator_fingerprint"] = current
    document["science_fingerprint"] = science
    report["adopted"] = True
    report["notices"].append(
        f"all {len(picked)} sampled cell(s) reproduced within {tolerance:.0e}; "
        f"{restamped} cell(s) re-stamped, not re-run"
        + (f"; {kept} already stale before the edit left stale" if kept else ""))
    return report
