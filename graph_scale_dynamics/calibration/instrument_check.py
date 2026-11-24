from __future__ import annotations

from graph_scale_dynamics.calibration.contract import CHANNELS
from graph_scale_dynamics.calibration.deviation import deviation_report
from graph_scale_dynamics.measurements.calibration import CALIBRATION_FAMILIES

CONTRACT = "gsd-instrument-check-1"

TOP_RUNG_STANDARD = 0.05

GATING_CHANNELS = ("d_s",)


def _declared_theory() -> dict[str, dict[str, float]]:
    return {family["name"]: dict(family.get("theory") or {})
            for family in CALIBRATION_FAMILIES}


def _top_measured_rung(rows: list[dict], channel: str) -> dict | None:
    for row in sorted(rows, key=lambda r: int(r["n"]), reverse=True):
        if not row.get("complete"):
            continue
        cell = (row.get("channels") or {}).get(channel) or {}
        if cell.get("measured") is not None:
            return {"n": int(row["n"]), **cell}
    return None


def _theory_drift(table: dict) -> list[dict]:
    declared = _declared_theory()
    stored = (table.get("families") or {})
    drift = []
    for name, family in sorted(stored.items()):
        want = declared.get(name)
        if want is None:
            drift.append({"family": name,
                          "problem": "family is not declared in the frozen source"})
            continue
        have = dict((family or {}).get("theory") or {})
        for channel in sorted(set(want) | set(have)):
            if want.get(channel) != have.get(channel):
                drift.append({"family": name, "channel": channel,
                              "declared": want.get(channel), "in_table": have.get(channel)})
    for name in sorted(set(declared) - set(stored)):
        drift.append({"family": name, "problem": "declared family is absent from the table"})
    return drift


def instrument_check(table: dict | None, *, standard: float = TOP_RUNG_STANDARD,
                     gating_channels: tuple[str, ...] = GATING_CHANNELS) -> dict:
    if not isinstance(table, dict) or not table:
        return {"ok": False, "contract": CONTRACT, "reason": "no calibration table"}
    profile = table.get("profile") or {}
    seeds = int(profile.get("seeds") or 1)
    from graph_scale_dynamics.calibration.table import cell_is_current
    cells = table.get("cells") or {}
    current = {key: cell for key, cell in cells.items() if cell_is_current(cell)}
    derived = deviation_report(list(CALIBRATION_FAMILIES), current,
                               seeds=seeds, max_nodes=profile.get("max_nodes"))
    families = derived.get("families") or {}

    top_rung: dict[str, dict] = {}
    misses: list[dict] = []
    for name, family in sorted(families.items()):
        if family.get("expectation") != "MEASURE":
            continue
        theory = dict(family.get("theory") or {})
        rows = family.get("rows") or []
        per_channel = {}
        for channel in sorted(set(theory) & set(CHANNELS)):
            expected = theory.get(channel)
            cell = _top_measured_rung(rows, channel)
            if expected in (None, 0) or cell is None:
                per_channel[channel] = {"n": (cell or {}).get("n"), "theory": expected,
                                        "measured": (cell or {}).get("measured"),
                                        "relative_deviation": None, "within_standard": None,
                                        "seeds": (cell or {}).get("seeds")}
                continue
            measured = float(cell["measured"])
            relative = abs(measured - float(expected)) / abs(float(expected))
            within = relative <= standard
            per_channel[channel] = {
                "n": cell["n"], "theory": float(expected), "measured": measured,
                "relative_deviation": round(relative, 6), "within_standard": within,
                "seeds": cell.get("seeds"), "seed_std": cell.get("seed_std"),
                "ladder_status": cell.get("status"),
            }
            if not within:
                misses.append({"family": name, "channel": channel, "n": cell["n"],
                               "theory": float(expected), "measured": measured,
                               "relative_deviation": round(relative, 6),
                               "gates": channel in gating_channels})
        top_rung[name] = per_channel

    false_confidence = [
        {"family": name, "channel": entry["channel"], "n": entry["n"]}
        for name, family in sorted(families.items())
        for entry in (family.get("gated_failures") or [])
        if family.get("expectation") == "REFUSE" and entry.get("status") == "FALSE_CONFIDENCE"]

    drift = _theory_drift(table)
    failing = list(derived.get("failing_families") or [])
    gating_misses = [m for m in misses if m["gates"]]
    ok = not failing and not gating_misses and not false_confidence and not drift
    return {
        "ok": ok,
        "contract": CONTRACT,
        "standard": {
            "relative_deviation": standard,
            "gates_on": list(gating_channels),
            "reading": (
                f"a probe reads a known object properly when it lands within "
                f"{standard:.0%} of the analytic value at the family's top measured rung. "
                f"One number for every probe; {', '.join(gating_channels)} gates a release and "
                f"the rest are charted. A miss is published, never accommodated by widening "
                f"the band."),
        },
        "ladder_verdict": derived.get("verdict"),
        "summary_line": derived.get("summary_line"),
        "seeds": seeds,
        "cells_judged": len(current),
        "stale_cells_left_out": len(cells) - len(current),
        "failing_families": failing,
        "incomplete_families": list(derived.get("incomplete_families") or []),
        "theory_drift": drift,
        "top_rung": top_rung,
        "misses": misses,
        "gating_misses": gating_misses,
        "false_confidence": false_confidence,
        "refusals_held": not false_confidence,
        "reading": (
            "Measured against theory on objects whose dimensions are known in advance. "
            "Nothing here is scored: a calibration family has nothing left to discover, so "
            "a score cannot be right or wrong about it. `ladder_verdict` is the table's own "
            "per-cell tolerance gate re-derived from the cells; `misses` is the same readings "
            "judged against one declared standard; `false_confidence` is a probe answering "
            "where the family says it must decline, which is the failure mode that matters "
            "most because it is the one a law can reproduce."),
    }
