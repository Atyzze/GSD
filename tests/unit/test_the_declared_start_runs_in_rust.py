from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.scaleflow import engine_door
from graph_scale_dynamics.measurements.calibration import control_family_edges
from graph_scale_dynamics.resources import committed
from graph_scale_dynamics.services.worker import engine_rs

ROOT = Path(__file__).resolve().parents[2]
CRITERION = committed.read(ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json")


class _Ctx:
    def __init__(self, spec, n):
        self.candidate_spec, self.n = spec, n
        self.spec_ops = {term["op"] for term in spec["terms"]}


def _both(law, n):
    spec = law["spec"]
    edges = control_family_edges(law["given_start"]["family"], n)
    _node_terms, empty, apply_edge = E._energy_model(spec, n)
    ctx = _Ctx(spec, n)

    def fresh():
        state = E.GraphState(n)
        state.require_ops(ctx.spec_ops)
        return state

    python = engine_door.declared_given(ctx, None, edges, fresh(), empty, apply_edge)
    rust = engine_door.declared_given(ctx, engine_rs.rust_chain_runner, edges, fresh(), empty, apply_edge)
    return python, rust


def test_every_control_s_declared_start_is_the_same_in_both_engines():
    for law in CRITERION["laws"]:
        for n in (64, 256):
            (state_p, energy_p), (state_r, energy_r) = _both(law, n)
            assert energy_p == energy_r and type(energy_p) is type(energy_r), (law["label"], n)
            assert state_p.edges == state_r.edges, (law["label"], n)
            for key, value in state_p.ledgers.items():
                assert state_r.ledgers[key] == value, (law["label"], n, key)


def test_the_curvature_law_starts_at_zero_curvature_on_the_cubic_lattice():
    c1 = next(law for law in CRITERION["laws"] if law["label"] == "C1")
    (_, _), (state, _) = _both(c1, 256)
    assert state.ledgers["ollivier_curvature"] == 0.0, "every edge of the cubic lattice has curvature 0"
