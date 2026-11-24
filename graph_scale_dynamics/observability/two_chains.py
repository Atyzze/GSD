from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL

CONTRACT = "two-chains-1"
PROBES = ("d_s", "d_V", "d_B", "d_w")
QUANTITIES = ("mean_degree", "energy_per_node", "triangles_per_node", "squares_per_node", "giant_fraction",
              "kappa", "reach", *PROBES)
CHAINS = ("empty", "given")
STORED_AS = {"empty": "empty", "given": "given"}
LEVEL = 1e-9


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _short(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else float(f"{value:.{digits}g}")


def _per_node(value, n: int) -> float | None:
    value = _number(value)
    return None if value is None else value / max(1, int(n))


def _given_probes(metrics: dict, name: str | None):
    return CL.probes_of(metrics, CL.GIVEN if name is None else name)


def _probe_value(metrics: dict, chain: str, probe: str, name: str | None = None) -> dict:
    if chain == "empty":
        from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE
        block = metrics.get(probe) if isinstance(metrics.get(probe), dict) else {}
        value = _number(block.get(PROBE_VALUE[probe])) if block.get("valid") else None
        withheld = None if block.get("valid") else _number(block.get("would_have_reported"))
    else:
        probes = _given_probes(metrics, name)
        if not isinstance(probes, dict):
            return {"value": None, "withheld": None, "refusal": None, "read": False}
        block = probes.get(probe) or {}
        value = _number(block.get("value")) if block.get("valid") else None
        withheld = None
    refusal = None if value is not None else (block.get("refusal") or (None if not block else "UNCODED"))
    return {"value": value, "withheld": withheld, "refusal": refusal, "read": True}


def _stored(metrics: dict, section: str, chain: str, name: str | None) -> dict:
    return CL.of_chain(metrics.get(section), STORED_AS[chain] if name is None else name) or {}


def log_diameter_of(seed_metrics: list[dict], chain: str, name: str | None = None) -> dict:
    from graph_scale_dynamics.decisions.structure_gate import log_diameter_flags
    if chain == "empty" and name is None:
        return log_diameter_flags(seed_metrics)
    return log_diameter_flags([_given_probes(m, name) or {} for m in seed_metrics])


def seed_values(metrics: dict, n: int, chain: str, name: str | None = None) -> dict:
    census = _stored(metrics, "census", chain, name)
    edges = _number(census.get("edges"))
    degree = 2.0 * edges / max(1, n) if edges is not None else None
    if degree is None and chain == "empty":
        degree = _number((metrics.get("health") or {}).get("mean_degree"))
    descended = name if name is not None else STORED_AS[chain]
    descents = (metrics.get("descent") or {}).get("chains") or {}
    descent = descents.get(descended) or (descents.get(f"{CL.GIVEN}:{name}") if name is not None else None) or {}
    energy = _per_node(descent.get("final_energy"), n)
    if energy is None:
        course = CL.of_chain(metrics.get("chains_course"), descended) or {}
        last = (course.get("course") or [None])[-1]
        energy = _number(last[1]) if isinstance(last, list) and len(last) > 1 else None
    curvature = _stored(metrics, "curvature", chain, name)
    reach_from = metrics if chain == "empty" else (_given_probes(metrics, name) or {})
    out = {"mean_degree": degree, "energy_per_node": energy,
           "triangles_per_node": _per_node((census.get("cliques") or {}).get("triangles"), n),
           "squares_per_node": _per_node(census.get("squares"), n),
           "giant_fraction": _per_node((census.get("largest_component") or {}).get("size"), n),
           "kappa": _number(curvature.get("mean")) if curvature.get("measured") else None,
           "reach": _number(reach_from.get("half_volume_radius")) if isinstance(reach_from, dict) else None}
    accepted = accepted_moves_of(metrics).get(descended)
    out["moved"] = accepted / edges if accepted is not None and edges else None
    for probe in PROBES:
        out[probe] = _probe_value(metrics, chain, probe, name)
    return out


def accepted_moves_of(metrics: dict | None) -> dict[str, int]:
    kept = (metrics or {}).get("accepted_moves")
    if isinstance(kept, dict):
        return {str(name): int(value) for name, value in kept.items()
                if isinstance(value, int) and not isinstance(value, bool)}
    out = {}
    for name, accounting in ((metrics or {}).get("move_accounting") or {}).items():
        counts = accounting.get("counts") if isinstance(accounting, dict) else None
        if isinstance(counts, dict):
            out[str(name)] = sum(int(value) for key, value in counts.items()
                                 if str(key).endswith(".accepted") and isinstance(value, (int, float)))
    return out


def moved_summary(values: list, total: int) -> dict:
    out = _summary(values, total)
    kept = [v for v in values if v is not None]
    out["median"] = _short(float(np.median(kept))) if kept else None
    return out


def _summary(values: list, total: int) -> dict:
    kept = [v for v in values if v is not None]
    if not kept:
        return {"mean": None, "se": None, "seeds": 0, "of": total, "values": []}
    sd = float(np.std(kept, ddof=1)) if len(kept) > 1 else None
    return {"mean": _short(float(np.mean(kept))), "se": None if sd is None else _short(sd / math.sqrt(len(kept)), 4),
            "seed_sd": None if sd is None else _short(sd, 4), "seeds": len(kept), "of": total,
            "values": [_short(v, 5) for v in kept]}


def _probe_summary(cells: list[dict], total: int) -> dict:
    out = _summary([c["value"] for c in cells], total)
    withheld = [(c["withheld"], c["refusal"]) for c in cells if c["value"] is None and c["withheld"] is not None]
    if withheld:
        reasons: dict = {}
        for _, code in withheld:
            reasons[str(code or "UNCODED")] = reasons.get(str(code or "UNCODED"), 0) + 1
        out["withheld"] = {"mean": _short(float(np.mean([v for v, _ in withheld]))), "seeds": len(withheld),
                           "values": [_short(v, 5) for v, _ in withheld], "reasons": reasons}
    refused: dict = {}
    for c in cells:
        if c["value"] is None and c["refusal"]:
            refused[str(c["refusal"])] = refused.get(str(c["refusal"]), 0) + 1
    if refused:
        out["refused"] = refused
    out["read"] = any(c["read"] for c in cells)
    return out


def chains_ended_at_cap(metrics: dict) -> list[str]:
    return list(metrics.get("ended_at_cap") or metrics.get("given_ended_at_cap") or [])


def ended_at_cap(seed_metrics: list[dict], chain: str, name: str | None = None) -> dict:
    key = STORED_AS[chain] if name is None else str(name)
    seeds = sum(1 for m in seed_metrics
                if (chain == "empty" and m.get("limit_refusal")) or key in chains_ended_at_cap(m))
    return {"seeds": seeds, "of": len(seed_metrics)}


def chunk_checks(metrics: dict) -> list[dict]:
    out = []
    for row in ((metrics.get("health") or {}).get("sampling_checkpoints")) or []:
        if not isinstance(row, dict):
            continue
        cert = row.get("certificate") or {}
        split = cert.get("split") or {}
        rest = ((cert.get("at_rest") or {}).get("chains")) or {}
        thresholds = cert.get("structural_thresholds") or {}
        structural = {}
        for key, value in (cert.get("structural_split") or {}).items():
            judged = thresholds.get(key) if isinstance(thresholds.get(key), dict) else {}
            structural[key] = {"gap": _short(_number(value), 4), "limit": _short(_number(judged.get("threshold")), 4)}
        check = {
            "sweeps": _number(row.get("cumulative_sweeps")), "multiplier": row.get("multiplier"),
            "passed": bool(row.get("passed")),
            "failures": [{"code": str(f.get("code")), "detail": f.get("detail")}
                         for f in row.get("failures") or [] if isinstance(f, dict)],
            "z": _z(split),
            "structural": structural,
            "effective_samples": _short(_number(cert.get("effective_samples", row.get("effective_samples"))), 4),
            "drift": _short(_number(cert.get("stationarity_drift")), 4),
            "rest": {chain: _short(_number((rest.get(STORED_AS[chain]) or {}).get("late_descent_share")), 4)
                     for chain in CHAINS if STORED_AS[chain] in rest} if rest else None,
            "rest_limit": _number((cert.get("at_rest") or {}).get("limit_late_descent_share")),
            "mean_degree": _short(_number(row.get("mean_degree")), 5),
            "wall_seconds": _short(_number(row.get("wall_seconds_so_far")), 4),
            "ended": row.get("termination"), "given_ended": row.get("given_termination"),
        }
        first = f"{CHAINS[0]}|{CHAINS[1]}"
        pairs = cert.get("pairs") or {}
        if first in pairs:
            check["z"] = _z((pairs[first] or {}).get("split") or {})
        more_z = {str(pair): _z((block or {}).get("split") or {})
                  for pair, block in pairs.items() if pair != first and isinstance(block, dict)}
        more_rest = {key: _short(_number((value or {}).get("late_descent_share")), 4)
                     for key, value in rest.items() if key not in STORED_AS.values()}
        if more_z:
            check["more_z"] = more_z
        if more_rest:
            check["more_rest"] = more_rest
        if cert.get("left_out"):
            check["left_out"] = dict(cert["left_out"])
        own = {}
        for name, row in (cert.get("chains") or {}).items():
            activity = (row or {}).get("activity") or {}
            own[str(name)] = {"effective_samples": _short(_number((row or {}).get("effective_samples")), 4),
                              "drift": _short(_number((row or {}).get("stationarity_drift")), 4),
                              "late_changes": _short(_number(activity.get("accepted_topology_changes_per_node_late")), 4),
                              "overlap": _short(_number(activity.get("late_edge_jaccard")), 6)}
        if own:
            check["chains"] = own
        if row.get("more_given_terminations"):
            check["more_given_ended"] = row["more_given_terminations"]
        out.append(check)
    return out


def _z(split: dict) -> dict:
    return {"energy_per_node": _short(_number(split.get("energy_per_node_z")), 4),
            "mean_degree": _short(_number(split.get("mean_degree_z")), 4)}


def met_from(checks: list[dict], z_limit: float) -> dict:
    def stayed(ok) -> float | None:
        at = None
        for check in checks:
            if ok(check):
                at = check["sweeps"] if at is None else at
            else:
                at = None
        return at

    def gap_ok(check) -> bool:
        blocks = [check.get("z") or {}, *(check.get("more_z") or {}).values()]
        zs = [v for block in blocks for v in block.values() if v is not None]
        return bool(zs) and max(zs) <= z_limit

    def rest_ok(check) -> bool:
        rest, limit = check.get("rest"), check.get("rest_limit")
        shares = [*(rest or {}).values(), *(check.get("more_rest") or {}).values()]
        return (bool(rest) and limit is not None and all(v is not None and v <= limit for v in shares))

    return {"gap": stayed(gap_ok), "rest": stayed(rest_ok) if any(c.get("rest") for c in checks) else None}


def seed_stop(metrics: dict) -> dict:
    terminal = ((metrics.get("health") or {}).get("rung_terminal")) or {}
    readings = {str((pair or {}).get("reading")) for pair in (((terminal.get("at_rest") or {}).get("pairs")) or {}).values()
                if (pair or {}).get("reading")}
    given_chains = (None if not readings else "same_minimum" if readings == {"same_minimum"} else "different_minima")
    return {"reason": terminal.get("reason"), "classification": terminal.get("classification"),
            "chunks": terminal.get("chunks"), "final_multiplier": terminal.get("final_multiplier"),
            "wall_seconds": _short(_number(terminal.get("wall_seconds")), 4),
            "work_units": (terminal.get("work") or {}).get("units"),
            "work_budget": (terminal.get("work") or {}).get("budget"),
            "mean_degree_cap": _number(terminal.get("mean_degree_cap")),
            "cap_chain": terminal.get("mean_degree_cap_chain"),
            "failures": [{"code": str(f.get("code")), "detail": f.get("detail")}
                         for f in terminal.get("failures") or [] if isinstance(f, dict)],
            "given_rest": given_chains}


def _seed_meeting(metrics: dict, values: dict, name: str | None = None) -> dict:
    reading = (metrics.get("meeting_reading") if name is None
               else (metrics.get("more_meeting_readings") or {}).get(name)) or {}
    gaps = {}
    for key, block in (reading.get("observables") or {}).items():
        if isinstance(block, dict):
            gaps[key] = {"late_gap": _short(_number(block.get("late_gap")), 4),
                         "late_noise": _short(_number(block.get("late_noise")), 4),
                         "agree": block.get("agree"), "closing": block.get("closing")}
    energies = (values["empty"]["energy_per_node"], values["given" if name is None else name]["energy_per_node"])
    lower = None
    if all(e is not None for e in energies):
        scale = max(1.0, abs(energies[0]), abs(energies[1]))
        lower = ("level" if abs(energies[0] - energies[1]) <= LEVEL * scale
                 else "empty" if energies[0] < energies[1] else "given" if name is None else name)
    return {"reading": reading.get("reading"), "why": reading.get("why"), "gaps": gaps,
            "moving": reading.get("moving"), "frozen": reading.get("frozen"), "lower_energy": lower}


def stopping_numbers(campaign_spec: dict) -> dict:
    policy = dict((campaign_spec or {}).get("policy") or {})
    sampling = dict((campaign_spec or {}).get("sampling_contract") or {})
    return {"required_consecutive_passes": max(1, int(sampling.get("required_consecutive_passes", 2))),
            "max_sweeps_multiplier": int(sampling.get("max_sweeps_multiplier",
                                                      policy.get("max_sweeps_multiplier", 64))),
            "min_effective_samples": float(policy.get("min_effective_samples", 8)),
            "equilibration_split_z": float(policy.get("equilibration_split_z", 3.0)),
            "stationarity_drift_max": float(policy.get("stationarity_drift_max", 3.0))}


RESERVED = frozenset({"empty", "given", "n", "seeds"})


def more_given_names(starts: list | None, seed_metrics: list[dict]) -> list[str]:
    named = [str(s.get("name")) for s in (starts or [])[1:] if isinstance(s, dict) and s.get("name")]
    seen = {str(name) for m in seed_metrics for name in CL.chains_in(m.get("census"))} - {CL.FROM_EMPTY, CL.GIVEN}
    names = named + sorted(seen - set(named))
    return [name for name in names if name not in RESERVED]


def _every_chain(starts: list | None, names: list[str], given_start: str | None) -> list[dict]:
    families = {str(s.get("name")): s.get("family") for s in starts or [] if isinstance(s, dict)}
    first = (starts or [{}])[0] if starts else {}
    chains = [{"name": "empty", "key": "empty", "start": "the empty graph"},
              {"name": str(first.get("name") or "given"), "key": "given",
               "start": first.get("family") or given_start}]
    chains += [{"name": name, "key": name, "start": families.get(name)} for name in names]
    return chains


COUNTED_QUANTITIES = ("mean_degree", "giant_fraction", "reach", *PROBES)


def settled_classes() -> frozenset[str]:
    from graph_scale_dynamics.scaleflow import equilibration as EQ
    return frozenset({EQ.EQUILIBRATED_ACTIVE, EQ.EQUILIBRATED_LOW_ACTIVITY, EQ.AT_REST, EQ.FROZEN_OR_ABSORBING})


def chain_stopped(metrics: dict, stored: str) -> bool:
    health = (metrics or {}).get("health") or {}
    if ((health.get("rung_terminal") or {}).get("classification")) in settled_classes():
        return True
    own = (((health.get("equilibration") or {}).get("chains") or {}).get(str(stored))) or {}
    return ((own.get("activity") or {}).get("frozen")) is True


def _counted(values: list[dict], stopped: list[bool], chain: str, total: int) -> dict:
    out = {"seeds": sum(1 for s in stopped if s), "of": total}
    for key in COUNTED_QUANTITIES:
        kept = [(v[chain][key]["value"] if key in PROBES else v[chain][key]) if s else None
                for v, s in zip(values, stopped, strict=True)]
        out[key] = _summary(kept, total)
    return out


def chains_per_rung(measurements: list[dict], starts: list | None = None) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    rows = [m for m in measurements or [] if isinstance(m.get("metrics"), dict)
            and not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {}).get("sampler_audit"))]
    by_n: dict[int, list] = {}
    for row in select_best_runs(rows):
        by_n.setdefault(int(row["n"]), []).append(row)
    names = more_given_names(starts, [row["metrics"] for row in rows])
    rungs = []
    for n in sorted(by_n):
        seeds = by_n[n]
        values = [{**{chain: seed_values(r["metrics"], n, chain) for chain in CHAINS},
                   **{name: seed_values(r["metrics"], n, "given", name) for name in names}} for r in seeds]
        rung = {"n": n, "seeds": len(seeds)}
        for chain in (*CHAINS, *names):
            summary = {key: (_probe_summary([v[chain][key] for v in values], len(seeds)) if key in PROBES
                             else _summary([v[chain][key] for v in values], len(seeds))) for key in QUANTITIES}
            summary["ended_at_cap"] = ended_at_cap([r["metrics"] for r in seeds], "empty" if chain == "empty"
                                                   else "given", None if chain in CHAINS else chain)
            summary["moved"] = moved_summary([v[chain]["moved"] for v in values], len(seeds))
            stored = STORED_AS[chain] if chain in CHAINS else chain
            summary["counted"] = _counted(values, [chain_stopped(r["metrics"], stored) for r in seeds], chain,
                                          len(seeds))
            if chain in CHAINS:
                rung[chain] = summary
            else:
                rung.setdefault("more_given", {})[chain] = summary
        ends: dict = {}
        for row in seeds:
            key = str(seed_stop(row["metrics"])["reason"] or "not recorded")
            ends[key] = ends.get(key, 0) + 1
        rung["ends"] = ends
        rungs.append(rung)
    out = {"rungs": rungs}
    if names:
        out["every_chain"] = _every_chain(starts, names, None)
    return out


