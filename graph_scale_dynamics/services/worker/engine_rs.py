from __future__ import annotations


from graph_scale_dynamics.engine import engine as _engine
from graph_scale_dynamics.engine.engine import GraphState, _Fenwick


def _terms_for_rust(ctx) -> list[dict]:
    terms = []
    for term in ctx.candidate_spec["terms"]:
        params = dict(term.get("params") or {})
        k = params.get("k")
        terms.append({
            "op": term["op"],
            "coeff": float(_engine.coefficient(term, ctx.n)),
            "k": int(k) if isinstance(k, int) and not isinstance(k, bool) else 0,
            "scale": (term.get("coeff") or {}).get("scale", "one"),
            "params_k": int(k) if isinstance(k, int) and not isinstance(k, bool) else None,
        })
    return terms


def _pairs(raw, n: int) -> list:
    if raw and type(raw[0]) is tuple:
        return raw
    ids = list(range(int(n)))
    return [(ids[u], ids[v]) for u, v in raw]


def _whole_state(n: int, spec_ops, rows, edge_list) -> GraphState:
    state = GraphState(n)
    state.require_ops(spec_ops)
    state.adj = [set(neighbours) for neighbours in rows]
    state.edge_list = edge_list
    state.edges = set(edge_list)
    state.edge_index = {e: i for i, e in enumerate(edge_list)}
    state.non_degree = [n - 1 - len(neighbours) for neighbours in rows]
    state._non_degree_tree = _Fenwick(state.non_degree)
    return state


class RanInRust(GraphState):
    def __init__(self, n: int, spec_ops, out: dict):
        ledgers = dict(GraphState(1).ledgers)
        for key, value in (out.get("ledgers") or {}).items():
            ledgers[key] = float(value)
        rows = out["adj"]
        self.__dict__.update({
            "n": int(n), "edge_list": _pairs(out["edge_list"], n),
            "degrees": [len(neighbours) for neighbours in rows], "ledgers": ledgers,
            "required_ops": frozenset(op for op in spec_ops if op in ledgers),
            "non_edge_fast_path_hits": int(out["non_edge_fast_path_hits"]),
            "non_edge_exact_fallbacks": int(out["non_edge_exact_fallbacks"]),
            "_rows": rows, "_ops": spec_ops})
        if out.get("structural_summary") is not None:
            self.__dict__["structural_summary_cache"] = dict(out["structural_summary"])

    def whole(self) -> GraphState:
        rows = self.__dict__.pop("_rows", None)
        if rows is not None:
            whole = _whole_state(self.n, self.__dict__.pop("_ops"), rows, self.edge_list)
            self.__dict__.update({key: value for key, value in whole.__dict__.items() if key not in self.__dict__})
        return self

    def __getattr__(self, name):
        if "_rows" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self.whole(), name)


def _state_from_rust(n: int, spec_ops, out: dict) -> GraphState:
    return RanInRust(n, spec_ops, out)


def _init_random_graph_through(door, ctx, rng, state, energy, target_edges):
    version, mt_state, _gauss = rng.getstate()
    if version != 3:
        raise ValueError(f"unexpected random.Random state version {version}")
    out = door("init_random_graph", {
        "n": int(ctx.n), "terms": _terms_for_rust(ctx), "target_edges": int(target_edges),
        "mt_words": list(mt_state[:624]), "mt_index": int(mt_state[624]), "energy": float(energy),
        "energy_is_int": isinstance(energy, int) and not isinstance(energy, bool)})
    rng.setstate((3, tuple(int(w) for w in out["mt_words"]) + (int(out["mt_index"]),), None))
    new_state = _state_from_rust(ctx.n, ctx.spec_ops, out)
    final_energy = int(out["energy"]) if out["energy_is_int"] else float(out["energy"])
    return new_state, final_energy


def _init_declared_through(door, ctx, edges, state, energy):
    out = door("init_declared", {
        "n": int(ctx.n), "terms": _terms_for_rust(ctx),
        "edges": edges if type(edges) is list and (not edges or type(edges[0]) is tuple) else [
            (int(u), int(v)) for u, v in edges],
        "energy": float(energy), "energy_is_int": isinstance(energy, int) and not isinstance(energy, bool)})
    new_state = _state_from_rust(ctx.n, ctx.spec_ops, out)
    final_energy = int(out["energy"]) if out["energy_is_int"] else float(out["energy"])
    return new_state, final_energy


