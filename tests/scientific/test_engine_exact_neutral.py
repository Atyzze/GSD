from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.measurements import shaped_starts
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
from tests.support.engines import require_rust_engine

pytestmark = [pytest.mark.scientific]

NEW = E.ENGINE_VERSION
VOLATILE = {"resource_usage", "engine", "wall_seconds", "wall_seconds_so_far", "elapsed_seconds", "started_utc",
            "finished_utc", "timing", "seconds", "runtime_fingerprint"}


def _stable(obj):
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in sorted(obj.items()) if k not in VOLATILE}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, mix=(0.25, 0.25, 0.5), sweeps=40, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.5, "sweeps": sweeps,
                         "move_mix": {"add": mix[0], "delete": mix[1], "swap": mix[2]}, **dynamics}}


DEGREES_ONLY = _law([_term("degree_anchor", 0.37, "inv_sqrt_N", k=5), _term("wedge_count", 0.21, "inv_log_N"),
                     _term("degree_fourth_sum", 0.013), _term("edge_count", -1.3, "log_N")], zero_temperature=True)
SEES_CYCLES = _law([_term("degree_anchor", 0.5, k=4), _term("triangle_count", 0.3, "inv_log_N"),
                    _term("square_count", -0.04, "inv_sqrt_N"), _term("edge_count", -0.8)], zero_temperature=True)
TOGGLES_CANCEL = _law([_term("edge_count", -0.5, "log_N"), _term("wedge_count", 0.05, "log_N")],
                      mix=(0.45, 0.45, 0.1), sweeps=6, zero_temperature=True)
LAWS = {
    "degrees_only": DEGREES_ONLY,
    "toggles_cancel": TOGGLES_CANCEL,
    "sees_cycles": SEES_CYCLES,
    "gradient_local": _law([_term("degree_neighbor_gradient", 0.01, "inv_N"), _term("degree_anchor_abs", 0.7, k=6),
                            _term("edge_count", -0.5)], zero_temperature=True, locality=0.6),
    "curvature_warm": _law([_term("degree_anchor", 0.5, k=6), _term("ollivier_curvature", -0.05),
                            _term("triangle_edge_overlap", 0.02), _term("induced_square_count", 0.01)],
                           mix=(0.4, 0.4, 0.2), sweeps=16),
}


def _swaps(envelope, chain="empty"):
    counts = CL.record(envelope, chain)["accounting"]["counts"]
    out = {}
    for key, count in counts.items():
        kind, _scope, sign, outcome = key.split(".")
        if kind == "swap" and count:
            out[(sign, outcome)] = out.get((sign, outcome), 0) + count
    return out


def test_the_engine_is_the_exact_one():
    assert E.ENGINE_VERSION == NEW and NEW in E.COMPATIBLE_ENGINE_VERSIONS
    assert "engine-3.1.0" in E.COMPATIBLE_ENGINE_VERSIONS, "a job stamped by an earlier build runs on this one"


def test_a_toggle_whose_terms_cancel_reads_exactly_zero():
    from graph_scale_dynamics.dsl.dsl import coefficient
    terms = TOGGLES_CANCEL["terms"]
    raw = 0.0 + coefficient(terms[0], 1024) * 1 + coefficient(terms[1], 1024) * 10
    assert raw != 0.0 and abs(raw) < 1e-15, "the rounding the fix is for"
    magnitude = abs(coefficient(terms[0], 1024)) + abs(coefficient(terms[1], 1024) * 10)
    assert E.exact_zero(raw, magnitude) == 0.0 and E.exact_zero(-raw, magnitude) == 0.0
    real = coefficient(terms[0], 1024) * 1 + coefficient(terms[1], 1024) * 9
    assert E.exact_zero(real, magnitude) == real
    assert E.exact_zero(1e-9, 1.0) == 1e-9, "a real change a millionth of a millionth of its terms is still read"


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_every_exactly_neutral_toggle_is_taken_at_zero_temperature(engine):
    if engine == "rust":
        require_rust_engine()
    _, run, _ = resolve_engine({"engine": engine})
    envelope = run(TOGGLES_CANCEL, 1024, 7)
    counts = CL.record(envelope, CL.FROM_EMPTY)["accounting"]["counts"]
    zero = {key: count for key, count in counts.items() if count and key.split(".")[0] in ("add", "delete")
            and key.split(".")[2] == "zero"}
    assert zero and all(key.endswith(".accepted") for key in zero), zero


def test_a_swap_s_change_is_its_terms_changes():
    ctx = E.ChainContext(n=100, candidate_spec=SEES_CYCLES)
    terms = E.swap_terms(ctx)
    assert [op for op, _ in terms] == ["triangle_count", "square_count", "edge_count"]
    neutral = [{"triangle_count": t, "square_count": s, "edge_count": e}
               for t, s, e in ((-2.0, -1.0, -1.0), (-1.0, 0.0, -1.0), (1.0, 1.0, 1.0), (2.0, 0.0, 1.0))]
    assert E.swap_change(terms, neutral) == 0.0
    moved = [dict(m) for m in neutral]
    moved[3]["square_count"] += 1.0
    assert E.swap_change(terms, moved) == terms[1][1] == pytest.approx(-0.004)
    assert E.swap_change([], neutral) == 0.0, "a law of node terms alone: a swap changes nothing"


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_every_neutral_swap_is_taken_at_zero_temperature(engine):
    if engine == "rust":
        require_rust_engine()
    _, run, _ = resolve_engine({"engine": engine})
    envelope = run(DEGREES_ONLY, 256, 3)
    for chain in ("empty", "given"):
        swaps = _swaps(envelope, chain)
        assert set(swaps) == {("zero", "accepted")}, (chain, swaps)
    proposed, accepted = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["proposed"], CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["accepted"]
    assert proposed["swap"] > 1000 and accepted["swap"] == proposed["swap"]


def test_a_swap_that_changes_a_term_is_still_decided():
    swaps = _swaps(resolve_engine({"engine": "python"})[1](SEES_CYCLES, 256, 4))
    assert swaps.get(("pos", "rejected"), 0) > 0 and swaps.get(("neg", "accepted"), 0) > 0, swaps
    assert not swaps.get(("pos", "accepted")) and not swaps.get(("zero", "rejected")), swaps


@pytest.mark.parametrize("name", sorted(LAWS))
def test_python_and_rust_agree(name):
    require_rust_engine()
    _, run_py, _ = resolve_engine({"engine": "python"})
    _, run_rs, _ = resolve_engine({"engine": "rust"})
    a = _stable(run_py(LAWS[name], 160, 5))
    b = _stable(run_rs(LAWS[name], 160, 5))
    assert a["engine_version"] == NEW
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_the_given_chain_s_local_walk_agrees_on_both_engines():
    require_rust_engine()
    declared = {"family": shaped_starts.family(2, 4), "edges": shaped_starts.build(196, 2, 4, 1),
                "kernel": "local_walk"}
    _, run_py, _ = resolve_engine({"engine": "python"})
    _, run_rs, _ = resolve_engine({"engine": "rust"})
    a = _stable(run_py(DEGREES_ONLY, 196, 2, target_sweeps=20, given_start=declared))
    b = _stable(run_rs(DEGREES_ONLY, 196, 2, target_sweeps=20, given_start=declared))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    swaps = _swaps(a, "given")
    assert set(swaps) == {("zero", "accepted")} and swaps[("zero", "accepted")] > 500, swaps
