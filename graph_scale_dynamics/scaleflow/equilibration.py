from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL

CERT_NUMERICS = "NUMERICS_NON_FINITE"
CERT_MISSING = "CERTIFICATE_MISSING"
CERT_ESS_MISSING = "EFFECTIVE_SAMPLES_MISSING"
CERT_ESS_LOW = "EFFECTIVE_SAMPLES_BELOW_TARGET"
CERT_SPLIT_MISSING = "STARTS_SPLIT_MISSING"
CERT_SPLIT_DISAGREED = "STARTS_DISAGREED"
CERT_STRUCTURAL_DISAGREED = "STARTS_STRUCTURAL_DISAGREED"
CERT_DRIFT_MISSING = "STATIONARITY_DRIFT_MISSING"
CERT_DRIFT = "STATIONARITY_DRIFT"
CERT_REST_MISSING = "AT_REST_EVIDENCE_MISSING"
CERT_NOT_AT_REST = "NOT_AT_REST"
CERT_STRUCTURAL_TREND = "STRUCTURAL_TREND"
CERT_STRUCTURAL_TREND_MISSING = "STRUCTURAL_TREND_MISSING"
CHAINS_DISAGREED_CODES = frozenset({CERT_SPLIT_DISAGREED, CERT_STRUCTURAL_DISAGREED})

SAMPLING_1 = "one-shot-sampling-1"
SAMPLING_CURRENT = "one-shot-sampling-2"

EQUILIBRATED_ACTIVE = "EQUILIBRATED_ACTIVE"
EQUILIBRATED_LOW_ACTIVITY = "EQUILIBRATED_LOW_ACTIVITY"
AT_REST = "AT_REST"
FROZEN_OR_ABSORBING = "FROZEN_OR_ABSORBING"
METASTABLE_OR_NONMIXING = "METASTABLE_OR_NONMIXING"
RELAXING_AT_CEILING = "RELAXING_AT_CEILING"
INSUFFICIENT_EFFECTIVE_SAMPLES = "INSUFFICIENT_EFFECTIVE_SAMPLES"
NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
OPERATIONAL_UNRESOLVED = "OPERATIONAL_UNRESOLVED"
MEAN_DEGREE_CAP_TERMINAL = "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
BUDGET_TERMINAL = "REFUSED_COMPUTE_BUDGET"


REST_LATE_DESCENT_SHARE = 0.01
DRIFT_ERRORS = 3.0


def structural_limits(policy: dict) -> dict:
    return {
        "connected_fraction": float(policy.get("equilibration_connected_delta_max", 0.25)),
        "two_core_fraction": float(policy.get("equilibration_two_core_delta_max", 0.25)),
        "largest_component_cycle_rank_density": float(policy.get("equilibration_cycle_density_delta_max", 0.15)),
        "component_count_per_node": float(policy.get("equilibration_component_count_delta_max", 0.10)),
    }


def structural_floors(policy: dict) -> dict:
    return {
        "connected_fraction": float(policy.get("equilibration_connected_delta_floor", 0.025)),
        "component_count_per_node": float(policy.get("equilibration_component_count_delta_floor", 0.01)),
    }


def structural_thresholds(policy: dict, cert: dict) -> dict:
    limits, floors = structural_limits(policy), structural_floors(policy)
    sigmas = float(policy.get("equilibration_split_z", 3.0))
    noise = (cert or {}).get("structural_noise_detrended") or {}
    out = {}
    for key, limit in limits.items():
        spread = noise.get(key)
        if key in floors and isinstance(spread, (int, float)) and math.isfinite(float(spread)):
            by_spread = sigmas * float(spread)
            out[key] = ({"threshold": by_spread, "basis": "spread", "noise": float(spread)}
                        if by_spread >= floors[key] else
                        {"threshold": floors[key], "basis": "floor", "noise": float(spread)})
        else:
            out[key] = {"threshold": limit, "basis": "absolute", "noise": None}
    return out


