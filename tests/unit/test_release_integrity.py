from __future__ import annotations

from tests.support.doubles import NullLog

from argparse import Namespace
from pathlib import Path

import pytest

import main
from graph_scale_dynamics.services.analyzer import main as analyzer
from graph_scale_dynamics.services.worker import main as worker
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.domain.version import runtime_environment, source_fingerprint


def test_runtime_fingerprint_ignores_non_runtime_tree(tmp_path):
    (tmp_path / "graph_scale_dynamics" / "services").mkdir(parents=True)
    (tmp_path / "graph_scale_dynamics" / "resources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "graph_scale_dynamics" / "services" / "service.py").write_text("VALUE = 1\n")
    (tmp_path / "graph_scale_dynamics" / "core.py").write_text("VALUE = 2\n")
    (tmp_path / "graph_scale_dynamics" / "resources" / "config.json").write_text('{"x": 1}\n')
    (tmp_path / "main.py").write_text("def main(): return 0\n")
    before = source_fingerprint(tmp_path)

    for directory in ("tests", "tools", "docs"):
        path = tmp_path / directory
        path.mkdir()
        (path / "noise.py").write_text("CHANGED = True\n")
    (tmp_path / "notes.txt").write_text("non-runtime note\n")
    assert source_fingerprint(tmp_path) == before

    (tmp_path / "graph_scale_dynamics" / "services" / "service.py").write_text("VALUE = 3\n")
    assert source_fingerprint(tmp_path) != before


def test_relative_var_path_belongs_to_project_root_not_calling_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "resolve_target", lambda target: "postgresql://rr:secret@127.0.0.1/rr")
    _, blobs, var = main.paths(Namespace(var="state"))
    assert var == (main.ROOT / "state").resolve()
    assert blobs == (main.ROOT / "state" / "blobs").resolve()


def test_packaged_config_fallback_works_without_root_copy():
    spec = main.read_config_file("campaign_engine_survey.json")
    candidate = main.read_config_file("candidate_sparse_anchor.json")
    assert spec["name"]
    assert candidate["dynamics"]["kind"]


class _WorkerRepo:
    def __init__(self):
        self.released = []
        self.closed = []

    def record_attempt(self, *args):
        pass

    def release_job(self, job_id, owner, generation):
        self.released.append((job_id, owner, generation))
        return True

    def close_attempt(self, *args, error_class=None):
        self.closed.append((*args, error_class))


class _AnalyzerRepo:
    def __init__(self):
        self.released = []
        self.analysis_attempts = []

    def record_analysis_attempt(self, *args, **kwargs):
        self.analysis_attempts.append(("open", args, kwargs))

    def close_analysis_attempt(self, *args, **kwargs):
        self.analysis_attempts.append(("close", args, kwargs))

    def release_analysis_claim(self, campaign, artifact, version, owner, token):
        self.released.append((campaign, artifact, version, owner, token))


def test_worker_spawn_failure_releases_lease_and_cleans_staging(monkeypatch, tmp_path):
    repo = _WorkerRepo()
    blobs = BlobStore(tmp_path / "blobs")
    job = {
        "job_id": "job-spawn-failure",
        "attempt_number": 1,
        "lease_generation": 7,
        "candidate_id": "candidate",
        "campaign_id": "campaign",
        "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
        "n": 8,
        "seed": 11,
    }
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn")))

    with pytest.raises(OSError, match="spawn"):
        worker.run_one(repo, blobs, NullLog(), "executor-1", job)

    assert repo.released == [("job-spawn-failure", "executor-1", 7)]
    assert repo.closed
    assert repo.closed[-1][-1] == "supervisor_interrupted", repo.closed
    assert list((blobs.root / "staging").iterdir()) == []


def test_analyzer_spawn_failure_releases_claim_and_cleans_staging(monkeypatch, tmp_path):
    repo = _AnalyzerRepo()
    blobs = BlobStore(tmp_path / "blobs")
    job = {
        "result_artifact": "a" * 64,
        "analysis_claim_token": "claim-token",
        "campaign_id": "campaign",
        "candidate_id": "candidate",
        "job_id": "job",
        "seed": 3,
        "n": 8,
        "lease_generation": 2,
    }
    monkeypatch.setattr(analyzer.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn")))

    with pytest.raises(OSError, match="spawn"):
        analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", job)

    assert len(repo.released) == 1
    assert repo.released[0][:2] == ("campaign", "a" * 64)
    assert list((blobs.root / "staging").iterdir()) == []


def test_obsolete_import_and_entrypoint_are_absent():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "tools" / "migrate_sqlite_to_postgres.py").exists()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "rrv2 =" not in pyproject
    assert not (root / "docs" / "POSTGRESQL_CUTOVER.md").exists()
    assert "fail_under" not in pyproject and "pytest-cov" not in pyproject and "tool.coverage" not in pyproject
    assert 'name = "pytest-cov"' not in (root / "uv.lock").read_text(encoding="utf-8")


def test_blobstore_explicit_delete_is_reference_agnostic_storage_primitive(tmp_path):
    blobs = BlobStore(tmp_path / "blobs-delete")
    digest, _ = blobs.put_json({"old": "campaign"})
    assert blobs.verify(digest)
    assert blobs.delete(digest) is True
    assert blobs.verify(digest) is False
    assert blobs.delete(digest) is False


def test_runtime_environment_records_numerical_backend_when_numpy_exposes_it():
    env = runtime_environment()
    assert env["python"]
    assert "numpy" in env["distributions"]
    assert isinstance(env["numerical_backend"], dict)
    if env["numerical_backend"]:
        assert "blas" in env["numerical_backend"]


def test_explicit_var_dir_cannot_escape_project_root(monkeypatch, tmp_path):
    external = tmp_path / "research-state"
    monkeypatch.setattr(main, "resolve_target", lambda target: "postgresql://rr:secret@127.0.0.1/rr")
    with pytest.raises(ValueError, match="state directory must remain beneath project root"):
        main.paths(Namespace(var=str(external)))
