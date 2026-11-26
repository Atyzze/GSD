from __future__ import annotations

import time

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.scaleflow.engine_door import RestoreInterrupted, run_simulation
from graph_scale_dynamics.scaleflow import equilibration as eq

ONE_SHOT_CONTRACT = eq.SAMPLING_CURRENT
ONE_SHOT_CONTRACTS = (eq.SAMPLING_1, ONE_SHOT_CONTRACT)

RESUME_CONTRACT = "one-shot-resume-1"
SAVE_EVERY_UNITS = 8 * 10 ** 12


class StopRequested(Exception):
    pass


def shared_numbers(edges, n: int):
    if not edges:
        return edges
    ids = list(range(int(n)))
    return [(ids[u], ids[v]) for u, v in edges]


def starts_of_the_chunk(more_given: list, checkpoint, n: int, seed: int) -> list[dict]:
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    running = {block.get("start") for block in (checkpoint or {}).get("chains") or []}
    out = []
    for start in more_given:
        given = {"name": str(start["name"]), "family": str(start["family"]),
                 **({"kernel": str(start["kernel"])} if start.get("kernel") else {})}
        if given["name"] not in running:
            given["edges"] = shared_numbers(control_family_edges(given["family"], int(n), seed=int(seed)), n)
            if given["edges"] is None:
                raise ValueError(f"the start {given['name']!r} ({given['family']}) cannot be built at N={n}")
        out.append(given)
    return out


def given_start_of_the_chunk(given_start, checkpoint, n: int, seed: int):
    if given_start is None or given_start.get("edges") is not None or not given_start.get("family"):
        return given_start
    kernel = {"kernel": str(given_start["kernel"])} if given_start.get("kernel") else {}
    if CL.checkpoint_block(checkpoint, CL.GIVEN):
        return {"family": str(given_start["family"]), **kernel}
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    edges = control_family_edges(str(given_start["family"]), int(n), seed=int(seed))
    if edges is None:
        raise ValueError(f"given_start family {given_start['family']!r} cannot be built at N={n}")
    return {"family": str(given_start["family"]), "edges": shared_numbers(edges, n), **kernel}