def rung_certified(per_seed_metrics: list[dict]) -> dict:
    terminals = [t for t in (((m or {}).get("health") or {}).get("rung_terminal") for m in per_seed_metrics) if t]
    if not terminals:
        return {"certified": None, "failures": []}
    failures = sorted({f"{t.get('classification') or t.get('reason')}: "
                       + "; ".join(str(f.get("detail") or f.get("code")) for f in (t.get("failures") or []))
                       for t in terminals if t.get("reason") != "completed"})
    return {"certified": not failures, "failures": failures}


def chain_words(name: str) -> str:
    return "the chain from empty" if name == CL.FROM_EMPTY else f"the {name} chain"


def certificate_asks(policy: dict) -> dict:
    return {"effective_samples": float(policy.get("min_effective_samples", 8)),
            "split_z": float(policy.get("equilibration_split_z", 3.0)),
            "drift": float(policy.get("stationarity_drift_max", DRIFT_ERRORS))}


def certificate_pass(policy: dict, health: dict) -> tuple[bool, list[dict]]:
    reasons: list[dict] = []

    def fail(code: str, detail: str) -> None:
        reasons.append({"code": code, "detail": detail})

    if health.get("numerics_ok") is False:
        return False, [{"code": CERT_NUMERICS, "detail": "non-finite numerical state"}]
    if health.get("regime") == "zero_temperature":
        passed, reasons = rest_pass(health)
        _trend_pass(health.get("structural_trend"), reasons)
        return not reasons, reasons
    cert = health.get("equilibration") or {}
    if not cert:
        return False, [{"code": CERT_MISSING, "detail": "missing equilibration certificate"}]
    if not isinstance(cert.get("decide"), list):
        return False, [{"code": CERT_MISSING, "detail": "a certificate of the chain from empty alone, from before every chain "
                                                       "counted its own (780): read it with the build that wrote it"}]
    for name in cert.get("decide") or []:
        reasons.extend(own_count_failures(policy, cert, name))
    for ended, going_on in twins_apart_at_the_cap(cert):
        fail(CERT_SPLIT_DISAGREED, f"{chain_words(ended)} ended at the mean-degree cap and {chain_words(going_on)} did not")
    _pairs_pass(policy, cert.get("pairs") or {}, reasons)
    _trend_pass(health.get("structural_trend"), reasons)
    for name in cert.get("decide") or []:
        reasons.extend(own_drift_failures(policy, cert, name))
    return not reasons, reasons


def own_count_failures(policy: dict, cert: dict, name: str) -> list[dict]:
    target = float(policy.get("min_effective_samples", 8))
    effective = ((cert.get("chains") or {}).get(name) or {}).get("effective_samples")
    if effective is None:
        return [{"code": CERT_ESS_MISSING, "detail": f"{chain_words(name)}'s effective-sample estimate missing"}]
    if float(effective) < target:
        return [{"code": CERT_ESS_LOW,
                 "detail": f"{chain_words(name)}'s effective samples {float(effective):.3g} < {target:.3g}"}]
    return []


def own_drift_failures(policy: dict, cert: dict, name: str) -> list[dict]:
    drift = (((cert.get("chains") or {}).get(name) or {}).get("stationarity") or {}).get("normalized_drift")
    if drift is None:
        return [{"code": CERT_DRIFT_MISSING, "detail": f"{chain_words(name)}'s late stationarity drift unavailable"}]
    if abs(float(drift)) > float(policy.get("stationarity_drift_max", DRIFT_ERRORS)):
        return [{"code": CERT_DRIFT, "detail": f"persistent late energy drift in {chain_words(name)}: "
                                               f"{abs(float(drift)):.3g} of its own errors"}]
    return []


ENDED_AT_CAP = "ended_at_the_mean_degree_cap"
NOT_RUN = "not_run"


