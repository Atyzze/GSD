from __future__ import annotations

import hashlib
import http.client
import json
import random
import threading
from contextlib import nullcontext
from pathlib import Path

import pytest

from tests.support.doubles import RollbackCapable

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.domain.randomness import derive_seed, stream_id
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.operations.audit import audit_state, report_exit_code
from graph_scale_dynamics.operations.liveness import liveness_findings
from graph_scale_dynamics.engine.engine import GraphState
from graph_scale_dynamics.scaleflow.engine_door import run_simulation
from graph_scale_dynamics.operations import backup as backup_module
from graph_scale_dynamics.operations.backup import MANIFEST_VERSION, restore_backup, verify_backup


class Cursor:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row = row
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


def bare_repo(conn) -> Repo:
    repo = object.__new__(Repo)
    repo.conn = conn
    repo.backend = "postgresql"
    repo._closed = False
    return repo


def candidate_spec(sweeps: int = 1) -> dict:
    return {
        "dsl_version": 1,
        "init": "empty",
        "terms": [
            {"op": "edge_count", "params": {}, "coeff": {"c0": 0.2, "scale": "one"}},
            {"op": "degree_anchor", "params": {"k": 3},
             "coeff": {"c0": 0.3, "scale": "one"}},
        ],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": sweeps},
    }


def test_full_width_named_random_streams_are_stable_and_separate():
    first = derive_seed("simulation", "candidate", 1024, 7, "declared")
    assert first == derive_seed("simulation", "candidate", 1024, 7, "declared")
    assert first.bit_length() > 200
    assert first != derive_seed("simulation", "candidate", 1024, 7, "control")
    assert len(stream_id("simulation", "candidate", 1024, 7, "declared")) == 64


def test_complement_sampler_is_bounded_at_near_complete_density():
    state = GraphState(20)
    missing = (3, 17)
    for u in range(20):
        for v in range(u + 1, 20):
            if (u, v) == missing:
                continue
            deltas = state.op_deltas(u, v, True)
            state.apply(u, v, True, deltas)
    assert state.non_degree[3] == state.non_degree[17] == 1
    assert sum(state.non_degree) == 2
    for seed in range(20):
        assert state.sample_non_edge(random.Random(seed)) == missing


def test_simulation_random_stream_provenance_replays_exactly():
    left = run_simulation(candidate_spec(), 12, 123, record_points=10)
    right = run_simulation(candidate_spec(), 12, 123, record_points=10)
    for key in ("chains", "random_streams"):
        assert [{**row, "seconds": 0} for row in left[key]] == [{**row, "seconds": 0} for row in right[key]] \
            if key == "chains" else left[key] == right[key]
    assert left["sampling_checkpoint"]["chains"] == right["sampling_checkpoint"]["chains"]
    assert len({row["stream"] for row in left["chains"]} | {left["random_streams"]["given_initialization"]}) == 3


def test_blobstore_enforces_decoded_limit_and_lists_objects(tmp_path: Path):
    store = BlobStore(tmp_path)
    digest, size = store.put_json({"payload": "x" * 200_000})
    assert list(store.iter_digests()) == [digest]
    assert store.get_json(digest, max_compressed_bytes=size,
                          max_decoded_bytes=300_000)["payload"].startswith("x")
    with pytest.raises(ValueError, match="decoded size limit"):
        store.get_json(digest, max_decoded_bytes=1_000)


class AuditConnection(RollbackCapable):
    def __init__(self, artifact: dict):
        self.artifact = artifact

    def execute(self, sql, args=()):
        if sql.startswith("SELECT a.artifact_hash,a.size_bytes,a.media_type"):
            return Cursor(rows=[self.artifact | {"body_state": "present", "storage_class": None,
                                                "compact_artifact": None, "checkpoint_artifact": None}])
        return Cursor(rows=[])