def run_one_shot(candidate_spec: dict, n: int, seed: int, *, one_shot: dict,
                 initial_multiplier: int = 1, record_points: int = 240,
                 proposal_locality: float = 0.0, engine_contract_version: str | None = None,
                 clock=time.monotonic, simulate=None, resume: dict | None = None, on_chunk=None,
                 stop_file: str | None = None, save_every_units: int | None = SAVE_EVERY_UNITS) -> dict:
    simulate = simulate or run_simulation
    if str(one_shot.get("contract")) not in ONE_SHOT_CONTRACTS:
        raise ValueError(f"unsupported one-shot contract {one_shot.get('contract')!r}")
    one_shot = {**one_shot, "contract": ONE_SHOT_CONTRACT}
    declared_sweeps = int(candidate_spec["dynamics"]["sweeps"])
    cap = max(1, int(one_shot["max_sweeps_multiplier"]))
    required = max(1, int(one_shot["required_consecutive_passes"]))
    budget = int(one_shot["work_budget"])
    weights = work_weights(one_shot)
    weights_in_order = [weights[name] for name in WORK_PARTS]
    mean_degree_cap = one_shot.get("mean_degree_cap")
    given_start = one_shot.get("given_start") or None
    more_given = list(one_shot.get("more_given") or [])

    def more_starts(checkpoint):
        return starts_of_the_chunk(more_given, checkpoint, n, seed)

    def declared_start(checkpoint):
        return given_start_of_the_chunk(given_start, checkpoint, n, seed)
    t0 = clock()
    spent_seconds, attempts_before = 0.0, 0
    multiplier = max(1, min(cap, int(initial_multiplier)))
    checkpoint = None
    history: list[dict] = []
    consecutive = 0
    if resume is not None:
        if str(resume.get("contract")) != RESUME_CONTRACT:
            raise ValueError(f"unsupported one-shot resume contract {resume.get('contract')!r}")
        spent_seconds = max(0.0, float(resume.get("seconds_spent") or 0.0))
        attempts_before = max(1, int(resume.get("attempts") or 1))
        checkpoint = resume["checkpoint"]
        multiplier = max(1, min(cap, int(resume["multiplier"])))
        consecutive = int(resume.get("consecutive") or 0)
        history = [dict(row) for row in resume.get("history") or []]
    envelope: dict | None = whole_chunk_of(resume)
    health = eq.inline_health(envelope, one_shot) if envelope is not None else None
    terminal_reason = "ceiling"
    predicted = None if resume is None else resume.get("predicted")
    cut_inside = None
    units_at_the_last_save = units_of_a_checkpoint(checkpoint, weights_in_order)
    while True:
        stop_at = work_stop(budget if history and envelope is not None else None, save_every_units,
                            units_at_the_last_save)
        try:
            chunk = simulate(
                candidate_spec, n, seed, record_points=record_points,
                engine_contract_version=engine_contract_version,
                target_sweeps=declared_sweeps * multiplier,
                resume_checkpoint=checkpoint, proposal_locality=proposal_locality,
                mean_degree_cap=mean_degree_cap,
                **({"stop_file": stop_file} if stop_file is not None else {}),
                **({"given_start": declared_start(checkpoint)} if given_start is not None else {}),
                **({"more_given": more_starts(checkpoint)} if more_given else {}),
                **({"work_budget": stop_at, "work_weights": weights_in_order} if stop_at is not None else {}),
            )
        except RestoreInterrupted as interrupted:
            if interrupted.reason == "stop_requested":
                raise StopRequested(f"stopped rebuilding the chunk at x{multiplier}") from interrupted
            raise
        termination = chunk.get("termination") or {}
        if chunk.get("stopped"):
            at_the_budget = (termination.get("reason") == "work_budget" and history and envelope is not None
                             and int(chunk["work_units"]) >= budget)
            if at_the_budget:
                terminal_reason = "budget"
                cut_inside = {"multiplier": int(multiplier), "chain": termination.get("chain_stopped"),
                              "at_move": int(termination["at_move"]), "units": int(chunk["work_units"])}
                break
            if on_chunk is not None:
                on_chunk({"contract": RESUME_CONTRACT, "checkpoint": chunk["sampling_checkpoint"],
                          "multiplier": multiplier, "consecutive": consecutive, "history": history,
                          "seconds_spent": clock() - t0 + spent_seconds, "attempts": attempts_before + 1,
                          "in_chunk": True, **({"predicted": predicted} if predicted is not None else {}),
                          **({"whole": {"checkpoint": envelope["sampling_checkpoint"],
                                        "envelope": without_its_checkpoint(envelope)}}
                             if history and envelope is not None else {})})
            if termination.get("reason") != "work_budget":
                raise StopRequested(f"stopped at move {termination.get('at_move')} of the chunk at x{multiplier}")
            checkpoint = chunk["sampling_checkpoint"]
            units_at_the_last_save = int(chunk["work_units"])
            continue
        envelope = chunk
        given_termination = CL.record(envelope, CL.GIVEN).get("termination") or {}
        given_reasons = {name: (CL.record(envelope, name).get("termination") or {}).get("reason")
                        for name in CL.more_names(envelope)}
        health = eq.inline_health(envelope, one_shot)
        passed, failures = eq.certificate_pass(one_shot, health)
        chunk_cert = health.get("equilibration") or {}
        accounting = CL.move_accounting(envelope)
        history.append({
            "multiplier": multiplier,
            "cumulative_sweeps": int(envelope.get("cumulative_sweeps") or 0),
            "passed": bool(passed) and termination.get("reason") == "completed",
            "failures": failures,
            "effective_samples": (health.get("equilibration") or {}).get("effective_samples"),
            "certificate": {"asked": eq.certificate_asks(one_shot),
                            "split": chunk_cert.get("split"),
                            "structural_split": chunk_cert.get("structural_split"),
                            "structural_limits": eq.structural_limits(one_shot),
                            "structural_noise": chunk_cert.get("structural_noise"),
                            "structural_thresholds": eq.structural_thresholds(one_shot, chunk_cert),
                            "at_rest": health.get("at_rest"),
                            "tau_int_sweeps": chunk_cert.get("tau_int_sweeps"),
                            "effective_samples": chunk_cert.get("effective_samples"),
                            "stationarity_drift": (health.get("stationarity") or {}).get("normalized_drift"),
                            "activity": health.get("activity"),
                            **_every_chain_certificate(one_shot, chunk_cert),
                            "structural_noise_detrended": chunk_cert.get("structural_noise_detrended"),
                            "structural_trend": health.get("structural_trend")},
            "mean_degree": float((CL.record(envelope, CL.FROM_EMPTY).get("final") or {}).get("mean_degree", 0.0)),
            "work_units": units_of(seed_work_parts(accounting), weights),
            "moves": seed_moves(accounting),
            **({"predicted_units": predicted} if predicted is not None else {}),
            "wall_seconds_so_far": clock() - t0 + spent_seconds,
            "termination": termination.get("reason"),
            "given_termination": given_termination.get("reason"),
            **({"more_given_terminations": given_reasons} if given_reasons else {}),
            "timing": CL.timing(envelope),
        })
        if termination.get("reason") == "mean_degree_cap":
            terminal_reason = "mean_degree_cap"
            cap_chain = str(termination.get("chain") or CL.FROM_EMPTY)
            break
        consecutive = consecutive + 1 if passed else 0
        if consecutive >= required:
            terminal_reason = "completed"
            break
        if eq.frozen_twice(history):
            terminal_reason = "frozen"
            break
        if multiplier >= cap:
            terminal_reason = "completed" if passed else "ceiling"
            break
        cert = health.get("equilibration") or {}
        following = eq.next_multiplier(one_shot, multiplier, cert, cap)
        predicted = predicted_chunk_units(history, envelope, declared_sweeps * following, int(n))
        if int(history[-1]["work_units"]) + predicted > budget:
            terminal_reason = "budget"
            break
        checkpoint = envelope.get("sampling_checkpoint")
        multiplier = following
        units_at_the_last_save = int(history[-1]["work_units"])
        if on_chunk is not None:
            on_chunk({"contract": RESUME_CONTRACT, "checkpoint": checkpoint, "multiplier": multiplier,
                      "consecutive": consecutive, "history": history, "predicted": predicted,
                      "seconds_spent": clock() - t0 + spent_seconds, "attempts": attempts_before + 1,
                      "whole_envelope": without_its_checkpoint(envelope)})

    last = history[-1]
    if terminal_reason == "completed":
        classification = eq.activity_label(health)
    elif terminal_reason == "mean_degree_cap":
        classification = eq.MEAN_DEGREE_CAP_TERMINAL
    else:
        classification = eq.terminal_at_ceiling(health, last["failures"])
    envelope["sampling_checkpoints"] = history
    envelope["certificate_chains"] = eq.deciding_chains(envelope, one_shot)
    from graph_scale_dynamics.scaleflow.descent import descent_record
    envelope["descent"] = descent_record(candidate_spec, n, envelope)
    from graph_scale_dynamics.scaleflow.couplings import couplings_at
    envelope["couplings"] = couplings_at(candidate_spec, n)
    envelope["rung_terminal"] = {
        "contract": ONE_SHOT_CONTRACT,
        "reason": terminal_reason,
        "classification": classification,
        "final_multiplier": last["multiplier"],
        "chunks": len(history),
        "passes_in_a_row": consecutive,
        "wall_seconds": clock() - t0 + spent_seconds,
        "work": work_record(history, budget, one_shot, predicted if terminal_reason == "budget" else None,
                            cut_inside),
        "mean_degree_cap": mean_degree_cap,
        "failures": last["failures"],
        "at_rest": health.get("at_rest"),
        "timing": {"chain_seconds": {
            name: sum(float(((row.get("timing") or {}).get("chain_seconds") or {}).get(name) or 0.0)
                      for row in history)
            for name in [str(row.get("start")) for row in CL.records(envelope)]}},
    }
    if more_given or (given_start or {}).get("name"):
        envelope["rung_terminal"]["given_chains"] = _given_record(one_shot, envelope)
    if terminal_reason == "mean_degree_cap":
        envelope["rung_terminal"]["mean_degree_cap_chain"] = cap_chain
    if resume is not None:
        envelope["rung_terminal"]["resumed"] = {"attempts_before": attempts_before,
                                                "seconds_before": spent_seconds,
                                                "chunks_before": len(resume.get("history") or [])}
    return envelope