def left_out_chains(envelope: dict) -> dict:
    out = {}
    for row in CL.records(envelope):
        name = str(row.get("start"))
        block = CL.block(envelope, name)
        if block.get("ended"):
            out[name] = ENDED_AT_CAP
        elif row.get("skipped") or not block:
            out[name] = NOT_RUN
    return out


def deciding_chains(envelope: dict, policy: dict | None = None) -> dict:
    recorded = envelope.get("certificate_chains")
    if (policy is None and isinstance(recorded, dict) and isinstance(recorded.get("decide"), list)
            and isinstance(recorded.get("meet"), list)):
        return {"decide": list(recorded["decide"]), "meet": list(recorded["meet"]),
                "twin_chains": list(recorded.get("twin_chains") or []), "left_out": dict(recorded.get("left_out") or {})}
    left_out = left_out_chains(envelope)
    decide = [name for name in CL.ran_names(envelope) if name not in left_out]
    twins = CL.twin_names(envelope)
    meet = twins if len(twins) == 2 and all(name in decide for name in twins) else []
    return {"decide": decide, "meet": meet, "twin_chains": twins, "left_out": left_out}


def twins_apart_at_the_cap(cert: dict) -> list[tuple[str, str]]:
    left_out, decide = cert.get("left_out") or {}, cert.get("decide") or []
    twins = list(cert.get("twin_chains") or [])
    ended = [name for name in twins if left_out.get(name) == ENDED_AT_CAP]
    going_on = [name for name in twins if name in decide]
    return [(name, other) for name in ended for other in going_on]


def _pairs_pass(policy: dict, pairs: dict, reasons: list[dict]) -> None:
    sigmas = float(policy.get("equilibration_split_z", 3.0))
    for pair, cert in sorted(pairs.items()):
        a, b = (cert or {}).get("chains") or pair.split("|")
        split = (cert or {}).get("split") or {}
        if not split:
            reasons.append({"code": CERT_SPLIT_MISSING,
                            "detail": f"split evidence missing between {chain_words(a)} and {chain_words(b)}"})
        elif max(float(v) for v in split.values()) > sigmas:
            reasons.append({"code": CERT_SPLIT_DISAGREED, "detail": f"{chain_words(a)} and {chain_words(b)} disagree"})
        thresholds = structural_thresholds(policy, cert or {})
        for key, value in ((cert or {}).get("structural_split") or {}).items():
            judged = thresholds.get(key)
            if judged is not None and float(value) > judged["threshold"]:
                reasons.append({"code": CERT_STRUCTURAL_DISAGREED,
                                "detail": f"{chain_words(a)} and {chain_words(b)} disagree in structure, in {key}: {float(value):.4g} "
                                          f"over {judged['threshold']:.4g} ({judged['basis']})"})


STRUCTURAL_TREND_CONTRACT = "structural-trend-2"
TREND_MIN_POINTS = 3
DETRENDED_NOISE_MIN_DOF = 2
TREND_MAX_LAG_ONE = 0.8
_TREND_STRUCTURE = {
    "connected_fraction": lambda row, n: float(row["largest_component"]) / n,
    "component_count_per_node": lambda row, n: float(row["components"]) / n,
}


def _late_structure_line(rows: list, key: str, n: int, from_move=None) -> dict | None:
    late = ([row for row in rows if isinstance(row.get("move"), (int, float)) and row["move"] >= from_move]
            if from_move is not None else rows[int(len(rows) * 0.4):])
    points = [row for row in late if isinstance(row.get("largest_component"), (int, float))
              and isinstance(row.get("components"), (int, float))]
    if len(points) < TREND_MIN_POINTS:
        return None
    by_move = all(isinstance(row.get("move"), (int, float)) for row in points)
    t = np.asarray([float(row["move"]) if by_move else float(i) for i, row in enumerate(points)], dtype=float)
    y = np.asarray([_TREND_STRUCTURE[key](row, n) for row in points], dtype=float)
    centred = t - t.mean()
    sxx = float(centred @ centred)
    if not sxx > 0.0:
        return None
    slope = float(centred @ (y - y.mean())) / sxx
    return {"points": len(points), "slope": slope, "sxx": sxx, "window": float(t[-1] - t[0]),
            "residuals": y - y.mean() - slope * centred}