def _restore_stop_file(state) -> str | None:
    deferred = state.__dict__.get("_deferred") if isinstance(state, DeferredRustState) else None
    return None if deferred is None or deferred[3] is None else str(deferred[3])


def _run_chain_through(door, ctx, rng, state, energy, points, *, start_move=0,
                      attempted=None, proposed=None, accepted=None, trajectory=None,
                      late_change=None, peak_edge_count=None, late_from_move=None,
                      enforce_limits=False, segment_start=None, stop_file=None,
                      accounting=None, work_room=None, work_weights=None):
    version, mt_state, _gauss = rng.getstate()
    if version != 3:
        raise ValueError(f"unexpected random.Random state version {version}")
    words, index = list(mt_state[:624]), int(mt_state[624])
    cap_edges = None
    if enforce_limits and ctx.mean_degree_cap is not None:
        cap_edges = int(_engine.math.floor(float(ctx.mean_degree_cap) * ctx.n / 2.0))
    edge_list = state.edge_list if type(state.edge_list) is list else [(int(u), int(v)) for u, v in state.edge_list]
    prior_trajectory = list(trajectory or [])
    out = door("run_chain", {
        "n": int(ctx.n), "terms": _terms_for_rust(ctx), "beta": float(ctx.beta), "p_add": float(ctx.p_add),
        "p_del": float(ctx.p_del), "p_swap": float(ctx.p_swap), "proposal_locality": float(ctx.proposal_locality),
        "total_moves": int(ctx.total_moves), "start_move": int(start_move), "points": int(points),
        "late_from_move": None if late_from_move is None else int(late_from_move), "mt_words": words,
        "mt_index": index, "edge_list": edge_list, "energy": float(energy),
        "attempted": _engine._counter(attempted), "proposed": _engine._counter(proposed),
        "accepted": _engine._counter(accepted),
        "late_change": None if not late_change else [
            int(late_change["from_move"]), [(int(u), int(v)) for u, v in late_change.get("added") or []],
            [(int(u), int(v)) for u, v in late_change.get("removed") or []]],
        "trajectory_len": len(prior_trajectory),
        "peak_edge_count": int(peak_edge_count or 0),
        "non_edge_fast_path_hits": int(state.non_edge_fast_path_hits),
        "non_edge_exact_fallbacks": int(state.non_edge_exact_fallbacks),
        "cap_edges": cap_edges,
        "mean_degree_cap": None if ctx.mean_degree_cap is None else float(ctx.mean_degree_cap),
        "energy_is_int": isinstance(energy, int) and not isinstance(energy, bool),
        "segment_start": None if segment_start is None else int(segment_start),
        "stop_file": None if stop_file is None else str(stop_file),
        "rebuild_stop_file": _restore_stop_file(state),
        "stop_check_seconds": float(_engine.STOP_CHECK_SECONDS),
        "locality": float(getattr(ctx, "locality", 0.0)),
        "zero_temperature": bool(getattr(ctx, "zero_temperature", False)),
        "accounting": _engine.new_accounting(accounting),
        "cooling_from_beta": getattr(ctx, "cooling_from_beta", None),
        "cooling_moves": getattr(ctx, "cooling_moves", None),
        "local_walk": bool(getattr(ctx, "local_walk", False)),
        "work_room": None if work_room is None else int(work_room),
        "work_weights": None if work_room is None else [int(weight) for weight in work_weights],
    })
    if out.get("interrupted"):
        raise _engine.RestoreInterrupted(str(out["interrupted"]), int(out.get("edges_rebuilt") or 0))
    if accounting is not None:
        accounting.clear()
        accounting.update(_engine.new_accounting(out["accounting"]))
    rng.setstate((3, tuple(int(w) for w in out["mt_words"]) + (int(out["mt_index"]),), None))
    new_state = _state_from_rust(ctx.n, ctx.spec_ops, out)
    late_out = None
    if out["late_change"] is not None:
        from_move, added, removed = out["late_change"]
        late_out = {"contract": _engine.LATE_CHANGE_CONTRACT, "from_move": int(from_move),
                    "added": [tuple(e) for e in added], "removed": [tuple(e) for e in removed]}
    points_out = []
    for point in out["trajectory"]:
        if point.pop("_energy_is_int", False):
            point["energy"] = int(point["energy"])
        points_out.append(point)
    final_energy = int(out["energy"]) if out["energy_is_int"] else float(out["energy"])
    return (new_state, final_energy, prior_trajectory + points_out,
            out["attempted"], out["proposed"], out["accepted"], late_out,
            int(out["peak_edge_count"]), out["termination"])