def test_integrity_audit_detects_blob_corruption(tmp_path: Path):
    store = BlobStore(tmp_path)
    digest, size = store.put_json({"ok": True})
    conn = AuditConnection({"artifact_hash": digest, "size_bytes": size,
                            "media_type": "application/json"})
    healthy = audit_state(conn, tmp_path, verify_hashes=True)
    assert healthy["ok"]
    store._path(digest).write_bytes(b"corrupt")
    broken = audit_state(conn, tmp_path, verify_hashes=True)
    assert not broken["ok"]
    assert {item["code"] for item in broken["findings"]} >= {
        "artifact.size_mismatch", "artifact.digest_mismatch"
    }


class _LivenessConnection(RollbackCapable):
    def __init__(self):
        self.campaigns = {"c": "active"}
        self.control = {"paused": "0"}
        self.candidates = {("c", "x"): "DISCOVERY_ACTIVE"}
        self.jobs = [{"campaign_id": "c", "candidate_id": "x", "job_id": "j",
                      "kind": "simulate", "status": "queued",
                      "created_utc": "2020-01-01T00:00:00Z"}]
        self.analysis = []
        self.heartbeats = []
        self.scheduler = {"updated_utc": "2020-01-01T00:00:00Z", "total_slots": 1,
                          "simulation_slots": 1, "analysis_slots": 0,
                          "queued_simulations": 1, "leased_simulations": 0}
        self.events = []
        self.cursors = {}

    def close(self):
        pass

    def _active_candidate(self, campaign_id, candidate_id, terminal):
        return (self.campaigns.get(campaign_id) == "active"
                and self.candidates.get((campaign_id, candidate_id)) not in terminal)

    def execute(self, sql, args=()):
        args = tuple(args)
        if sql.startswith("SELECT COUNT(*) c FROM campaigns"):
            return Cursor(row={"c": sum(status == "active" for status in self.campaigns.values())})
        if sql.startswith("SELECT value FROM control"):
            return Cursor(row={"value": self.control.get("paused", "0")})
        if sql.startswith("SELECT COUNT(*) c FROM jobs j"):
            terminal = set(args)
            count = sum(row["kind"] == "simulate" and row["status"] == "queued"
                        and self._active_candidate(row["campaign_id"], row["candidate_id"], terminal)
                        for row in self.jobs)
            return Cursor(row={"c": count})
        if sql.startswith("SELECT COUNT(*) c FROM analysis_queue q"):
            now, *terminal_args = args
            terminal = set(terminal_args)
            count = sum(row["status"] == "queued"
                        and (row.get("next_attempt_utc") is None or row["next_attempt_utc"] <= now)
                        and self._active_candidate(row["campaign_id"], row["candidate_id"], terminal)
                        for row in self.analysis)
            return Cursor(row={"c": count})
        if sql.startswith("SELECT COUNT(*) c FROM service_heartbeats"):
            pattern, cutoff = args
            prefix = pattern.removesuffix("%")
            count = sum(row["service"].startswith(prefix) and row["sampled_utc"] >= cutoff
                        for row in self.heartbeats)
            return Cursor(row={"c": count})
        if sql.startswith("SELECT updated_utc,total_slots"):
            return Cursor(row=dict(self.scheduler) if self.scheduler else None)
        if sql.startswith("SELECT MIN(j.created_utc) oldest FROM jobs"):
            terminal = set(args)
            dates = [row["created_utc"] for row in self.jobs
                     if row["kind"] == "simulate" and row["status"] == "queued"
                     and self._active_candidate(row["campaign_id"], row["candidate_id"], terminal)]
            return Cursor(row={"oldest": min(dates) if dates else None})
        if sql.startswith("SELECT (SELECT COUNT(*) FROM analysis_queue WHERE status='leased')"):
            return Cursor(row={"c": sum(row["status"] == "leased" for row in self.analysis)})
        if sql.startswith("SELECT MIN(COALESCE(q.next_attempt_utc,q.created_utc))"):
            terminal = set(args[1:])
            dates = [row.get("next_attempt_utc") or row["created_utc"] for row in self.analysis
                     if row["status"] == "queued"
                     and self._active_candidate(row["campaign_id"], row["candidate_id"], terminal)]
            return Cursor(row={"oldest": min(dates) if dates else None})
        if sql.startswith("SELECT cc.state,COUNT(*) c FROM campaign_candidates cc"):
            terminal = set(args[:-1])
            grouped = {}
            for (campaign_id, candidate_id), state in self.candidates.items():
                if self.campaigns.get(campaign_id) != "active" or state in terminal or state in {"PROPOSED", "VALIDATING"}:
                    continue
                live_job = any(row["campaign_id"] == campaign_id and row["candidate_id"] == candidate_id
                               and row["status"] in {"queued", "leased"} for row in self.jobs)
                live_analysis = any(row["campaign_id"] == campaign_id and row["candidate_id"] == candidate_id
                                    and row["status"] in {"queued", "leased"} for row in self.analysis)
                if not live_job and not live_analysis:
                    grouped[state] = grouped.get(state, 0) + 1
            return Cursor(rows=[{"state": state, "c": count} for state, count in grouped.items()])
        if sql.startswith("SELECT COUNT(*) c FROM campaign_candidates cc JOIN campaigns cm") and "cc.state='PROPOSED'" in sql:
            count = sum(self.campaigns.get(campaign_id) == "active" and state == "PROPOSED"
                        for (campaign_id, _), state in self.candidates.items())
            return Cursor(row={"c": count})
        if sql.startswith("SELECT COUNT(*) c FROM campaign_candidates cc"):
            terminal = set(args)
            count = 0
            for (campaign_id, candidate_id), state in self.candidates.items():
                if state not in terminal:
                    continue
                live_job = any(row["campaign_id"] == campaign_id
                               and row["candidate_id"] == candidate_id
                               and row["status"] in {"queued", "leased"} for row in self.jobs)
                live_analysis = any(row["campaign_id"] == campaign_id
                                    and row["candidate_id"] == candidate_id
                                    and row["status"] in {"queued", "leased"}
                                    for row in self.analysis)
                count += int(live_job or live_analysis)
            return Cursor(row={"c": count})
        raise AssertionError(f"unexpected liveness SQL: {sql}")


