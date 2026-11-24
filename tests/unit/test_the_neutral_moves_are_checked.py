from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
_spec = importlib.util.spec_from_file_location("neutral_moves_check", ROOT / "tools" / "neutral_moves_check.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)
NAMED = {"beta": 3.90317, "local_move": "toggle", "locality": 0.900939, "regime": "zero_temperature",
         "swap_share": 0.205939, "sweeps": 70, "zero_temperature": True,
         "terms": [["degree_anchor_abs", 8, 0.567036, "log_N", None],
                   ["degree_neighbor_gradient", None, 0.130229, "power", -0.00234285]]}
NAMED_ID = "ec7c97587eb5e34a4f1c1d3421481ba9363075d3a1c49274b0c8c7515f4c5fed"


def _fleet_start(spec: dict, n: int):
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    _node_terms, empty_energy, apply_edge = E._energy_model(spec, n)
    state = E.GraphState(n)
    state.require_ops({t["op"] for t in spec["terms"]})
    energy = empty_energy
    for u, v in control_family_edges("periodic_tesseract_quotient", n, seed=0):
        if v not in state.adj[u]:
            deltas, change = apply_edge(state, u, v, True, energy)
            state.apply(u, v, True, deltas)
            energy += change
    return state, energy, apply_edge


def _swap_as_the_engine_reads_it(state, energy, apply_edge, rng) -> float:
    edges = sorted(state.edges)
    while True:
        (a, b), (c, d) = rng.sample(edges, 2)
        n1, n2 = state._edge(a, c), state._edge(b, d)
        near = {a, b} & (state.adj[c] | state.adj[d] | {c, d})
        if not near and n1 not in state.edges and n2 not in state.edges:
            break
    before, done = energy, []
    for (x, y), adding in (((a, b), False), ((c, d), False), (n1, True), (n2, True)):
        deltas, change = apply_edge(state, x, y, adding, energy)
        state.apply(x, y, adding, deltas)
        energy += change
        done.append(((x, y), adding))
    for (x, y), adding in reversed(done):
        deltas, _change = apply_edge(state, x, y, not adding, energy)
        state.apply(x, y, not adding, deltas)
    return energy - before


def test_a_swap_that_changes_nothing_reads_above_zero_at_16384_and_exactly_zero_without_the_gradient():
    spec = T.law_spec(NAMED, NAMED_ID)
    state, energy, apply_edge = _fleet_start(spec, 16384)
    change = _swap_as_the_engine_reads_it(state, energy, apply_edge, random.Random(5))
    assert 0 < change < 1e-12, change
    state, energy, apply_edge = _fleet_start(T.variant(spec, "no_gradient"), 16384)
    assert _swap_as_the_engine_reads_it(state, energy, apply_edge, random.Random(5)) == 0.0


def test_the_neutral_share_reads_what_a_swap_can_change():
    squares = T.law_spec({"beta": 2.0, "sweeps": 10, "swap_share": 0.2, "zero_temperature": True,
                          "terms": [["degree_anchor", 8, 0.5, "one", None], ["square_count", None, -0.3, "one", None]]})
    degrees = T.law_spec({"beta": 2.0, "sweeps": 10, "swap_share": 0.2, "zero_temperature": True,
                          "terms": [["degree_anchor_abs", 8, 0.5, "log_N", None]]})
    on_4d = T.neutral_share(squares, "tesseract", 1024, 200, 1)
    assert (on_4d["share"], on_4d["raise"]) == (0.0, 200)
    assert T.neutral_share(squares, "honeycomb", 1024, 200, 1)["share"] >= 0.95
    assert T.neutral_share(degrees, "tesseract", 1024, 200, 1)["share"] == 1.0
    assert T.neutral_share(degrees, "honeycomb", 1024, 200, 1)["share"] == 1.0
    assert T.neutral_class(1.0) == "neutral" and T.neutral_class(0.0) == "changes" and T.neutral_class(0.5) == "between"


def _row(law, shift, fate, *, share=1.0, zero=True, kind="zero", proposed=10):
    return {"law": law, "set": kind, "zero_temperature": zero, "lattice": "tesseract", "n": 4096, "variant": "drawn",
            "shift": shift, "seed": 1, "fate": fate, "accepted": {"add": 0, "delete": 0, "swap": 1},
            "proposed_swaps": proposed, "swaps_taken_share": 0.1,
            "start_edges_left": 1.0 if fate in ("holds", "unmoved") else 0.0, **(
                {"swaps_at_the_start": {"share": share}} if shift is None else {})}


def test_a_shift_turns_a_hold_only_where_it_changes_whether_the_lattice_is_kept():
    rows = ([_row("a", None, "holds"), _row("a", 1e-6, "melted"), _row("a", -1e-6, "holds")]
            + [_row("b", None, "unmoved"), _row("b", 1e-6, "holds"), _row("b", -1e-6, "holds")]
            + [_row("c", None, "holds", share=0.0), _row("c", 1e-6, "holds", share=0.0)]
            + [_row("d", None, "melted"), _row("d", 1e-6, "holds")])
    by = T.groups(rows)
    assert [T.turns(by[(law, "tesseract", 4096, "drawn", 1)]) for law in "abcd"] == [True, False, False, True]
    criterion = {"contract": "c", "predictions": [
        {"id": "A", "claim": "", "rule": {"kind": "turn_share_at_least", "neutral_at_least": 0.9, "share": 0.5,
                                          "needs_at_least": 2}},
        {"id": "B", "claim": "", "rule": {"kind": "turn_share_at_most", "neutral_at_most": 0.01, "share": 0.0}},
        {"id": "C", "claim": "", "rule": {"kind": "turn_share_at_least", "neutral_at_least": 0.9, "share": 0.5,
                                          "needs_at_least": 3}}]}
    verdicts = [(p["verdict"], p["read"]["reproduced"]) for p in T.judge(criterion, {"rows": rows})["predictions"]]
    assert verdicts == [("held", 2), ("held", 1), ("nothing to measure", 2)], "d was not kept by the fleet's start"
    told = T.summary(rows)["groups"]
    assert told["zero, zero, neutral"] == {"groups": 3, "fleet_kept": 2, "every_way_kept": 1, "none_kept": 0,
                                           "a_shift_changes": 2, "same_moves": 1}


def test_a_hold_is_marked_by_what_its_law_sees():
    squares = {"beta": 2.0, "sweeps": 10, "swap_share": 0.2, "zero_temperature": True,
               "terms": [["degree_anchor", 8, 0.5, "one", None], ["square_count", None, -0.3, "one", None]]}
    against = dict(squares, terms=[["degree_anchor", 8, 0.5, "one", None], ["square_count", None, 0.3, "one", None]])
    degrees = dict(squares, terms=[["degree_anchor_abs", 8, 0.5, "log_N", None]])
    specs = {}
    for name, compact in (("a", squares), ("b", against), ("c", degrees)):
        from graph_scale_dynamics.dsl.dsl import fingerprint
        specs[fingerprint(T.law_spec(compact))] = (name, compact)
    laws = {law: {"at_n": 1024, "fates": {"tesseract": "holds", "cubic": "melted"}} for law in specs}
    marked = T.mark(laws, {law: compact for law, (_n, compact) in specs.items()}, [], bundle="hand", samples=100)
    by_name = {specs[law][0]: h["label"] for law in specs for h in marked["holds"] if h["law"] == law[:12]}
    assert by_name == {"a": "resists", "b": "drives", "c": "blind"}
    assert marked["holds_by_label"] == {"blind": 1, "resists": 1, "drives": 1, "between": 0}
    assert marked["holders"]["zero"] == {"holders": 3, "a_lattice_it_resists": 1, "only_blind_lattices": 1}