class DeferredRustState(GraphState):
    def __init__(self, door, ctx, chain, stop_file):
        self.__dict__.update({
            "n": int(ctx.n),
            "edge_list": [(int(u), int(v)) for u, v in chain.get("edge_list") or []],
            "non_edge_fast_path_hits": int(chain.get("non_edge_fast_path_hits", 0)),
            "non_edge_exact_fallbacks": int(chain.get("non_edge_exact_fallbacks", 0)),
            "_deferred": (door, ctx, chain, stop_file),
        })

    def __getattr__(self, name):
        deferred = self.__dict__.pop("_deferred", None)
        if deferred is None:
            raise AttributeError(name)
        door, ctx, chain, stop_file = deferred
        self.__dict__.update(_rebuilt_now_through(door, ctx, chain, stop_file=stop_file).whole().__dict__)
        return getattr(self, name)


def _rebuild_through(door, ctx, chain, *, stop_file=None) -> GraphState:
    if (chain or {}).get("ended"):
        return _rebuilt_now_through(door, ctx, chain, stop_file=stop_file)
    return DeferredRustState(door, ctx, chain, stop_file)


def _rebuilt_now_through(door, ctx, chain, *, stop_file=None) -> GraphState:
    edge_list = [(int(u), int(v)) for u, v in chain.get("edge_list") or []]
    out = door("rebuild_graph", {
        "n": int(ctx.n), "terms": _terms_for_rust(ctx), "edge_list": edge_list,
        "non_edge_fast_path_hits": int(chain.get("non_edge_fast_path_hits", 0)),
        "non_edge_exact_fallbacks": int(chain.get("non_edge_exact_fallbacks", 0)),
        "stop_file": None if stop_file is None else str(stop_file),
        "stop_check_seconds": float(_engine.STOP_CHECK_SECONDS),
    })
    if out.get("interrupted"):
        raise _engine.RestoreInterrupted(str(out["interrupted"]), int(out.get("edges_rebuilt") or 0))
    return _state_from_rust(ctx.n, ctx.spec_ops, out)


class ChainsThroughTheBoundary:
    def __init__(self, door):
        self.door = door

    def __call__(self, ctx, rng, state, energy, points, *, start_move=0, attempted=None, proposed=None,
                 accepted=None, trajectory=None, late_change=None, peak_edge_count=None, late_from_move=None,
                 enforce_limits=False, segment_start=None, stop_file=None, accounting=None, work_room=None,
                 work_weights=None):
        return _run_chain_through(self.door, ctx, rng, state, energy, points, start_move=start_move,
                                  attempted=attempted, proposed=proposed, accepted=accepted, trajectory=trajectory,
                                  late_change=late_change, peak_edge_count=peak_edge_count,
                                  late_from_move=late_from_move, enforce_limits=enforce_limits,
                                  segment_start=segment_start,
                                  stop_file=stop_file, accounting=accounting, work_room=work_room,
                                  work_weights=work_weights)

    def init_random_graph(self, ctx, rng, state, energy, target_edges):
        return _init_random_graph_through(self.door, ctx, rng, state, energy, target_edges)

    def init_declared(self, ctx, edges, state, energy):
        return _init_declared_through(self.door, ctx, edges, state, energy)

    def rebuild(self, ctx, chain, *, stop_file=None):
        return _rebuild_through(self.door, ctx, chain, stop_file=stop_file)


def the_default_door(operation: str, request: dict) -> dict:
    from graph_scale_dynamics.services.worker import engine_registry
    return engine_registry.door_of()(operation, request)


rust_chain_runner = ChainsThroughTheBoundary(the_default_door)
init_random_graph = rust_chain_runner.init_random_graph
init_declared = rust_chain_runner.init_declared
rebuild = rust_chain_runner.rebuild


def simulation_through(door):
    def run_simulation(candidate_spec: dict, n: int, seed: int, **kwargs) -> dict:
        return _engine.run_simulation(candidate_spec, n, seed, chain_runner=ChainsThroughTheBoundary(door), **kwargs)
    run_simulation.door = getattr(door, "door", None)
    return run_simulation


def run_simulation(candidate_spec: dict, n: int, seed: int, **kwargs) -> dict:
    return _engine.run_simulation(candidate_spec, n, seed, chain_runner=rust_chain_runner, **kwargs)
