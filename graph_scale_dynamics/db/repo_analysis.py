from __future__ import annotations

import json
import secrets
import time

from graph_scale_dynamics.domain.model import EVIDENCE_SUMMARY_CONTRACT, utc_now
from graph_scale_dynamics.observability.faults import hit as fault_hit
from graph_scale_dynamics.db.repo_shared import TERMINAL_STATES, _probe_seconds_columns, analysis_runnable_candidate_sql, runnable_candidate_sql


class AnalysisStore:
    def ensure_analysis_queue(self, analysis_version: str) -> int:
        now = utc_now()
        status = ("CASE WHEN EXISTS(SELECT 1 FROM measurements m2 "
                  "WHERE m2.campaign_id=excluded.campaign_id "
                  "AND m2.input_artifact=excluded.input_artifact "
                  "AND m2.analysis_version=excluded.analysis_version) THEN 'done' "
                  "WHEN analysis_queue.status='leased' THEN 'leased' "
                  "WHEN analysis_queue.status='failed' THEN 'failed' ELSE 'queued' END")
        cursor = self.conn.execute(
            "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,"
            "n,seed,producer_job,priority,status,created_utc,updated_utc) "
            "SELECT j.campaign_id,j.result_artifact,?,j.candidate_id,j.n,j.seed,j.job_id,j.priority,"
            "CASE WHEN m.analysis_id IS NULL THEN 'queued' ELSE 'done' END,?,? "
            "FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
            "LEFT JOIN measurements m ON m.campaign_id=j.campaign_id "
            "AND m.input_artifact=j.result_artifact AND m.analysis_version=? "
            "WHERE j.kind='simulate' AND j.status='done' AND j.result_artifact IS NOT NULL "
            "AND c.status='active' "
            "AND " + runnable_candidate_sql("cc.state") + " "
            "ON CONFLICT(campaign_id,input_artifact,analysis_version) DO UPDATE SET "
            f"status={status},"
            "attempts=CASE WHEN analysis_queue.status='cancelled' THEN 0 "
            "ELSE analysis_queue.attempts END,"
            "updated_utc=excluded.updated_utc "
            f"WHERE ({status}) IS DISTINCT FROM analysis_queue.status",
            (analysis_version, now, now, analysis_version, *TERMINAL_STATES),
        )
        return max(0, int(cursor.rowcount))

    def cancel_superseded_analysis_work(self, analysis_version: str) -> int:
        from graph_scale_dynamics.scheduling.recovery import superseded_analysis_keys

        rows = self.conn.execute(
            "SELECT q.campaign_id,q.input_artifact,q.analysis_version,q.candidate_id,"
            "q.n,q.seed,q.status,q.created_utc,j.created_utc AS job_created_utc,"
            "j.spec_json,c.spec_json AS campaign_spec_json "
            "FROM analysis_queue q JOIN jobs j ON j.job_id=q.producer_job "
            "JOIN campaigns c ON c.campaign_id=q.campaign_id "
            "WHERE q.analysis_version=? AND q.status IN ('queued','leased','done')",
            (analysis_version,),
        ).fetchall()
        normalized = [
            dict(row) | {
                "spec": json.loads(row["spec_json"] or "{}"),
                "campaign_spec": json.loads(row["campaign_spec_json"] or "{}"),
            }
            for row in rows
        ]
        keys = superseded_analysis_keys(normalized)
        if not keys:
            return 0
        now = utc_now()
        changed = 0
        self.begin_transaction(attempts=12)
        try:
            for campaign_id, artifact, version in keys:
                cursor = self.conn.execute(
                    "UPDATE analysis_queue SET status='cancelled',lease_owner=NULL,claim_token=NULL,"
                    "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,"
                    "error='superseded/recovery-excess analysis work',"
                    "error_class='superseded',updated_utc=? "
                    "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
                    "AND status='queued'",
                    (now, campaign_id, artifact, version),
                )
                changed += max(0, int(cursor.rowcount or 0))
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise
        return changed

    def ensure_candidate_evidence_rebuilds(self, analysis_version: str) -> int:
        now = utc_now()
        touched: set[tuple[str, str, str]] = set()
        self.conn.execute("BEGIN")
        try:
            stale = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds r SET status='queued',"
                "next_attempt_utc=NULL,error=NULL,updated_utc=? "
                "WHERE r.analysis_version=? AND r.status='done' AND EXISTS ("
                "SELECT 1 FROM campaigns c JOIN campaign_candidates cc "
                "ON cc.campaign_id=c.campaign_id WHERE c.campaign_id=r.campaign_id "
                "AND cc.candidate_id=r.candidate_id AND c.status='active' "
                f"AND cc.state NOT IN ({','.join('?' for _ in TERMINAL_STATES)})) AND EXISTS ("
                "SELECT 1 FROM rung_summaries s WHERE s.campaign_id=r.campaign_id "
                "AND s.candidate_id=r.candidate_id AND s.analysis_version=r.analysis_version "
                "AND COALESCE((s.summary_json::jsonb)->>'summary_contract','')<>?) "
                "RETURNING r.campaign_id,r.candidate_id,r.analysis_version",
                (now, analysis_version, *TERMINAL_STATES, EVIDENCE_SUMMARY_CONTRACT),
            )
            touched.update(
                (str(row["campaign_id"]), str(row["candidate_id"]), str(row["analysis_version"]))
                for row in stale.fetchall()
            )
            refreshed = self.conn.execute(
                "INSERT INTO candidate_evidence_rebuilds(campaign_id,candidate_id,analysis_version,"
                "status,requested_measurement_count,requested_newest_utc,created_utc,updated_utc) "
                "SELECT m.campaign_id,m.candidate_id,m.analysis_version,'queued',COUNT(*),"
                "COALESCE(MAX(m.created_utc),''),MIN(m.created_utc),? FROM measurements m "
                "JOIN campaigns c ON c.campaign_id=m.campaign_id "
                "JOIN campaign_candidates cc ON cc.campaign_id=m.campaign_id "
                "AND cc.candidate_id=m.candidate_id "
                "WHERE m.analysis_version=? AND c.status='active' "
                f"AND cc.state NOT IN ({','.join('?' for _ in TERMINAL_STATES)}) "
                "GROUP BY m.campaign_id,m.candidate_id,m.analysis_version "
                "ON CONFLICT(campaign_id,candidate_id,analysis_version) DO UPDATE SET "
                "requested_measurement_count=excluded.requested_measurement_count,"
                "requested_newest_utc=excluded.requested_newest_utc,"
                "status=CASE WHEN candidate_evidence_rebuilds.status='leased' THEN 'leased' "
                "WHEN candidate_evidence_rebuilds.built_measurement_count="
                "excluded.requested_measurement_count AND candidate_evidence_rebuilds.built_newest_utc="
                "excluded.requested_newest_utc THEN 'done' ELSE 'queued' END,"
                "next_attempt_utc=CASE WHEN candidate_evidence_rebuilds.status='leased' "
                "THEN candidate_evidence_rebuilds.next_attempt_utc ELSE NULL END,"
                "error=CASE WHEN candidate_evidence_rebuilds.status='leased' "
                "THEN candidate_evidence_rebuilds.error ELSE NULL END,updated_utc=excluded.updated_utc "
                "WHERE candidate_evidence_rebuilds.requested_measurement_count IS DISTINCT FROM "
                "excluded.requested_measurement_count OR candidate_evidence_rebuilds.requested_newest_utc "
                "IS DISTINCT FROM excluded.requested_newest_utc OR "
                "(candidate_evidence_rebuilds.status='done' AND "
                "(candidate_evidence_rebuilds.built_measurement_count IS DISTINCT FROM "
                "excluded.requested_measurement_count OR candidate_evidence_rebuilds.built_newest_utc "
                "IS DISTINCT FROM excluded.requested_newest_utc)) "
                "RETURNING campaign_id,candidate_id,analysis_version",
                (now, analysis_version, *TERMINAL_STATES),
            )
            touched.update(
                (str(row["campaign_id"]), str(row["candidate_id"]), str(row["analysis_version"]))
                for row in refreshed.fetchall()
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise
        return len(touched)

    def engine_decisions(self, campaign_id: str, candidate_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT decision_id,at_n,next_n,action,rule,reason,priority,queue_order,jobs_created,"
            "rows_changed,released_hold,engine,facts_json,created_utc FROM engine_decisions "
            "WHERE campaign_id=? AND candidate_id=? ORDER BY decision_id",
            (str(campaign_id), str(candidate_id)),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["facts"] = json.loads(item.pop("facts_json") or "{}")
            out.append(item)
        return out

    def campaign_engine_decisions(self, campaign_id: str) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for row in self.conn.execute(
            "SELECT candidate_id,decision_id,at_n,next_n,action,rule,reason,priority,queue_order,jobs_created,"
            "rows_changed,released_hold,engine,facts_json,created_utc FROM engine_decisions "
            "WHERE campaign_id=? ORDER BY candidate_id,decision_id", (str(campaign_id),),
        ).fetchall():
            item = dict(row)
            item["facts"] = json.loads(item.pop("facts_json") or "{}")
            grouped.setdefault(str(item.pop("candidate_id")), []).append(item)
        return grouped

    def rung_diagnostics(self, campaign_id: str, candidate_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT n,analysis_version,contract,diagnostics_json,created_utc FROM rung_diagnostics "
            "WHERE campaign_id=? AND candidate_id=? ORDER BY n,analysis_version",
            (str(campaign_id), str(candidate_id)),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["diagnostics"] = json.loads(item.pop("diagnostics_json") or "{}")
            out.append(item)
        return out

    def live_laws_latest_decision(self, campaign_id: str) -> list[dict]:
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        rows = self.conn.execute(
            "SELECT c.candidate_id,c.state,d.action,d.next_n FROM campaign_candidates c "
            "LEFT JOIN engine_decisions_latest d "
            "ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
            f"WHERE c.campaign_id=? AND c.state NOT IN ({placeholders})",
            (str(campaign_id), *TERMINAL_STATES),
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_engine_decisions(self, campaign_id: str) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT candidate_id,decision_id,at_n,next_n,action,rule,reason,"
            "priority,jobs_created,created_utc FROM engine_decisions_latest WHERE campaign_id=? "
            "ORDER BY candidate_id",
            (str(campaign_id),),
        ).fetchall()
        return {str(row["candidate_id"]): dict(row) for row in rows}

    def candidate_evidence_pending(self, campaign_id: str, candidate_id: str,
                                   analysis_version: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "AND status IN ('queued','leased','failed','lost') UNION ALL "
            "SELECT 1 FROM analysis_queue WHERE campaign_id=? AND candidate_id=? "
            "AND analysis_version=? AND status IN ('queued','leased','failed') UNION ALL "
            "SELECT 1 FROM candidate_evidence_rebuilds WHERE campaign_id=? AND candidate_id=? "
            "AND analysis_version=? AND (status!='done' OR built_measurement_count<>requested_measurement_count "
            "OR built_newest_utc<>requested_newest_utc) LIMIT 1",
            (campaign_id, candidate_id, campaign_id, candidate_id, analysis_version,
             campaign_id, candidate_id, analysis_version),
        ).fetchone()
        return row is not None

    def analysis_backlog(self, analysis_version: str) -> int:
        now = utc_now()
        terminal_marks = ",".join("?" for _ in TERMINAL_STATES)
        analyses = int(self.conn.execute(
            "SELECT COUNT(*) c FROM analysis_queue q "
            "JOIN campaigns c ON c.campaign_id=q.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id "
            "AND cc.candidate_id=q.candidate_id "
            "WHERE q.analysis_version=? AND q.status IN ('queued','leased') "
            "AND c.status='active' "
            "AND " + analysis_runnable_candidate_sql("cc.state") + " "
            "AND (q.status='leased' OR q.next_attempt_utc IS NULL OR q.next_attempt_utc<=?)",
            (analysis_version, *TERMINAL_STATES, now),
        ).fetchone()["c"])
        rebuilds = int(self.conn.execute(
            "SELECT COUNT(*) c FROM candidate_evidence_rebuilds r "
            "JOIN campaigns c ON c.campaign_id=r.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=r.campaign_id "
            "AND cc.candidate_id=r.candidate_id "
            "WHERE r.analysis_version=? AND r.status IN ('queued','leased') "
            "AND c.status='active' "
            f"AND cc.state NOT IN ({terminal_marks}) "
            "AND (r.status='leased' OR r.next_attempt_utc IS NULL OR r.next_attempt_utc<=?)",
            (analysis_version, *TERMINAL_STATES, now),
        ).fetchone()["c"])
        return analyses + rebuilds

    def cancel_unclaimable_analysis_work(self, *, reason: str =
                                         "campaign/candidate no longer claimable") -> int:
        now = utc_now()
        terminal_marks = ",".join("?" for _ in TERMINAL_STATES)
        self.begin_transaction(attempts=12)
        try:
            raw = self.conn.execute(
                "UPDATE analysis_queue q SET status='cancelled',lease_owner=NULL,"
                "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,"
                "error=COALESCE(q.error,?),error_class=COALESCE(q.error_class,'not_claimable'),"
                "updated_utc=? WHERE q.status IN ('queued','leased') AND NOT EXISTS ("
                "SELECT 1 FROM campaigns c JOIN campaign_candidates cc "
                "ON cc.campaign_id=c.campaign_id WHERE c.campaign_id=q.campaign_id "
                "AND cc.candidate_id=q.candidate_id AND c.status='active' "
                "AND " + analysis_runnable_candidate_sql("cc.state") + ")",
                (reason, now, *TERMINAL_STATES),
            ).rowcount
            rebuilds = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds r SET status='cancelled',lease_owner=NULL,"
                "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,"
                "error=COALESCE(r.error,?),updated_utc=? "
                "WHERE r.status IN ('queued','leased') AND NOT EXISTS ("
                "SELECT 1 FROM campaigns c JOIN campaign_candidates cc "
                "ON cc.campaign_id=c.campaign_id WHERE c.campaign_id=r.campaign_id "
                "AND cc.candidate_id=r.candidate_id AND c.status='active' "
                f"AND cc.state NOT IN ({terminal_marks}))",
                (reason, now, *TERMINAL_STATES),
            ).rowcount
            self.conn.execute("COMMIT")
            return int(raw) + int(rebuilds)
        except Exception:
            self.conn.rollback_if_open()
            raise

    def claim_candidate_evidence_rebuild(self, owner: str, analysis_version: str,
                                         lease_seconds: int = 180) -> dict | None:
        now = utc_now()
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + lease_seconds)
        )
        token = secrets.token_hex(16)
        self.begin_transaction(attempts=12)
        try:
            row = self.conn.execute(
                "SELECT * FROM candidate_evidence_rebuilds WHERE analysis_version=? "
                "AND status='queued' AND (next_attempt_utc IS NULL OR next_attempt_utc<=?) "
                "ORDER BY updated_utc,candidate_id FOR UPDATE SKIP LOCKED LIMIT 1",
                (analysis_version, now),
            ).fetchone()
            if row is None:
                self.conn.execute("COMMIT")
                return None
            changed = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status='leased',lease_owner=?,claim_token=?,"
                "lease_expires_utc=?,attempts=attempts+1,error=NULL,updated_utc=? "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? AND status='queued'",
                (owner, token, expires, now, row["campaign_id"], row["candidate_id"],
                 analysis_version),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return None
            self.conn.execute("COMMIT")
            return dict(row) | {"rebuild_claim_token": token, "lease_owner": owner,
                                "lease_expires_utc": expires,
                                "rebuild_attempt_number": int(row["attempts"]) + 1}
        except Exception:
            self.conn.rollback_if_open()
            raise

    def release_candidate_evidence_rebuild(self, campaign_id: str, candidate_id: str,
                                            analysis_version: str, owner: str,
                                            claim_token: str, error: str | None = None) -> bool:
        return self._write(
            "UPDATE candidate_evidence_rebuilds SET status='queued',lease_owner=NULL,"
            "claim_token=NULL,lease_expires_utc=NULL,error=?,updated_utc=? "
            "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? AND status='leased' "
            "AND lease_owner=? AND claim_token=?",
            (error, utc_now(), campaign_id, candidate_id, analysis_version, owner, claim_token),
        )

    def fail_candidate_evidence_rebuild(self, campaign_id: str, candidate_id: str,
                                        analysis_version: str, owner: str,
                                        claim_token: str, error: str) -> dict | None:
        self.begin_transaction(attempts=12)
        try:
            row = self.conn.execute(
                "SELECT attempts,max_attempts FROM candidate_evidence_rebuilds "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=? FOR UPDATE",
                (campaign_id, candidate_id, analysis_version, owner, claim_token),
            ).fetchone()
            if row is None:
                self.conn.rollback_if_open()
                return None
            attempts = int(row["attempts"])
            retry = attempts < int(row["max_attempts"])
            status = "queued" if retry else "failed"
            next_attempt = None
            if retry:
                delay = min(300, 2 ** max(0, attempts - 1))
                next_attempt = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + delay)
                )
            self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status=?,lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,next_attempt_utc=?,error=?,updated_utc=? "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=?",
                (status, next_attempt, error[:4000], utc_now(), campaign_id, candidate_id,
                 analysis_version, owner, claim_token),
            )
            if not retry:
                self.conn.execute(
                    "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                    ("analysis_failed", json.dumps({
                        "campaign_id": campaign_id, "candidate_id": candidate_id,
                        "analysis_version": analysis_version, "stage": "evidence_rebuild",
                        "error": error[:4000], "attempts": attempts, "retry": False,
                    }), utc_now()),
                )
            self.conn.execute("COMMIT")
            return {"status": status, "retry": retry, "attempts": attempts,
                    "next_attempt_utc": next_attempt}
        except Exception:
            self.conn.rollback_if_open()
            raise

    def complete_candidate_evidence_rebuild(
            self, *, campaign_id: str, candidate_id: str, analysis_version: str,
            owner: str, claim_token: str, measurement_count: int,
            newest_measurement_utc: str, summaries: dict[int, dict],
            transitions: list[tuple[int, int, dict]],
            certified_rungs: dict[int, bool] | None = None,
            diagnostics: dict[int, dict] | None = None) -> str:
        self.begin_transaction(attempts=12)
        try:
            if not self.lock_candidate(campaign_id, candidate_id):
                self.conn.rollback_if_open()
                return "fenced"
            claim = self.conn.execute(
                "SELECT 1 FROM candidate_evidence_rebuilds WHERE campaign_id=? "
                "AND candidate_id=? AND analysis_version=? AND status='leased' "
                "AND lease_owner=? AND claim_token=? AND lease_expires_utc>=? FOR UPDATE",
                (campaign_id, candidate_id, analysis_version, owner, claim_token, utc_now()),
            ).fetchone()
            if claim is None:
                self.conn.rollback_if_open()
                return "fenced"
            current = self.conn.execute(
                "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') newest FROM measurements "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=?",
                (campaign_id, candidate_id, analysis_version),
            ).fetchone()
            current_revision = (int(current["c"]), current["newest"])
            expected_revision = (int(measurement_count), newest_measurement_utc)
            if current_revision != expected_revision:
                self.conn.rollback_if_open()
                return "stale"
            now = utc_now()
            for n, summary in summaries.items():
                self.conn.execute(
                    "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,"
                    "summary_json,created_utc) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(campaign_id,candidate_id,n,analysis_version) DO UPDATE SET "
                    "summary_json=excluded.summary_json,created_utc=excluded.created_utc",
                    (campaign_id, candidate_id, int(n), analysis_version,
                     json.dumps(summary), now),
                )
            for n, diagnostic in (diagnostics or {}).items():
                self.conn.execute(
                    "INSERT INTO rung_diagnostics(campaign_id,candidate_id,n,analysis_version,contract,"
                    "diagnostics_json,created_utc) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(campaign_id,candidate_id,n,analysis_version) DO UPDATE SET "
                    "contract=excluded.contract,diagnostics_json=excluded.diagnostics_json,created_utc=excluded.created_utc",
                    (campaign_id, candidate_id, int(n), analysis_version, str(diagnostic.get("contract") or ""),
                     json.dumps(diagnostic), now),
                )
            changed = self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status='done',"
                "built_measurement_count=?,built_newest_utc=?,"
                "requested_measurement_count=?,requested_newest_utc=?,"
                "lease_owner=NULL,claim_token=NULL,lease_expires_utc=NULL,"
                "next_attempt_utc=NULL,error=NULL,updated_utc=? "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=?",
                (expected_revision[0], expected_revision[1], expected_revision[0],
                 expected_revision[1], now, campaign_id, candidate_id,
                 analysis_version, owner, claim_token),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return "fenced"
            self.conn.execute(
                "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                ("analysis_ready", json.dumps({
                    "campaign_id": campaign_id, "candidate_id": candidate_id,
                    "rungs": sorted(int(n) for n in summaries),
                    "measurement_revision": {
                        "count": expected_revision[0],
                        "newest_utc": expected_revision[1],
                    },
                }), now),
            )
            self.conn.execute("COMMIT")
            return "done"
        except Exception:
            self.conn.rollback_if_open()
            raise

    def analysis_queue_status(self, campaign_id: str,
                              analysis_version: str | None = None) -> dict:
        clauses = ["campaign_id=?"]
        params: list = [campaign_id]
        if analysis_version is not None:
            clauses.append("analysis_version=?")
            params.append(analysis_version)
        where = " AND ".join(clauses)
        raw_counts = {row["status"]: int(row["c"]) for row in self.conn.execute(
            f"SELECT status,COUNT(*) c FROM analysis_queue WHERE {where} GROUP BY status",
            params,
        ).fetchall()}
        rebuild_counts = {row["status"]: int(row["c"]) for row in self.conn.execute(
            f"SELECT status,COUNT(*) c FROM candidate_evidence_rebuilds WHERE {where} "
            "GROUP BY status", params,
        ).fetchall()}
        counts = dict(raw_counts)
        for status, count in rebuild_counts.items():
            counts[status] = counts.get(status, 0) + count
        raw_retrying = int(self.conn.execute(
            f"SELECT COUNT(*) c FROM analysis_queue WHERE {where} "
            "AND status='queued' AND attempts>0", params,
        ).fetchone()["c"])
        rebuild_retrying = int(self.conn.execute(
            f"SELECT COUNT(*) c FROM candidate_evidence_rebuilds WHERE {where} "
            "AND status='queued' AND attempts>0", params,
        ).fetchone()["c"])
        latest = self.conn.execute(
            "SELECT * FROM ("
            f"SELECT candidate_id,input_artifact,error,error_class,attempts,max_attempts,"
            f"updated_utc,'raw_analysis' stage FROM analysis_queue WHERE {where} AND status='failed' "
            "UNION ALL "
            f"SELECT candidate_id,NULL input_artifact,error,NULL error_class,attempts,max_attempts,"
            f"updated_utc,'evidence_rebuild' stage FROM candidate_evidence_rebuilds "
            f"WHERE {where} AND status='failed') failures "
            "ORDER BY updated_utc DESC,candidate_id LIMIT 1",
            (*params, *params),
        ).fetchone()
        return {"counts": counts, "raw_counts": raw_counts,
                "rebuild_counts": rebuild_counts,
                "retrying": raw_retrying + rebuild_retrying,
                "raw_retrying": raw_retrying,
                "rebuild_retrying": rebuild_retrying,
                "latest_failure": dict(latest) if latest else None}


    def campaign_pending_work(self, campaign_id: str,
                              analysis_version: str | None = None) -> bool:
        params: list = [campaign_id]
        analysis_clause = ""
        if analysis_version is not None:
            analysis_clause = " AND analysis_version=?"
            params.append(analysis_version)
        row = self.conn.execute(
            "SELECT 1 FROM jobs WHERE campaign_id=? AND status IN ('queued','leased') "
            "UNION ALL SELECT 1 FROM analysis_queue WHERE campaign_id=? "
            "AND status IN ('queued','leased')" + analysis_clause +
            " UNION ALL SELECT 1 FROM candidate_evidence_rebuilds WHERE campaign_id=? "
            "AND status IN ('queued','leased')" + analysis_clause + " LIMIT 1",
            (campaign_id, campaign_id, *params[1:], campaign_id, *params[1:]),
        ).fetchone()
        return row is not None

    def fleet_has_work(self, analysis_version: str | None = None) -> bool:
        if self.conn.execute(
            "SELECT 1 FROM campaigns WHERE status='active' LIMIT 1"
        ).fetchone() is not None:
            return True
        if analysis_version is None:
            backlog = int(self.conn.execute(
                "SELECT (SELECT COUNT(*) FROM analysis_queue WHERE status IN ('queued','leased')) "
                "+ (SELECT COUNT(*) FROM candidate_evidence_rebuilds "
                "WHERE status IN ('queued','leased')) c"
            ).fetchone()["c"])
        else:
            backlog = self.analysis_backlog(analysis_version)
        return backlog > 0

    def simulation_work_counts(self, ordered: bool = False) -> dict[str, int]:
        from graph_scale_dynamics.scheduling import work_groups
        counts = {"queued": 0, "leased": 0, "blocked": 0}
        now = utc_now()
        rows = self.conn.execute(
            "SELECT c.campaign_id,c.workers_target,"
            "(c.spec_json::jsonb #>> '{study_design,kind}') AS design_kind,"
            "(c.spec_json::jsonb #>> '{study_design,focus,part}') AS focus_part,"
            "COUNT(*) FILTER (WHERE j.status='queued' AND "
            "(j.next_attempt_utc IS NULL OR j.next_attempt_utc<=?)) queued,"
            "COUNT(*) FILTER (WHERE j.status='queued' AND j.priority>=? AND "
            "(j.next_attempt_utc IS NULL OR j.next_attempt_utc<=?)) behind,"
            "COUNT(*) FILTER (WHERE j.status='leased') leased "
            "FROM campaigns c LEFT JOIN jobs j ON j.campaign_id=c.campaign_id "
            "AND j.kind='simulate' AND j.status IN ('queued','leased') "
            "AND EXISTS(SELECT 1 FROM campaign_candidates cc "
            "WHERE cc.campaign_id=j.campaign_id AND cc.candidate_id=j.candidate_id "
            "AND " + runnable_candidate_sql("cc.state") + ") "
            "WHERE c.status='active' GROUP BY c.campaign_id,c.workers_target,c.spec_json",
            (now, work_groups.BEHIND, now, *TERMINAL_STATES),
        ).fetchall()
        rows = [dict(row) for row in rows]
        for row in rows:
            counts["queued"] += int(row["queued"] or 0)
            counts["leased"] += int(row["leased"] or 0)
        found = work_groups.ordered(rows) if ordered else None
        if found is not None:
            counts["tiers"] = {tier: sum(int(row["behind"] or 0) if tier == work_groups.LEFTOVER_TIER
                                         else int(row["queued"] or 0) - int(row["behind"] or 0) for row in first)
                               for tier, first in found}
        return counts

    def analysis_backlog_tiers(self, analysis_version: str) -> dict[int, int]:
        from graph_scale_dynamics.scheduling.work_groups import BEHIND, LEFTOVER_TIER, TIER_SQL
        rows = self.conn.execute(
            f"SELECT (CASE WHEN q.priority>={int(BEHIND)} THEN {int(LEFTOVER_TIER)} ELSE t.tier END) AS tier,"
            "COUNT(*) AS c FROM analysis_queue q "
            f"JOIN (SELECT c.campaign_id, {TIER_SQL} AS tier FROM campaigns c WHERE c.status='active') t "
            "ON t.campaign_id=q.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id AND cc.candidate_id=q.candidate_id "
            "WHERE q.analysis_version=? AND q.status IN ('queued','leased') "
            "AND " + analysis_runnable_candidate_sql("cc.state") + " "
            "AND (q.status='leased' OR q.next_attempt_utc IS NULL OR q.next_attempt_utc<=?) GROUP BY 1",
            (analysis_version, *TERMINAL_STATES, utc_now()),
        ).fetchall()
        return {int(row["tier"]): int(row["c"]) for row in rows}

    def refresh_scheduler_state(self, *, analysis_version: str, total_slots: int,
                                max_analyzers: int, analysis_weight: float = 2.0) -> dict:
        from graph_scale_dynamics.scheduling.allocation import compute_allocation
        work = self.simulation_work_counts(ordered=True)
        whole = backlog = self.analysis_backlog(analysis_version)
        queued = work["queued"]
        if "tiers" in work:
            from graph_scale_dynamics.scheduling.allocation import first_work
            backlog, queued = first_work(work["tiers"], self.analysis_backlog_tiers(analysis_version),
                                         backlog, queued)
        allocation = compute_allocation(
            total_slots=total_slots,
            max_analyzers=max_analyzers,
            analysis_backlog=backlog,
            queued_simulations=queued,
            leased_simulations=work["leased"],
            paused=self.get_flag("paused") == "1",
            analysis_weight=analysis_weight,
        )
        allocation["analysis_backlog"] = whole
        now = utc_now()
        monotonic_now = time.monotonic()
        critical_signature = (bool(allocation["paused"]), int(total_slots), int(max_analyzers))
        publish = (monotonic_now >= self._next_scheduler_publish_at
                   or critical_signature != self._last_scheduler_critical_signature)
        if publish:
            self._next_scheduler_publish_at = monotonic_now + self._scheduler_publish_interval_seconds
            self._last_scheduler_critical_signature = critical_signature
            self.conn.execute(
            "INSERT INTO scheduler_state(singleton,analysis_version,total_slots,analysis_slots,"
            "simulation_slots,analysis_backlog,queued_simulations,leased_simulations,"
            "blocked_simulations,paused,updated_utc) "
            "VALUES(TRUE,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(singleton) DO UPDATE SET analysis_version=excluded.analysis_version,"
            "total_slots=excluded.total_slots,analysis_slots=excluded.analysis_slots,"
            "simulation_slots=excluded.simulation_slots,analysis_backlog=excluded.analysis_backlog,"
            "queued_simulations=excluded.queued_simulations,leased_simulations=excluded.leased_simulations,"
            "blocked_simulations=excluded.blocked_simulations,paused=excluded.paused,"
            "updated_utc=excluded.updated_utc",
                (analysis_version, int(total_slots), int(allocation["analysis_slots"]),
                 int(allocation["simulation_slots"]), int(allocation["analysis_backlog"]),
                 int(work["queued"]), int(work["leased"]), int(work["blocked"]),
                 bool(allocation["paused"]), now),
            )
        return allocation | {"queued_simulations": work["queued"],
                             "leased_simulations": work["leased"],
                             "blocked_simulations": work["blocked"],
                             "updated_utc": now}

    def scheduler_snapshot(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM scheduler_state WHERE singleton=TRUE").fetchone()
        return dict(row) if row else None

    def sync_operational_alerts(self, source: str, findings: list[dict]) -> None:
        self.begin_transaction(attempts=12)
        try:
            now = utc_now()
            keys = []
            for finding in findings:
                key = str(finding["key"])
                keys.append(key)
                self.conn.execute(
                    "INSERT INTO operational_alerts(alert_key,source,severity,category,message,"
                    "detail_json,first_seen_utc,last_seen_utc,occurrences,resolved_utc) "
                    "VALUES(?,?,?,?,?,?,?,?,1,NULL) ON CONFLICT(alert_key) DO UPDATE SET "
                    "source=excluded.source,severity=excluded.severity,category=excluded.category,"
                    "message=excluded.message,detail_json=excluded.detail_json,"
                    "last_seen_utc=excluded.last_seen_utc,"
                    "occurrences=operational_alerts.occurrences+1,resolved_utc=NULL",
                    (key, source, finding["severity"], finding["category"],
                     finding["message"], json.dumps(finding.get("detail") or {}), now, now),
                )
            if keys:
                marks = ",".join("?" for _ in keys)
                self.conn.execute(
                    f"UPDATE operational_alerts SET resolved_utc=? WHERE source=? "
                    f"AND resolved_utc IS NULL AND alert_key NOT IN ({marks})",
                    (now, source, *keys),
                )
            else:
                self.conn.execute(
                    "UPDATE operational_alerts SET resolved_utc=? WHERE source=? "
                    "AND resolved_utc IS NULL", (now, source),
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise

    def operational_alerts(self, *, active_only: bool = True, limit: int = 100) -> list[dict]:
        where = "WHERE resolved_utc IS NULL" if active_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM operational_alerts {where} ORDER BY "
            "CASE severity WHEN 'error' THEN 0 ELSE 1 END,last_seen_utc DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) | {"detail": json.loads(row["detail_json"] or "{}")} for row in rows]

    def claim_analysis_job(self, owner: str, analysis_version: str, lease_seconds: int = 120,
                           campaign_id: str | None = None, max_n: int | None = None,
                           min_n: int | None = None, order: str = "priority",
                           tier_at_most: int | None = None) -> dict | None:
        from graph_scale_dynamics.scheduling.work_groups import BEHIND, LEFTOVER_TIER, TIER_SQL
        expires_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(time.time() + lease_seconds))
        claim_token = secrets.token_hex(16)
        now = utc_now()
        params: list = [analysis_version, now, *TERMINAL_STATES]
        claim_clause = ""
        if campaign_id is not None:
            claim_clause += " AND q.campaign_id=?"
            params.append(campaign_id)
        if max_n is not None:
            claim_clause += " AND q.n<=?"
            params.append(int(max_n))
        if min_n is not None:
            claim_clause += " AND q.n>=?"
            params.append(int(min_n))
        tier = f"(CASE WHEN q.priority>={int(BEHIND)} THEN {int(LEFTOVER_TIER)} ELSE t.tier END)"
        if tier_at_most is not None:
            claim_clause += f" AND {tier}<=?"
            params.append(int(tier_at_most))
        from graph_scale_dynamics.db.decision_store import QUEUE_RANK_STEP
        ordering = tier + "," + (f"q.priority / {QUEUE_RANK_STEP},q.created_utc,q.input_artifact" if order == "oldest"
                                 else "q.priority,q.next_attempt_utc NULLS FIRST,q.updated_utc,q.input_artifact")
        params.extend([owner, claim_token, expires_utc, now])
        row = self.conn.execute(
            "WITH picked AS (SELECT q.campaign_id,q.input_artifact,q.analysis_version "
            "FROM analysis_queue q JOIN campaigns c ON c.campaign_id=q.campaign_id "
            f"JOIN (SELECT c.campaign_id, {TIER_SQL} AS tier FROM campaigns c WHERE c.status='active') t "
            "ON t.campaign_id=q.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id "
            "AND cc.candidate_id=q.candidate_id "
            "WHERE q.analysis_version=? AND q.status='queued' "
            "AND (q.next_attempt_utc IS NULL OR q.next_attempt_utc<=?) "
            "AND q.attempts < q.max_attempts "
            "AND c.status='active' AND c.workers_target IS DISTINCT FROM 0 "
            "AND " + analysis_runnable_candidate_sql("cc.state") + claim_clause + " "
            f"ORDER BY {ordering} "
            "FOR UPDATE OF q SKIP LOCKED LIMIT 1) "
            "UPDATE analysis_queue q SET status='leased',lease_owner=?,claim_token=?,"
            "memory_reservation_bytes=0,"
            "lease_expires_utc=?,attempts=q.attempts+1,next_attempt_utc=NULL,updated_utc=? "
            "FROM picked p WHERE q.campaign_id=p.campaign_id "
            "AND q.input_artifact=p.input_artifact "
            "AND q.analysis_version=p.analysis_version RETURNING q.*",
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        job = self.conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (row["producer_job"],)
        ).fetchone()
        if job is None:
            self.fail_analysis_claim(
                row["campaign_id"], row["input_artifact"], analysis_version, owner,
                claim_token, error="producer job missing", error_class="producer_missing",
                retryable=False, terminal_topic="analysis_failed",
                terminal_payload={"job_id": row["producer_job"],
                                  "campaign_id": row["campaign_id"],
                                  "candidate_id": row["candidate_id"],
                                  "artifact": row["input_artifact"]},
            )
            return None
        return dict(job) | {"spec": json.loads(job["spec_json"]),
                            "analysis_claim_token": claim_token,
                            "analysis_attempt_number": int(row["attempts"]),
                            "analysis_max_attempts": int(row["max_attempts"]),
                            "result_artifact": row["input_artifact"]}

    def record_analysis_attempt(self, analysis_attempt_id: str, *, campaign_id: str,
                                input_artifact: str, analysis_version: str,
                                attempt_number: int, owner: str, claim_token: str) -> None:
        from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
        self._write(
            "INSERT INTO analysis_attempts(analysis_attempt_id,campaign_id,input_artifact,"
            "analysis_version,attempt_number,owner,claim_token,started_utc,build_number,runtime_fingerprint,"
            "memory_reservation_bytes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,(SELECT memory_reservation_bytes FROM analysis_queue "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?)) ON CONFLICT DO NOTHING",
            (analysis_attempt_id, campaign_id, input_artifact, analysis_version,
             int(attempt_number), owner, claim_token, utc_now(), int(BUILD_NUMBER), runtime_fingerprint(),
             campaign_id, input_artifact, analysis_version),
        )

    def close_analysis_attempt(self, analysis_attempt_id: str, *, exit_code: int,
                               wall_seconds: float, peak_rss_bytes: int,
                               error: str | None = None, error_class: str | None = None,
                               resource: dict | None = None) -> None:
        resource = dict(resource or {})
        self._write(
            "UPDATE analysis_attempts SET finished_utc=?,exit_code=?,wall_seconds=?,"
            "peak_rss_bytes=?,peak_uss_bytes=?,peak_pss_bytes=?,error=?,error_class=?,resource_json=? "
            "WHERE analysis_attempt_id=? AND finished_utc IS NULL",
            (utc_now(), int(exit_code), max(0.0, float(wall_seconds)),
             max(0, int(peak_rss_bytes)),
             max(0, int(resource.get("peak_uss_bytes") or 0)),
             max(0, int(resource.get("peak_pss_bytes") or 0)),
             error, error_class, json.dumps(resource), analysis_attempt_id),
        )

    def renew_analysis_claim(self, campaign_id: str, artifact: str, analysis_version: str,
                             owner: str, claim_token: str, lease_seconds: int = 120) -> bool:
        expires_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(time.time() + lease_seconds))
        return self._write(
            "UPDATE analysis_queue SET lease_expires_utc=? WHERE campaign_id=? "
            "AND input_artifact=? AND analysis_version=? AND status='leased' "
            "AND lease_owner=? AND claim_token=?",
            (expires_utc, campaign_id, artifact, analysis_version, owner, claim_token),
        )

    def settle_analysis_memory_reservation(self, campaign_id: str, artifact: str,
                                           analysis_version: str, owner: str,
                                           claim_token: str,
                                           reservation_bytes: int) -> bool:
        return self._write(
            "UPDATE analysis_queue SET memory_reservation_bytes=? "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
            "AND status='leased' AND lease_owner=? AND claim_token=?",
            (max(1, int(reservation_bytes)), campaign_id, artifact,
             analysis_version, owner, claim_token),
        )

    def release_analysis_claim(self, campaign_id: str, artifact: str, analysis_version: str,
                               owner: str, claim_token: str,
                               defer_seconds: int | None = None) -> bool:
        now = utc_now()
        next_attempt = None
        if defer_seconds is not None and int(defer_seconds) > 0:
            next_attempt = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(defer_seconds))
            )
        return self._write(
            "UPDATE analysis_queue SET status=CASE WHEN EXISTS (SELECT 1 FROM campaigns c "
            "JOIN campaign_candidates cc ON cc.campaign_id=analysis_queue.campaign_id "
            "AND cc.candidate_id=analysis_queue.candidate_id "
            "WHERE c.campaign_id=analysis_queue.campaign_id AND c.status='active' "
            "AND " + analysis_runnable_candidate_sql("cc.state") + ") THEN 'queued' ELSE 'cancelled' END,"
            "lease_owner=NULL,claim_token=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
            "next_attempt_utc=CASE WHEN EXISTS (SELECT 1 FROM campaigns c "
            "JOIN campaign_candidates cc ON cc.campaign_id=analysis_queue.campaign_id "
            "AND cc.candidate_id=analysis_queue.candidate_id "
            "WHERE c.campaign_id=analysis_queue.campaign_id AND c.status='active' "
            "AND " + analysis_runnable_candidate_sql("cc.state") + ") THEN ? ELSE NULL END,"
            "attempts=GREATEST(0,attempts-1),updated_utc=? WHERE campaign_id=? "
            "AND input_artifact=? AND analysis_version=? AND status='leased' "
            "AND lease_owner=? AND claim_token=?",
            (*TERMINAL_STATES, *TERMINAL_STATES, next_attempt, now, campaign_id, artifact,
             analysis_version, owner, claim_token),
        )

    def fail_analysis_claim(self, campaign_id: str, artifact: str, analysis_version: str,
                            owner: str, claim_token: str, *, error: str,
                            error_class: str, retryable: bool,
                            base_backoff_seconds: int = 5,
                            terminal_topic: str | None = None,
                            terminal_payload: dict | None = None) -> dict | None:
        if str(error_class).endswith("no_space_left"):
            back = self.release_analysis_claim(campaign_id, artifact, analysis_version, owner, claim_token,
                                               defer_seconds=60)
            return {"status": "queued", "retry": True, "attempts": 0, "max_attempts": 0} if back else None
        self.begin_transaction(attempts=12)
        try:
            row = self.conn.execute(
                "SELECT attempts,max_attempts FROM analysis_queue WHERE campaign_id=? "
                "AND input_artifact=? AND analysis_version=? AND status='leased' "
                "AND lease_owner=? AND claim_token=? FOR UPDATE",
                (campaign_id, artifact, analysis_version, owner, claim_token),
            ).fetchone()
            if row is None:
                self.conn.rollback_if_open()
                return None
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            retry = bool(retryable and attempts < max_attempts)
            status = "queued" if retry else "failed"
            next_attempt = None
            if retry:
                delay = min(300, max(1, int(base_backoff_seconds)) * (2 ** max(0, attempts - 1)))
                next_attempt = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + delay)
                )
            changed = self.conn.execute(
                "UPDATE analysis_queue SET status=?,lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=?,error=?,error_class=?,updated_utc=? "
                "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=?",
                (status, next_attempt, error[:4000], error_class[:100], utc_now(),
                 campaign_id, artifact, analysis_version, owner, claim_token),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return None
            if not retry and terminal_topic:
                payload = dict(terminal_payload or {})
                payload.update({"artifact": artifact, "campaign_id": campaign_id,
                                "retry": False, "status": status, "error": error,
                                "error_class": error_class, "attempts": attempts,
                                "max_attempts": max_attempts})
                self.conn.execute(
                    "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                    (terminal_topic, json.dumps(payload), utc_now()),
                )
            self.conn.execute("COMMIT")
            return {"status": status, "retry": retry, "attempts": attempts,
                    "max_attempts": max_attempts, "next_attempt_utc": next_attempt,
                    "error_class": error_class}
        except Exception:
            self.conn.rollback_if_open()
            raise

    def stop_analysis_at_resource_boundary(
            self, *, campaign_id: str, input_artifact: str, analysis_version: str,
            owner: str, claim_token: str, peak_rss_bytes: int, wall_seconds: float,
            hard_limit_bytes: int, error: str,
            peak_uss_bytes: int | None = None,
            peak_pss_bytes: int | None = None, requeue: bool = False) -> bool:
        from graph_scale_dynamics.db.repo_jobs import RUNAWAY_REQUEUE_SECONDS
        from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_MEMORY_RUNAWAY
        self.begin_transaction(attempts=12)
        try:
            row = self.conn.execute(
                "SELECT candidate_id FROM analysis_queue WHERE campaign_id=? "
                "AND input_artifact=? AND analysis_version=? AND status='leased' "
                "AND lease_owner=? AND claim_token=? FOR UPDATE",
                (campaign_id, input_artifact, analysis_version, owner, claim_token),
            ).fetchone()
            if row is None:
                self.conn.rollback_if_open()
                return False
            now = utc_now()
            again = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + RUNAWAY_REQUEUE_SECONDS))
            changed = self.conn.execute(
                "UPDATE analysis_queue SET status=?,lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=?,error=?,error_class=?,"
                "wall_seconds=GREATEST(COALESCE(wall_seconds,0),?),"
                "peak_rss_bytes=GREATEST(COALESCE(peak_rss_bytes,0),?),"
                "peak_uss_bytes=GREATEST(COALESCE(peak_uss_bytes,0),?),"
                "peak_pss_bytes=GREATEST(COALESCE(peak_pss_bytes,0),?),updated_utc=? "
                "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=?",
                ("queued" if requeue else "failed", again if requeue else None, error[:4000],
                 ATTEMPT_CLASS_MEMORY_RUNAWAY if requeue else "memory_hard_cap", max(0.0, float(wall_seconds)),
                 max(0, int(peak_rss_bytes)), max(0, int(peak_uss_bytes or 0)),
                 max(0, int(peak_pss_bytes or 0)), now, campaign_id, input_artifact,
                 analysis_version, owner, claim_token),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return False
            if requeue:
                self.conn.execute("COMMIT")
                return True
            self.conn.execute(
                "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                ("analysis_ready", json.dumps({
                    "campaign_id": campaign_id,
                    "candidate_id": row["candidate_id"],
                    "resource_hard_stop": True,
                    "phase": "analysis",
                    "artifact": input_artifact,
                    "observed_peak_rss_bytes": int(peak_rss_bytes),
                    "hard_limit_bytes": int(hard_limit_bytes),
                }), now),
            )
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.rollback_if_open()
            raise

    def commit_analysis_result(self, *, campaign_id: str, input_artifact: str,
                               analysis_version: str, owner: str, claim_token: str,
                               curves_digest: str, curves_size: int, producer_job: str,
                               analysis_id: str, candidate_id: str, n: int, seed: int,
                               metrics: dict, wall_seconds: float | None = None,
                               peak_rss_bytes: int | None = None,
                               peak_uss_bytes: int | None = None,
                               peak_pss_bytes: int | None = None,
                               provenance_status: str | None = None,
                               provenance_detail: dict | None = None) -> bool:
        self.begin_transaction(attempts=12)
        try:
            if not self.lock_candidate(campaign_id, candidate_id):
                self.conn.rollback_if_open()
                return False
            claim = self.conn.execute(
                "SELECT 1 FROM analysis_queue WHERE campaign_id=? AND input_artifact=? "
                "AND analysis_version=? AND status='leased' AND lease_owner=? "
                "AND claim_token=? FOR UPDATE",
                (campaign_id, input_artifact, analysis_version, owner, claim_token),
            ).fetchone()
            if claim is None:
                self.conn.rollback_if_open()
                return False
            now = utc_now()
            self.conn.execute(
                "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,"
                "meta_json,created_utc) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (curves_digest, curves_size, "application/json", producer_job,
                 json.dumps({"schema": "analysis-curves-v1",
                             "analysis_version": analysis_version}), now),
            )
            self.conn.execute(
                "INSERT INTO artifact_producers(artifact_hash,job_id,role,created_utc) "
                "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                (curves_digest, producer_job, "analysis", now),
            )
            fault_hit("analysis.after_artifact_before_measurement")
            self.conn.execute(
                "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,"
                "analysis_version,input_artifact,metrics_json,curves_artifact,created_utc,"
                "probe_seconds_d_s,probe_seconds_d_v,probe_seconds_d_b,probe_seconds_d_w) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (campaign_id, analysis_id, candidate_id, int(n), int(seed), analysis_version,
                 input_artifact, json.dumps(metrics), curves_digest, now,
                 *_probe_seconds_columns(metrics)),
            )
            fault_hit("analysis.after_measurement_before_audit")
            if provenance_status is not None:
                self.conn.execute(
                    "INSERT INTO evidence_audits(campaign_id,artifact_hash,candidate_id,status,"
                    "detail_json,audited_utc) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(campaign_id,artifact_hash) DO UPDATE SET "
                    "candidate_id=excluded.candidate_id,status=excluded.status,"
                    "detail_json=excluded.detail_json,audited_utc=excluded.audited_utc",
                    (campaign_id, input_artifact, candidate_id, provenance_status,
                     json.dumps(provenance_detail or {}), now),
                )
            revision = self.conn.execute(
                "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') newest FROM measurements "
                "WHERE campaign_id=? AND candidate_id=? AND analysis_version=?",
                (campaign_id, candidate_id, analysis_version),
            ).fetchone()
            self.conn.execute(
                "INSERT INTO candidate_evidence_rebuilds(campaign_id,candidate_id,analysis_version,"
                "status,requested_measurement_count,requested_newest_utc,created_utc,updated_utc) "
                "VALUES(?,?,?,'queued',?,?,?,?) "
                "ON CONFLICT(campaign_id,candidate_id,analysis_version) DO UPDATE SET "
                "requested_measurement_count=excluded.requested_measurement_count,"
                "requested_newest_utc=excluded.requested_newest_utc,"
                "status=CASE WHEN candidate_evidence_rebuilds.status='leased' "
                "THEN 'leased' ELSE 'queued' END,"
                "next_attempt_utc=NULL,error=NULL,updated_utc=excluded.updated_utc",
                (campaign_id, candidate_id, analysis_version, int(revision["c"]),
                 revision["newest"], now, now),
            )
            fault_hit("analysis.after_rebuild_enqueue_before_queue_done")
            changed = self.conn.execute(
                "UPDATE analysis_queue SET status='done',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,error_class=NULL,"
                "wall_seconds=GREATEST(COALESCE(wall_seconds,0),?),"
                "peak_rss_bytes=GREATEST(COALESCE(peak_rss_bytes,0),?),"
                "peak_uss_bytes=GREATEST(COALESCE(peak_uss_bytes,0),?),"
                "peak_pss_bytes=GREATEST(COALESCE(peak_pss_bytes,0),?),updated_utc=? WHERE campaign_id=? "
                "AND input_artifact=? AND analysis_version=? AND status='leased' "
                "AND lease_owner=? AND claim_token=?",
                (None if wall_seconds is None else max(0.0, float(wall_seconds)),
                 None if peak_rss_bytes is None else max(0, int(peak_rss_bytes)),
                 None if peak_uss_bytes is None else max(0, int(peak_uss_bytes)),
                 None if peak_pss_bytes is None else max(0, int(peak_pss_bytes)),
                 now, campaign_id, input_artifact, analysis_version, owner, claim_token),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return False
            fault_hit("analysis.after_queue_done_before_commit")
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.rollback_if_open()
            raise
