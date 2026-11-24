from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements.certificate import structural_noise
from graph_scale_dynamics.observability.meeting_reading import seed_meeting_reading
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scaleflow.probes import bucket_for_rung
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from tests.support import chains as SC

ROOT = Path(__file__).resolve().parents[2]


def _term(op, c0, **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": "one"}}


COLD = {"dsl_version": 1, "init": "empty",
        "terms": [_term("degree_anchor", 1.0, k=3), _term("triangle_count", -0.5)],
        "dynamics": {"kind": "equilibrium", "beta": 1.0, "sweeps": 30, "zero_temperature": True,
                     "move_mix": {"add": 0.45, "delete": 0.45, "swap": 0.10}}}


@pytest.fixture(scope="module")
def policy():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    return dict(one_shot_policy(campaign), mean_degree_cap=16.0)


def _passing_health(**cert):
    own = {"effective_samples": 50.0, "stationarity": {"normalized_drift": 0.0}}
    pair = {"chains": ["empty", "given"], "split": {"energy_per_node_z": 0.1}, **cert}
    return {"numerics_ok": True, "stationarity": {"normalized_drift": 0.0},
            "structural_trend": {"chains": {"empty": {"connected_fraction": {"drifting": False}}}},
            "equilibration": {"effective_samples": 50.0, "split": {"energy_per_node_z": 0.1},
                              "decide": ["empty", "given"], "chains": {"empty": own, "given": own},
                              "pairs": {"empty|given": pair}, **cert}}


def test_a_zero_temperature_law_is_read_at_rest(policy):
    envelope = run_one_shot(COLD, 64, 1, one_shot=policy, initial_multiplier=1)
    terminal = envelope["rung_terminal"]
    assert terminal["classification"] == eq.AT_REST and terminal["failures"] == [], terminal
    rest = terminal["at_rest"]
    assert all(row["at_rest"] for row in rest["chains"].values()), rest
    assert rest["pairs"]["empty|given"]["reading"] in ("same_minimum", "different_minima")
    assert bucket_for_rung({"valid": True, "d_s": 1.0}, terminal_classification=eq.AT_REST) is None


def test_a_chain_still_falling_is_continued_and_at_the_ceiling_is_relaxing():
    health = {"numerics_ok": True, "regime": "zero_temperature",
              "structural_trend": {"chains": {"empty": {"connected_fraction": {"drifting": False}}}},
              "at_rest": {"limit_late_descent_share": 0.01, "chains": {
                  "empty": {"at_rest": False, "late_descent_share": 0.2},
                  "given": {"at_rest": True, "late_descent_share": 0.0}}}}
    passed, failures = eq.certificate_pass({}, health)
    assert not passed and [f["code"] for f in failures] == [eq.CERT_NOT_AT_REST], failures
    assert "the chain from empty still improving" in failures[0]["detail"]
    assert eq.terminal_at_ceiling(health, failures) == eq.RELAXING_AT_CEILING
    assert eq.terminal_at_ceiling(health, []) == eq.AT_REST, "at rest on the last chunk only is at rest"
    health["at_rest"]["chains"]["empty"] = {"at_rest": True, "late_descent_share": 0.001}
    assert eq.certificate_pass({}, health) == (True, [])
    assert eq.activity_label(health) == eq.AT_REST


def test_given_chains_at_rest_in_different_minima_are_a_finding():
    rows = [{"move": 0, "energy": 100.0}, {"move": 50, "energy": -10.0}, {"move": 100, "energy": -10.0}]
    late = {"late": {"from_move": 60, "counts": {"add.global.zero.accepted": 5}}}
    envelope = SC.pair(10, rows, [dict(r, energy=r["energy"] + (2 if i else 0)) for i, r in enumerate(rows)],
                       empty={"final": {"energy": -10.0}, "accounting": late}, given_record={"accounting": late},
                       given_block={"energy": -8.0}, proposal_model={"dynamics_regime": "zero_temperature"})
    rest = eq.rest_reading(envelope)
    assert rest["pairs"] == {"empty|given": {"reading": "different_minima", "energy_per_node_gap": 0.2,
                                              "structural_split": None}}
    assert eq.rest_pass({"at_rest": rest}) == (True, [])
    assert eq.rest_reading(dict(envelope, proposal_model={})) is None, "other laws are certified as before"


def test_a_gap_is_judged_by_its_own_spread_with_a_floor():
    limits = eq.structural_limits({})
    noisy = _passing_health(structural_split={"connected_fraction": 0.3},
                            structural_noise_detrended={"connected_fraction": 0.12})
    assert eq.certificate_pass({}, noisy) == (True, []) and 0.3 > limits["connected_fraction"]
    tight = _passing_health(structural_split={"connected_fraction": 0.2},
                            structural_noise_detrended={"connected_fraction": 0.006})
    passed, failures = eq.certificate_pass({}, tight)
    assert not passed and failures[0]["detail"].endswith("(floor)"), failures
    inside = _passing_health(structural_split={"connected_fraction": 0.02},
                             structural_noise_detrended={"connected_fraction": 1e-6})
    assert eq.certificate_pass({}, inside) == (True, [])
    judged = eq.structural_thresholds({}, inside["equilibration"]["pairs"]["empty|given"])
    assert judged["connected_fraction"]["basis"] == "floor"
    assert judged["two_core_fraction"] == {"threshold": limits["two_core_fraction"], "basis": "absolute",
                                           "noise": None}
    final_only = _passing_health(structural_split={"two_core_fraction": 0.3})
    assert not eq.certificate_pass({}, final_only)[0]


def test_the_spread_is_read_from_both_chains_structure_points():
    n = 100
    from_empty = [{"move": i, "largest_component": 90 + (i % 2) * 2, "components": 5} for i in range(10)]
    given = [{"move": i, "largest_component": 80 + (i % 2) * 2, "components": 6} for i in range(10)]
    noise = structural_noise(SC.pair(n, from_empty, given), "empty", "given")
    assert noise["connected_fraction"] == pytest.approx((2 * 0.01 ** 2 * 12 / 10) ** 0.5, rel=1e-9)
    assert noise["component_count_per_node"] == pytest.approx(0.0, abs=1e-12)
    assert structural_noise(SC.pair(n, from_empty[:2]), "empty", "given")["connected_fraction"] is None


def _rows(triangles, *, n=64):
    return [{"move": i * 100, "energy": -1.0 * n, "mean_degree": 4.0, "edges": 128 + i % 3,
             "accepted_add": 20 * i, "accepted_delete": 0, "accepted_swap": 0,
             **({"triangles": triangles} if i % 20 == 0 else {})} for i in range(80)]


def test_the_meeting_reading_sees_wiring():
    envelope = SC.pair(64, _rows(40), _rows(40))
    same = seed_meeting_reading(envelope, {"empty": {"cliques": {"triangles": 40}},
                                        "given": {"cliques": {"triangles": 41}}})
    assert same["reading"] == "agreeing" and same["observables"]["triangles_per_node"]["source"] == "census"
    rewired = seed_meeting_reading(envelope, {"empty": {"cliques": {"triangles": 40}},
                                           "given": {"cliques": {"triangles": 3}}})
    wiring = rewired["observables"]["triangles_per_node"]
    assert not wiring["agree"] and rewired["reading"] == "disagreeing_while_moving", rewired
    CL.block(envelope, CL.GIVEN)["trajectory"] = _rows(3)
    fallback = seed_meeting_reading(envelope, {"empty": {"cliques": {"triangles": None}}, "given": None})
    assert fallback["observables"]["triangles_per_node"]["source"] == "trajectory"
    assert not fallback["observables"]["triangles_per_node"]["agree"]


def test_a_certificate_of_the_chain_from_empty_alone_is_not_read_as_a_pass():
    old = {"numerics_ok": True, "stationarity": {"normalized_drift": 0.0},
           "structural_trend": {"chains": {}}, "equilibration": {"effective_samples": 0.5, "split": {}}}
    passed, failures = eq.certificate_pass({}, old)
    assert not passed and [f["code"] for f in failures] == [eq.CERT_MISSING], (
        "with no chains that decide, nothing would be judged: an old certificate is refused, never passed")
