from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine.engine import configuration_energy
from graph_scale_dynamics.measurements.calibration import control_family_edges
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from benchmark_campaign import DEFAULT_SPEC, control_spec  # noqa: E402

CRITERION = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "positive_control_criterion.json").read_text())
LATTICE_LAW = CRITERION["laws"][0]["spec"]


def _campaign(declared: bool) -> dict:
    spec = control_spec(json.loads(DEFAULT_SPEC.read_text()))
    spec["sampling_contract"]["max_sweeps_multiplier"] = 1
    if not declared:
        spec["sampling_contract"].pop("given_start")
    return spec


def _run(declared: bool, n: int = 64, simulate=None):
    policy = one_shot_policy(_campaign(declared), n)
    return run_one_shot(LATTICE_LAW, n, 0, one_shot=policy, initial_multiplier=1,
                        simulate=simulate or resolve_engine({})[1])


def test_the_job_carries_the_torus_and_the_given_chain_starts_there():
    envelope = _run(declared=True)
    assert CL.record(envelope, CL.GIVEN)["init"] == "family_periodic_square_lattice", \
        "every chunk says where the given chain began, the last one included"
    given = CL.block(envelope, CL.GIVEN)
    first = given["trajectory"][0]
    torus = configuration_energy(LATTICE_LAW, 64, control_family_edges("periodic_square_lattice", 64))
    assert abs(torus / 64 - (-4.0)) < 1e-9, "the flat torus is the lattice law's ground state, -4 a node"
    assert abs(first["energy"] - torus) <= 20.0, \
        "the given chain's first recorded energy is the torus's, give or take its first move"
    from_empty = CL.block(envelope, CL.FROM_EMPTY)["trajectory"][0]
    assert from_empty["edges"] <= 1 and from_empty["energy"] > 0, \
        "the chain from empty starts from the empty graph, as every law does, its first point one move on"
    assert given["init"] == "family_periodic_square_lattice", "the checkpoint carries the declared start"


def test_an_undeclared_given_chain_is_the_historical_draw_and_its_checkpoint_says_so():
    envelope = _run(declared=False)
    assert CL.record(envelope, CL.GIVEN)["init"] == "erdos_renyi_mean_degree_8"
    assert CL.block(envelope, CL.GIVEN)["init"] == "erdos_renyi_mean_degree_8", \
        "every chain's block names its start, the random draw's as well (775)"


def test_the_policy_carries_no_start_for_a_campaign_that_declares_none():
    assert one_shot_policy(_campaign(declared=False), 1024)["given_start"] is None
    declared = one_shot_policy(_campaign(declared=True), 1024)["given_start"]
    assert declared == {"family": "periodic_square_lattice", "n": 1024}
    assert len(control_family_edges(declared["family"], declared["n"])) == 2048


def test_both_engines_start_the_given_chain_on_the_same_graph():
    python = _run(declared=True, simulate=resolve_engine({"engine": "python"})[1])
    rust = _run(declared=True, simulate=resolve_engine({"engine": "rust"})[1])
    for chain in ("empty", "given"):
        assert (CL.block(python, chain)["edge_list"] == CL.block(rust, chain)["edge_list"]), chain
    assert CL.record(python, CL.GIVEN)["init"] == CL.record(rust, CL.GIVEN)["init"] == "family_periodic_square_lattice"


def test_a_continuation_still_says_where_the_given_chain_began():
    campaign = control_spec(json.loads(DEFAULT_SPEC.read_text()))
    campaign["sampling_contract"]["max_sweeps_multiplier"] = 4
    envelope = run_one_shot(LATTICE_LAW, 64, 0, one_shot=one_shot_policy(campaign, 64), initial_multiplier=1,
                            simulate=resolve_engine({})[1])
    chunks = envelope["rung_terminal"]["history"] if "history" in envelope.get("rung_terminal", {}) else None
    assert envelope["sampling_checkpoint"]["cumulative_sweeps"] > 250, "more than one chunk ran"
    assert CL.record(envelope, CL.GIVEN)["init"] == "family_periodic_square_lattice", chunks