WORK_UNIT_CONTRACT = "gsd-work-unit-1"
WORK_RECORD_CONTRACT = "gsd-seed-work-1"
WORK_PARTS = ("moves", "evaluations", "changes", "lists", "entries", "tests")


def work_weights(one_shot: dict) -> dict:
    unit = one_shot.get("work_unit") or {}
    if str(unit.get("contract")) != WORK_UNIT_CONTRACT:
        raise ValueError(f"a one-shot job weighs its work by a unit of {WORK_UNIT_CONTRACT}, not "
                         f"{unit.get('contract')!r}")
    weights = unit.get("weights") or {}
    if set(weights) != set(WORK_PARTS) or any(isinstance(weights[name], bool) or not isinstance(weights[name], int)
                                             or weights[name] < 0 for name in WORK_PARTS):
        raise ValueError(f"the work unit weighs each of {', '.join(WORK_PARTS)} by a whole number of at least 0")
    return {name: int(weights[name]) for name in WORK_PARTS}


def units_of(parts: dict | None, weights: dict) -> int:
    return int(sum(int(weights[name]) * int((parts or {}).get(name) or 0) for name in WORK_PARTS))


def seed_moves(accounting: dict) -> int:
    return int((seed_work_parts(accounting) or {}).get("moves") or 0)


