from __future__ import annotations

import hashlib
import math

import numpy as np
import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.artifact_store import chain_record as CR
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.measurements.structure_census import census
from graph_scale_dynamics.scaleflow.descent import disjoint_cliques, reference_configuration
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.services.worker import engine_rs
from tests.support.engines import require_rust_engine
from graph_scale_dynamics.scaleflow import engine_door

POLICY = {"contract": "one-shot-sampling-1", "max_sweeps_multiplier": 4, "required_consecutive_passes": 2,
          "work_budget": 10 ** 15, "work_unit": {"contract": "gsd-work-unit-1", "weights": {
              "moves": 1, "evaluations": 1, "changes": 1, "lists": 1, "entries": 1, "tests": 1}}}


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, sweeps=20, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": sweeps, **dynamics}}


CLIQUES_AT_ZERO_T = _law([_term("degree_anchor", 0.3, k=3), _term("triangle_count", -0.4, "log_N")],
                         zero_temperature=True)
WARM = _law([_term("edge_count", 0.25, "log_N"), _term("degree_anchor", 0.3, k=4)])


@pytest.fixture(scope="module")
def cold():
    require_rust_engine()
    return run_one_shot(CLIQUES_AT_ZERO_T, 128, 2, one_shot=POLICY, simulate=engine_door.simulate_of("rust"))


@pytest.fixture(scope="module")
def warm():
    require_rust_engine()
    return run_one_shot(WARM, 128, 2, one_shot=POLICY, simulate=engine_door.simulate_of("rust"))


