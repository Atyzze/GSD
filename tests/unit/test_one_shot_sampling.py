from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.scaleflow.engine_door import run_simulation
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import (ONE_SHOT_CONTRACT, WORK_RECORD_CONTRACT, WORK_UNIT_CONTRACT,
                                                     analyze_one_shot_envelope, run_one_shot)
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.scheduling.limits import work_budget

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "graph_scale_dynamics" / "resources" / "configs"


@pytest.fixture(scope="module")
def law():
    return json.loads((CONFIGS / "candidate_sparse_anchor.json").read_text())


@pytest.fixture(scope="module")
def policy():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    return dict(one_shot_policy(campaign), mean_degree_cap=16.0)


def test_policy_is_copied_from_the_spec_limits(policy):
    assert policy["contract"] == ONE_SHOT_CONTRACT
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    assert one_shot_policy(campaign)["mean_degree_cap"] == 16.0
    assert policy["work_budget"] == work_budget(campaign, None) > 0
    assert policy["work_unit"]["contract"] == WORK_UNIT_CONTRACT
    assert policy["required_consecutive_passes"] == 2


def test_uncapped_run_is_bit_identical_to_an_unlimited_run(law):
    plain = run_simulation(law, 64, 1, record_points=40)
    limited = run_simulation(law, 64, 1, record_points=40, mean_degree_cap=1e9)
    assert CL.sorted_edges(plain) == CL.sorted_edges(limited)
    assert CL.record(plain, CL.FROM_EMPTY)["final"]["energy"] == CL.record(limited, CL.FROM_EMPTY)["final"]["energy"]
    assert plain["termination"]["reason"] == "completed"


def test_completed_exit_records_two_passing_checkpoints(law, policy):
    envelope = run_one_shot(law, 64, 1, one_shot=policy, initial_multiplier=4, record_points=120)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] == "completed"
    assert terminal["classification"] in {eq.EQUILIBRATED_ACTIVE, eq.EQUILIBRATED_LOW_ACTIVITY}
    passes = [row["passed"] for row in envelope["sampling_checkpoints"]]
    assert passes[-2:] == [True, True]
    assert envelope["sampling_checkpoints"][-1]["multiplier"] == terminal["final_multiplier"]
    chunks = [row["timing"] for row in envelope["sampling_checkpoints"]]
    assert all(c["chain_seconds"]["empty"] > 0 and c["chain_seconds"]["given"] > 0 for c in chunks), chunks
    for name in ("empty", "given"):
        assert terminal["timing"]["chain_seconds"][name] == sum(c["chain_seconds"][name] for c in chunks)


def test_mean_degree_cap_stops_the_chain_and_refuses_every_probe(law, policy):
    envelope = run_one_shot(law, 64, 1, one_shot=dict(policy, mean_degree_cap=4.0), initial_multiplier=4)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] == "mean_degree_cap"
    assert terminal["classification"] == "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
    assert envelope["termination"]["mean_degree_at_stop"] > 4.0
    assert [CL.block(envelope, name)["ended"]["reason"] for name in CL.twin_names(envelope)] == ["mean_degree_cap"] * 2, (
        "the rung ends at the cap once both twins have crossed it")
    assert terminal["mean_degree_cap_chain"] == envelope["termination"]["chain"]
    metrics, curves = analyze_one_shot_envelope(envelope)
    assert metrics["limit_refusal"] == "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
    for probe in ("d_s", "d_V", "d_B", "d_w"):
        assert metrics[probe]["valid"] is False
        assert metrics[probe]["refusal"] == "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
    assert metrics["health"]["rung_terminal"]["reason"] == "mean_degree_cap"
    assert curves == {}


def test_budget_exit_keeps_the_trajectory_so_far(law, policy):
    envelope = run_one_shot(law, 1024, 1, one_shot=dict(policy, work_budget=1), initial_multiplier=4)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] == "budget" and terminal["work"]["contract"] == WORK_RECORD_CONTRACT
    assert terminal["work"]["next_chunk_predicted"] > 0 and len(envelope["sampling_checkpoints"]) == 1
    assert terminal["classification"] != "REFUSED_COMPUTE_BUDGET", "read and decided as any other"
    assert len(CL.trajectory(envelope)) >= 1
    assert envelope["termination"]["reason"] == "completed", "the chunk it ran ran whole: no clock cut it"


def test_ceiling_exit_classifies_from_the_last_checkpoint(law, policy):
    tight = dict(policy, max_sweeps_multiplier=1)
    envelope = run_one_shot(law, 64, 1, one_shot=tight, initial_multiplier=1)
    assert envelope["rung_terminal"]["reason"] == "ceiling"
    assert envelope["rung_terminal"]["classification"] in {
        eq.RELAXING_AT_CEILING, eq.INSUFFICIENT_EFFECTIVE_SAMPLES, eq.METASTABLE_OR_NONMIXING,
        eq.FROZEN_OR_ABSORBING, eq.OPERATIONAL_UNRESOLVED,
    }


def test_contract_is_checked(law, policy):
    with pytest.raises(ValueError, match="unsupported one-shot contract"):
        run_one_shot(law, 64, 1, one_shot=dict(policy, contract="other"))


def _identity_fields(envelope, law):
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
    cid = fingerprint(law)
    envelope.update({
        "candidate_id": cid, "candidate_fingerprint": cid, "job_id": "j" * 64,
        "declared_sweeps": law["dynamics"]["sweeps"], "execution_spec_hash": "a" * 64,
        "sweeps_multiplier": envelope.get("sweeps_multiplier", 1),
        "provenance": {"build_number": BUILD_NUMBER, "lease_generation": 1,
                       "source_fingerprint": runtime_fingerprint(), "environment_fingerprint": "e" * 16},
        "resource_usage": {"peak_rss_bytes": 1, "user_cpu_seconds": 0.1, "system_cpu_seconds": 0.0},
    })
    return cid


@pytest.mark.parametrize("override", [{}, {"mean_degree_cap": 4.0}, {"work_budget": 1}])
def test_every_exit_publishes_through_the_streaming_envelope_contract(tmp_path, law, policy, override):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.artifact_store.streaming_envelope import publish_envelope_artifacts
    envelope = run_one_shot(law, 256, 1, one_shot=dict(policy, **override), initial_multiplier=4)
    cid = _identity_fields(envelope, law)
    assert envelope["moves"] == envelope["sweeps"] * 256
    assert envelope["executed_moves"] <= envelope["moves"]
    assert isinstance(CL.record(envelope, CL.GIVEN), dict)
    manifest = publish_envelope_artifacts(
        BlobStore(tmp_path), envelope, expected_n=256, expected_seed=1,
        expected_job_id="j" * 64, expected_candidate_id=cid, keep_checkpoint=True,
    )
    assert manifest


def test_the_analysis_records_d_s_on_its_whole_range(law, policy):
    envelope = run_one_shot(law, 256, 1, one_shot=policy, initial_multiplier=1)
    metrics, curves = analyze_one_shot_envelope(envelope)
    assert "return_probability" in curves
    whole = metrics["d_s_whole_range"]
    assert "whole_range_comparable" in whole and "error" not in whole, whole
    if whole["whole_range_comparable"]:
        assert isinstance(whole["whole_range_delta_aicc"], float) and whole["whole_range_points"] >= 8
