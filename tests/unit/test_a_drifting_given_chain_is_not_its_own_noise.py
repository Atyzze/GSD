from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow import one_shot as OS
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
from tests.support import chains as SC

ROOT = Path(__file__).resolve().parents[2]
N = 10_000
ROWS = 240
STRIDE = 20
NOISE = 0.002

FIXTURE = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
POLICY = one_shot_policy(FIXTURE)


def _chain(connected, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(ROWS):
        row = {"move": i * 100, "energy": -2.0 * N + float(rng.normal(0.0, 5.0)),
               "mean_degree": 4.0 + float(rng.normal(0.0, 0.01)),
               "accepted_add": 30 * i, "accepted_delete": 30 * i, "accepted_swap": 10 * i}
        if i % STRIDE == 0:
            fraction = connected(i / (ROWS - 1)) + float(rng.normal(0.0, NOISE))
            row.update(largest_component=round(fraction * N), components=50 + i % 2, triangles=0)
        rows.append(row)
    return rows


def _structure(rows: list[dict]) -> dict:
    last = [row for row in rows if "largest_component" in row][-1]
    return {"connected_fraction": last["largest_component"] / N, "two_core_fraction": 0.5,
            "largest_component_cycle_rank_density": 0.1, "component_count": last["components"]}


def _envelope(from_empty, given) -> dict:
    first, second = _chain(from_empty, 11), _chain(given, 12)
    late = second[-ROWS // 3:]
    return SC.pair(
        N, first, second,
        empty={"final": {"energy": first[-1]["energy"], "mean_degree": 4.0}, "final_structure": _structure(first),
               "acceptance": {"accepted": {"add": 1, "delete": 1, "swap": 1}}},
        given_record={"init": SC.RANDOM_START, "final_structure": _structure(second),
                      "late": {"energy_per_node": {"values": [row["energy"] / N for row in late]},
                               "mean_degree": {"values": [row["mean_degree"] for row in late]}}})


DRIFTING_APART = _envelope(lambda t: 0.40 + 0.30 * t, lambda t: 0.35 + 0.20 * t)
STATIONARY = _envelope(lambda t: 0.60, lambda t: 0.60)
STATIONARY_APART = _envelope(lambda t: 0.60, lambda t: 0.45)


def _verdict(envelope, policy):
    health = eq.inline_health(envelope, policy)
    passed, failures = eq.certificate_pass(policy, health)
    return passed, {f["code"] for f in failures}, health


def test_given_chains_drifting_apart_fail():
    passed, codes, health = _verdict(DRIFTING_APART, POLICY)
    assert not passed
    assert {eq.CERT_STRUCTURAL_DISAGREED, eq.CERT_STRUCTURAL_TREND} <= codes, codes
    gap = health["equilibration"]["structural_split"]["connected_fraction"]
    assert gap < 3 * health["equilibration"]["structural_noise"]["connected_fraction"]
    detrended = health["equilibration"]["structural_noise_detrended"]["connected_fraction"]
    assert detrended < 3 * NOISE * 2 ** 0.5
    assert eq.structural_thresholds(POLICY, health["equilibration"])["connected_fraction"]["basis"] == "floor"
    trend = health["structural_trend"]
    for chain in ("empty", "given"):
        row = trend["chains"][chain]["connected_fraction"]
        assert row["drifting"] and row["drift"] > 0.025 and row["z"] > trend["z_max"], (chain, row)
        assert trend["chains"][chain]["component_count_per_node"]["drifting"] is False


def test_a_stationary_pair_with_the_same_noise_passes():
    passed, codes, health = _verdict(STATIONARY, POLICY)
    assert passed, codes
    trend = health["structural_trend"]
    assert not any(row["drifting"] for chain in trend["chains"].values() for row in chain.values()), trend


def test_a_stationary_pair_with_a_real_gap_fails():
    passed, codes, _ = _verdict(STATIONARY_APART, POLICY)
    assert not passed and eq.CERT_STRUCTURAL_DISAGREED in codes, codes
    assert eq.CERT_STRUCTURAL_TREND not in codes


def test_a_policy_naming_no_contract_reads_the_same():
    assert eq.inline_health(DRIFTING_APART, POLICY) == eq.inline_health(
        DRIFTING_APART, {k: v for k, v in POLICY.items() if k != "contract"})


def test_a_health_block_without_its_trend_is_refused():
    health = eq.inline_health(STATIONARY, POLICY)
    del health["structural_trend"]
    passed, failures = eq.certificate_pass(POLICY, health)
    assert not passed and [f["code"] for f in failures] == [eq.CERT_STRUCTURAL_TREND_MISSING]


def test_a_chain_too_short_to_fit_is_read_as_unknown_not_refused():
    short = copy.deepcopy(STATIONARY)
    CL.block(short, CL.GIVEN)["trajectory"] = CL.block(short, CL.GIVEN)["trajectory"][:60]
    trend = eq.structural_trend(short, POLICY)
    assert trend["chains"]["given"]["connected_fraction"] == {
        "points": None, "drift": None, "drift_se": None, "z": None, "drifting": None}
    assert trend["chains"]["empty"]["connected_fraction"]["drifting"] is False


def test_a_structural_trend_at_the_ceiling_is_relaxing():
    failures = [{"code": eq.CERT_STRUCTURAL_TREND, "detail": "chain from empty's connected_fraction still drifting"}]
    assert eq.terminal_at_ceiling({"numerics_ok": True}, failures) == eq.RELAXING_AT_CEILING


def _run(policy, envelope):
    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())

    def simulate(*_args, **_kwargs):
        return dict(copy.deepcopy(envelope), termination={"reason": "completed"}, cumulative_sweeps=30)

    return OS.run_one_shot(law, N, 1, one_shot=dict(policy, max_sweeps_multiplier=1, mean_degree_cap=None),
                           simulate=simulate)


def test_each_chunk_records_what_the_trend_test_read():
    run = _run(POLICY, DRIFTING_APART)
    terminal, row = run["rung_terminal"], run["sampling_checkpoints"][-1]
    assert terminal["contract"] == OS.ONE_SHOT_CONTRACT and terminal["reason"] == "ceiling"
    assert terminal["classification"] == eq.METASTABLE_OR_NONMIXING, terminal
    certificate = row["certificate"]
    assert certificate["structural_trend"]["contract"] == eq.STRUCTURAL_TREND_CONTRACT
    assert certificate["structural_trend"]["chains"]["empty"]["connected_fraction"]["drifting"] is True
    assert certificate["structural_noise_detrended"]["connected_fraction"] < 0.01
    assert certificate["structural_thresholds"]["connected_fraction"]["basis"] == "floor"
    json.dumps(row, allow_nan=False)


def test_a_job_queued_under_the_old_contract_is_certified_under_this_one():
    old = _run(dict(POLICY, contract=eq.SAMPLING_1), DRIFTING_APART)
    assert old["rung_terminal"]["contract"] == OS.ONE_SHOT_CONTRACT == eq.SAMPLING_CURRENT
    assert old["sampling_checkpoints"][-1]["passed"] is False


def test_a_job_naming_no_known_contract_is_refused():
    with pytest.raises(ValueError, match="unsupported one-shot contract"):
        _run(dict(POLICY, contract="one-shot-sampling-9"), STATIONARY)


def test_every_campaign_samples_under_the_one_contract():
    assert one_shot_policy(FIXTURE)["contract"] == OS.ONE_SHOT_CONTRACT
    assert one_shot_policy({"limits": {}})["contract"] == OS.ONE_SHOT_CONTRACT
    assert one_shot_policy(freeze_campaign_spec(FIXTURE))["contract"] == OS.ONE_SHOT_CONTRACT
