import json
import math
from importlib.resources import files as resource_files
from pathlib import Path

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.envelope import EnvelopeValidationError, validate_raw_envelope
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scheduling.campaign import validate_campaign

ROOT = Path(__file__).resolve().parents[2]


def candidate(k):
    return {
        "dsl_version": 1,
        "init": "empty",
        "terms": [{"op": "degree_anchor", "params": {"k": k},
                   "coeff": {"c0": 0.3, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 2},
    }


def test_degree_anchor_k_is_integer_and_canonical():
    assert any("must be an integer" in problem for problem in dsl.validate(candidate(4.5)))
    assert any("must be an integer" in problem for problem in dsl.validate(candidate(4.0)))
    assert dsl.validate(candidate(4)) == []
    assert dsl.normalize(candidate(4))["terms"][0]["params"]["k"] == 4
    assert dsl.execution_identity_problems(candidate(4.5), "x" * 64)


def test_empty_campaign_is_rejected_at_admission():
    problems = validate_campaign({})
    assert "ladder must be a non-empty list" in problems
    assert "budgets must be an object" in problems
    assert any("analysis_version" in problem for problem in problems)


def valid_envelope():
    return {
        "schema": "raw-simulation-envelope-v2",
        "engine_version": "engine-test",
        "job_id": "job",
        "candidate_id": "c" * 64,
        "candidate_fingerprint": "c" * 64,
        "n": 4,
        "seed": 7,
        "sweeps": 2,
        "moves": 8,
        "chains": [{"start": "empty", "final": {"edge_count": 2, "mean_degree": 1.0}, "acceptance": {}},
                   {"start": "given", "skipped": True, "acceptance": {}}],
        "sampling_checkpoint": {"chains": [{"start": "empty", "edge_list": [[0, 1], [1, 2]], "trajectory": [],
                                            "snapshots": [{"move": 4, "edges": [[0, 1]]}]}]},
        "provenance": {
            "build_number": 26,
            "source_fingerprint": "f" * 64,
            "lease_generation": 1,
        },
    }


def test_envelope_identity_and_graph_invariants_are_validated():
    envelope = valid_envelope()
    assert validate_raw_envelope(envelope, expected_n=4, expected_seed=7,
                                 expected_job_id="job", expected_candidate_id="c" * 64) is envelope
    bad = json.loads(json.dumps(envelope))
    bad["sampling_checkpoint"]["chains"][0]["edge_list"].append([1, 2])
    with pytest.raises(EnvelopeValidationError, match="duplicate edge"):
        validate_raw_envelope(bad)
    bad = json.loads(json.dumps(envelope))
    bad["candidate_fingerprint"] = "d" * 64
    with pytest.raises(EnvelopeValidationError, match="fingerprint"):
        validate_raw_envelope(bad, expected_candidate_id="c" * 64)
    bad = json.loads(json.dumps(envelope))
    bad["chains"][0]["final"]["mean_degree"] = math.nan
    with pytest.raises(EnvelopeValidationError):
        validate_raw_envelope(bad)


def test_blob_reads_verify_content_digest(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    digest, _ = blobs.put_json({"ok": True})
    assert blobs.get_json(digest) == {"ok": True}
    blobs._path(digest).write_bytes(b"tampered")
    with pytest.raises(OSError, match="digest verification failed"):
        blobs.get_json(digest)
    assert blobs.verify(digest) is False


def test_shipped_campaign_specs_pass_admission():
    name = "campaign_engine_survey.json"
    spec = json.loads(resource_files("graph_scale_dynamics.resources").joinpath("configs", name).read_text())
    assert validate_campaign(spec) == [], name


def test_envelope_requires_explicit_candidate_identity_and_provenance():
    envelope = valid_envelope()
    envelope.pop("candidate_id")
    envelope.pop("candidate_fingerprint")
    with pytest.raises(EnvelopeValidationError, match="candidate_id"):
        validate_raw_envelope(
            envelope, expected_n=4, expected_seed=7, expected_job_id="job",
            expected_candidate_id="c" * 64,
        )

    envelope = valid_envelope()
    envelope.pop("provenance")
    with pytest.raises(EnvelopeValidationError, match="provenance"):
        validate_raw_envelope(envelope)


def test_prescreen_admission_declaration_must_be_boolean():
    spec_path = ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json"
    spec = json.loads(spec_path.read_text())
    assert validate_campaign(spec) == []
    spec["prescreen"]["admission_enabled"] = "false"
    assert "prescreen.admission_enabled must be boolean" in validate_campaign(spec)


def test_prescreen_parallel_candidates_must_be_positive_integer():
    spec_path = ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json"
    spec = json.loads(spec_path.read_text())
    assert validate_campaign(spec) == []
    spec["prescreen"]["parallel_candidates"] = 0
    assert "prescreen.parallel_candidates must be a positive integer" in validate_campaign(spec)
    spec["prescreen"]["parallel_candidates"] = True
    assert "prescreen.parallel_candidates must be a positive integer" in validate_campaign(spec)


def test_the_shipped_sparse_survey_validates():
    spec_path = ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json"
    spec = json.loads(spec_path.read_text())
    assert validate_campaign(spec) == []

    spec["prescreen"]["early_pilot_short_circuit"] = "yes"
    assert "prescreen.early_pilot_short_circuit must be boolean" in validate_campaign(spec)

    spec = json.loads(spec_path.read_text())
    spec["runtime_budget"]["enforcement_contract"] = "invented"
    assert "runtime_budget.enforcement_contract must be actual-spend-1" in validate_campaign(spec)
