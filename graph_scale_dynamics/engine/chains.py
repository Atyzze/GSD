from __future__ import annotations

import math
import time

from graph_scale_dynamics.domain.chain_list import is_a_twin
from graph_scale_dynamics.domain.randomness import rng as stream_rng, stream_id
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.engine.summaries import late_stats, structural_summary, tuple_state

CHECKPOINT_CONTRACT = "adaptive-chain-checkpoint-3"
FROM_EMPTY = "empty"
GIVEN = "given"
RESERVED = frozenset({FROM_EMPTY, GIVEN})
FROM_EMPTY_STREAM = "simulation-declared-chain"
GIVEN_STREAM = "simulation-control-chain"
GIVEN_INITIALISATION_STREAM = "simulation-control-initialization"


def declared_more(more_given) -> list[dict]:
    out, names = [], set()
    for start in more_given or []:
        name = start.get("name") if isinstance(start, dict) else None
        if not isinstance(name, str) or not name or name in names or name in RESERVED:
            raise ValueError(f"each given start past the first has a name of its own, neither "
                             f"{sorted(RESERVED)}: {start!r}")
        if not start.get("family"):
            raise ValueError(f"the start {name!r} names no family: a given start past the first is a declared graph")
        names.add(name)
        out.append(dict(start))
    return out


def chain_list(given_start, more_given) -> list[dict]:
    chains = [{"name": FROM_EMPTY, "start": None, "kernel": None, "label": FROM_EMPTY,
               "stream": (FROM_EMPTY_STREAM,)}]
    chains.append({"name": GIVEN, "start": given_start, "kernel": E.given_start_kernel(given_start),
                   "label": E.given_start_name(given_start), "stream": (GIVEN_STREAM,)})
    for start in declared_more(more_given):
        chains.append({"name": start["name"], "start": start, "kernel": E.given_start_kernel(start),
                       "label": E.given_start_name(start), "stream": (GIVEN_STREAM, start["name"])})
    for chain in chains:
        chain["is_twin"] = is_a_twin(chain["name"], chain["label"])
    return chains


def every_twin_ended(chains: list[dict], blocks: dict, incoming: dict) -> bool:
    twins = [chain["name"] for chain in chains if chain["is_twin"]]
    return bool(twins) and all((blocks.get(name) or incoming.get(name) or {}).get("ended") for name in twins)


def stream_of(chain: dict, stream_context: tuple) -> tuple:
    label, *named = chain["stream"]
    return (label, *stream_context, *named)


def final_of(state, energy, peak: int, n: int) -> dict:
    lean = vars(state).get("degrees")
    degrees = lean if lean is not None else [len(neighbours) for neighbours in state.adj]
    edges = len(state.edge_list) if lean is not None else len(state.edges)
    return {"edge_count": edges, "peak_edge_count": peak, "mean_degree": 2 * edges / n,
            "max_degree": max(degrees) if degrees else 0, "min_degree": min(degrees) if degrees else 0,
            "isolated_vertices": sum(1 for degree in degrees if degree == 0), "energy": energy,
            "ledgers": {op: (value if op in state.required_ops else None) for op, value in state.ledgers.items()}}


def acceptance_of(attempted, proposed, accepted) -> dict:
    attempted, proposed, accepted = E._counter(attempted), E._counter(proposed), E._counter(accepted)
    return {"attempted": attempted, "proposed": proposed, "accepted": accepted,
            "rate": {k: (accepted[k] / proposed[k]) if proposed[k] else None for k in proposed},
            "feasible_fraction": {k: (proposed[k] / attempted[k]) if attempted[k] else None for k in attempted}}


def chain_block(chain: dict, state, energy, rng, attempted, proposed, accepted, trajectory, peak, late_change,
                accounting, n: int) -> dict:
    return {"start": chain["name"], "init": chain["label"], "kernel": chain["kernel"],
            "edge_list": list(state.edge_list), "energy": energy, "rng_state": rng.getstate(),
            "attempted": attempted, "proposed": proposed, "accepted": accepted, "trajectory": trajectory,
            "late_change": late_change, "peak_edge_count": peak,
            "non_edge_fast_path_hits": state.non_edge_fast_path_hits,
            "non_edge_exact_fallbacks": state.non_edge_exact_fallbacks,
            "accounting": accounting if accounting is not None else E.new_accounting(),
            "final": final_of(state, energy, peak, n), "final_structure": structural_summary(state, n)}