def _pooled_about_lines(lines: list) -> tuple[float | None, int]:
    squares = sum(float(line["residuals"] @ line["residuals"]) for line in lines)
    dof = sum(line["points"] - 2 for line in lines)
    return (squares / dof if dof >= DETRENDED_NOISE_MIN_DOF else None), dof


def detrended_structural_noise(envelope: dict, a: str, b: str) -> dict:
    n = max(1, int(envelope.get("n") or 1))
    chains = [CL.trajectory(envelope, a), CL.trajectory(envelope, b)]
    out: dict = {}
    for key in _TREND_STRUCTURE:
        lines = [line for line in (_late_structure_line(rows, key, n) for rows in chains) if line is not None]
        variance, _ = _pooled_about_lines(lines)
        out[key] = math.sqrt(2.0 * variance) if variance is not None else None
    return out


def trend_groups(chosen: dict) -> list[list[str]]:
    meet = list(chosen.get("meet") or [])
    return ([meet] if meet else []) + [[name] for name in chosen.get("decide") or [] if name not in meet]


def structural_trend(envelope: dict, policy: dict | None = None) -> dict:
    policy = policy or {}
    n = max(1, int(envelope.get("n") or 1))
    z_max = float(policy.get("equilibration_structural_trend_z", policy.get("equilibration_split_z", 3.0)))
    floors = structural_floors(policy)
    groups = trend_groups(deciding_chains(envelope, policy))
    readings: dict = {chain: {} for group in groups for chain in group}
    pooled: dict = {}
    at_rest = (envelope.get("proposal_model") or {}).get("dynamics_regime") == "zero_temperature"
    for group in groups:
        chains = {name: CL.trajectory(envelope, name) for name in group}
        late_from = {name: (((CL.record(envelope, name).get("accounting") or {}).get("late") or {}).get("from_move")
                            if at_rest else None) for name in group}
        pooled[pair_label(group)] = {}
        for key in _TREND_STRUCTURE:
            lines = {chain: _late_structure_line(rows, key, n, late_from[chain]) for chain, rows in chains.items()}
            fitted = [line for line in lines.values() if line is not None]
            variance, dof = _pooled_about_lines(fitted)
            squares = sum(float(line["residuals"] @ line["residuals"]) for line in fitted)
            lagged = sum(float(line["residuals"][:-1] @ line["residuals"][1:]) for line in fitted)
            lag_one = min(TREND_MAX_LAG_ONE, max(0.0, lagged / squares)) if squares > 0 else 0.0
            widen = math.sqrt((1.0 + lag_one) / (1.0 - lag_one))
            for chain, line in lines.items():
                if line is None:
                    readings[chain][key] = {"points": None, "drift": None, "drift_se": None, "z": None,
                                            "drifting": None}
                    continue
                drift = line["slope"] * line["window"]
                if variance is None:
                    readings[chain][key] = {"points": line["points"], "drift": drift, "drift_se": None, "z": None,
                                            "drifting": None}
                    continue
                se = line["window"] * math.sqrt(variance / line["sxx"]) * widen
                z = abs(drift) / se if se > 0 else None
                beyond = (z > z_max) if z is not None else drift != 0
                readings[chain][key] = {"points": line["points"], "drift": drift, "drift_se": se, "z": z,
                                        "drifting": bool(beyond and abs(drift) > floors[key])}
            pooled[pair_label(group)][key] = {"dof": dof, "lag_one": lag_one}
    return {"contract": STRUCTURAL_TREND_CONTRACT, "z_max": z_max, "floors": floors, "pooled": pooled,
            "window": "the rest reading's late window" if at_rest else "the late 60% of the points",
            "chains": readings}


