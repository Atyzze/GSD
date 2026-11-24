from __future__ import annotations

import itertools
import math

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.dsl.dsl import fingerprint
from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import study_design as SD
from graph_scale_dynamics.resources import committed
from graph_scale_dynamics.scaleflow import engine_door
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from tests.support import designs

pytestmark = [pytest.mark.scientific]

WITHIN = 1e-9
CHUNKS_AT_LEAST = 2
ENGINES = {"python": (engine_door.run_simulation,), "rust": (engine_door.simulate_of("rust"),),
           "both, chunk by chunk": (engine_door.run_simulation, engine_door.simulate_of("rust"))}
SIZES_AND_CEILINGS = {"python": ((64, 16),), "rust": ((64, 64), (256, 8)), "both, chunk by chunk": ((64, 16),)}


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, mix=(0.45, 0.45, 0.10), sweeps=6, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": mix[0], "delete": mix[1], "swap": mix[2]},
                         "sweeps": sweeps, **dynamics}}


LAWS = {
    "edges_and_anchor": _law([_term("edge_count", 0.25, "log_N"), _term("degree_anchor", 0.3, k=6)]),
    "triangles_and_squares": _law([_term("edge_count", 0.4), _term("triangle_count", 0.2, "inv_log_N"),
                                   _term("square_count", 0.05, "inv_N")], locality=0.6),
    "overlaps": _law([_term("square_edge_overlap", 0.02), _term("triangle_edge_overlap", -0.05)], mix=(0.3, 0.3, 0.4)),
    "induced_squares": _law([_term("edge_count", 0.3), _term("induced_square_count", 0.01), _term("wedge_count", -0.1)],
                            locality=0.4),
    "moments": _law([_term("degree_neighbor_gradient", 0.01, "inv_N"), _term("degree_cube_sum", 0.002),
                     _term("degree_fourth_sum", 0.0001, "inv_sqrt_N"), _term("degree_anchor_abs", 0.2, k=4),
                     _term("degree_square_sum", 0.05)]),
    "curvature": _law([_term("degree_anchor", 0.5, k=6), _term("ollivier_curvature", -0.05), _term("edge_count", 0.2)],
                      mix=(0.4, 0.4, 0.2), locality=0.3),
    "zero_temperature": _law([_term("edge_count", -1.0), _term("degree_square_sum", 0.1)],
                             zero_temperature=True, locality=0.9),
    "cooled": _law([_term("edge_count", 0.3), _term("degree_anchor", 0.4, k=4), _term("induced_square_count", -0.2)],
                   mix=(0.4, 0.4, 0.2), cooling={"from_beta": 0.25, "over_sweeps": 10}),
    "integer_couplings": _law([_term("edge_count", 1.0), _term("triangle_count", -2.0), _term("degree_anchor", 1.0, k=4)],
                              locality=0.5),
}


def _campaign_spec() -> dict:
    design = designs.a_design()
    design.pop("starts_reading", None)
    return SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][0], 0)


def chains_of(envelope: dict):
    for record in CL.records(envelope):
        block = CL.block(envelope, record["start"])
        if not block:
            continue
        yield f"{record['start']}, as it ends", block["edge_list"], (record.get("final") or block["final"])["energy"]
        yield f"{record['start']}, as it resumes", block["edge_list"], block["energy"]


def off_its_graph(spec: dict, n: int, envelope: dict) -> list[str]:
    off = []
    for name, edges, running in chains_of(envelope):
        scratch = engine.configuration_energy(spec, n, edges)
        if not math.isfinite(float(running)) or abs(float(running) - scratch) > WITHIN * max(1.0, abs(scratch)):
            off.append(f"{name}: carries {running!r}, its {len(edges)} edges sum to {scratch!r}")
    return off


def held(simulators, seen: list):
    turn = itertools.cycle(simulators)

    def simulate(candidate_spec, n, seed, **kwargs):
        envelope = next(turn)(candidate_spec, n, seed, **kwargs)
        seen.append({"chains": sum(1 for _ in chains_of(envelope)), "off": off_its_graph(candidate_spec, n, envelope)})
        return envelope
    return simulate


@pytest.mark.parametrize("name", sorted(LAWS))
@pytest.mark.parametrize("engines", sorted(ENGINES))
def test_each_chain_s_running_energy_is_its_graph_s_at_every_chunk_s_end(name, engines):
    law = LAWS[name]
    assert dsl.validate(law) == [], dsl.validate(law)
    spec = _campaign_spec()
    for n, ceiling in SIZES_AND_CEILINGS[engines]:
        policy = dict(one_shot_policy(spec, n, fingerprint(law), law), max_sweeps_multiplier=ceiling,
                      required_consecutive_passes=99, work_budget=10 ** 15)
        seen: list = []
        run_one_shot(law, n, 11, one_shot=policy, record_points=24, simulate=held(ENGINES[engines], seen))
        assert len(seen) >= CHUNKS_AT_LEAST, (n, len(seen))
        every_chain = 2 * (2 + len(policy.get("more_given") or []))
        assert every_chain >= 2 * 8 and all(chunk["chains"] == every_chain for chunk in seen), (n, every_chain, seen)
        assert not [chunk["off"] for chunk in seen if chunk["off"]], (n, [chunk["off"] for chunk in seen])


def test_the_laws_hold_every_term_and_every_way_of_moving():
    assert {term["op"] for law in LAWS.values() for term in law["terms"]} == set(dsl.OPERATORS)
    dynamics = [law["dynamics"] for law in LAWS.values()]
    assert any(d.get("locality") for d in dynamics) and any(d.get("zero_temperature") for d in dynamics)
    assert any(d.get("cooling") for d in dynamics) and any(d["move_mix"]["swap"] > 0 for d in dynamics)
    assert all(dsl.validate(law) == [] for law in LAWS.values())


def test_the_check_refuses_a_running_energy_that_has_drifted():
    law = LAWS["edges_and_anchor"]
    envelope = engine_door.simulate_of("rust")(law, 64, 3, record_points=4)
    assert off_its_graph(law, 64, envelope) == []
    CL.block(envelope, CL.FROM_EMPTY)["energy"] += 1e-6 * max(1.0, abs(CL.record(envelope, CL.FROM_EMPTY)["final"]["energy"]))
    assert [line.split(":")[0] for line in off_its_graph(law, 64, envelope)] == ["empty, as it resumes"]