def chain_record(chain: dict, block: dict | None, *, n: int, sweeps: int, termination, seconds: float,
                 stream: str, skipped_reason) -> dict:
    trajectory = list((block or {}).get("trajectory") or [])
    late = trajectory[-max(3, len(trajectory) // 3):]
    ran = bool(late)
    return {"start": chain["name"], "init": chain["label"], "kernel": chain["kernel"],
            "sweeps": sweeps if ran else 0, "termination": termination,
            "skipped": not ran, "skipped_reason": None if ran else skipped_reason,
            "ended": (block or {}).get("ended"),
            "late": late_stats(late, n) if ran else {},
            "final": (block or {}).get("final") if ran else None,
            "final_structure": (block or {}).get("final_structure") if ran else None,
            "acceptance": acceptance_of((block or {}).get("attempted"), (block or {}).get("proposed"),
                                        (block or {}).get("accepted")),
            "accepted_moves": sum(E._counter((block or {}).get("accepted")).values()) if ran else 0,
            "accounting": (block or {}).get("accounting") or E.new_accounting(),
            "non_edge_fast_path_hits": int((block or {}).get("non_edge_fast_path_hits") or 0),
            "non_edge_exact_fallbacks": int((block or {}).get("non_edge_exact_fallbacks") or 0),
            "seconds": seconds, "stream": stream}


def stopped_envelope(identity: dict, termination: dict, chain: str, segment_start: int, points: int,
                     blocks: list[dict]) -> dict:
    checkpoint = dict(identity, cumulative_moves=int(segment_start), chains=blocks,
                      in_segment={"chain": chain, "segment_start": int(segment_start), "points": int(points),
                                  "next_move": int(termination["at_move"]) + 1})
    return {"termination": dict(termination), "stopped": True, "sampling_checkpoint": checkpoint}


def _fresh_state(chain: dict, *, ctx, runner, chain_ctx, rng_of, n: int, empty_energy):
    state = E.GraphState(n)
    state.require_ops(ctx.spec_ops)
    if chain["name"] == FROM_EMPTY:
        return state, empty_energy
    edges = E.given_start_edges(chain["start"], n)
    if edges is not None:
        return E.declared_given(chain_ctx, runner, edges, state, empty_energy, ctx.apply_edge)
    if chain["name"] != GIVEN:
        raise ValueError(f"the start {chain['name']!r} carries no edges to start from")
    target_edges = min(ctx.max_edges, (E.GIVEN_START_MEAN_DEGREE * n) // 2)
    if ctx.mean_degree_cap is not None:
        target_edges = min(target_edges, int(math.floor(float(ctx.mean_degree_cap) * n / 2.0)))
    rng = rng_of(GIVEN_INITIALISATION_STREAM)
    init_random_graph = getattr(runner, "init_random_graph", None)
    if init_random_graph is not None:
        return init_random_graph(ctx, rng, state, empty_energy, target_edges)
    energy = empty_energy
    while len(state.edges) < target_edges:
        u, v = state.sample_non_edge(rng)
        deltas, delta_h = ctx.apply_edge(state, u, v, True, energy)
        state.apply(u, v, True, deltas)
        energy += delta_h
    return state, energy


def run_chains(*, ctx, runner, chains: list[dict], stream_context: tuple, checkpoint: dict, segment: dict,
               start_move: int, record_points: int, late_from_move: int, sweeps: int, stop_file,
               restore, empty_energy, identity: dict, work_budget: int | None = None, work_weights=None) -> dict:
    n = int(ctx.n)
    incoming = {block.get("start"): block for block in (checkpoint or {}).get("chains") or []}
    names = [chain["name"] for chain in chains]
    stopped_in = str((segment or {}).get("chain") or "")
    if segment and stopped_in not in names:
        raise ValueError(f"the checkpoint stopped in a chain this run does not list: {stopped_in!r}")
    stopped_at = names.index(stopped_in) if segment else None
    blocks, records, ended_by, run_termination = {}, [], None, None
    for index, chain in enumerate(chains):
        name = chain["name"]
        stream = stream_of(chain, stream_context)
        block = incoming.get(name)
        if block is not None and block.get("kernel") != chain["kernel"]:
            raise ValueError(f"sampling checkpoint kernel mismatch for {name!r}: a chain goes on as it began")
        carried = (ended_by is not None or bool((block or {}).get("ended"))
                   or (stopped_at is not None and index < stopped_at))
        if carried:
            if block is not None:
                blocks[name] = block
            records.append(chain_record(chain, block, n=n, sweeps=sweeps, termination=(block or {}).get("ended"),
                                        seconds=0.0, stream=stream_id(*stream), skipped_reason=ended_by))
            continue
        chain_ctx = E.ChainContext(**dict(vars(ctx), **({"local_walk": True} if chain["kernel"] == E.LOCAL_WALK
                                                        else {})))
        rng = stream_rng(*stream)
        if block is not None:
            rng.setstate(tuple_state(block["rng_state"]))
            state, energy = restore(block)
            initial = block
        else:
            state, energy = _fresh_state(chain, ctx=ctx, runner=runner, chain_ctx=chain_ctx, n=n,
                                         empty_energy=empty_energy,
                                         rng_of=lambda label: stream_rng(label, *stream_context))
            initial = {}
        resuming = stopped_at is not None and index == stopped_at
        points = record_points
        tally = E.new_accounting(initial.get("accounting"))
        weighed, spent_so_far = {}, 0
        if work_budget is not None:
            spent_so_far = sum(E.units_of_an_accounting((blocks.get(other) or incoming.get(other) or {}).get(
                "accounting"), work_weights) for other in names)
            weighed = {"work_room": max(0, int(work_budget) - spent_so_far), "work_weights": list(work_weights)}
        started = time.monotonic()
        (state, energy, trajectory, attempted, proposed, accepted, late_change, peak, termination) = runner(
            chain_ctx, rng, state, energy, points,
            start_move=int(segment["next_move"]) if resuming else start_move,
            segment_start=int(segment["segment_start"]) if resuming else None, stop_file=stop_file,
            attempted=initial.get("attempted"), proposed=initial.get("proposed"), accepted=initial.get("accepted"),
            trajectory=initial.get("trajectory"), late_change=initial.get("late_change"),
            peak_edge_count=initial.get("peak_edge_count"), late_from_move=late_from_move,
            enforce_limits=True, accounting=tally, **weighed,
        )
        seconds = time.monotonic() - started
        reason = (termination or {}).get("reason")
        block = chain_block(chain, state, energy, rng, attempted, proposed, accepted, trajectory, peak, late_change,
                            tally, n)
        if reason in E.STOPPED_INSIDE_A_SEGMENT:
            later = [incoming[other] for other in names[index + 1:] if other in incoming]
            earlier = [blocks[other] for other in names[:index] if other in blocks]
            stopped = stopped_envelope(identity, termination, name, start_move, points, earlier + [block] + later)
            if reason == "work_budget":
                stopped["work_units"] = spent_so_far + int(termination["units"])
                stopped["termination"]["chain_stopped"] = name
            return {"stopped": stopped}
        if reason == "mean_degree_cap":
            block["ended"] = dict(termination)
        elif name == FROM_EMPTY:
            run_termination = termination
            if reason is not None:
                ended_by = reason
        blocks[name] = block
        if reason == "mean_degree_cap" and chain["is_twin"] and every_twin_ended(chains, blocks, incoming):
            run_termination = dict(termination, chain=name)
            ended_by = reason
        records.append(chain_record(chain, block, n=n, sweeps=sweeps, termination=termination, seconds=seconds,
                                    stream=stream_id(*stream), skipped_reason=ended_by))
    return {"blocks": [blocks[name] for name in names if name in blocks], "records": records,
            "termination": run_termination}