def pair_label(names) -> str:
    return "|".join(str(name) for name in names)


def _trend_pass(trend: dict | None, reasons: list[dict]) -> None:
    if not trend:
        reasons.append({"code": CERT_STRUCTURAL_TREND_MISSING, "detail": "structural trend reading missing"})
        return
    floors = trend.get("floors") or {}
    for chain, observables in sorted((trend.get("chains") or {}).items()):
        for key, row in sorted((observables or {}).items()):
            if (row or {}).get("drifting"):
                reasons.append({"code": CERT_STRUCTURAL_TREND,
                                "detail": (f"{chain_words(chain)}'s {key} still drifting: {float(row['drift']):+.4g} over its "
                                           f"late window, "
                                           + (f"{float(row['z']):.3g} standard errors" if row.get("z") is not None
                                              else "with no spread about its line")
                                           + f" (over {float(trend.get('z_max')):.3g}) and over the floor "
                                             f"{float(floors.get(key)):.4g}")})


def _read_structural_trend(envelope: dict, policy: dict, health: dict) -> None:
    cert = health.get("equilibration")
    if cert is not None:
        pairs = {}
        for pair, other in (cert.get("pairs") or {}).items():
            a, b = other["chains"]
            pairs[pair] = dict(other, structural_noise_detrended=(
                detrended_structural_noise(envelope, a, b) if other.get("structural_split") else None))
        detrended = [row["structural_noise_detrended"] for row in pairs.values() if row.get("structural_noise_detrended")]
        keys = sorted({key for row in detrended for key in row})
        health["equilibration"] = dict(cert, pairs=pairs, structural_noise_detrended=(
            {key: min((row[key] for row in detrended if row.get(key) is not None), default=None) for key in keys}
            if detrended else None))
    health["structural_trend"] = structural_trend(envelope, policy)


def rest_pass(health: dict) -> tuple[bool, list[dict]]:
    rest = health.get("at_rest") or {}
    chains = rest.get("chains") or {}
    if not chains:
        return False, [{"code": CERT_REST_MISSING, "detail": "no move accounting to tell whether the chains rest"}]
    reasons = []
    for chain, row in chains.items():
        if row.get("at_rest") is None:
            reasons.append({"code": CERT_REST_MISSING, "detail": f"no late-window accounting for {chain_words(chain)}"})
        elif not row["at_rest"]:
            reasons.append({"code": CERT_NOT_AT_REST,
                            "detail": (f"{chain_words(chain)} still improving: its late window fell "
                                       f"{row['late_descent_share']:.3g} of its whole descent, over "
                                       f"{rest.get('limit_late_descent_share'):.3g}")})
    return not reasons, reasons


def rest_reading(envelope: dict, policy: dict | None = None) -> dict | None:
    regime = (envelope.get("proposal_model") or {}).get("dynamics_regime")
    if regime != "zero_temperature":
        return None
    limit = float((policy or {}).get("zero_temperature_rest_late_descent_share", REST_LATE_DESCENT_SHARE))
    n = max(1, int(envelope.get("n") or 1))
    chosen = deciding_chains(envelope, policy)
    chains = {name: _rest_row(CL.trajectory(envelope, name), CL.record(envelope, name).get("accounting"), limit, n)
              for name in chosen["decide"]}
    out = {"contract": "at-rest-3", "limit_late_descent_share": limit, "chains": chains, "pairs": None}
    if chosen["left_out"]:
        out["left_out"] = dict(chosen["left_out"])
    twins = list(chosen["meet"])
    if twins and all((chains.get(name) or {}).get("at_rest") for name in twins):
        a, b = twins
        out["pairs"] = {pair_label(twins): _minima(_end_energy(envelope, a), _end_energy(envelope, b), n)}
    return out


def _end_energy(envelope: dict, name: str):
    energy = CL.block(envelope, name).get("energy")
    return energy if isinstance(energy, (int, float)) else (CL.record(envelope, name).get("final") or {}).get("energy")


