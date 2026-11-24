from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL

CONTRACT = "meeting-reading-2"
OBSERVABLES = ("energy_per_node", "mean_degree")
READINGS = ("disagreeing_while_moving", "frozen", "converging", "agreeing", "not_enough_points")
MIN_POINTS = 8
FROZEN_ACTIVITY = 0.05
CONVERGING_FACTOR = 0.5
AGREE_SIGMAS = 2.0
WIRING_RELATIVE_FLOOR = 0.1
WIRING_FLOOR = 0.01


def _value(point: dict, observable: str, n: int) -> float | None:
    raw = (point.get("energy") / n if observable == "energy_per_node" and point.get("energy") is not None
           else point.get(observable))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)):
        return float(raw)
    return None


def _accepted(point: dict) -> float | None:
    parts = [point.get(key) for key in ("accepted_add", "accepted_delete", "accepted_swap")]
    if any(isinstance(p, (int, float)) and not isinstance(p, bool) for p in parts):
        return float(sum(float(p) for p in parts if isinstance(p, (int, float)) and not isinstance(p, bool)))
    return None


def _activity(late: list, n: int) -> float:
    first, last = _accepted(late[0]), _accepted(late[-1])
    if first is not None and last is not None and last >= first:
        return (last - first) / max(1, n)
    changed = any(late[i].get("edges") != late[i + 1].get("edges")
                  or late[i].get("energy") != late[i + 1].get("energy") for i in range(len(late) - 1))
    return float("inf") if changed else 0.0


def _triangles(census: dict | None) -> float | None:
    value = (((census or {}).get("cliques") or {}).get("triangles"))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _given_census(census: dict | None, name: str | None) -> dict | None:
    return CL.of_chain(census, CL.GIVEN if name is None else name)


def _wiring(late: dict, n: int, census: dict | None, name: str | None = None) -> dict | None:
    series = {chain: [float(p["triangles"]) / n for p in rows
                      if isinstance(p.get("triangles"), (int, float)) and not isinstance(p.get("triangles"), bool)]
              for chain, rows in late.items()}
    finals = {"empty": _triangles((census or {}).get("empty")), "given": _triangles(_given_census(census, name))}
    if all(v is not None for v in finals.values()):
        values, source = {chain: v / n for chain, v in finals.items()}, "census"
    elif all(series.values()):
        values, source = {chain: rows[-1] for chain, rows in series.items()}, "trajectory"
    else:
        return None
    late_gap = values["empty"] - values["given"]
    halves = {chain: (rows[:len(rows) // 2], rows[len(rows) // 2:]) for chain, rows in series.items()}
    noise = math.sqrt(sum(float(np.var(later)) for _earlier, later in halves.values() if len(later) >= 2))
    early_gap = (float(np.mean(halves["empty"][0]) - np.mean(halves["given"][0]))
                 if all(earlier for earlier, _later in halves.values()) else None)
    floor = max(WIRING_FLOOR, WIRING_RELATIVE_FLOOR * max(abs(values["empty"]), abs(values["given"])))
    return {"early_gap": None if early_gap is None else round(early_gap, 6), "late_gap": round(late_gap, 6),
            "late_noise": round(noise, 6), "agree": abs(late_gap) <= max(AGREE_SIGMAS * noise, floor),
            "closing": early_gap is not None and abs(late_gap) <= CONVERGING_FACTOR * abs(early_gap),
            "source": source, "empty": round(values["empty"], 6), "given": round(values["given"], 6)}


def seed_meeting_reading(envelope: dict, census: dict | None = None, name: str | None = None) -> dict:
    n = max(1, int(envelope.get("n") or 1))
    from_empty = CL.trajectory(envelope, CL.FROM_EMPTY)
    given = CL.trajectory(envelope, CL.GIVEN if name is None else name)
    out: dict = {"contract": CONTRACT, "points": {"empty": len(from_empty), "given": len(given)}}
    late = {"empty": from_empty[len(from_empty) // 2:], "given": given[len(given) // 2:]}
    if any(len(rows) < 2 * MIN_POINTS for rows in late.values()):
        return out | {"reading": "not_enough_points",
                      "why": (f"fewer than {2 * MIN_POINTS} recorded points in a chain's late half"
                              if given else "no trajectory of the given chain was recorded")}
    activity = {chain: _activity(rows, n) for chain, rows in late.items()}
    moving = {chain: activity[chain] > FROZEN_ACTIVITY for chain in late}
    observables: dict = {}
    for observable in OBSERVABLES:
        parts = {}
        for chain, rows in late.items():
            values = [v for v in (_value(p, observable, n) for p in rows) if v is not None]
            half = len(values) // 2
            parts[chain] = (values[:half], values[half:])
        if any(len(part) < MIN_POINTS for pair in parts.values() for part in pair):
            continue
        early_gap = float(np.mean(parts["empty"][0]) - np.mean(parts["given"][0]))
        late_gap = float(np.mean(parts["empty"][1]) - np.mean(parts["given"][1]))
        noise = math.sqrt(float(np.var(parts["empty"][1])) + float(np.var(parts["given"][1])))
        scale = max(abs(float(np.mean(parts["empty"][1]))), abs(float(np.mean(parts["given"][1]))), 1e-12)
        agree = abs(late_gap) <= max(AGREE_SIGMAS * noise, 1e-9 * scale)
        observables[observable] = {"early_gap": round(early_gap, 6), "late_gap": round(late_gap, 6),
                                   "late_noise": round(noise, 6), "agree": agree,
                                   "closing": abs(late_gap) <= CONVERGING_FACTOR * abs(early_gap)}
    wiring = _wiring(late, n, census, name)
    if wiring is not None:
        observables["triangles_per_node"] = wiring
    out |= {"activity_per_node": {k: (None if math.isinf(v) else round(v, 4)) for k, v in activity.items()},
            "moving": moving, "observables": observables}
    if not observables:
        return out | {"reading": "not_enough_points", "why": "no observable recorded in both chains"}
    disagreeing = [o for o in observables.values() if not o["agree"]]
    if not disagreeing:
        return out | {"reading": "agreeing"}
    if not all(moving.values()):
        return out | {"reading": "frozen",
                      "frozen": sorted(chain for chain, moves in moving.items() if not moves)}
    if all(o["closing"] for o in disagreeing):
        return out | {"reading": "converging"}
    return out | {"reading": "disagreeing_while_moving"}


def seed_more_meeting_readings(envelope: dict, census: dict | None = None) -> dict | None:
    if not CL.has_more(envelope):
        return None
    return {str(name): seed_meeting_reading(envelope, census, name=str(name))
            for name in CL.more_names(envelope) if not CL.record(envelope, name).get("skipped")}


def rung_meeting_reading(seed_metrics: list[dict], name: str | None = None) -> dict:
    counts = {reading: 0 for reading in READINGS}
    for metrics in seed_metrics:
        block = (metrics.get("meeting_reading") if name is None
                 else ((metrics.get("more_meeting_readings") or {}).get(name)))
        reading = ((block or {}).get("reading"))
        if reading in counts:
            counts[reading] += 1
    seen = sum(counts.values())
    if not seen:
        return {"contract": CONTRACT, "reading": None, "counts": counts, "seeds": 0}
    top = max(counts.values())
    reading = next(r for r in READINGS if counts[r] == top)
    return {"contract": CONTRACT, "reading": reading, "counts": counts, "seeds": seen}