def _liveness_database() -> _LivenessConnection:
    return _LivenessConnection()


class _PsycopgPercentGuard:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        parameters = tuple(args)
        if parameters and "%" in sql:
            raise AssertionError(
                "parameterized SQL must pass literal percent patterns as values"
            )
        return self.raw.execute(sql, parameters)

def test_liveness_parameterizes_executor_like_pattern():
    raw = _liveness_database()
    conn = _PsycopgPercentGuard(raw)
    try:
        liveness_findings(conn, queue_age_seconds=1)
    finally:
        raw.close()


def test_liveness_watchdog_finds_missing_executors_and_stale_scheduler():
    conn = _liveness_database()
    try:
        findings = liveness_findings(conn, queue_age_seconds=1)
    finally:
        conn.close()
    keys = {item["key"] for item in findings}
    assert "liveness:no-recent-executors" in keys
    assert "liveness:stale-scheduler" in keys
    assert "liveness:old-simulation-queue" not in keys


def test_old_queue_is_called_starved_only_with_fresh_unused_physical_capacity():
    conn = _liveness_database()
    try:
        from graph_scale_dynamics.domain.model import utc_now
        now = utc_now()
        conn.heartbeats.append({"service": "executor-1", "sampled_utc": now})
        conn.scheduler["updated_utc"] = now
        findings = liveness_findings(conn, queue_age_seconds=1)
    finally:
        conn.close()
    item = next(item for item in findings if item["key"] == "liveness:old-simulation-queue")
    assert item["detail"]["unused_compute_slots"] == 1
    assert item["detail"]["oldest_queue_item_age_seconds"] > 1
    assert "age_seconds" not in item["detail"]


def test_cross_role_analysis_occupancy_is_not_simulation_starvation():
    conn = _liveness_database()
    try:
        from graph_scale_dynamics.domain.model import utc_now
        now = utc_now()
        conn.heartbeats.append({"service": "executor-1", "sampled_utc": now})
        conn.scheduler["updated_utc"] = now
        conn.analysis.append({"campaign_id": "c", "candidate_id": "x",
                              "status": "leased", "created_utc": now})
        findings = liveness_findings(conn, queue_age_seconds=1)
    finally:
        conn.close()
    assert "liveness:old-simulation-queue" not in {item["key"] for item in findings}