def predicted_chunk_units(history: list[dict], envelope: dict, target_sweeps: int, n: int) -> int:
    last = history[-1]
    before = history[-2] if len(history) > 1 else {"work_units": 0, "moves": 0}
    units = int(last["work_units"]) - int(before.get("work_units") or 0)
    moves = int(last["moves"]) - int(before.get("moves") or 0)
    running = sum(1 for name in CL.ran_names(envelope) if not CL.block(envelope, name).get("ended"))
    coming = max(0, int(target_sweeps) - int(last["cumulative_sweeps"])) * int(n) * running
    if moves <= 0 or coming <= 0:
        return 0
    return -(-units * coming // moves)


def work_record(history: list[dict], budget: int, one_shot: dict, refused: int | None,
                cut_inside: dict | None = None) -> dict:
    first = history[0]
    return {"contract": WORK_RECORD_CONTRACT, "unit": dict(one_shot.get("work_unit") or {}),
            "budget": int(budget), "units": int(history[-1]["work_units"]), "moves": int(history[-1]["moves"]),
            "first_chunk": {"units": int(first["work_units"]), "moves": int(first["moves"]),
                            "multiplier": int(first["multiplier"])},
            **({"next_chunk_predicted": int(refused)} if refused is not None else {}),
            **({"cut_inside_a_chunk": dict(cut_inside)} if cut_inside is not None else {})}


def work_stop(budget: int | None, save_every_units: int | None, units_at_the_last_save: int) -> int | None:
    save_at = None if not save_every_units else int(units_at_the_last_save) + int(save_every_units)
    found = [limit for limit in (budget, save_at) if limit is not None]
    return min(found) if found else None


def units_of_a_checkpoint(checkpoint: dict | None, weights_in_order: list) -> int:
    from graph_scale_dynamics.engine.engine import units_of_an_accounting
    return sum(units_of_an_accounting(block.get("accounting"), weights_in_order)
               for block in (checkpoint or {}).get("chains") or [])


def without_its_checkpoint(envelope: dict) -> dict:
    return {key: value for key, value in envelope.items() if key != "sampling_checkpoint"}


def whole_chunk_of(resume: dict | None) -> dict | None:
    if not resume or not resume.get("history"):
        return None
    whole = resume.get("whole")
    if resume.get("in_chunk"):
        if not isinstance(whole, dict) or not isinstance(whole.get("envelope"), dict):
            return None
        return dict(whole["envelope"], sampling_checkpoint=whole["checkpoint"])
    if not isinstance(resume.get("whole_envelope"), dict):
        return None
    return dict(resume["whole_envelope"], sampling_checkpoint=resume["checkpoint"])


def seed_work(accounting: dict) -> int | None:
    found = [block.get("work") for block in (accounting or {}).values() if isinstance(block, dict)]
    if not found or any(not isinstance(value, int) for value in found):
        return None
    return int(sum(found))


def seed_work_parts(accounting: dict) -> dict | None:
    blocks = [block.get("parts") for block in (accounting or {}).values() if isinstance(block, dict)]
    if not blocks or any(not isinstance(parts, dict) for parts in blocks):
        return None
    out: dict = {}
    for parts in blocks:
        for name, value in parts.items():
            out[name] = out.get(name, 0) + int(value)
    return out


def _every_chain_certificate(policy: dict, cert: dict) -> dict:
    if not cert:
        return {}
    return {"decide": list(cert.get("decide") or []), "meet": list(cert.get("meet") or []),
            "twin_chains": list(cert.get("twin_chains") or []),
            "left_out": dict(cert.get("left_out") or {}), "fewest_samples": cert.get("fewest_samples"),
            "chains": {name: {"effective_samples": row.get("effective_samples"),
                              "tau_int_sweeps": row.get("tau_int_sweeps"),
                              "stationarity_drift": (row.get("stationarity") or {}).get("normalized_drift"),
                              "activity": row.get("activity")}
                       for name, row in (cert.get("chains") or {}).items()},
            "pairs": {pair: {"chains": row.get("chains"), "split": row.get("split"),
                             "structural_split": row.get("structural_split"),
                             "structural_noise": row.get("structural_noise"),
                             "structural_noise_detrended": row.get("structural_noise_detrended"),
                             "structural_thresholds": eq.structural_thresholds(policy, row)}
                      for pair, row in (cert.get("pairs") or {}).items()}}


def _given_record(policy: dict, envelope: dict) -> list[dict]:
    first, given = policy.get("given_start") or {}, CL.record(envelope, CL.GIVEN)
    rows = [{"name": first.get("name"), "init": given.get("init"),
             "termination": (given.get("termination") or {}).get("reason"),
             "ended_at_cap": bool(CL.block(envelope, CL.GIVEN).get("ended"))}]
    for start in policy.get("more_given") or []:
        name = str(start["name"])
        given = CL.record(envelope, name)
        rows.append({"name": name, "init": given.get("init"),
                     "termination": (given.get("termination") or {}).get("reason"),
                     "ended_at_cap": bool(CL.block(envelope, name).get("ended")),
                     **({"skipped": True} if given.get("skipped") else {})})
    return rows


def analyze_one_shot_envelope(envelope: dict, *, seed: int = 0, analyzer=None):
    from graph_scale_dynamics.measurements.analysis import analyze_envelope
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    analyzer = analyzer or analyze_envelope

    terminal = envelope.get("rung_terminal") or {}
    rung_at_cap = terminal.get("reason") == "mean_degree_cap"
    ended = sorted(name for name, why in eq.left_out_chains(envelope).items() if why == eq.ENDED_AT_CAP)
    if rung_at_cap or CL.FROM_EMPTY in ended:
        code = str(terminal.get("classification") if rung_at_cap else eq.MEAN_DEGREE_CAP_TERMINAL)
        at_sweep = ((CL.block(envelope, CL.FROM_EMPTY).get("ended") or envelope.get("termination") or {})
                    .get("at_sweep"))
        refusal = {"valid": False, "refusal": code,
                   "reason": f"mean degree crossed the window cap at sweep {at_sweep}"}
        health = eq.inline_health(envelope)
        final = CL.record(envelope, CL.FROM_EMPTY).get("final") or {}
        health.update({"edge_count": final.get("edge_count"), "mean_degree": final.get("mean_degree"),
                       "max_degree": final.get("max_degree"), "peak_edge_count": final.get("peak_edge_count")})
        metrics = {"analysis_version": ANALYSIS_VERSION, "health": health,
                   "d_V": dict(refusal), "d_s": dict(refusal), "d_B": dict(refusal), "d_w": dict(refusal),
                   "log_diameter_flag": None, "geometry_snapshot_mode": "not_measured",
                   **({"limit_refusal": code} if rung_at_cap else {})}
        curves = {}
    else:
        metrics, curves = analyzer(envelope, seed=seed)
    metrics.update(return_readings((curves or {}).get("return_probability")))
    health = metrics.setdefault("health", {})
    health["termination"] = envelope.get("termination")
    health["rung_terminal"] = envelope.get("rung_terminal")
    health["sampling_checkpoints"] = envelope.get("sampling_checkpoints")
    health["peak_edge_count"] = (CL.record(envelope, CL.FROM_EMPTY).get("final") or {}).get("peak_edge_count")
    from graph_scale_dynamics.measurements.structure_census import census, log_diameter_state
    n = int(envelope["n"])
    ran = {name: CL.block(envelope, name) for name in CL.ran_names(envelope)}
    metrics["census"] = {name: census(n, CL.sorted_edges(envelope, name) if name == CL.FROM_EMPTY
                                      else block.get("edge_list") or [])
                         for name, block in ran.items()}
    if ended:
        metrics["ended_at_cap"] = ended
    state = log_diameter_state(metrics, metrics["census"].get(CL.FROM_EMPTY))
    metrics["log_diameter_flag_estimator"] = metrics.get("log_diameter_flag")
    metrics["log_diameter_flag"] = state["flag"]
    metrics["log_diameter"] = state
    metrics["move_accounting"] = CL.move_accounting(envelope)
    metrics["work"] = seed_work(metrics["move_accounting"])
    metrics["work_parts"] = seed_work_parts(metrics["move_accounting"])
    metrics["descent"] = envelope.get("descent")
    metrics["couplings"] = envelope.get("couplings")
    read = {} if rung_at_cap else {name: block for name, block in ran.items()
                                   if name != CL.FROM_EMPTY and name not in ended}
    chain_curves: dict = {}
    metrics["chain_probes"] = {}
    for name, block in read.items():
        summary = chain_probes(n, block.get("edge_list") or [], seed=seed, name=None if name == CL.GIVEN else name,
                               curves=chain_curves.setdefault(name, {}))
        summary.update(return_readings(chain_curves[name].get("return_probability")))
        chain_state = log_diameter_state(summary, metrics["census"].get(name))
        summary["log_diameter_flag_estimator"] = summary.get("log_diameter_flag")
        summary["log_diameter_flag"] = chain_state["flag"]
        summary["log_diameter"] = chain_state
        metrics["chain_probes"][name] = summary
    if chain_curves:
        curves = dict(curves or {}, chains=chain_curves)
    metrics["curvature"] = curvature_reading(n, envelope, metrics, read, ended)
    return metrics, curves


def return_readings(curve) -> dict:
    out: dict = {}
    if not curve:
        return out
    try:
        from graph_scale_dynamics.measurements.spectral_whole_range import whole_range
        out["d_s_whole_range"] = whole_range(curve)
    except Exception as exc:  # noqa: BLE001
        out["d_s_whole_range"] = {"whole_range_comparable": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from graph_scale_dynamics.measurements.d_s_shape import shape
        out["d_s_shape"] = shape(curve)
    except Exception as exc:  # noqa: BLE001
        out["d_s_shape"] = {"measured": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


def curvature_reading(n: int, envelope: dict, metrics: dict, read: dict, ended: list | None = None) -> dict:
    from graph_scale_dynamics.measurements.curvature_probe import CONTRACT, read as read_curvature
    at_cap = {"contract": CONTRACT, "measured": False, "reason": "the chain ended at the mean-degree cap"}
    if metrics.get("limit_refusal"):
        return {CL.FROM_EMPTY: dict(at_cap, reason="the rung ended at the mean-degree cap")}
    out = {CL.FROM_EMPTY: (dict(at_cap) if CL.FROM_EMPTY in (ended or [])
                           else read_curvature(n, CL.sorted_edges(envelope, CL.FROM_EMPTY)))}
    for name, block in read.items():
        out[name] = read_curvature(n, block.get("edge_list") or [])
    seconds = sum(float(reading.get("seconds") or 0.0) for reading in out.values())
    metrics.setdefault("probe_seconds", {})["kappa"] = round(seconds, 4)
    return out


PROBE_VALUE = {"d_s": "d_s", "d_V": "d_V_window", "d_B": "d_B", "d_w": "d_w"}
CHAIN_PROBES_CONTRACT = "gsd-chain-probes-1"
DIAMETER_KEYS = ("log_diameter_flag", "diameter_lower_bound", "diameter_upper_bound")


def chain_probes(n: int, edges, *, seed: int, name: str | None = None, curves: dict | None = None) -> dict:
    import numpy as np

    from graph_scale_dynamics.domain.randomness import derive_seed
    from graph_scale_dynamics.measurements.estimators import _measure_graph
    from graph_scale_dynamics.measurements.version import PROBE_STREAM
    stream = (PROBE_STREAM, int(seed), int(n)) + ((str(name),) if name is not None else ())
    rng = np.random.default_rng(derive_seed("probes-of-a-given-graph", *stream) % (2 ** 63))
    result, measured = _measure_graph(int(n), edges, rng, measure_geometry=True)
    if curves is not None:
        curves.update(measured)
    out = {"contract": CHAIN_PROBES_CONTRACT, "component": result.get("component"),
           "probe_seconds": result.get("probe_seconds"), "half_volume_radius": result.get("half_volume_radius"),
           **{key: result.get(key) for key in DIAMETER_KEYS}}
    for probe, key in PROBE_VALUE.items():
        block = result.get(probe) or {}
        value = block.get(key)
        out[probe] = {"valid": bool(block.get("valid")) and isinstance(value, (int, float)),
                      "value": value if isinstance(value, (int, float)) else None,
                      "se": block.get("se"), "refusal": block.get("refusal")}
        if isinstance(block.get("measured_se"), (int, float)):
            out[probe]["measured_se"] = block["measured_se"]
    if isinstance(result.get("small_world"), bool):
        out["small_world"] = result["small_world"]
    return out
