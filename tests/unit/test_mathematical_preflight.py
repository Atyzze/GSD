from __future__ import annotations

import random

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.services.proposer.main import generate_batch
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research.hamiltonian_preflight import (
    effective_basis, equilibrium_identity, preflight_assessment,
)
from graph_scale_dynamics.research.proposal_memory import proposal_assessment
from graph_scale_dynamics.scaleflow.engine_door import run_simulation


def _spec(terms, beta=1.0, sweeps=3):
    return {
        "dsl_version": 1,
        "init": "empty",
        "terms": terms,
        "dynamics": {
            "kind": "equilibrium",
            "beta": beta,
            "move_mix": {"add": 0.5, "delete": 0.5},
            "sweeps": sweeps,
        },
    }


def _term(op, c0, scale="one", params=None, p=None):
    coeff = {"c0": c0, "scale": scale}
    if scale == "power":
        coeff["p"] = p
    return {"op": op, "params": params or {}, "coeff": coeff}


def test_quadratic_degree_identities_and_beta_are_exactly_quotiented():
    left = _spec([_term("wedge_count", 2.0), _term("edge_count", 3.0)], beta=1.0)
    right = _spec([_term("degree_square_sum", 0.5), _term("edge_count", 0.5)], beta=2.0)
    assert equilibrium_identity(left)[0] == equilibrium_identity(right)[0]
    assert effective_basis(left) == effective_basis(right)


def test_anchor_additive_constant_and_power_aliases_do_not_change_identity():
    anchor = _spec([
        _term("degree_anchor", 1.0, "power", {"k": 4}, p=-1.0),
        _term("edge_count", 16.0, "inv_N"),
    ])
    reduced = _spec([_term("degree_square_sum", 1.0, "inv_N")])
    assert equilibrium_identity(anchor)[0] == equilibrium_identity(reduced)[0]


def test_preflight_downweights_but_does_not_exclude_degree_only_laws():
    spec = _spec([_term("edge_count", 1.0, "log_N"),
                  _term("degree_anchor_abs", 1.0, "one", {"k": 4})])
    preflight = preflight_assessment(spec)
    assert preflight["classification"] == "degree_sequence_only"
    assert preflight["degree_sequence_only"] is True
    assert 0 < preflight["allocation_multiplier"] < 1
    assessment = proposal_assessment(spec, {}, {"exploration_floor": 0.08})
    assert assessment["would_admit"] is True
    assert assessment["allocation_weight"] >= 0.08
    assert assessment["physical_equivalence_id"] == preflight["physical_equivalence_id"]


def test_vanishing_topology_term_and_missing_sparse_mechanism_are_visible():
    spec = _spec([_term("triangle_count", -0.2, "inv_N")])
    preflight = preflight_assessment(spec)
    assert preflight["classification"] == "topology_sensitive"
    assert preflight["topology_relevant_terms"] == 0
    assert preflight["robust_sparse_mechanism"] is False
    assert any("vanish" in warning for warning in preflight["warnings"])


def test_generation_omits_existing_physical_equivalents():
    existing_spec = _spec([_term("degree_square_sum", 1.0), _term("edge_count", 1.0)])
    existing_physical = {equilibrium_identity(existing_spec)[0]}
    batch = generate_batch(
        random.Random(7), 12,
        {"operator_whitelist": list(dsl.OPERATORS), "complexity_budget": 6,
         "proposer": {"weights": {"enumeration": 0.0, "mutation": 0.0, "novelty": 1.0}}},
        set(), [], existing_physical=existing_physical,
    )
    assert batch
    assert all(equilibrium_identity(spec)[0] not in {equilibrium_identity(existing_spec)[0]}
               for spec, _, _ in batch)
    assert len({equilibrium_identity(spec)[0] for spec, _, _ in batch}) == len(batch)


def test_empty_start_envelope_reports_growth_and_given_start_diagnostics():
    spec = _spec([_term("edge_count", 0.4, "log_N"),
                  _term("degree_square_sum", 0.05)], sweeps=4)
    envelope = run_simulation(spec, 24, 17, record_points=24)
    diagnostics = envelope["trajectory_diagnostics"]
    assert diagnostics["late_fraction"] == 0.30
    assert isinstance(diagnostics["declared_still_growing"], bool)
    assert "empty_given_late_mean_degree_relative_gap" in diagnostics
    assert CL.trajectory(envelope)[-1]["accepted_add"] >= 0
    assert CL.record(envelope, CL.GIVEN)["init"].startswith("erdos_renyi_mean_degree_")


def test_simulation_rejects_noncurrent_engine_contract():
    spec = _spec([_term("edge_count", 0.4, "log_N"),
                  _term("degree_square_sum", 0.05)], sweeps=2)
    import pytest
    with pytest.raises(ValueError, match="unsupported engine contract"):
        run_simulation(spec, 20, 5, engine_contract_version="engine-2.6.0")


def test_square_reward_overlap_control_is_recognized():
    controlled = _spec([
        _term("edge_count", 0.3, "log_N"),
        _term("induced_square_count", -0.2),
        _term("square_edge_overlap", 0.15),
    ])
    assessment = preflight_assessment(controlled)
    assert assessment["classification"] == "topology_sensitive"
    assert any("paired with a square edge-overlap penalty" in warning
               for warning in assessment["warnings"])
    assert not any("lacks an edge-overlap" in warning for warning in assessment["warnings"])


def test_negative_quadratic_with_positive_quartic_is_marked_stabilized():
    spec = _spec([
        _term("degree_anchor", -0.08, params={"k": 7}),
        _term("degree_fourth_sum", 0.004),
        _term("edge_count", 0.18, "log_N"),
    ])
    assessment = preflight_assessment(spec)
    assert assessment["anti_coercive_degree_terms"] == 1
    assert assessment["stabilized_anti_coercive_degree_terms"] == 1
    assert assessment["unstabilized_anti_coercive_degree_terms"] == 0
    assert any("positive quartic stabilizer" in warning for warning in assessment["warnings"])
