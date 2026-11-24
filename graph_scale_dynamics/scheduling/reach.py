from __future__ import annotations

GIB = 1024 ** 3


def _fmt_bytes(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unknown"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if v < 1024 or unit == "TiB":
            return f"{v:.1f} {unit}" if v < 10 else f"{v:.0f} {unit}"
        v /= 1024
    return f"{v:.0f} TiB"


def reach(spec: dict, *, snapshot=None) -> dict:
    from graph_scale_dynamics.scheduling.base_block import anchor_n, base_sizes, extension_sizes
    from graph_scale_dynamics.scheduling.campaign_limits import campaign_max_n
    from graph_scale_dynamics.scheduling.base_block import measurement_seeds
    from graph_scale_dynamics.scheduling.limits import estimated_seconds, limits, work_budget

    lim = limits(spec)
    base = [int(n) for n in base_sizes(spec)]
    extension = [int(n) for n in extension_sizes(spec)]
    ladder = [int(n) for n in (spec.get("ladder") or (base + extension))]
    deepest = max(ladder) if ladder else 0
    seeds = measurement_seeds(spec)
    ceiling = campaign_max_n(spec)

    rungs: list[dict] = []
    problems: list[str] = []
    notes: list[str] = []
    for n in ladder:
        row: dict = {"n": n, "kind": "base" if n in base else
                     ("extension" if n in extension else "declared, unreachable")}
        row["work_budget"] = work_budget(spec, n)
        row["estimated_seconds"] = estimated_seconds(spec, n)
        try:
            from graph_scale_dynamics.scheduling.memory import (
                effective_hard_fraction, sane_peak_prediction_bytes, system_memory)
            mem = snapshot or system_memory()
            sim, _, _ = sane_peak_prediction_bytes(None, spec, n, "simulation", snapshot=mem)
            ana, _, _ = sane_peak_prediction_bytes(None, spec, n, "analysis", snapshot=mem)
            _, fraction = effective_hard_fraction(spec, n)
            row["predicted_peak_bytes"] = int(max(sim, ana))
            row["single_job_fraction"] = float(fraction)
            row["single_job_limit_bytes"] = int(int(mem.total) * fraction)
            row["memory_feasible"] = row["predicted_peak_bytes"] <= row["single_job_limit_bytes"]
        except Exception as exc:                                   # noqa: BLE001
            row["memory_feasible"] = None
            row["memory_note"] = f"{type(exc).__name__}: {exc}"[:120]

        if ceiling is not None and n > int(ceiling):
            problems.append(
                f"N={n} is on the ladder and above budgets.max_n={ceiling}: the controller "
                "parks a candidate whose rung exceeds the ceiling, so this rung is declared "
                "and forbidden")
        if row["memory_feasible"] is False:
            problems.append(
                f"N={n} predicts {_fmt_bytes(row['predicted_peak_bytes'])} against a single-job "
                f"limit of {_fmt_bytes(row['single_job_limit_bytes'])}: refused at admission")
        rungs.append(row)

    previous = None
    for row in rungs:
        if previous is not None and row["work_budget"] < previous:
            notes.append(f"N={row['n']:,} has a smaller budget in work than the rung below it")
        previous = row["work_budget"]

    if extension and deepest not in extension and deepest not in base:
        problems.append(f"the deepest declared rung N={deepest} is on neither the base block "
                        "nor the extension ladder, so nothing will ever buy it")

    return {
        "contract": "gsd-campaign-reach-1",
        "base_block": base, "extension_ladder": extension, "ladder": ladder,
        "anchor_n": anchor_n(spec), "deepest_rung": deepest,
        "budgets_max_n": ceiling, "measurement_seeds": seeds,
        "mean_degree_window": lim["mean_degree_window"],
        "mean_degree_cap_armed_from_n": lim["mean_degree_cap_armed_from_n"],
        "rungs": rungs, "problems": problems, "notes": notes,
        "reachable": not problems,
    }


def describe(spec: dict, *, snapshot=None) -> str:
    from graph_scale_dynamics.observability.live_panel import _duration, units_text
    r = reach(spec, snapshot=snapshot)
    window = r["mean_degree_window"]
    head = (f"campaign reach ({r['contract']}): ladder {r['ladder']}, anchor N={r['anchor_n']}, "
            f"{r['measurement_seeds']} seeds per rung, mean degree "
            f"[{window['min']:g}, {window['max']:g}] with the cap armed from "
            f"N={int(r['mean_degree_cap_armed_from_n'])}.")
    memory_known = any(row.get("predicted_peak_bytes") or row.get("memory_feasible") is not None
                       for row in r["rungs"])
    header = "  rung        kind        budget in work (about)"
    lines = [head, header + ("    predicted peak   admits" if memory_known else "")]
    for row in r["rungs"]:
        about = f" ({_duration(row['estimated_seconds'])})" if row.get("estimated_seconds") else ""
        line = f"  N={row['n']:<9} {row['kind']:<11} {units_text(row['work_budget']) + ' units' + about:>22}"
        if memory_known:
            peak = (_fmt_bytes(row["predicted_peak_bytes"]) if row.get("predicted_peak_bytes")
                    else "unknown")
            admits = {True: "yes", False: "NO", None: "?"}[row.get("memory_feasible")]
            line += f" {peak:>17}   {admits}"
        lines.append(line)
    if not memory_known:
        lines.append("  memory: not predicted here; admission prices each claim from the rung's measured "
                     "peaks once it has run, and from a fallback prediction before that")
    if r["problems"]:
        lines.append("  PROBLEMS -- this campaign cannot reach its own ladder:")
        lines.extend(f"    * {p}" for p in r["problems"])
    else:
        lines.append(f"  every declared rung is reachable; deepest is N={r['deepest_rung']}.")
    for note in r["notes"]:
        lines.append(f"  note: {note}")
    lines.append("  A spec is frozen at creation and is never adapted, so a later build that "
                 "changes these numbers does not change this campaign.")
    return "\n".join(lines)