def _rest_row(trajectory: list, accounting: dict | None, limit: float, n: int) -> dict:
    late = ((accounting or {}).get("late") or {})
    rows = [r for r in trajectory if isinstance(r.get("energy"), (int, float))]
    start = late.get("from_move")
    tail = [r for r in rows if start is not None and int(r["move"]) >= int(start)]
    if not rows or not tail:
        return {"at_rest": None, "late_descent_share": None}
    whole = float(rows[0]["energy"]) - float(rows[-1]["energy"])
    recent = float(tail[0]["energy"]) - float(tail[-1]["energy"])
    share = 0.0 if recent <= 0 else (recent / whole if whole > 0 else float("inf"))
    counts = late.get("counts") or {}
    return {"at_rest": share <= limit, "late_descent_share": share,
            "late_descent": recent, "whole_descent": whole,
            "decreases_per_node": sum(int(v) for k, v in counts.items()
                                      if k.endswith(".neg.accepted")) / n,
            "late_accepted_per_node": sum(int(v) for k, v in counts.items()
                                          if k.endswith(".accepted")) / n}


def _minima(from_empty, given, n: int) -> dict | None:
    if not isinstance(from_empty, (int, float)) or not isinstance(given, (int, float)):
        return None
    gap = abs(float(from_empty) - float(given)) / n
    scale = max(1e-12, abs(float(from_empty)) / n, abs(float(given)) / n)
    return {"reading": "same_minimum" if gap <= 1e-6 * scale else "different_minima",
            "energy_per_node_gap": gap, "structural_split": None}


def failure_codes(failures) -> set[str]:
    return {str(f.get("code")) for f in (failures or []) if isinstance(f, dict) and f.get("code")}


def activity_label(health: dict) -> str:
    if health.get("regime") == "zero_temperature":
        return AT_REST
    activity = health.get("activity") or {}
    late = activity.get("accepted_topology_changes_per_node_late")
    cumulative = activity.get("accepted_topology_changes_per_node_cumulative")
    value = late if isinstance(late, (int, float)) else cumulative
    if isinstance(value, (int, float)) and float(value) <= 0.05:
        return EQUILIBRATED_LOW_ACTIVITY
    return EQUILIBRATED_ACTIVE


def terminal_at_ceiling(health: dict, failures: list[dict]) -> str:
    if health.get("numerics_ok") is False:
        return NUMERICAL_FAILURE
    codes = failure_codes(failures)
    if health.get("regime") == "zero_temperature":
        if CERT_NOT_AT_REST in codes or CERT_STRUCTURAL_TREND in codes:
            return RELAXING_AT_CEILING
        return OPERATIONAL_UNRESOLVED if codes else AT_REST
    activity = health.get("activity") or {}
    late = activity.get("accepted_topology_changes_per_node_late")
    retention = activity.get("late_edge_jaccard")
    if (isinstance(late, (int, float)) and float(late) <= 0.05
            and isinstance(retention, (int, float)) and float(retention) >= 0.999):
        return FROZEN_OR_ABSORBING
    if codes & CHAINS_DISAGREED_CODES:
        return METASTABLE_OR_NONMIXING
    if CERT_DRIFT in codes or CERT_STRUCTURAL_TREND in codes:
        return RELAXING_AT_CEILING
    if codes & {CERT_ESS_LOW, CERT_ESS_MISSING}:
        return INSUFFICIENT_EFFECTIVE_SAMPLES
    return OPERATIONAL_UNRESOLVED


def chunk_frozen(row: dict | None) -> bool:
    certificate = (row or {}).get("certificate") or {}
    if (certificate.get("at_rest") or {}).get("chains"):
        return False
    chains = [(certificate.get("chains") or {}).get(name) or {} for name in certificate.get("decide") or []]
    return bool(chains) and all(((chain.get("activity") or {}).get("frozen")) is True for chain in chains)