def test_old_queue_is_not_called_starved_when_scheduler_capacity_is_full():
    conn = _liveness_database()
    try:
        from graph_scale_dynamics.domain.model import utc_now
        now = utc_now()
        conn.heartbeats.append({"service": "executor-1", "sampled_utc": now})
        conn.scheduler["updated_utc"] = now
        conn.scheduler["leased_simulations"] = conn.scheduler["simulation_slots"]
        findings = liveness_findings(conn, queue_age_seconds=1)
    finally:
        conn.close()
    assert "liveness:old-simulation-queue" not in {item["key"] for item in findings}


def test_log_rotation_is_bounded(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GSD_LOG_MAX_BYTES", "65536")
    monkeypatch.setenv("GSD_LOG_RETAINED", "2")
    log = Log(tmp_path, "service")
    log.write("large", payload="x" * 40_000)
    log.write("large", payload="y" * 40_000)
    assert log.path.exists()
    assert log.path.with_suffix(".jsonl.1").exists()
    current = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert current["utc"].endswith("Z")
    assert current["run_id"]


def test_backup_manifest_verification_catches_tampering(tmp_path: Path):
    backup = tmp_path / "backup"
    store = BlobStore(backup / "blob_store")
    digest, size = store.put_json({"evidence": 1})
    dump = backup / "database.dump"
    dump.write_bytes(b"postgres-dump")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "build": 26,
        "created_utc": "2026-01-01T00:00:00Z",
        "quiescence": {"paused": True, "leased_jobs": 0, "leased_analysis": 0},
        "database": {"file": "database.dump", "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                     "size_bytes": dump.stat().st_size},
        "blobs": {"root": "blob_store", "count": 1, "size_bytes": size,
                  "objects": [{"digest": digest, "size_bytes": size}]},
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_backup(backup)["verified_blobs"]
    dump.write_bytes(b"tampered")
    with pytest.raises(OSError, match="dump"):
        verify_backup(backup)


def test_an_admin_route_requires_the_token_from_loopback_and_sets_hardening_headers(monkeypatch, tmp_path: Path):
    class FakeRepo:
        def __init__(self, target):
            pass
        def close(self):
            pass

    monkeypatch.setattr(api_main, "Repo", FakeRepo)
    token = "secret-token"
    handler = api_main.build_handler("unused", str(tmp_path), token, 0)
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    headers = {"Content-Type": "application/json"}
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", "/api/campaigns/manage", body=b"{}", headers=headers)
        response = connection.getresponse()
        assert response.status == 403
        assert "default-src" in response.getheader("Content-Security-Policy")
        assert "admin token" in json.loads(response.read())["error"]
        connection.close()

        handler._client_is_loopback = lambda self: False
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", "/api/campaigns/manage", body=b"{}",
                           headers=headers | {"X-GSD-Admin-Token": token})
        response = connection.getresponse()
        assert response.status == 403
        assert "local admin" in json.loads(response.read())["error"]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_failed_change_from_the_campaigns_page_answers_with_what_failed(monkeypatch, tmp_path: Path):
    class FakeRepo:
        def __init__(self, target):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def close(self):
            pass

    def failing(repo, body):
        raise RuntimeError("the database went away mid-change")

    monkeypatch.setattr(api_main, "Repo", FakeRepo)
    monkeypatch.setattr(api_main.campaign_manager, "handle", failing)
    token = "secret-token"
    handler = api_main.build_handler("unused", str(tmp_path), token, 0)
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", "/api/campaigns/manage", body=b'{"action": "workers"}',
                           headers={"Content-Type": "application/json", "X-GSD-Admin-Token": token})
        response = connection.getresponse()
        answer = json.loads(response.read())
        assert response.status == 500 and "the database went away" in answer["error"], answer
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_runtime_resources_have_one_canonical_packaged_copy():
    root = Path(__file__).resolve().parents[2]
    packaged = root / "graph_scale_dynamics" / "resources"
    assert {path.name for path in (packaged / "schema").glob("*.sql")} == {"schema.sql"}
    assert {p.name for p in (packaged / "configs").glob("*.json")} == {
        "campaign_engine_survey.json",
        "candidate_sparse_anchor.json",
    }
    assert (packaged / "ui" / "index.html").is_file()
    for duplicate in ("schema", "migrations_postgres", "configs", "ui"):
        assert not (root / duplicate).exists()


