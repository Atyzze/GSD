from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.measurements import shaped_starts
from graph_scale_dynamics.measurements.calibration import control_family_edges, control_family_reaches
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy, resolve_given_start
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

CRITERION = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json").read_text())
P2 = next(law for law in CRITERION["laws"] if law["label"] == "P2")["spec"]


def test_a_shaped_family_is_named_reached_and_built_from_the_job_s_seed():
    name = shaped_starts.family(3, 6)
    assert name == "random_geometric_3d_degree_6" and shaped_starts.parse(name) == (3, 6)
    assert shaped_starts.parse("periodic_square_lattice") is None
    assert shaped_starts.parse("random_geometric_0d_degree_4") is None
    assert control_family_reaches(name, 1000) and control_family_reaches(name, 4_194_304)
    assert not control_family_reaches(name, 4), "too small to have a shape"
    first, again, other = (control_family_edges(name, 500, seed=s) for s in (1, 1, 2))
    assert first == again and first != other, "each seed its own start, the same every time"
    degrees = [0] * 500
    for u, v in first:
        degrees[u] += 1
        degrees[v] += 1
    assert max(degrees) <= 6 and sum(d == 6 for d in degrees) >= 0.9 * 500


def _campaign(kernel="local_walk", candidate_id="law") -> dict:
    spec = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                       / "campaign_engine_survey.json").read_text())
    sampling = spec.setdefault("sampling_contract", {})
    sampling["max_sweeps_multiplier"] = 1
    sampling.pop("given_start", None)
    declared = {"family": shaped_starts.family(2, 4)}
    if kernel is not None:
        declared["kernel"] = kernel
    sampling["given_start_by_law"] = {candidate_id: declared}
    return spec


def test_the_job_carries_the_start_and_the_given_chain_s_way_of_moving():
    assert resolve_given_start(_campaign(), 256, "law") == {"family": "random_geometric_2d_degree_4", "n": 256,
                                                             "kernel": "local_walk"}
    assert resolve_given_start(_campaign(kernel=None), 256, "law") == {"family": "random_geometric_2d_degree_4",
                                                                        "n": 256}
    with pytest.raises(ValueError, match="kernel"):
        resolve_given_start(_campaign(kernel="teleport"), 256, "law")


def _run(spec, n=256, seed=1, sweeps=60, kernel="local_walk", simulate=None):
    law = json.loads(json.dumps(spec))
    law["dynamics"]["sweeps"] = sweeps
    policy = one_shot_policy(_campaign(kernel=kernel), n, "law")
    return run_one_shot(law, n, seed, one_shot=policy, initial_multiplier=1,
                        simulate=simulate or resolve_engine({})[1])


def test_the_given_chain_starts_from_the_shape_moves_locally_and_says_so():
    envelope = _run(P2)
    assert CL.record(envelope, CL.GIVEN)["init"] == "family_random_geometric_2d_degree_4"
    assert CL.record(envelope, CL.GIVEN)["kernel"] == "local_walk"
    given = CL.block(envelope, CL.GIVEN)
    assert given["init"] == "family_random_geometric_2d_degree_4" and given["kernel"] == "local_walk", \
        "the checkpoint carries both, so a continuation goes on as it began"
    start = shaped_starts.build(256, 2, 4, 1)
    first = given["trajectory"][0]
    assert abs(first["edges"] - len(start)) <= 1, "the given chain's first recorded point is its start, one move on"
    assert abs(E.configuration_energy(P2, 256, given["edge_list"]) - given["energy"]) < 1e-6
    from_empty = CL.block(envelope, CL.FROM_EMPTY)["trajectory"][0]
    assert from_empty["edges"] <= 1, "the chain from empty grows from the empty graph, as every law's does, one move on"
    scopes = {key.split(".")[1] for key, count in given["accounting"]["counts"].items() if count}
    assert scopes == {"local"}, "no global move: every one of the given chain's moves stays within three steps"


def test_the_chain_from_empty_is_what_it_was_whatever_the_given_chain_does():
    declared = {"family": shaped_starts.family(2, 4), "edges": shaped_starts.build(256, 2, 4, 1),
                "kernel": "local_walk"}
    shaped = engine_door.run_simulation(P2, 256, 1, target_sweeps=30, given_start=declared)
    random_chain = engine_door.run_simulation(P2, 256, 1, target_sweeps=30)
    assert CL.sorted_edges(shaped) == CL.sorted_edges(random_chain) and CL.trajectory(shaped) == CL.trajectory(random_chain)
    assert CL.record(random_chain, CL.GIVEN)["kernel"] is None, "a given chain that moves as the law does names no kernel"


def test_a_continuation_that_would_change_the_given_chain_s_way_of_moving_is_refused():
    law = json.loads(json.dumps(P2))
    law["dynamics"]["sweeps"] = 20
    start = shaped_starts.build(128, 2, 4, 0)
    declared = {"family": shaped_starts.family(2, 4), "edges": start, "kernel": "local_walk"}
    first = engine_door.run_simulation(law, 128, 0, target_sweeps=20, given_start=declared)
    with pytest.raises(ValueError, match="kernel mismatch"):
        engine_door.run_simulation(law, 128, 0, target_sweeps=40, resume_checkpoint=first["sampling_checkpoint"],
                         given_start={"family": shaped_starts.family(2, 4)})
    again = engine_door.run_simulation(law, 128, 0, target_sweeps=40, resume_checkpoint=first["sampling_checkpoint"],
                             given_start={"family": shaped_starts.family(2, 4), "kernel": "local_walk"})
    assert CL.record(again, CL.GIVEN)["kernel"] == "local_walk"
