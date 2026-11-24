from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
CONTROLS = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json").read_text())


def _law(beta=2.0, cooling=None, sweeps=12):
    dynamics = {"kind": "equilibrium", "beta": beta, "sweeps": sweeps,
                "move_mix": {"add": 0.4, "delete": 0.4, "swap": 0.2}}
    if cooling is not None:
        dynamics["cooling"] = cooling
    return {"dsl_version": 1, "init": "empty", "dynamics": dynamics,
            "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "one"}},
                      {"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 0.4, "scale": "one"}}]}


def test_every_law_made_before_it_keeps_its_id():
    ids = {law["label"]: dsl.fingerprint(law["spec"])[:10] for law in CONTROLS["laws"]}
    assert ids == {"P1": "6f364db7b7", "P2": "a283415b10", "N1": "e4ed71e5bc", "N2": "e06a125bf0",
                   "C1": "c9b022c38d"}
    assert "cooling" not in dsl.normalize(_law())["dynamics"]


def test_a_schedule_is_part_of_the_law_and_is_checked():
    cooled = _law(cooling={"from_beta": 0.5, "over_sweeps": 600})
    assert dsl.validate(cooled) == []
    assert dsl.normalize(cooled)["dynamics"]["cooling"] == {"from_beta": 0.5, "over_sweeps": 600}
    assert dsl.fingerprint(cooled) != dsl.fingerprint(_law()), "a cooled law is another law"
    assert dsl.cooling_schedule(cooled) == {"from_beta": 0.5, "over_sweeps": 600}
    assert dsl.cooling_schedule(_law()) is None
    bad = {
        "hotter": _law(cooling={"from_beta": 2.0, "over_sweeps": 10}),
        "sweeps": _law(cooling={"from_beta": 0.5, "over_sweeps": 0}),
        "keys": _law(cooling={"from_beta": 0.5, "over_sweeps": 10, "shape": "geometric"}),
        "frozen": dict(_law(cooling={"from_beta": 0.5, "over_sweeps": 10})),
    }
    bad["frozen"]["dynamics"] = dict(bad["frozen"]["dynamics"], zero_temperature=True)
    for name, law in bad.items():
        assert dsl.validate(law), name


def test_beta_rises_linearly_then_holds():
    assert E.cooled_beta(4.0, 1.0, 100, 0) == 1.0
    assert E.cooled_beta(4.0, 1.0, 100, 50) == 2.5
    assert E.cooled_beta(4.0, 1.0, 100, 100) == 4.0
    assert E.cooled_beta(4.0, 1.0, 100, 10 ** 9) == 4.0


def test_a_law_without_a_schedule_runs_as_it_did_and_a_cooled_one_does_not():
    plain = engine_door.run_simulation(_law(), 64, 3, target_sweeps=12, record_points=6)
    again = engine_door.run_simulation(_law(), 64, 3, target_sweeps=12, record_points=6)
    assert CL.sorted_edges(plain) == CL.sorted_edges(again) and "beta_schedule" not in plain["proposal_model"]
    cooled = engine_door.run_simulation(_law(cooling={"from_beta": 0.05, "over_sweeps": 6}), 64, 3, target_sweeps=12,
                              record_points=6)
    schedule = cooled["proposal_model"]["beta_schedule"]
    assert schedule == {"shape": "linear_in_beta", "from_beta": 0.05, "to_beta": 2.0, "over_sweeps": 6,
                        "over_moves": 384, "then": "held at the law's beta"}
    early = lambda env: CL.record(env, CL.FROM_EMPTY)["accounting"]  # noqa: E731
    assert CL.sorted_edges(cooled) != CL.sorted_edges(plain)
    assert early(cooled) != early(plain)


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_a_cooled_chain_resumed_is_the_uninterrupted_one(engine):
    from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
    if engine == "rust":
        from tests.support.engines import require_rust_engine
        require_rust_engine()
    _, run, _ = resolve_engine({"engine": engine})
    law = _law(cooling={"from_beta": 0.25, "over_sweeps": 9})
    whole = run(law, 96, 5, target_sweeps=16, record_points=8)
    half = run(law, 96, 5, target_sweeps=6, record_points=8)
    checkpoint = json.loads(json.dumps(half["sampling_checkpoint"], default=list))
    resumed = run(law, 96, 5, target_sweeps=16, record_points=8, resume_checkpoint=checkpoint)
    assert CL.sorted_edges(resumed) == CL.sorted_edges(whole)
    assert CL.block(resumed, CL.FROM_EMPTY)["rng_state"] == CL.block(whole, CL.FROM_EMPTY)["rng_state"]