def test_audit_exit_code_uses_counts_when_details_are_truncated():
    report = {
        "counts": {"error": 1, "warning": 0, "info": 0},
        "findings": [],
        "findings_truncated": True,
    }
    assert report_exit_code(report, "error") == 2
    assert report_exit_code({"counts": {"error": 0, "warning": 1}}, "error") == 0
    assert report_exit_code({"counts": {"error": 0, "warning": 1}}, "warning") == 2


def test_liveness_oldest_queue_ignores_inactive_campaign_work():
    conn = _liveness_database()
    try:
        conn.campaigns["old"] = "completed"
        conn.candidates[("old", "z")] = "DISCOVERY_ACTIVE"
        conn.jobs.append({"campaign_id": "old", "candidate_id": "z",
                          "job_id": "old-job", "kind": "simulate",
                          "status": "queued", "created_utc": "2000-01-01T00:00:00Z"})
        from graph_scale_dynamics.domain.model import utc_now
        now = utc_now()
        conn.jobs[0]["created_utc"] = now
        conn.heartbeats.append({"service": "executor-1", "sampled_utc": now})
        conn.scheduler["updated_utc"] = now
        findings = liveness_findings(conn, queue_age_seconds=60)
    finally:
        conn.close()
    assert "liveness:old-simulation-queue" not in {item["key"] for item in findings}


def test_backup_verification_rejects_inconsistent_aggregate(tmp_path: Path):
    backup = tmp_path / "backup"
    store = BlobStore(backup / "blob_store")
    digest, size = store.put_json({"evidence": 1})
    dump = backup / "database.dump"
    dump.write_bytes(b"postgres-dump")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "build": 26,
        "created_utc": "2026-01-01T00:00:00Z",
        "quiescence": {"paused": True, "leased_jobs": 0, "leased_analysis": 0},
        "database": {"file": "database.dump", "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                     "size_bytes": dump.stat().st_size},
        "blobs": {"root": "blob_store", "count": 2, "size_bytes": size,
                  "objects": [{"digest": digest, "size_bytes": size}]},
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OSError, match="count"):
        verify_backup(backup)


