from __future__ import annotations

import json
import secrets
from typing import Callable

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.domain.model import content_hash, interrupted_sql, utc_now
from graph_scale_dynamics.operations.dev_mode import provenance as dev_mode_provenance
from graph_scale_dynamics.db.repo_shared import (
    FENCE_PAUSED_CLASS, _validated_search_seed, candidate_may_run_job, retryable_db_error,
)


class CampaignStore:
    def insert_campaign(self, campaign_id: str, spec: dict, spec_hash: str) -> None:
        self._write(
            "INSERT INTO campaigns(campaign_id,spec_json,spec_hash,created_utc) "
            "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
            (str(campaign_id), json.dumps(spec), spec_hash, utc_now()),
        )
        existing = self.conn.execute(
            "SELECT spec_json,spec_hash FROM campaigns WHERE campaign_id=?", (str(campaign_id),)
        ).fetchone()
        if existing is None:
            raise RuntimeError("campaign insert did not become visible")
        if existing["spec_hash"] != spec_hash or json.loads(existing["spec_json"]) != spec:
            raise ValueError("campaign id collision: stored specification differs")

    def research_instance_id(self) -> str:
        existing = self.get_flag("research_instance_id", "").strip()
        if existing:
            return existing
        proposed = secrets.token_hex(16)
        return self.set_flag_if_absent("research_instance_id", proposed)

    def _next_campaign_id_locked(self) -> str:
        self.conn.execute(
            "INSERT INTO control(key,value) VALUES('next_campaign_number','1') "
            "ON CONFLICT(key) DO NOTHING"
        )
        row = self.conn.execute(
            "SELECT value FROM control WHERE key='next_campaign_number' FOR UPDATE"
        ).fetchone()
        if row is None:
            raise RuntimeError("campaign number allocator is unavailable")
        try:
            number = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("campaign number allocator is corrupt") from exc
        if number <= 0:
            raise RuntimeError("campaign number allocator must remain positive")
        campaign_id = str(number)
        while self.conn.execute(
            "SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone() is not None:
            number += 1
            campaign_id = str(number)
        self.conn.execute(
            "UPDATE control SET value=? WHERE key='next_campaign_number'",
            (str(number + 1),),
        )
        return campaign_id

    def record_campaign_event(self, campaign_id: str, event_type: str,
                              detail: dict | None = None, *,
                              build_number: int | None = None,
                              runtime_fingerprint: str | None = None) -> None:
        if build_number is None or runtime_fingerprint is None:
            try:
                from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint as _runtime_fingerprint
                build_number = BUILD_NUMBER if build_number is None else build_number
                runtime_fingerprint = (_runtime_fingerprint() if runtime_fingerprint is None
                                       else runtime_fingerprint)
            except Exception:
                pass
        self._write(
            "INSERT INTO campaign_events(campaign_id,event_type,detail_json,build_number,"
            "runtime_fingerprint,created_utc) VALUES(?,?,?,?,?,?)",
            (str(campaign_id), str(event_type), json.dumps(detail or {}, sort_keys=True),
             build_number, runtime_fingerprint, utc_now()),
        )

    def campaign_events(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM campaign_events WHERE campaign_id=? AND event_type<>'fleet_ladder_snapshot' "
            "ORDER BY created_utc,campaign_event_id", (str(campaign_id),)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
            out.append(item)
        return out

    def fleet_ladder_hourly(self, campaign_id: str) -> dict:
        rows = self.conn.execute(
            "SELECT DISTINCT ON (substr(created_utc,1,13)) substr(created_utc,1,13) AS hour,created_utc,detail_json "
            "FROM campaign_events WHERE campaign_id=? AND event_type='fleet_ladder_snapshot' "
            "ORDER BY substr(created_utc,1,13),created_utc DESC,campaign_event_id DESC", (str(campaign_id),)
        ).fetchall()
        count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id=? AND event_type='fleet_ladder_snapshot'",
            (str(campaign_id),)).fetchone()["c"]
        return {"snapshots": int(count or 0),
                "hours": [{"hour": row["hour"], "snapshot_utc": row["created_utc"],
                           **json.loads(row["detail_json"] or "{}")} for row in rows]}

    def create_campaign(self, spec: dict, *, search_seed: int, role: str = "discovery",
                        parent_campaign_id: str | None = None,
                        change_reason: str | None = None,
                        based_on_report_artifact: str | None = None,
                        based_on_report_sha256: str | None = None) -> dict:
        from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
        from graph_scale_dynamics.scheduling.provenance import (
            CAMPAIGN_PROVENANCE_CONTRACT, experiment_config_hash, policy_hashes,
        )
        search_seed = _validated_search_seed(search_seed)
        hashes = policy_hashes(spec)
        spec_hash = content_hash(spec)
        experiment_hash = experiment_config_hash(spec, search_seed)
        self.begin_transaction(attempts=12)
        try:
            campaign_id = self._next_campaign_id_locked()
            parent = None
            series = campaign_id
            if parent_campaign_id is not None:
                parent = self.conn.execute(
                    "SELECT campaign_id,campaign_series_id FROM campaigns WHERE campaign_id=? FOR SHARE",
                    (str(parent_campaign_id),),
                ).fetchone()
                if parent is None:
                    raise KeyError(f"unknown parent campaign {parent_campaign_id}")
                series = str(parent["campaign_series_id"] or parent["campaign_id"])
            now = utc_now()
            source = runtime_fingerprint()
            self.conn.execute(
                "INSERT INTO campaigns(campaign_id,spec_json,spec_hash,status,created_utc,"
                "provenance_contract,campaign_role,parent_campaign_id,campaign_series_id,"
                "search_seed,science_contract_hash,search_policy_hash,resource_policy_hash,"
                "experiment_config_hash,created_build,created_runtime_fingerprint,change_reason,"
                "based_on_report_artifact,based_on_report_sha256) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, json.dumps(spec), spec_hash, "active", now,
                 CAMPAIGN_PROVENANCE_CONTRACT, str(role),
                 None if parent_campaign_id is None else str(parent_campaign_id), series,
                 int(search_seed), hashes["science_contract_hash"],
                 hashes["search_policy_hash"], hashes["resource_policy_hash"],
                 experiment_hash, int(BUILD_NUMBER), source, change_reason,
                 based_on_report_artifact, based_on_report_sha256),
            )
            self.conn.execute(
                "INSERT INTO campaign_events(campaign_id,event_type,detail_json,build_number,"
                "runtime_fingerprint,created_utc) VALUES(?,?,?,?,?,?)",
                (campaign_id, "campaign_created", json.dumps({
                    "role": str(role),
                    "run_provenance": dev_mode_provenance(),
                    "parent_campaign_id": parent_campaign_id,
                    "change_reason": change_reason,
                    "based_on_report_sha256": based_on_report_sha256,
                }, sort_keys=True), int(BUILD_NUMBER), source, now),
            )
            if based_on_report_sha256:
                self.conn.execute(
                    "INSERT INTO campaign_events(campaign_id,event_type,detail_json,build_number,"
                    "runtime_fingerprint,created_utc) VALUES(?,?,?,?,?,?)",
                    (campaign_id, "report_attached", json.dumps({
                        "artifact": based_on_report_artifact,
                        "sha256": based_on_report_sha256,
                    }, sort_keys=True), int(BUILD_NUMBER), source, now),
                )
            self.conn.execute(
                "INSERT INTO control(key,value) VALUES('research_instance_id',?) "
                "ON CONFLICT(key) DO NOTHING", (secrets.token_hex(16),)
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise
        created = self.campaign(campaign_id)
        if created is None:
            raise RuntimeError("new campaign did not become visible")
        return created

    def set_flag(self, key: str, value: str) -> None:
        self._write(
            "INSERT INTO control(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        if key == "paused":
            try:
                self.conn.execute(
                    "SELECT pg_notify('gsd_work', ?)",
                    (json.dumps({"kind": "control", "key": key, "value": value}),),
                )
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise

    EXTEND_ONLY_PREFIX = "extend_only:"

    def set_campaign_extend_only(self, campaign_id: str, enabled: bool) -> bool:
        self.set_flag(f"{self.EXTEND_ONLY_PREFIX}{campaign_id}", "1" if enabled else "0")
        return bool(enabled)

    def campaign_extend_only(self, campaign_id: str) -> bool:
        return self.get_flag(f"{self.EXTEND_ONLY_PREFIX}{campaign_id}", "0") == "1"

    def extend_only_campaigns(self) -> frozenset[str]:
        rows = self.conn.execute(
            "SELECT key,value FROM control WHERE key LIKE ?",
            (f"{self.EXTEND_ONLY_PREFIX}%",),
        ).fetchall()
        return frozenset(str(r["key"])[len(self.EXTEND_ONLY_PREFIX):]
                         for r in rows if str(r["value"]) == "1")

    def set_flag_if_absent(self, key: str, value: str) -> str:
        self._write("INSERT INTO control(key,value) VALUES(?,?) ON CONFLICT DO NOTHING", (key, value))
        stored = self.get_flag(key, "")
        if not stored:
            raise RuntimeError(f"control value {key!r} was not persisted")
        return stored

    def get_flag(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def active_campaigns(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM campaigns WHERE status='active' ORDER BY created_utc"
        ).fetchall()
        return [dict(r) | {"spec": json.loads(r["spec_json"])} for r in rows]

    def all_campaigns(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM campaigns ORDER BY created_utc").fetchall()
        return [dict(r) | {"spec": json.loads(r["spec_json"])} for r in rows]

    def campaign_link(self, child_campaign_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM campaign_links WHERE child_campaign_id=?", (child_campaign_id,)
        ).fetchone()
        return dict(row) if row else None

    def child_campaigns(self, parent_campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT l.*,c.status,c.spec_hash,c.campaign_role,c.provenance_contract,"
            "c.created_utc AS campaign_created_utc "
            "FROM campaign_links l JOIN campaigns c ON c.campaign_id=l.child_campaign_id "
            "WHERE l.parent_campaign_id=? ORDER BY l.created_utc",
            (parent_campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def dependent_campaigns(self, parent_campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.campaign_id AS child_campaign_id,c.status,c.spec_hash,c.campaign_role,"
            "c.provenance_contract,c.created_utc AS campaign_created_utc,c.parent_campaign_id "
            "FROM campaigns c WHERE c.parent_campaign_id=? "
            "UNION "
            "SELECT c.campaign_id AS child_campaign_id,c.status,c.spec_hash,c.campaign_role,"
            "c.provenance_contract,c.created_utc AS campaign_created_utc,c.parent_campaign_id "
            "FROM campaign_links l JOIN campaigns c ON c.campaign_id=l.child_campaign_id "
            "WHERE l.parent_campaign_id=? "
            "ORDER BY campaign_created_utc,child_campaign_id",
            (str(parent_campaign_id), str(parent_campaign_id)),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_campaign_status(self, campaign_id: str, status: str) -> None:
        row = self.conn.execute("SELECT status FROM campaigns WHERE campaign_id=?",
                                (str(campaign_id),)).fetchone()
        previous = row["status"] if row else None
        changed = self._write("UPDATE campaigns SET status=? WHERE campaign_id=?",
                              (status, str(campaign_id)))
        if changed and previous != status:
            self.record_campaign_event(str(campaign_id), "campaign_status_changed",
                                       {"from": previous, "to": status})

    def set_workers_target(self, campaign_id: str, target: int | None) -> None:
        row = self.conn.execute("SELECT workers_target FROM campaigns WHERE campaign_id=?",
                                (str(campaign_id),)).fetchone()
        previous = row["workers_target"] if row else None
        changed = self._write("UPDATE campaigns SET workers_target=? WHERE campaign_id=?",
                              (target, str(campaign_id)))
        if changed and previous != target:
            self.record_campaign_event(str(campaign_id), "worker_allocation_changed",
                                       {"from": previous, "to": target})

    def operator_pause_cancel_active_work(self, *, reason: str = "user cancelled by pause") -> dict:
        self.begin_transaction(attempts=12)
        try:
            now = utc_now()
            leased_jobs = self.conn.execute(
                "SELECT job_id FROM jobs WHERE status='leased' FOR UPDATE"
            ).fetchall()
            leased_job_ids = [str(row["job_id"]) for row in leased_jobs]
            if leased_job_ids:
                marks = ",".join("?" for _ in leased_job_ids)
                self.conn.execute(
                    f"UPDATE attempts SET finished_utc=COALESCE(finished_utc,?),"
                    "wall_seconds=COALESCE(wall_seconds,GREATEST(0,EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_utc::timestamptz)))),"
                    "exit_code=COALESCE(exit_code,-15),error=COALESCE(error,?),"
                    f"error_class=COALESCE(error_class,'{FENCE_PAUSED_CLASS}') "
                    f"WHERE finished_utc IS NULL AND job_id IN ({marks})",
                    (now, reason, *leased_job_ids),
                )
            jobs = self.conn.execute(
                "UPDATE jobs SET status='queued',lease_owner=NULL,lease_expires_utc=NULL,"
                "memory_reservation_bytes=0,lease_generation=lease_generation+1,"
                "attempts=GREATEST(0,attempts-1),next_attempt_utc=NULL,updated_utc=?,error=NULL "
                "WHERE status='leased'",
                (now,),
            ).rowcount

            analysis_rows = self.conn.execute(
                "SELECT campaign_id,input_artifact,analysis_version FROM analysis_queue "
                "WHERE status='leased' FOR UPDATE"
            ).fetchall()
            for row in analysis_rows:
                self.conn.execute(
                    "UPDATE analysis_attempts SET finished_utc=COALESCE(finished_utc,?),"
                    "wall_seconds=COALESCE(wall_seconds,GREATEST(0,EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_utc::timestamptz)))),"
                    "exit_code=COALESCE(exit_code,-15),error=COALESCE(error,?),"
                    "error_class=COALESCE(error_class,'user_cancelled') "
                    "WHERE finished_utc IS NULL AND campaign_id=? AND input_artifact=? "
                    "AND analysis_version=?",
                    (now, reason, row["campaign_id"], row["input_artifact"], row["analysis_version"]),
                )
            analyses = self.conn.execute(
                "UPDATE analysis_queue SET status='queued',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,"
                "attempts=GREATEST(0,attempts-1),error=NULL,error_class=NULL,updated_utc=? "
                "WHERE status='leased'",
                (now,),
            ).rowcount
            rebuilds = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status='queued',lease_owner=NULL,"
                "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,error=NULL,"
                "updated_utc=? WHERE status='leased'",
                (now,),
            ).rowcount
            self.conn.execute("COMMIT")
            payload = {
                "reason": reason, "jobs_user_cancelled": int(jobs or 0),
                "analysis_user_cancelled": int(analyses or 0),
                "rebuilds_user_cancelled": int(rebuilds or 0),
            }
            self.emit("operator_pause_cancelled_active_work", payload)
            return payload
        except Exception:
            self.conn.rollback_if_open()
            raise

    def stop_campaign_work(self, campaign_id: str, *, reason: str = "operator stopped campaign") -> dict:
        row = self.conn.execute(
            "SELECT status FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if row is None:
            return {"found": False, "jobs_cancelled": 0, "analysis_cancelled": 0}
        self.begin_transaction(attempts=12)
        try:
            now = utc_now()
            self.conn.execute(
                "UPDATE campaigns SET workers_target=0,status=CASE WHEN status='active' "
                "THEN 'closed' ELSE status END WHERE campaign_id=?", (campaign_id,)
            )
            jobs = self.conn.execute(
                "UPDATE jobs SET status='cancelled',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
                "lease_generation=lease_generation+CASE WHEN status='leased' THEN 1 ELSE 0 END,"
                "updated_utc=?,error=COALESCE(error,?) WHERE campaign_id=? "
                "AND status IN ('queued','leased')",
                (now, reason, campaign_id),
            ).rowcount
            analyses = self.conn.execute(
                "UPDATE analysis_queue SET status='cancelled',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=COALESCE(error,?),"
                "error_class=COALESCE(error_class,'campaign_stopped'),updated_utc=? "
                "WHERE campaign_id=? AND status IN ('queued','leased')",
                (reason, now, campaign_id),
            ).rowcount
            analyses += self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status='cancelled',lease_owner=NULL,"
                "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,"
                "error=COALESCE(error,?),updated_utc=? WHERE campaign_id=? "
                "AND status IN ('queued','leased')",
                (reason, now, campaign_id),
            ).rowcount
            self.conn.execute("COMMIT")
            self.record_campaign_event(str(campaign_id), "campaign_stopped", {
                "reason": reason, "jobs_cancelled": int(jobs),
                "analysis_cancelled": int(analyses),
                "stopped_utc": now,
            })
            return {"found": True, "jobs_cancelled": int(jobs),
                    "analysis_cancelled": int(analyses)}
        except Exception:
            self.conn.rollback_if_open()
            raise

    def revive_stopped_work(self, campaign_id: str) -> dict:
        from datetime import datetime, timedelta, timezone

        from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES
        row = self.conn.execute(
            "SELECT detail_json,created_utc FROM campaign_events WHERE campaign_id=? AND event_type='campaign_stopped' "
            "ORDER BY campaign_event_id DESC LIMIT 1", (str(campaign_id),)).fetchone()
        if row is None:
            return {"jobs": 0, "analyses": 0, "rebuilds": 0, "stopped_utc": None}
        detail = json.loads(row["detail_json"] or "{}")
        since = detail.get("stopped_utc")
        if not since:
            at = datetime.fromisoformat(str(row["created_utc"]).replace("Z", "+00:00")) - timedelta(minutes=5)
            since = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        states = sorted(RUNNING_CANDIDATE_STATES)
        live = ("EXISTS (SELECT 1 FROM campaign_candidates cc WHERE cc.campaign_id={t}.campaign_id "
                "AND cc.candidate_id={t}.candidate_id AND cc.state IN (" + ",".join("?" * len(states)) + "))")
        now = utc_now()
        self.begin_transaction(attempts=12)
        try:
            jobs = self.conn.execute(
                "UPDATE jobs j SET status='queued',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
                "error=NULL,updated_utc=? WHERE j.campaign_id=? AND j.status='cancelled' AND j.result_artifact IS NULL "
                "AND j.updated_utc>=? AND " + live.format(t="j"), (now, str(campaign_id), since, *states)).rowcount
            analyses = self.conn.execute(
                "UPDATE analysis_queue q SET status='queued',lease_owner=NULL,claim_token=NULL,lease_expires_utc=NULL,"
                "memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,error_class=NULL,updated_utc=? "
                "WHERE q.campaign_id=? AND q.status='cancelled' AND q.error_class='campaign_stopped' "
                "AND q.updated_utc>=? AND " + live.format(t="q"), (now, str(campaign_id), since, *states)).rowcount
            rebuilds = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds r SET status='queued',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,next_attempt_utc=NULL,error=NULL,updated_utc=? WHERE r.campaign_id=? "
                "AND r.status='cancelled' AND r.updated_utc>=? AND " + live.format(t="r"),
                (now, str(campaign_id), since, *states)).rowcount
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise
        return {"jobs": int(jobs), "analyses": int(analyses), "rebuilds": int(rebuilds), "stopped_utc": since}

    def campaign_storage_profile(self, campaign_id: str) -> dict:
        from graph_scale_dynamics.db.campaign_storage import storage_profile
        return storage_profile(self.conn, campaign_id)

    def worker_allocation(self, claimable: bool = False) -> list[dict]:
        ready = " AND COALESCE(j.next_attempt_utc,'')<=?" if claimable else ""
        rows = self.conn.execute(
            "SELECT c.campaign_id,c.workers_target,"
            "(c.spec_json::jsonb #>> '{study_design,group}') AS work_group,"
            "SUM(CASE WHEN j.status='leased' THEN 1 ELSE 0 END) AS leased,"
            f"SUM(CASE WHEN j.status='queued'{ready} THEN 1 ELSE 0 END) AS queued "
            "FROM campaigns c LEFT JOIN jobs j ON j.campaign_id=c.campaign_id "
            "WHERE c.status='active' GROUP BY c.campaign_id,c.workers_target,c.created_utc,c.spec_json "
            "ORDER BY c.created_utc",
            (utc_now(),) if claimable else ()
        ).fetchall()
        return [dict(r) for r in rows]

    def campaign_stats(self, campaign_id: str) -> dict:
        archived = self.conn.execute(
            "SELECT state,summary_json FROM campaign_archives WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        campaign_row = self.conn.execute(
            "SELECT status FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if archived is not None and campaign_row is not None and campaign_row["status"] == "archived":
            summary = json.loads(archived["summary_json"] or "{}")
            return {"job_counts": summary.get("source_job_counts") or {},
                    "analysis_counts": {}, "analysis_retrying": 0,
                    "last_activity_utc": summary.get("last_activity_utc"),
                    "compute_seconds": round(float(summary.get("compute_seconds", 0) or 0), 1),
                    "candidates": int(summary.get("candidates", 0) or 0)}
        counts = {r["status"]: r["c"] for r in self.conn.execute(
            "SELECT status,COUNT(*) c FROM jobs WHERE campaign_id=? GROUP BY status", (campaign_id,)
        )}
        last = self.conn.execute(
            "SELECT GREATEST("
            " COALESCE((SELECT MAX(updated_utc) FROM jobs WHERE campaign_id=?),''),"
            " COALESCE((SELECT MAX(finished_utc) FROM auxiliary_attempts WHERE campaign_id=?),''),"
            " COALESCE((SELECT MAX(started_utc) FROM auxiliary_attempts WHERE campaign_id=?),'')) m",
            (campaign_id, campaign_id, campaign_id),
        ).fetchone()["m"]
        simulation_compute = self.conn.execute(
            "SELECT COALESCE(SUM(a.wall_seconds),0) s FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=?", (campaign_id,)
        ).fetchone()["s"]
        analysis_compute = self.conn.execute(
            "SELECT COALESCE(SUM(wall_seconds),0) s FROM analysis_attempts WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()["s"]
        auxiliary_compute = self.conn.execute(
            "SELECT COALESCE(SUM(wall_seconds),0) s FROM auxiliary_attempts WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()["s"]
        compute = (float(simulation_compute or 0) + float(analysis_compute or 0)
                   + float(auxiliary_compute or 0))
        candidates = self.conn.execute(
            "SELECT COUNT(*) c FROM campaign_candidates WHERE campaign_id=?", (campaign_id,)
        ).fetchone()["c"]
        analysis = self.analysis_queue_status(campaign_id)
        return {"job_counts": counts, "analysis_counts": analysis["counts"],
                "analysis_retrying": analysis["retrying"],
                "last_activity_utc": last,
                "compute_seconds": round(float(compute or 0), 1),
                "simulation_compute_seconds": round(float(simulation_compute or 0), 1),
                "analysis_compute_seconds": round(float(analysis_compute or 0), 1),
                "auxiliary_compute_seconds": round(float(auxiliary_compute or 0), 1),
                "candidates": candidates}

    def queued_simulation_claimability(self, campaign_id: str) -> list[dict]:
        now = utc_now()
        rows = self.conn.execute(
            "SELECT j.n,j.stage,cc.state,"
            "(j.next_attempt_utc IS NOT NULL AND j.next_attempt_utc>?) AS deferred,"
            "(c.status='active') AS campaign_active,COUNT(*) AS c "
            "FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
            "WHERE j.campaign_id=? AND j.kind='simulate' AND j.status='queued' "
            "GROUP BY j.n,j.stage,cc.state,deferred,campaign_active",
            (now, str(campaign_id)),
        ).fetchall()
        out = []
        for row in rows:
            state = str(row["state"] or "")
            if not bool(row["campaign_active"]):
                reason = "campaign_inactive"
            elif not candidate_may_run_job(state):
                reason = "candidate_terminal"
            elif bool(row["deferred"]):
                reason = "next_attempt_future"
            else:
                reason = "claimable"
            out.append({"n": int(row["n"]), "state": state, "stage": row["stage"],
                        "reason": reason, "count": int(row["c"] or 0)})
        return out

    def candidate_rung_compute(self, campaign_id: str, candidate_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT j.n,COUNT(DISTINCT j.job_id) jobs,COUNT(a.attempt_id) attempts,"
            "COALESCE(SUM(a.wall_seconds),0) core_seconds,"
            "COALESCE(SUM(CASE WHEN a.exit_code=0 THEN a.wall_seconds ELSE 0 END),0) successful_seconds,"
            "COALESCE(SUM(CASE WHEN a.exit_code IS NOT NULL AND a.exit_code!=0 "
            f"AND NOT {interrupted_sql('a')} THEN a.wall_seconds ELSE 0 END),0) failed_seconds,"
            f"COALESCE(SUM(CASE WHEN {interrupted_sql('a')} THEN a.wall_seconds ELSE 0 END),0) interrupted_seconds,"
            f"COUNT(a.attempt_id) FILTER (WHERE {interrupted_sql('a')}) interrupted_attempts,"
            "MAX(a.wall_seconds) max_attempt_seconds,MAX(a.peak_rss_bytes) peak_rss_bytes,"
            "MAX(a.peak_uss_bytes) peak_uss_bytes,MAX(a.peak_pss_bytes) peak_pss_bytes,"
            "MAX(a.peak_edge_count) peak_edge_count,MAX(a.final_edge_count) final_edge_count "
            "FROM jobs j LEFT JOIN attempts a ON a.job_id=j.job_id "
            "WHERE j.campaign_id=? AND j.candidate_id=? AND j.kind='simulate' "
            "GROUP BY j.n ORDER BY j.n",
            (campaign_id, candidate_id),
        ).fetchall()
        analysis_rows = self.conn.execute(
            "SELECT n,COALESCE(SUM(seconds),0) analysis_seconds,"
            "MAX(peak_rss_bytes) analysis_peak_rss_bytes FROM ("
            "SELECT q.n,aa.wall_seconds seconds,aa.peak_rss_bytes FROM analysis_attempts aa "
            "JOIN analysis_queue q ON q.campaign_id=aa.campaign_id "
            "AND q.input_artifact=aa.input_artifact AND q.analysis_version=aa.analysis_version "
            "WHERE q.campaign_id=? AND q.candidate_id=? "
            "UNION ALL "
            "SELECT q.n,q.wall_seconds seconds,q.peak_rss_bytes FROM analysis_queue q "
            "WHERE q.campaign_id=? AND q.candidate_id=? AND q.status='done' "
            "AND NOT EXISTS (SELECT 1 FROM analysis_attempts aa WHERE aa.campaign_id=q.campaign_id "
            "AND aa.input_artifact=q.input_artifact AND aa.analysis_version=q.analysis_version)"
            ") x GROUP BY n",
            (campaign_id, candidate_id, campaign_id, candidate_id),
        ).fetchall()
        analysis_by_n = {int(row["n"]): row for row in analysis_rows}
        cumulative = 0.0
        out = []
        for row in rows:
            simulation_core = float(row["core_seconds"] or 0.0)
            analysis_row = analysis_by_n.get(int(row["n"]))
            analysis_core = float(analysis_row["analysis_seconds"] or 0.0) if analysis_row else 0.0
            core = simulation_core + analysis_core
            cumulative += core
            out.append({
                "n": int(row["n"]), "jobs": int(row["jobs"] or 0),
                "attempts": int(row["attempts"] or 0),
                "core_seconds": round(core, 3),
                "simulation_core_seconds": round(simulation_core, 3),
                "analysis_core_seconds": round(analysis_core, 3),
                "successful_seconds": round(float(row["successful_seconds"] or 0.0), 3),
                "failed_seconds": round(float(row["failed_seconds"] or 0.0), 3),
                "interrupted_seconds": round(float(row["interrupted_seconds"] or 0.0), 3),
                "interrupted_attempts": int(row["interrupted_attempts"] or 0),
                "max_attempt_seconds": (None if row["max_attempt_seconds"] is None
                                        else round(float(row["max_attempt_seconds"]), 3)),
                "peak_rss_bytes": row["peak_rss_bytes"],
                "analysis_peak_rss_bytes": (analysis_row["analysis_peak_rss_bytes"]
                                             if analysis_row else None),
                "peak_uss_bytes": row["peak_uss_bytes"],
                "peak_pss_bytes": row["peak_pss_bytes"],
                "peak_edge_count": row["peak_edge_count"],
                "final_edge_count": row["final_edge_count"],
                "cumulative_core_seconds": round(cumulative, 3),
            })
        return out

    def delete_campaign(self, campaign_id: str, *, force: bool = False,
                        progress: Callable[[str], None] | None = None,
                        batch_size: int = 5000) -> dict:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        row = self.conn.execute(
            "SELECT status FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if row is None:
            return {"campaigns": 0}
        leased = self.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE campaign_id=? AND status='leased'", (campaign_id,)
        ).fetchone()["c"]
        leased_analysis = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM analysis_queue WHERE campaign_id=? AND status='leased') "
            "+ (SELECT COUNT(*) FROM candidate_evidence_rebuilds WHERE campaign_id=? "
            "AND status='leased') c",
            (campaign_id, campaign_id),
        ).fetchone()["c"]
        children = self.conn.execute(
            "SELECT COUNT(*) c FROM campaigns c WHERE c.parent_campaign_id=? "
            "OR EXISTS (SELECT 1 FROM campaign_links l WHERE l.child_campaign_id=c.campaign_id "
            "AND l.parent_campaign_id=?)", (campaign_id, campaign_id)
        ).fetchone()["c"]
        if not force and children:
            raise ValueError("campaign has dependent child campaigns; delete those first")
        if not force and (row["status"] == "active" or leased or leased_analysis):
            raise ValueError(
                "campaign must be closed and have no leased simulation or analysis work before deletion"
            )

        say = progress or (lambda _message: None)
        counts: dict[str, int] = {}

        def relation_exists(table: str) -> bool:
            row = self.conn.execute(
                "SELECT to_regclass(?) AS relation_name", (table,)
            ).fetchone()
            return bool(row and row["relation_name"] is not None)

        def count_where(table: str, where: str, args: tuple) -> int:
            return int(self.conn.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE {where}", args
            ).fetchone()["c"] or 0)

        def delete_where(label: str, table: str, where: str, args: tuple,
                         *, optional: bool = False) -> int:
            if optional and not relation_exists(table):
                counts[label] = 0
                say(f"delete {campaign_id}: {label}: skipped (relation absent)")
                return 0
            expected = count_where(table, where, args)
            if expected <= 0:
                counts[label] = 0
                return 0
            removed = 0
            say(f"delete {campaign_id}: {label}: 0/{expected}")
            while removed < expected:
                cursor = self.conn.execute(
                    f"WITH doomed AS (SELECT ctid FROM {table} WHERE {where} LIMIT ?) "
                    f"DELETE FROM {table} t USING doomed d WHERE t.ctid=d.ctid",
                    (*args, batch_size),
                )
                step = int(cursor.rowcount or 0)
                removed += step
                say(f"delete {campaign_id}: {label}: {removed}/{expected}")
                if step == 0:
                    break
            counts[label] = removed
            return removed

        def delete_joined_to_jobs(label: str, table: str, alias: str, job_column: str) -> int:
            expected = int(self.conn.execute(
                f"SELECT COUNT(*) c FROM {table} {alias} JOIN jobs j "
                f"ON j.job_id={alias}.{job_column} WHERE j.campaign_id=?",
                (campaign_id,),
            ).fetchone()["c"] or 0)
            if expected <= 0:
                counts[label] = 0
                return 0
            removed = 0
            say(f"delete {campaign_id}: {label}: 0/{expected}")
            while removed < expected:
                cursor = self.conn.execute(
                    f"WITH doomed AS (SELECT {alias}.ctid FROM {table} {alias} JOIN jobs j "
                    f"ON j.job_id={alias}.{job_column} WHERE j.campaign_id=? LIMIT ?) "
                    f"DELETE FROM {table} x USING doomed d WHERE x.ctid=d.ctid",
                    (campaign_id, batch_size),
                )
                step = int(cursor.rowcount or 0)
                removed += step
                say(f"delete {campaign_id}: {label}: {removed}/{expected}")
                if step == 0:
                    break
            counts[label] = removed
            return removed

        self.begin_transaction(attempts=12)
        try:
            self.conn.execute(
                "UPDATE campaigns SET status='deleting',workers_target=0 WHERE campaign_id=?",
                (campaign_id,),
            )

            delete_where("analysis_queue", "analysis_queue", "campaign_id=?", (campaign_id,))
            delete_where("evidence_rebuilds", "candidate_evidence_rebuilds",
                         "campaign_id=?", (campaign_id,))
            delete_where("measurements", "measurements", "campaign_id=?", (campaign_id,))
            delete_where("evidence_audits", "evidence_audits", "campaign_id=?", (campaign_id,))
            delete_where("rung_summaries", "rung_summaries", "campaign_id=?", (campaign_id,))
            delete_where("engine_decisions", "engine_decisions", "campaign_id=?", (campaign_id,))
            delete_where("latest_decisions", "engine_decisions_latest", "campaign_id=?", (campaign_id,))
            delete_where("rung_diagnostics", "rung_diagnostics", "campaign_id=?", (campaign_id,))
            delete_where("proposal_assessments", "proposal_assessments",
                         "campaign_id=?", (campaign_id,))
            delete_where("proposal_exposures", "proposal_exposures",
                         "campaign_id=?", (campaign_id,))

            delete_joined_to_jobs("attempts", "attempts", "a", "job_id")
            delete_joined_to_jobs("artifact_producers", "artifact_producers", "ap", "job_id")

            producer_links = int(self.conn.execute(
                "SELECT COUNT(*) c FROM artifacts a JOIN jobs j ON j.job_id=a.producer_job "
                "WHERE j.campaign_id=?", (campaign_id,),
            ).fetchone()["c"] or 0)
            if producer_links:
                changed = 0
                say(f"delete {campaign_id}: artifact producer links: 0/{producer_links}")
                while changed < producer_links:
                    cursor = self.conn.execute(
                        "WITH doomed AS (SELECT a.ctid FROM artifacts a JOIN jobs j "
                        "ON j.job_id=a.producer_job WHERE j.campaign_id=? LIMIT ?) "
                        "UPDATE artifacts a SET producer_job=NULL FROM doomed d WHERE a.ctid=d.ctid",
                        (campaign_id, batch_size),
                    )
                    step = int(cursor.rowcount or 0)
                    changed += step
                    say(f"delete {campaign_id}: artifact producer links: {changed}/{producer_links}")
                    if step == 0:
                        break
                counts["artifact_producer_links"] = changed
            else:
                counts["artifact_producer_links"] = 0

            delete_where("jobs", "jobs", "campaign_id=?", (campaign_id,))
            delete_where("auxiliary_attempts", "auxiliary_attempts",
                         "campaign_id=?", (campaign_id,), optional=True)
            delete_where("campaign_events", "campaign_events",
                         "campaign_id=?", (campaign_id,), optional=True)
            delete_where("proposal_policy_epochs", "proposal_policy_epochs",
                         "campaign_id=?", (campaign_id,), optional=True)

            delete_where("campaign_candidates", "campaign_candidates",
                         "campaign_id=?", (campaign_id,))
            delete_where("promotion_policy", "campaign_promotion_policies",
                         "source_campaign_id=?", (campaign_id,), optional=True)
            delete_where("campaign_links", "campaign_links",
                         "child_campaign_id=? OR parent_campaign_id=?",
                         (campaign_id, campaign_id))

            delete_where("archive_measurements", "campaign_archive_measurements",
                         "campaign_id=?", (campaign_id,), optional=True)
            delete_where("archive_runs", "campaign_archive_runs",
                         "campaign_id=?", (campaign_id,), optional=True)
            delete_where("archive_candidates", "campaign_archive_candidates",
                         "campaign_id=?", (campaign_id,), optional=True)
            delete_where("archive_header", "campaign_archives",
                         "campaign_id=?", (campaign_id,), optional=True)

            cursor = self.conn.execute("DELETE FROM campaigns WHERE campaign_id=?", (campaign_id,))
            counts["campaigns"] = int(cursor.rowcount or 0)
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.rollback_if_open()
            raise
        say(f"delete {campaign_id}: complete")
        return counts

    def campaign(self, campaign_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        return dict(row) | {"spec": json.loads(row["spec_json"])} if row else None