def two_chains(measurements: list[dict], *, given_start: str | None = None, policy: dict | None = None,
               starts: list | None = None) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    from graph_scale_dynamics.observability.meeting_reading import rung_meeting_reading

    policy = policy or {}
    z_limit = float(policy.get("equilibration_split_z", 3.0))
    rows = [m for m in measurements or [] if isinstance(m.get("metrics"), dict)
            and not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {}).get("sampler_audit"))]
    by_n: dict[int, list] = {}
    for row in select_best_runs(rows):
        by_n.setdefault(int(row["n"]), []).append(row)
    names = more_given_names(starts, [row["metrics"] for row in rows])
    rungs = []
    zero_temperature = False
    for n in sorted(by_n):
        seeds = sorted(by_n[n], key=lambda r: (r.get("seed") is None, r.get("seed")))
        total = len(seeds)
        values = [{**{chain: seed_values(r["metrics"], n, chain) for chain in CHAINS},
                   **{name: seed_values(r["metrics"], n, "given", name) for name in names}} for r in seeds]
        chains = {}
        for chain in (*CHAINS, *names):
            chains[chain] = {key: (_probe_summary([v[chain][key] for v in values], total) if key in PROBES
                                   else _summary([v[chain][key] for v in values], total))
                             for key in QUANTITIES}
            chains[chain]["ended_at_cap"] = ended_at_cap([r["metrics"] for r in seeds], "empty" if chain == "empty"
                                                         else "given", None if chain in CHAINS else chain)
            chains[chain]["log_diameter"] = log_diameter_of([r["metrics"] for r in seeds], "empty" if chain == "empty"
                                                            else "given", None if chain in CHAINS else chain)
        per_seed = []
        for row, value in zip(seeds, values, strict=True):
            metrics = row["metrics"]
            checks = chunk_checks(metrics)
            zero_temperature = zero_temperature or any(c.get("rest") for c in checks)
            course = metrics.get("chains_course")
            seed = {"seed": row.get("seed"), "meeting": _seed_meeting(metrics, value),
                    "stop": seed_stop(metrics), "checks": checks, "met_from": met_from(checks, z_limit),
                    "course": course if isinstance(course, dict) and not course.get("error") else None}
            if names:
                seed["more_meetings"] = {name: _seed_meeting(metrics, value, name) for name in names}
                seed["ended_at_cap"] = chains_ended_at_cap(metrics)
            per_seed.append(seed)
        lower = {}
        for seed in per_seed:
            side = seed["meeting"]["lower_energy"]
            if side:
                lower[side] = lower.get(side, 0) + 1
        ends: dict = {}
        for seed in per_seed:
            key = str(seed["stop"]["reason"] or "not recorded")
            ends[key] = ends.get(key, 0) + 1
        rung = {"n": n, "seeds": total, **{chain: chains[chain] for chain in CHAINS},
                "reading": rung_meeting_reading([r["metrics"] for r in seeds]),
                "lower_energy": lower, "ends": ends, "per_seed": per_seed,
                "courses": sum(1 for s in per_seed if s["course"])}
        if names:
            rung["more_given"] = {name: chains[name] for name in names}
            rung["more_readings"] = {name: rung_meeting_reading([r["metrics"] for r in seeds], name) for name in names}
        rungs.append(rung)
    rule = {"required_consecutive_passes": int(policy.get("required_consecutive_passes", 2)),
            "max_sweeps_multiplier": int(policy.get("max_sweeps_multiplier", 64)),
            "min_effective_samples": float(policy.get("min_effective_samples", 8)),
            "split_z": z_limit, "drift": float(policy.get("stationarity_drift_max", 3.0))}
    from graph_scale_dynamics.scaleflow.equilibration import REST_LATE_DESCENT_SHARE
    rule["rest_share"] = float(policy.get("zero_temperature_rest_late_descent_share", REST_LATE_DESCENT_SHARE))
    out = {"contract": CONTRACT, "given_start": given_start, "zero_temperature": zero_temperature,
           "given_probes_read": any(r["given"]["d_s"].get("read") for r in rungs), "rule": rule,
           "quantities": list(QUANTITIES), "rungs": rungs}
    if names:
        out["every_chain"] = _every_chain(starts, names, given_start)
        out["more_probes_read"] = {name: any(((r.get("more_given") or {}).get(name) or {}).get("d_s", {}).get("read")
                                             for r in rungs) for name in names}
    return out