def test_failed_restore_leaves_existing_blob_root_untouched(monkeypatch, tmp_path: Path):
    backup = tmp_path / "backup"
    store = BlobStore(backup / "blob_store")
    digest, size = store.put_json({"evidence": 1})
    dump = backup / "database.dump"
    dump.write_bytes(b"postgres-dump")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "build": 26,
        "created_utc": "2026-01-01T00:00:00Z",
        "quiescence": {"paused": True, "leased_jobs": 0, "leased_analysis": 0},
        "database": {"file": "database.dump", "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                     "size_bytes": dump.stat().st_size},
        "blobs": {"root": "blob_store", "count": 1, "size_bytes": size,
                  "objects": [{"digest": digest, "size_bytes": size}]},
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "target-blobs"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("original", encoding="utf-8")
    monkeypatch.setattr(backup_module, "_command", lambda name: name)
    monkeypatch.setattr(backup_module, "Repo", lambda database: nullcontext(object()))
    monkeypatch.setattr(backup_module, "exclusive_maintenance", lambda repo: nullcontext())
    monkeypatch.setattr(
        backup_module, "_run",
        lambda command: (_ for _ in ()).throw(RuntimeError("restore failed")),
    )
    with pytest.raises(RuntimeError, match="restore failed"):
        restore_backup(backup, "postgresql://unused", target, force=True)
    assert marker.read_text(encoding="utf-8") == "original"


def test_restore_uses_single_postgres_transaction(monkeypatch, tmp_path: Path):
    backup = tmp_path / "backup-single-tx"
    store = BlobStore(backup / "blob_store")
    digest, size = store.put_json({"evidence": 1})
    dump = backup / "database.dump"
    dump.write_bytes(b"postgres-dump")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "build": 29,
        "created_utc": "2026-01-01T00:00:00Z",
        "quiescence": {"paused": True, "leased_jobs": 0, "leased_analysis": 0},
        "database": {"file": "database.dump", "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                     "size_bytes": dump.stat().st_size},
        "blobs": {"root": "blob_store", "count": 1, "size_bytes": size,
                  "objects": [{"digest": digest, "size_bytes": size}]},
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    seen = []
    monkeypatch.setattr(backup_module, "_command", lambda name: name)
    monkeypatch.setattr(backup_module, "Repo", lambda database: nullcontext(object()))
    monkeypatch.setattr(backup_module, "exclusive_maintenance", lambda repo: nullcontext())
    monkeypatch.setattr(backup_module, "_run", lambda command: seen.append(command))
    target = tmp_path / "restored-blobs"

    restore_backup(backup, "postgresql://unused", target)

    assert seen and "--single-transaction" in seen[0]
    assert BlobStore(target).verify(digest)


def test_wildcard_bound_dashboard_requires_actual_loopback_and_capability(monkeypatch, tmp_path: Path):
    class FakeRepo:
        flags = {}
        def __init__(self, target):
            pass
        def close(self):
            pass
        def set_flag(self, key, value):
            self.flags[key] = value
        def get_flag(self, key, default=""):
            return self.flags.get(key, default)

    monkeypatch.setattr(api_main, "Repo", FakeRepo)
    token = "secret-token"
    handler = api_main.build_handler(
        "unused", str(tmp_path), token, 8765,
        bind_host="0.0.0.0",
    )
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(
            "POST", "/api/pause", body=b'{"paused":true}',
            headers={"Host": "192.168.1.50:8765", "Content-Type": "application/json",
                     "X-GSD-Admin-Token": token},
        )
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["paused"] is True
        conn.close()

        handler._client_is_loopback = lambda self: False
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(
            "POST", "/api/pause", body=b'{"paused":false}',
            headers={"Host": "192.168.1.50:8765", "Content-Type": "application/json",
                     "X-GSD-Admin-Token": token},
        )
        response = conn.getresponse()
        assert response.status == 403
        assert "needs the admin token" in json.loads(response.read())["error"]
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("GET", "/not-found", headers={"Host": "evil.example:8765"})
        response = conn.getresponse()
        assert response.status == 403
        assert json.loads(response.read())["error"] == "host not allowed"
        conn.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_a_page_without_the_admin_token_never_pauses_the_fleet(monkeypatch, tmp_path: Path):
    class FakeRepo:
        flags = {}
        workers = {}
        def __init__(self, target):
            pass
        def close(self):
            pass
        def set_flag(self, key, value):
            self.flags[key] = value
        def get_flag(self, key, default=""):
            return self.flags.get(key, default)

    monkeypatch.setattr(api_main, "Repo", FakeRepo)
    token = "secret-token"
    handler = api_main.build_handler(
        "unused", str(tmp_path), token, 8765, bind_host="0.0.0.0",
        allowed_hosts=("snekpas.nl",), base_path="/research",
    )
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(
            "POST", "/research/api/public-pause-mode", body=b'{"enabled":true}',
            headers={"Host": "snekpas.nl", "Origin": "https://snekpas.nl",
                     "Content-Type": "application/json", "X-GSD-Admin-Token": token},
        )
        response = conn.getresponse()
        assert response.status != 200
        response.read(); conn.close()
        handler._client_is_loopback = lambda self: False
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(
            "POST", "/research/api/pause", body=b'{"paused":true}',
            headers={"Host": "snekpas.nl", "Origin": "https://snekpas.nl", "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        assert response.status == 403 and "admin token" in json.loads(response.read())["error"]
        conn.close()
        assert FakeRepo.flags.get("paused") != "1"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_same_host_reverse_proxy_cannot_make_server_disclose_admin_token(monkeypatch, tmp_path: Path):
    class FakeRepo:
        flags = {}
        def __init__(self, target):
            pass
        def close(self):
            pass
        def set_flag(self, key, value):
            self.flags[key] = value
        def get_flag(self, key, default=""):
            return self.flags.get(key, default)

    monkeypatch.setattr(api_main, "Repo", FakeRepo)
    token = "proxy-must-not-see-this-token"
    handler = api_main.build_handler(
        "unused", str(tmp_path), token, 0, bind_host="0.0.0.0",
        allowed_hosts=("proxy.example",), base_path="/research",
    )
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", "/research/", headers={"Host": "127.0.0.1:8765"})
        response = connection.getresponse()
        payload = response.read().decode()
        assert response.status == 404
        assert token not in payload
        assert "separate web process" in payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST", "/api/pause", body=json.dumps({"paused": True}),
            headers={"Host": "127.0.0.1:8765", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read(); connection.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_mcmc_boundary_self_transitions_preserve_scheduled_trajectory():
    spec = {
        "dsl_version": 1,
        "init": "empty",
        "terms": [{"op": "edge_count", "params": {},
                   "coeff": {"c0": 0.0, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.001, "delete": 0.999}, "sweeps": 5},
    }
    n = 32
    points = 40
    envelope = run_simulation(spec, n, 91, record_points=points)
    total_moves = n * spec["dynamics"]["sweeps"]
    record_every = max(1, total_moves // points)
    expected_moves = list(range(0, total_moves, record_every))
    if expected_moves[-1] != total_moves - 1:
        expected_moves.append(total_moves - 1)

    assert [row["move"] for row in CL.trajectory(envelope)] == expected_moves
    attempted = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["attempted"]
    proposed = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["proposed"]
    assert sum(attempted.values()) == total_moves
    assert sum(proposed.values()) < sum(attempted.values())


def test_node_only_hamiltonian_disables_expensive_graph_ledgers():
    state = GraphState(32)
    state.require_ops({"degree_anchor", "degree_cube_sum"})
    assert state.required_ops == frozenset()


def test_reversible_edge_swap_kernel_executes_and_preserves_feasible_acceptance():
    spec = {
        "dsl_version": 1,
        "init": "empty",
        "terms": [{"op": "edge_count", "params": {},
                   "coeff": {"c0": 0.0, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.1, "delete": 0.1, "swap": 0.8},
                     "sweeps": 80},
    }
    envelope = run_simulation(spec, 12, 3701, record_points=60)
    attempted = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["attempted"]
    proposed = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["proposed"]
    accepted = CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["accepted"]
    assert attempted["swap"] > 0
    assert proposed["swap"] > 0
    assert accepted["swap"] == proposed["swap"]
    assert envelope["proposal_model"]["move_mix"]["swap"] == 0.8
    assert CL.trajectory(envelope)[-1]["attempted_swap"] == attempted["swap"]


def test_liveness_names_upstream_work_supply_starvation():
    conn = _liveness_database()
    try:
        from graph_scale_dynamics.domain.model import utc_now
        now = utc_now()
        conn.jobs.clear()
        conn.heartbeats.append({"service": "executor-1", "sampled_utc": now})
        conn.scheduler.update({
            "updated_utc": now, "total_slots": 28, "simulation_slots": 27,
            "analysis_slots": 1, "queued_simulations": 0, "leased_simulations": 1,
        })
        findings = liveness_findings(conn, queue_age_seconds=1)
    finally:
        conn.close()
    item = next(item for item in findings if item["key"] == "liveness:work-supply-starved")
    assert item["category"] == "pipeline_starvation"
    assert item["detail"]["unused_compute_slots"] == 27
    assert item["detail"]["stranded_by_state"] == {"DISCOVERY_ACTIVE": 1}
