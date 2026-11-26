from __future__ import annotations

import statistics
from collections import Counter, defaultdict

CONTRACT = "gsd-chains-meeting-1"


def _quartiles(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return {"q1": ordered[0], "median": ordered[0], "q3": ordered[0], "max": ordered[0]}
    q1, median, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    return {"q1": round(q1, 4), "median": round(median, 4), "q3": round(q3, 4), "max": round(ordered[-1], 4)}


def _seeds(measurements: list[dict]) -> list[dict]:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    by_law: dict[str, list] = defaultdict(list)
    for row in measurements or []:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict) or row.get("n") is None:
            continue
        if (((metrics.get("health") or {}).get("sampler") or {}).get("sampler_audit")):
            continue
        by_law[str(row.get("candidate_id"))].append(row)
    return [row for rows in by_law.values() for row in select_best_runs(rows)]


def chains_meeting(measurements: list[dict], split_z: float = 3.0) -> dict:
    from graph_scale_dynamics.observability.two_chains import chains_ended_at_cap, chunk_checks, met_from, seed_stop
    rungs: dict[int, dict] = {}
    for row in _seeds(measurements):
        metrics = row["metrics"]
        checks = chunk_checks(metrics)
        if not checks:
            continue
        rung = rungs.setdefault(int(row["n"]), {"seeds": 0, "laws": set(), "readings": Counter(), "ends": Counter(),
                                                "finite": {"seeds": 0, "met": [], "share": []},
                                                "zero_temperature": {"seeds": 0, "met": [], "share": []},
                                                "more_readings": {}, "ended_at_cap": Counter()})
        for name, reading in (metrics.get("more_meeting_readings") or {}).items():
            rung["more_readings"].setdefault(str(name), Counter())[str((reading or {}).get("reading") or "not read")] += 1
        rung["ended_at_cap"].update(str(name) for name in chains_ended_at_cap(metrics))
        rung["seeds"] += 1
        rung["laws"].add(str(row.get("candidate_id")))
        rung["readings"][str((metrics.get("meeting_reading") or {}).get("reading") or "not read")] += 1
        rung["ends"][str(seed_stop(metrics)["reason"] or "not recorded")] += 1
        cold = any(check.get("rest") for check in checks)
        regime = rung["zero_temperature" if cold else "finite"]
        regime["seeds"] += 1
        met = met_from(checks, split_z)["rest" if cold else "gap"]
        last = checks[-1].get("sweeps")
        if met is not None:
            regime["met"].append(float(met))
            if last:
                regime["share"].append(float(met) / float(last))
    out = []
    for n in sorted(rungs):
        rung = rungs[n]
        row = {"n": n, "seeds": rung["seeds"], "laws": len(rung["laws"]), "readings": dict(rung["readings"]),
               "ends": dict(rung["ends"])}
        if rung["more_readings"]:
            row["more_readings"] = {name: dict(counts) for name, counts in sorted(rung["more_readings"].items())}
        if rung["ended_at_cap"]:
            row["ended_at_cap"] = dict(rung["ended_at_cap"])
        for name in ("finite", "zero_temperature"):
            regime = rung[name]
            if regime["seeds"]:
                row[name] = {"seeds": regime["seeds"], "met": len(regime["met"]),
                             "never": regime["seeds"] - len(regime["met"]),
                             "sweeps": _quartiles(regime["met"]), "share_of_the_run": _quartiles(regime["share"])}
        out.append(row)
    return {"contract": CONTRACT, "split_z": split_z, "rungs": out,
            "reading": ("finite: from how many sweeps every later check found the chains within their noise (split z at "
                        "or under the limit); zero_temperature: from how many sweeps every later check found both "
                        "chains at rest (they need not meet). never: seeds whose last check did not. share_of_the_run: "
                        "those sweeps over the sweeps at the last check. readings: the meeting reading per seed.")}