def frozen_twice(history: list[dict]) -> bool:
    return len(history) >= 2 and chunk_frozen(history[-1]) and chunk_frozen(history[-2])


def next_multiplier(policy: dict, current: int, cert: dict, cap: int) -> int:
    target_eff = float(policy.get("min_effective_samples", 8))
    eff = cert.get("effective_samples")
    sized = 2 * current
    if isinstance(eff, (int, float)) and float(eff) > 0:
        sized = max(sized, math.ceil(1.3 * current * target_eff / float(eff)))
    split = cert.get("split") or {}
    if split and max(float(v) for v in split.values()) > float(policy.get("equilibration_split_z", 3.0)):
        sized = max(sized, 2 * current)
    return min(int(cap), max(current + 1, int(sized)))


def _rung_activity(cert: dict | None) -> dict:
    rows = [((cert or {}).get("chains") or {}).get(name, {}).get("activity") or {} for name in (cert or {}).get("decide") or []]
    if not rows:
        return {"accepted_topology_changes_per_node_late": None, "accepted_topology_changes_per_node_cumulative": None,
                "late_edge_jaccard": None}

    def every(key, pick):
        values = [row.get(key) for row in rows]
        return pick(values) if all(isinstance(v, (int, float)) for v in values) else None

    return {"accepted_topology_changes_per_node_late": every("accepted_topology_changes_per_node_late", max),
            "accepted_topology_changes_per_node_cumulative": every("accepted_topology_changes_per_node_cumulative", max),
            "late_edge_jaccard": every("late_edge_jaccard", min)}


def _rung_stationarity(cert: dict | None) -> dict | None:
    rows = {name: ((cert or {}).get("chains") or {}).get(name, {}).get("stationarity")
            for name in (cert or {}).get("decide") or []}
    if not rows or any(row is None for row in rows.values()):
        return None
    name = max(rows, key=lambda key: abs(float(rows[key]["normalized_drift"])))
    return dict(rows[name], chain=name)


def chains_health(envelope: dict, policy: dict | None = None, numerics_ok: bool = True) -> dict:
    from graph_scale_dynamics.measurements.certificate import equilibration_certificate
    chosen = deciding_chains(envelope, policy)
    cert = (equilibration_certificate(envelope, chosen["decide"], chosen["meet"])
            if numerics_ok and chosen["decide"] else None)
    if cert is not None:
        cert["twin_chains"] = list(chosen["twin_chains"])
        cert["left_out"] = dict(chosen["left_out"])
    return {"equilibration": cert, "stationarity": _rung_stationarity(cert), "activity": _rung_activity(cert)}


def inline_health(envelope: dict, policy: dict | None = None) -> dict:
    n = int(envelope["n"])
    energies = [float(row.get("energy", 0.0)) for name in CL.ran_names(envelope) for row in CL.trajectory(envelope, name)]
    finals = [float((CL.record(envelope, name).get("final") or {}).get("energy", 0.0)) for name in CL.ran_names(envelope)]
    numerics_ok = all(math.isfinite(e) for e in energies + finals)
    rung = chains_health(envelope, policy, numerics_ok)
    rest = rest_reading(envelope, policy)
    cert = rung["equilibration"]
    if rest and rest.get("pairs") and cert:
        for pair, reading in rest["pairs"].items():
            if reading is not None:
                reading["structural_split"] = ((cert.get("pairs") or {}).get(pair) or {}).get("structural_split")
    health = {
        "n": n,
        "numerics_ok": numerics_ok,
        "regime": "zero_temperature" if rest is not None else None,
        "at_rest": rest,
        "equilibration": cert,
        "stationarity": rung["stationarity"],
        "sweeps_multiplier": int(envelope.get("sweeps_multiplier", 1)),
        "activity": rung["activity"],
        "source": "inline-one-shot-2",
    }
    if numerics_ok:
        _read_structural_trend(envelope, policy or {}, health)
    return health
