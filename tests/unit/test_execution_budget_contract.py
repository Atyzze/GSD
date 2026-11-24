from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.services.worker.child import _sweeps_multiplier, main as child_main
from graph_scale_dynamics.services.worker.main import simulation_child_payload
from graph_scale_dynamics.artifact_store.envelope import validate_raw_envelope
from graph_scale_dynamics.domain.version import ROOT, environment_fingerprint, source_fingerprint
from graph_scale_dynamics.dsl.dsl import fingerprint
from graph_scale_dynamics.engine.engine import ENGINE_VERSION


def candidate_spec(*, sweeps: int = 1) -> dict:
    return {
        "dsl_version": 1,
        "init": "empty",
        "terms": [
            {"op": "edge_count", "params": {},
             "coeff": {"c0": 0.1, "scale": "one"}},
        ],
        "dynamics": {
            "kind": "equilibrium",
            "beta": 1.0,
            "move_mix": {"add": 0.5, "delete": 0.5},
            "sweeps": sweeps,
        },
    }


def test_worker_supervisor_forwards_database_engine_stamp_to_child():
    spec = candidate_spec(sweeps=2)
    candidate_id = fingerprint(spec)
    payload = simulation_child_payload(
        {
            "job_id": "job-forwarding-test",
            "candidate_id": candidate_id,
            "spec": {
                "candidate_spec": spec,
                "engine_version": ENGINE_VERSION,
                "execution": {"sweeps_multiplier": 2},
                "record_points": 12,
            },
            "n": 8,
            "seed": 13,
        },
        "executor-test",
        4,
    )

    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["candidate_id"] == candidate_id
    assert payload["candidate_spec"] == spec
    assert payload["execution"] == {"sweeps_multiplier": 2}
    assert payload["execution_provenance"]["lease_generation"] == 4
    assert payload["execution_provenance"]["worker_owner"] == "executor-test"


def _one_shot_policy():
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scaleflow.one_shot import ONE_SHOT_CONTRACT
    from graph_scale_dynamics.scheduling.limits import work_unit
    return {"contract": ONE_SHOT_CONTRACT, "max_sweeps_multiplier": 2, "required_consecutive_passes": 1,
            "work_budget": 10 ** 15, "work_unit": work_unit(shipped_spec()), "mean_degree_cap": 16.0}


def test_worker_child_runs_a_one_shot_job_without_touching_the_candidate(tmp_path):
    spec = candidate_spec(sweeps=1)
    candidate_id = fingerprint(spec)
    job_file = tmp_path / "job.json"
    out_file = tmp_path / "result.json"
    job_file.write_text(json.dumps({
        "job_id": "job-test",
        "candidate_id": candidate_id,
        "candidate_spec": spec,
        "engine_version": ENGINE_VERSION,
        "execution": {"sweeps_multiplier": 1, "one_shot": _one_shot_policy(), "engine": "python"},
        "n": 4,
        "seed": 7,
        "record_points": 8,
        "execution_provenance": {
            "build_number": 26,
            "source_fingerprint": source_fingerprint(ROOT),
            "environment_fingerprint": environment_fingerprint(),
            "lease_generation": 1,
            "worker_owner": "test-worker",
        },
    }))

    assert child_main([str(job_file), str(out_file)]) == 0
    envelope = json.loads(out_file.read_text())

    assert fingerprint(spec) == candidate_id
    assert spec["dynamics"]["sweeps"] == 1
    assert envelope["candidate_id"] == candidate_id
    assert envelope["candidate_fingerprint"] == candidate_id
    assert envelope["declared_sweeps"] == 1
    assert envelope["rung_terminal"]["reason"] in {"completed", "ceiling", "budget", "mean_degree_cap"}
    assert len(envelope["execution_spec_hash"]) == 64
    assert envelope["resource_usage"]["peak_rss_bytes"] > 0
    assert envelope["provenance"]["source_execution_verified"] is True
    assert envelope["provenance"]["source_verification_contract"] == "child-pre-post-1"
    assert envelope["provenance"]["source_fingerprint"] == source_fingerprint(ROOT)
    assert CL.record(envelope, CL.FROM_EMPTY)["final"]["peak_edge_count"] >= CL.record(envelope, CL.FROM_EMPTY)["final"]["edge_count"]
    validate_raw_envelope(
        envelope,
        expected_n=4,
        expected_seed=7,
        expected_job_id="job-test",
        expected_candidate_id=candidate_id,
    )


def test_worker_child_refuses_a_job_that_is_not_one_shot(tmp_path):
    spec = candidate_spec(sweeps=1)
    job_file = tmp_path / "job-plain.json"
    job_file.write_text(json.dumps({
        "job_id": "job-plain", "candidate_id": fingerprint(spec), "candidate_spec": spec,
        "engine_version": ENGINE_VERSION, "execution": {"sweeps_multiplier": 3}, "n": 4, "seed": 7,
        "execution_provenance": {"source_fingerprint": source_fingerprint(ROOT),
                                 "environment_fingerprint": environment_fingerprint()},
    }))
    with pytest.raises(ValueError, match="one-shot"):
        child_main([str(job_file), str(tmp_path / "out.json")])


def test_worker_child_rejects_stale_supervisor_source_fingerprint(tmp_path):
    spec = candidate_spec(sweeps=1)
    job_file = tmp_path / "job-stale.json"
    out_file = tmp_path / "result-stale.json"
    job_file.write_text(json.dumps({
        "job_id": "job-stale",
        "candidate_id": fingerprint(spec),
        "candidate_spec": spec,
        "engine_version": ENGINE_VERSION,
        "execution": {"sweeps_multiplier": 1},
        "n": 4,
        "seed": 7,
        "execution_provenance": {
            "build_number": 117,
            "source_fingerprint": "0" * 64,
            "environment_fingerprint": environment_fingerprint(),
            "lease_generation": 1,
            "worker_owner": "stale-supervisor",
        },
    }))
    with pytest.raises(RuntimeError, match="source fingerprint mismatch"):
        child_main([str(job_file), str(out_file)])
    assert not out_file.exists()


def test_worker_rejects_job_from_another_engine_version(tmp_path):
    spec = candidate_spec(sweeps=1)
    job_file = tmp_path / "job.json"
    out_file = tmp_path / "result.json"
    job_file.write_text(json.dumps({
        "job_id": "old-job",
        "candidate_id": fingerprint(spec),
        "candidate_spec": spec,
        "engine_version": "engine-2.5.0",
        "execution": {"sweeps_multiplier": 1},
        "n": 4,
        "seed": 7,
    }))
    with pytest.raises(ValueError, match="is not one this worker runs"):
        child_main([str(job_file), str(out_file)])


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "2", []])
def test_worker_rejects_invalid_execution_multiplier(value):
    with pytest.raises(ValueError, match="positive integer"):
        _sweeps_multiplier({"execution": {"sweeps_multiplier": value}})
