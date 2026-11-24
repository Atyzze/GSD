from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.postgres_contract import scenario

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_postgres_repository_contract(isolated_postgres_schema):
    result = scenario(isolated_postgres_schema.dsn)
    assert result["backlog"] == 0
    assert result["active_claims"] == 0
    job_status = {job["job_id"]: job["status"] for job in result["jobs"]}
    assert job_status["job-contract"] == "done"
    assert result["artifact_producers"] == 1
    assert result["analysis_failure_status"] == "failed"
    assert result["terminal_jobs_cancelled"] == 1


def test_engine_campaign_vertical_slice(isolated_postgres_schema):
    import shutil
    import uuid

    var_dir = ROOT / f".pytest_slice_var_{uuid.uuid4().hex[:8]}"
    env = dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=isolated_postgres_schema.schema)
    result = subprocess.run([sys.executable, "tests/integration/slice_driver.py", "--var", str(var_dir), "--engine"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    try:
        assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    finally:
        shutil.rmtree(var_dir, ignore_errors=True)


def test_every_chain_vertical_slice(isolated_postgres_schema):
    import shutil
    import uuid

    var_dir = ROOT / f".pytest_slice_var_{uuid.uuid4().hex[:8]}"
    env = dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=isolated_postgres_schema.schema)
    result = subprocess.run([sys.executable, "tests/integration/slice_driver.py", "--var", str(var_dir), "--every-chain"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    try:
        assert result.returncode == 0 and "EVERY CHAIN SLICE OK" in result.stdout, (
            result.stdout[-4000:] + result.stderr[-4000:])
    finally:
        shutil.rmtree(var_dir, ignore_errors=True)


def test_the_let_through_slice(isolated_postgres_schema):
    import shutil
    import uuid

    var_dir = ROOT / f".pytest_slice_var_{uuid.uuid4().hex[:8]}"
    env = dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=isolated_postgres_schema.schema)
    result = subprocess.run([sys.executable, "tests/integration/slice_driver.py", "--var", str(var_dir), "--let-through"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    try:
        assert result.returncode == 0 and "LET THROUGH SLICE OK" in result.stdout, (
            result.stdout[-4000:] + result.stderr[-4000:])
    finally:
        shutil.rmtree(var_dir, ignore_errors=True)


def test_postgres_fault_injection_preserves_transaction_atomicity(
    monkeypatch, isolated_postgres_schema
):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash
    from graph_scale_dynamics.observability.faults import InjectedFault

    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        spec = {"mode": "bounded", "ladder": [16]}
        candidate_spec = {
            "terms": [{"kind": "edge_count", "coefficient": 0.1}],
            "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 1},
        }
        repo.insert_campaign("camp-fault", spec, content_hash(spec))
        repo.insert_candidate(
            "candidate-fault",
            "camp-fault",
            candidate_spec,
            "metropolis",
            1,
            "DISCOVERY_ACTIVE",
        )
        repo.insert_job(
            job_id="job-fault",
            campaign_id="camp-fault",
            candidate_id="candidate-fault",
            kind="simulate",
            stage="PILOT",
            n=16,
            seed=1,
            replicate=0,
            spec={"candidate_spec": candidate_spec},
            priority=1,
            sealed=False,
            requested_by="fault-test",
        )

        monkeypatch.setenv("GSD_ENABLE_FAULT_INJECTION", "1")
        monkeypatch.setenv("GSD_FAULT_ACTION", "exception")
        monkeypatch.setenv("GSD_FAULT_POINTS", "terminal.after_state_before_cancel")
        with pytest.raises(InjectedFault):
            repo.terminalize_candidate(
                "camp-fault", "candidate-fault", "QUARANTINE", "fault"
            )
        assert repo.candidate("candidate-fault", "camp-fault")["state"] == "DISCOVERY_ACTIVE"
        assert repo.jobs("camp-fault", job_id="job-fault")[0]["status"] == "queued"

        claim = repo.claim_job("executor-fault", ("simulate",))
        monkeypatch.setenv("GSD_FAULT_POINTS", "simulation.after_job_before_analysis")
        with pytest.raises(InjectedFault):
            repo.commit_job_result(
                job_id="job-fault",
                owner="executor-fault",
                lease_generation=claim["lease_generation"],
                digest="d" * 64,
                size=10,
                media_type="application/json",
                meta={},
                analysis_version="fault-v1",
            )
        assert repo.jobs("camp-fault", job_id="job-fault")[0]["status"] == "leased"
        assert (
            repo.conn.execute(
                "SELECT COUNT(*) c FROM artifacts WHERE artifact_hash=?", ("d" * 64,)
            ).fetchone()["c"]
            == 0
        )
        assert (
            repo.conn.execute(
                "SELECT COUNT(*) c FROM analysis_queue WHERE input_artifact=?",
                ("d" * 64,),
            ).fetchone()["c"]
            == 0
        )
    finally:
        repo.close()


def test_postgres_reclaim_expired_accepts_null_analysis_lease_identity(
    isolated_postgres_schema,
):
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash

    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        spec = {"mode": "continuous", "ladder": [16]}
        candidate_spec = {
            "terms": [{"kind": "edge_count", "coefficient": 0.1}],
            "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 1},
        }
        repo.insert_campaign("camp-null-lease", spec, content_hash(spec))
        repo.insert_candidate(
            "candidate-null-lease",
            "camp-null-lease",
            candidate_spec,
            "metropolis",
            1,
            "DISCOVERY_ACTIVE",
        )
        repo.insert_job(
            job_id="job-null-lease",
            campaign_id="camp-null-lease",
            candidate_id="candidate-null-lease",
            kind="simulate",
            stage="PILOT",
            n=16,
            seed=1,
            replicate=0,
            spec={"candidate_spec": candidate_spec},
            priority=1,
            sealed=False,
            requested_by="null-lease-test",
        )
        now = utc_now()
        digest = "a" * 64
        repo.conn.execute(
            "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
            "VALUES(?,?,?,?,?,?)",
            (digest, 1, "application/json", "job-null-lease", "{}", now),
        )
        repo.conn.execute(
            "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
            "producer_job,priority,status,lease_owner,claim_token,lease_expires_utc,created_utc,updated_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "camp-null-lease",
                digest,
                "analysis-null-lease",
                "candidate-null-lease",
                16,
                1,
                "job-null-lease",
                1,
                "leased",
                None,
                None,
                "2000-01-01T00:00:00Z",
                now,
                now,
            ),
        )

        assert repo.reclaim_expired() == 1
        row = repo.conn.execute(
            "SELECT status,lease_owner,claim_token FROM analysis_queue "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
            ("camp-null-lease", digest, "analysis-null-lease"),
        ).fetchone()
        assert row["status"] == "queued"
        assert row["lease_owner"] is None
        assert row["claim_token"] is None
    finally:
        repo.close()


def test_postgres_campaign_delete_removes_dependencies_and_keeps_artifact_row(
    isolated_postgres_schema,
):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash, utc_now

    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        spec = {"mode": "continuous", "ladder": [16]}
        candidate_spec = {
            "terms": [{"kind": "edge_count", "coefficient": 0.1}],
            "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 1},
        }
        repo.insert_campaign("camp-delete", spec, content_hash(spec))
        repo.insert_candidate(
            "candidate-delete",
            "camp-delete",
            candidate_spec,
            "metropolis",
            1,
            "DISCOVERY_ACTIVE",
        )
        repo.insert_job(
            job_id="job-delete",
            campaign_id="camp-delete",
            candidate_id="candidate-delete",
            kind="simulate",
            stage="PILOT",
            n=16,
            seed=1,
            replicate=0,
            spec={"candidate_spec": candidate_spec},
            priority=1,
            sealed=False,
            requested_by="delete-test",
        )
        now = utc_now()
        digest = "b" * 64
        repo.conn.execute(
            "INSERT INTO attempts(attempt_id,job_id,number,started_utc) VALUES(?,?,?,?)",
            ("attempt-delete", "job-delete", 1, now),
        )
        repo.conn.execute(
            "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
            "VALUES(?,?,?,?,?,?)",
            (digest, 10, "application/json", "job-delete", "{}", now),
        )
        repo.conn.execute(
            "INSERT INTO artifact_producers(artifact_hash,job_id,role,created_utc) VALUES(?,?,?,?)",
            (digest, "job-delete", "simulation", now),
        )
        repo.conn.execute(
            "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
            "producer_job,priority,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "camp-delete",
                digest,
                "analysis-delete",
                "candidate-delete",
                16,
                1,
                "job-delete",
                1,
                "cancelled",
                now,
                now,
            ),
        )
        messages = []
        repo.stop_campaign_work("camp-delete")
        removed = repo.delete_campaign(
            "camp-delete", force=True, progress=messages.append, batch_size=1
        )
        assert removed["campaigns"] == 1
        assert (
            repo.conn.execute(
                "SELECT COUNT(*) c FROM campaigns WHERE campaign_id='camp-delete'"
            ).fetchone()["c"]
            == 0
        )
        assert (
            repo.conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE job_id='job-delete'"
            ).fetchone()["c"]
            == 0
        )
        assert (
            repo.conn.execute(
                "SELECT COUNT(*) c FROM attempts WHERE job_id='job-delete'"
            ).fetchone()["c"]
            == 0
        )
        artifact = repo.conn.execute(
            "SELECT producer_job FROM artifacts WHERE artifact_hash=?", (digest,)
        ).fetchone()
        assert artifact is not None
        assert artifact["producer_job"] is None
        assert messages[-1] == "delete camp-delete: complete"
    finally:
        repo.close()


def test_postgres_maintenance_advisory_lock_serializes_only_maintenance(isolated_postgres_schema):
    import threading

    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations.maintenance import exclusive_maintenance

    init_db(isolated_postgres_schema.dsn)
    contender_started = threading.Event()
    contender_acquired = threading.Event()
    contender_done = threading.Event()

    def contend():
        with Repo(isolated_postgres_schema.dsn) as other:
            contender_started.set()
            with exclusive_maintenance(other):
                contender_acquired.set()
        contender_done.set()

    with Repo(isolated_postgres_schema.dsn) as first:
        with exclusive_maintenance(first):
            thread = threading.Thread(target=contend, daemon=True)
            thread.start()
            assert contender_started.wait(10)
            assert not contender_acquired.wait(0.2)

            with Repo(isolated_postgres_schema.dsn) as ordinary:
                assert ordinary.conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

        assert contender_acquired.wait(10)
        assert contender_done.wait(10)
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_campaign_numbers_are_run_identity_not_policy_hash(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec

    init_db(isolated_postgres_schema.dsn)
    spec = freeze_campaign_spec({"mode": "bounded", "ladder": [64]})
    with Repo(isolated_postgres_schema.dsn) as repo:
        first = repo.create_campaign(spec, search_seed=11)
        second = repo.create_campaign(spec, search_seed=12)
        assert first["campaign_id"] == "1"
        assert second["campaign_id"] == "2"
        assert first["spec_hash"] == second["spec_hash"]
        assert first["search_policy_hash"] == second["search_policy_hash"]
        assert first["experiment_config_hash"] != second["experiment_config_hash"]


def test_a_failed_creation_does_not_burn_a_campaign_number(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec

    init_db(isolated_postgres_schema.dsn)
    spec = freeze_campaign_spec({"mode": "bounded", "ladder": [64]})
    with Repo(isolated_postgres_schema.dsn) as repo:
        with pytest.raises(KeyError):
            repo.create_campaign(spec, search_seed=1, parent_campaign_id="999")
        created = repo.create_campaign(spec, search_seed=2)
        assert created["campaign_id"] == "1"


def test_a_campaign_definition_is_immutable_in_the_database(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec

    init_db(isolated_postgres_schema.dsn)
    spec = freeze_campaign_spec({"mode": "bounded", "ladder": [64]})
    with Repo(isolated_postgres_schema.dsn) as repo:
        created = repo.create_campaign(spec, search_seed=3)
        with pytest.raises(Exception):
            repo.conn.execute(
                "UPDATE campaigns SET spec_json=? WHERE campaign_id=?",
                ('{"mutated":true}', created["campaign_id"]),
            )
        if repo.conn.in_transaction:
            repo.conn.execute("ROLLBACK")
        assert repo.campaign(created["campaign_id"])["spec"] == spec
        repo.set_campaign_status(created["campaign_id"], "completed")
        assert repo.campaign(created["campaign_id"])["status"] == "completed"


def test_fleet_lock_holder_is_named_and_can_be_reaped(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db

    init_db(isolated_postgres_schema.dsn)
    name = "gsd-test:fleet-lock-reap"
    first = Repo(isolated_postgres_schema.dsn)
    second = Repo(isolated_postgres_schema.dsn)
    try:
        assert second.service_lock_holder(name) is None
        assert first.acquire_service_lock(name)
        first_pid = int(first.conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])

        holder = second.service_lock_holder(name)
        assert holder and int(holder["pid"]) == first_pid, holder
        assert not second.acquire_service_lock(name)

        assert second.service_lock_holder("gsd-test:some-other-lock") is None

        assert second.terminate_service_lock_holder(name) == first_pid
        import time
        for _ in range(50):
            if second.service_lock_holder(name) is None:
                break
            time.sleep(0.1)
        assert second.service_lock_holder(name) is None
        assert second.acquire_service_lock(name)
        assert int(second.service_lock_holder(name)["pid"]) != first_pid
    finally:
        try:
            second.release_service_lock(name)
        except Exception:
            pass
        second.close()
        try:
            first.close()
        except Exception:
            pass


def test_run_reaps_a_dead_supervisors_fleet_lock_and_refuses_a_live_one(isolated_postgres_schema, tmp_path):
    import json
    import os
    import socket
    import subprocess
    import sys

    from graph_scale_dynamics.db.repo import Repo, init_db
    import main as supervisor

    init_db(isolated_postgres_schema.dsn)
    name = "gsd-test:fleet-lock-reaper"
    old = Repo(isolated_postgres_schema.dsn)
    new = Repo(isolated_postgres_schema.dsn)
    var = tmp_path / "var"
    var.mkdir()
    pid_file = var / supervisor.FLEET_PID_FILE
    try:
        assert old.acquire_service_lock(name)

        assert supervisor._reap_orphaned_fleet_lock(new, var, name) is False
        assert new.service_lock_holder(name) is not None

        pid_file.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                        "started_utc": "now"}))
        assert supervisor._reap_orphaned_fleet_lock(new, var, name) is False
        assert new.service_lock_holder(name) is not None

        pid_file.write_text(json.dumps({"pid": 1, "host": "somewhere-else", "started_utc": "now"}))
        assert supervisor._reap_orphaned_fleet_lock(new, var, name) is False

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        pid_file.write_text(json.dumps({"pid": dead.pid, "host": socket.gethostname(),
                                        "started_utc": "earlier"}))
        assert supervisor._reap_orphaned_fleet_lock(new, var, name) is True
        holder = new.service_lock_holder(name)
        new_pid = int(new.conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])
        assert holder and int(holder["pid"]) == new_pid
    finally:
        try:
            new.release_service_lock(name)
        except Exception:
            pass
        new.close()
        try:
            old.close()
        except Exception:
            pass


def test_an_unconsumed_event_is_not_fleet_work(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash

    init_db(isolated_postgres_schema.dsn)
    spec = {"mode": "bounded", "ladder": [64], "analysis_version": "events-v1"}
    with Repo(isolated_postgres_schema.dsn) as repo:
        repo.insert_campaign("camp", spec, content_hash(spec))
        repo.set_campaign_status("camp", "closed")
        for topic in ("analysis_ready", "decision", "job_failed", "job_lost", "integrity_failure", "analysis_failed"):
            repo.emit(topic, {"campaign_id": "camp", "candidate_id": "law"})
        assert repo.fleet_has_work("events-v1") is False
        assert repo.fleet_has_work() is False
        repo.set_campaign_status("camp", "active")
        assert repo.fleet_has_work("events-v1") is True
