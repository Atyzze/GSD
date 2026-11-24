from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements import certificate as C
from graph_scale_dynamics.research.certificate_known_answers import ar1, envelope_of, phi_for
from graph_scale_dynamics.scaleflow import equilibration as eq
from tests.support import chains as SC

ROOT = Path(__file__).resolve().parents[2]
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "certificate_fixes_criterion.json"
POINTS, REPLICATES, LAGS = 240, 300, (1.0, 5.0, 20.0)
ERRORS = eq.DRIFT_ERRORS


def _late_drift_se(phi: float) -> float:
    late = np.arange(int(POINTS * C.LATE_SHARE), POINTS, dtype=float)
    centred = late - late.mean()
    lag = np.abs(np.subtract.outer(np.arange(len(late)), np.arange(len(late))))
    covariance = phi ** lag / (1.0 - phi * phi)
    window = late[-1] - late[0]
    return window * float(np.sqrt(centred @ covariance @ centred)) / float(centred @ centred)


def _fails(series) -> bool:
    drift = C.own_drift(envelope_of(series), CL.FROM_EMPTY)
    return abs(drift["normalized_drift"]) > ERRORS


@pytest.fixture(scope="module")
def runs():
    rng = np.random.default_rng(20261119)
    out = {}
    for tau in LAGS:
        phi = phi_for(tau)
        noise = ar1(phi, POINTS, REPLICATES, rng)
        start = int(POINTS * C.LATE_SHARE)
        ramp = np.clip((np.arange(POINTS) - start) / (POINTS - 1 - start), 0.0, None)
        out[tau] = (noise, noise + 10.0 * _late_drift_se(phi) * ramp)
    return out


def test_the_criterion_came_before_the_fixes():
    criterion = json.loads(CRITERION.read_text(encoding="utf-8"))
    assert criterion["committed_utc"] == "2026-11-19T02:23:47Z"
    assert {case["id"] for case in criterion["known_answers"]} == {
        "drift_none", "drift_some", "drift_offset", "split_rounding", "split_real", "rest_wandering",
        "rest_drifting", "cap_confirmed", "cap_refused"}


@pytest.mark.parametrize("tau", LAGS)
def test_drift_some_fails_at_every_lag(runs, tau):
    _still, moving = runs[tau]
    assert sum(_fails(series) for series in moving) >= 0.95 * REPLICATES, f"a drift of 10 errors passes (lag {tau})"


@pytest.mark.parametrize("tau", LAGS[:2])
def test_drift_none_passes_at_a_lag_of_1_and_5_points(runs, tau):
    still, _moving = runs[tau]
    assert sum(_fails(series) for series in still) <= 0.05 * REPLICATES, f"a chain with no drift fails (lag {tau})"


def test_drift_none_at_a_lag_of_20_points_is_the_criterion_s_one_miss(runs):
    still, _moving = runs[20.0]
    failed = [series for series in still if _fails(series)]
    assert 0.05 * REPLICATES < len(failed) <= 0.15 * REPLICATES, len(failed)
    counted = [C.own_count(envelope_of(series), CL.FROM_EMPTY)["effective_samples"] for series in failed]
    assert sum(samples >= 16 for samples in counted) <= 0.01 * REPLICATES, (
        "nearly every chain the drift test holds back wrongly here also fails the 16 samples a study asks")


def test_drift_offset_changes_no_verdict(runs):
    for still, moving in runs.values():
        for series in (*still[:60], *moving[:60]):
            verdict = _fails(series)
            assert _fails(series + 1e6) == verdict and _fails(series * 1e3) == verdict


def _frozen_pair(a: float, b: float) -> dict:
    rows = lambda energy: [{"move": float(t), "energy": energy * 100.0, "mean_degree": 4.0} for t in range(60)]  # noqa: E731
    return SC.pair(100, rows(a), rows(b))


def test_split_rounding_and_split_real():
    assert C.pair_split(_frozen_pair(7.0, 7.0 * (1 + 1e-11)), CL.FROM_EMPTY, CL.GIVEN)["energy_per_node_z"] == 0.0
    assert C.pair_split(_frozen_pair(7.0, 7.007), CL.FROM_EMPTY, CL.GIVEN)["energy_per_node_z"] > 3.0


def _resting(largest_from: float, largest_to: float) -> dict:
    n, total, late_from = 100, 24000, 20400
    rows = []
    for i in range(POINTS):
        move = i * total // POINTS
        late = move >= late_from
        share = (move - late_from) / (total - late_from) if late else 0.0
        rows.append({"move": move, "energy": 50.0 if late else 150.0 - move * 100.0 / late_from,
                     "largest_component": round(largest_from + (largest_to - largest_from) * share),
                     "components": 1 if late else 2, "mean_degree": 3.0})
    accounting = {"late": {"from_move": late_from, "counts": {"swap.global.zero.accepted": 900,
                                                              "add.global.neg.accepted": 0}}}
    return SC.pair(n, rows, list(rows), empty={"accounting": accounting, "final": {"energy": 50.0}},
                   given_record={"accounting": accounting, "final": {"energy": 50.0}},
                   proposal_model={"dynamics_regime": "zero_temperature"})


def test_rest_wandering_is_at_rest_and_rest_drifting_is_not():
    policy = {}
    wandering = eq.inline_health(_resting(100, 100), policy)
    assert wandering["at_rest"]["chains"]["empty"]["late_accepted_per_node"] == 9.0, "neutral moves, late"
    assert eq.certificate_pass(policy, wandering) == (True, [])
    drifting = eq.inline_health(_resting(100, 90), policy)
    passed, failures = eq.certificate_pass(policy, drifting)
    assert not passed and {f["code"] for f in failures} == {eq.CERT_STRUCTURAL_TREND}, failures
    assert drifting["structural_trend"]["window"] == "the rest reading's late window"
    assert eq.terminal_at_ceiling(drifting, failures) == eq.RELAXING_AT_CEILING


def _run_with(verdicts: list[bool], cap: int) -> tuple[dict, list]:
    from graph_scale_dynamics.scaleflow import one_shot as O
    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    policy = dict(one_shot_policy(campaign), max_sweeps_multiplier=cap, mean_degree_cap=None,
                  work_budget=10 ** 15)
    asked = list(verdicts)

    def judged(_policy, _health):
        passed = asked.pop(0)
        return passed, [] if passed else [{"code": eq.CERT_ESS_LOW, "detail": "made to fail"}]

    original = eq.certificate_pass
    eq.certificate_pass = judged
    try:
        envelope = O.run_one_shot(law, 32, 1, one_shot=policy, initial_multiplier=1, record_points=20)
    finally:
        eq.certificate_pass = original
    return envelope["rung_terminal"], [row["multiplier"] for row in envelope["sampling_checkpoints"]]


def test_a_pass_at_the_cap_ends_the_run_and_a_failure_there_is_the_ceiling():
    terminal, multipliers = _run_with([False, False, True], cap=4)
    assert (terminal["reason"], terminal["passes_in_a_row"], multipliers) == ("completed", 1, [1, 2, 4]), \
        "no chunk of no moves is run at the cap to confirm it"
    terminal, multipliers = _run_with([False, False, False], cap=4)
    assert (terminal["reason"], terminal["passes_in_a_row"], multipliers) == ("ceiling", 0, [1, 2, 4])
    terminal, multipliers = _run_with([False, True, True], cap=4)
    assert (terminal["reason"], terminal["passes_in_a_row"], multipliers) == ("completed", 2, [1, 2, 4]), \
        "a pass below the cap goes on as before"
