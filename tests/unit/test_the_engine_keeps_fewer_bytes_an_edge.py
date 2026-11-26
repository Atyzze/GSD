from __future__ import annotations

import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


LAW = {"dsl_version": 1, "init": "empty",
       "terms": [_term("edge_count", 0.3), _term("square_edge_overlap", 0.02), _term("triangle_edge_overlap", -0.05),
                 _term("ollivier_curvature", -0.05), _term("degree_anchor", 0.5, k=6)],
       "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": 0.45, "delete": 0.45, "swap": 0.10},
                    "sweeps": 6}}


def _ran(n=300, seed=4):
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.services.worker import engine_rs as R
    from graph_scale_dynamics.services.worker.engine_registry import door_of
    pytest.importorskip("gsd_engine_rs")
    node_terms, empty_energy, apply_edge = E._energy_model(LAW, n)
    settings = E._law_dynamics(LAW, 0.0)
    ctx = E.ChainContext(n=n, total_moves=6 * n, mean_degree_cap=None, proposal_locality=0.0, apply_edge=apply_edge,
                         locality=settings["locality"], zero_temperature=settings["zero_temperature"], p_add=0.45,
                         p_del=0.45, p_swap=0.10, beta=1.0, max_edges=n * (n - 1) // 2, cooling_from_beta=None,
                         cooling_moves=None, candidate_spec=LAW, spec_ops={t["op"] for t in LAW["terms"]},
                         node_terms=node_terms)
    state = E.GraphState(n)
    state.require_ops(ctx.spec_ops)
    out = R._run_chain_through(door_of("rust"), ctx, random.Random(seed), state, empty_energy, 20)
    return ctx, out


def test_a_run_s_state_holds_its_edges_and_degrees_and_builds_the_rest_only_when_asked():
    from graph_scale_dynamics.engine.chains import final_of
    from graph_scale_dynamics.services.worker import engine_rs as R
    ctx, out = _ran()
    state, energy, peak = out[0], out[1], out[7]
    assert isinstance(state, R.RanInRust)
    held = set(vars(state))
    assert not held & {"adj", "edges", "edge_index", "non_degree"}, "no sets nor index until something asks"
    lean = final_of(state, energy, peak, ctx.n)
    assert set(vars(state)) == held, "the final reading reads the degrees, not the sets"
    assert state.edges == set(state.edge_list) and len(state.adj) == ctx.n, "asked, the whole state is there"
    assert [len(neighbours) for neighbours in state.adj] == state.degrees
    assert final_of(state, energy, peak, ctx.n) == lean, "the same final reading either way"


def test_the_door_shares_one_number_per_node_across_the_edges():
    ctx, out = _ran()
    state = out[0]
    seen = {}
    for u, v in state.edge_list:
        for x in (u, v):
            assert seen.setdefault(x, x) is x, "one number object per node, not one per mention"
    assert any(x > 256 for x in seen), "past the numbers Python shares itself"


def test_the_science_is_the_engine_s_science_version_and_the_crate_moves_on_its_own(tmp_path):
    from graph_scale_dynamics.reporting import science_contract
    from graph_scale_dynamics.services.worker.engine_registry import rust_science_version, rust_source_version
    assert rust_source_version(ROOT) == "0.875.0" and rust_science_version(ROOT) == "0.840.0", (
        "the diet changed the binary, not one chain: the science stays where 840 put it")
    assert science_contract.parts()[0]["engine"] == rust_science_version()
    (tmp_path / "engine_rs").mkdir()
    (tmp_path / "engine_rs" / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    assert rust_science_version(tmp_path) == "1.2.3", "without a science version the crate's stands for it"