def test_a_chain_s_graph_is_recorded_by_its_size_and_digest_in_any_order():
    rng = np.random.default_rng(1)
    pairs = np.unique(np.sort(rng.integers(0, 5000, size=(20000, 2)), axis=1), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    shuffled = pairs[rng.permutation(len(pairs))][:, ::-1]
    digest = CR.graph_digest(shuffled)
    assert digest == CR.graph_digest(pairs) and digest["edges"] == len(pairs)
    assert digest["sha256"] == hashlib.sha256(np.ascontiguousarray(pairs, dtype="<i8").tobytes()).hexdigest()
    assert CR.graph_digest([]) == {"edges": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    assert CR.graph_digest(pairs[1:])["sha256"] != digest["sha256"]


def test_a_seed_run_again_grows_the_graph_its_record_names(warm):
    record = CR.build_record(warm)
    again = run_one_shot(WARM, 128, 2, one_shot=POLICY, simulate=engine_door.simulate_of("rust"))
    assert [chain["graph"] for chain in CR.build_record(again)["chains"]] == [chain["graph"] for chain in record["chains"]]
    assert record["chains"][0]["graph"] == CR.graph_digest(CL.sorted_edges(again))

def test_zero_temperature_never_accepts_a_rise_and_a_warm_chain_does(cold, warm):
    cold_counts = CL.record(cold, CL.FROM_EMPTY)["accounting"]["counts"]
    assert sum(v for k, v in cold_counts.items() if ".pos.accepted" in k) == 0
    assert sum(v for k, v in cold_counts.items() if ".neg.accepted" in k) > 0
    warm_counts = CL.record(warm, CL.FROM_EMPTY)["accounting"]["counts"]
    assert sum(v for k, v in warm_counts.items() if ".pos.accepted" in k) > 0
    for envelope in (cold, warm):
        for chain in ("empty", "given"):
            acc = CL.record(envelope, chain)["accounting"]
            late, whole = acc["late"]["counts"], acc["counts"]
            assert all(late[k] <= whole[k] for k in whole)
            accepted_total = sum(v for k, v in whole.items() if k.endswith(".accepted"))
            assert sum(acc["delta_h_log2"]["accepted"].values()) == accepted_total


def test_the_accounting_agrees_with_the_chains_own_counters(warm):
    counts = CL.record(warm, CL.FROM_EMPTY)["accounting"]["counts"]
    accepted = CL.record(warm, CL.FROM_EMPTY)["acceptance"]["accepted"]
    for kind in ("add", "delete", "swap"):
        assert sum(v for k, v in counts.items() if k.startswith(f"{kind}.") and k.endswith(".accepted")) == accepted[kind]
    proposed = CL.record(warm, CL.FROM_EMPTY)["acceptance"]["proposed"]
    assert sum(counts.values()) == sum(proposed.values())


def test_recorded_points_carry_the_structure_of_the_graph_they_describe():
    require_rust_engine()
    envelope = engine_door.simulate_of("rust")(WARM, 128, 2, record_points=160)
    points = CL.trajectory(envelope)
    assert (len(points) - 1) % E.STRUCTURE_POINT_STRIDE == 0
    final = census(128, CL.sorted_edges(envelope))
    assert points[-1]["components"] == final["components"]["count"]
    assert points[-1]["largest_component"] == final["largest_component"]["size"]
    assert points[-1]["triangles"] == final["cliques"]["triangles"]
    carrying = [i for i, p in enumerate(points) if "triangles" in p]
    assert carrying == list(range(0, len(points), E.STRUCTURE_POINT_STRIDE))


def test_a_term_records_the_scale_it_was_declared_with_and_an_unused_ledger_reads_null(warm):
    parts = CL.trajectory(warm)[-1]["active_term_components"]
    assert [p["scale"] for p in parts] == ["log_N", "one"]
    ledgers = CL.record(warm, CL.FROM_EMPTY)["final"]["ledgers"]
    assert ledgers["edge_count"] == CL.record(warm, CL.FROM_EMPTY)["final"]["edge_count"], "a term of this law: kept"
    assert ledgers["triangle_count"] is None and ledgers["square_count"] is None, "not terms of this law: null"


def test_a_configurations_energy_is_summed_as_the_chain_sums_it(warm):
    assert math.isclose(E.configuration_energy(WARM, 128, CL.sorted_edges(warm)), CL.record(warm, CL.FROM_EMPTY)["final"]["energy"],
                        rel_tol=1e-9, abs_tol=1e-9)


def test_the_descent_record_names_the_reference_it_is_measured_from(cold, warm):
    reference = cold["descent"]["reference"]
    assert reference["kind"] == "disjoint_cliques" and reference["clique_size"] == 4
    assert math.isclose(reference["energy"],
                        E.configuration_energy(CLIQUES_AT_ZERO_T, 128, disjoint_cliques(128, 4)))
    from_empty = cold["descent"]["chains"]["empty"]
    assert from_empty["last_decrease_move"] is not None
    assert math.isclose(from_empty["distance_from_reference"], CL.record(cold, CL.FROM_EMPTY)["final"]["energy"] - reference["energy"])
    assert warm["descent"]["reference"]["kind"] is None, "no degree anchor with a triangle reward: null, never 0"
    assert warm["descent"]["chains"]["empty"]["distance_from_reference"] is None
    assert reference_configuration(CLIQUES_AT_ZERO_T, 10 ** 7)["energy"] is None


def test_every_chunk_keeps_the_certificate_values_it_was_judged_on(warm):
    for chunk in warm["sampling_checkpoints"]:
        cert = chunk["certificate"]
        assert set(cert["structural_limits"]) == {"connected_fraction", "two_core_fraction",
                                                  "largest_component_cycle_rank_density",
                                                  "component_count_per_node"}
        assert "split" in cert and "stationarity_drift" in cert


def test_the_record_keeps_both_chains_and_each_chain_s_late_change_by_its_size(warm):
    record = CR.decode_record(CR.encode_record(warm))
    assert record["contract"] == CR.RECORD_CONTRACT and record["n"] == 128
    assert [chain["start"] for chain in record["chains"]] == ["empty", "given"], "one list, in the order they ran"
    from_empty, given = record["chains"]
    assert from_empty["graph"] == CR.graph_digest(CL.sorted_edges(warm))
    assert given["graph"] == CR.graph_digest(CL.block(warm, CL.GIVEN)["edge_list"])
    assert from_empty["trajectory"]["points"] == len(CL.trajectory(warm))
    assert from_empty["trajectory"]["columns"]["energy"] == [p["energy"] for p in CL.trajectory(warm)]
    assert from_empty["trajectory"]["columns"]["term1.observable"][-1] == \
        CL.trajectory(warm)[-1]["active_term_components"][1]["observable"]
    for chain in record["chains"]:
        late = CL.block(warm, chain["start"])["late_change"]
        assert chain["late_change"] == {"from_move": late["from_move"], "added": len(late["added"]),
                                        "removed": len(late["removed"]), "overlap": chain["late_change"]["overlap"]}
        assert "snapshots" not in chain, "no copy of a graph is stored, at any size"
    assert from_empty["accounting"] == CL.record(warm, CL.FROM_EMPTY)["accounting"]


def test_the_couplings_at_each_rung_are_recorded(warm):
    couplings = warm["couplings"]
    assert couplings["n"] == 128 and [t["op"] for t in couplings["terms"]] == ["edge_count", "degree_anchor"]
    assert math.isclose(couplings["terms"][0]["coefficient"], 0.25 * math.log(128))
    reduced = {(r["op"], r["scale"]): r["beta_coefficient"] for r in couplings["reduced"]}
    assert math.isclose(reduced[("edge_count", "one")], -4 * 4 * 0.3), "the anchor's -4k E, folded"
