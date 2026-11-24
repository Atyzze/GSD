from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, utc_now
from graph_scale_dynamics.observability.faults import hit as fault_hit


class CandidateStore:
    def insert_candidate(self, candidate_id: str, campaign_id: str, spec: dict, dynamics: str,
                         complexity: int, state: str, lineage_parent: str | None = None,
                         *, unfiltered: bool = False) -> None:
        now = utc_now()
        spec_json = json.dumps(spec)
        from graph_scale_dynamics.db.law_columns import LAW_COLUMNS, law_columns
        self.begin_transaction(attempts=12)
        try:
            self.conn.execute(
                f"INSERT INTO candidate_specs(candidate_id,spec_json,dynamics,complexity,created_utc,{LAW_COLUMNS}) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (candidate_id, spec_json, dynamics, complexity, now, *law_columns(spec)))
            existing = self.conn.execute(
                "SELECT spec_json FROM candidate_specs WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if existing is None:
                raise RuntimeError("candidate insert did not become visible")
            if json.loads(existing["spec_json"]) != spec:
                raise ValueError("candidate id collision: stored specification differs")
            self.conn.execute(
                "INSERT INTO campaign_candidates(campaign_id,candidate_id,candidate_number,"
                "lineage_parent,state,created_utc,updated_utc,unfiltered) "
                "SELECT ?,?,COALESCE(MAX(candidate_number),0)+1,?,?,?,?,? "
                "FROM campaign_candidates WHERE campaign_id=? "
                "ON CONFLICT (campaign_id, candidate_id) DO NOTHING",
                (campaign_id, candidate_id, lineage_parent, state, now, now, bool(unfiltered),
                 campaign_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.rollback_if_open()
            raise

    def _resolve_campaign_for_candidate(self, candidate_id: str, campaign_id: str | None) -> str | None:
        if campaign_id is not None:
            return campaign_id
        rows = self.conn.execute(
            "SELECT campaign_id FROM campaign_candidates WHERE candidate_id=? ORDER BY created_utc",
            (candidate_id,),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["campaign_id"]
        return None

    def set_candidate_state(self, candidate_id: str, state: str, reason: str = "",
                            campaign_id: str | None = None, *, only_from=None) -> bool:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            raise ValueError("candidate membership is ambiguous; campaign_id is required")
        if only_from is not None:
            allowed = sorted({str(s) for s in only_from})
            if not allowed:
                return False
            return self._write(
                "UPDATE campaign_candidates SET state=?,state_reason=?,updated_utc=? "
                f"WHERE campaign_id=? AND candidate_id=? AND state<>? AND state IN ({','.join('?' for _ in allowed)})",
                (state, reason, utc_now(), resolved, candidate_id, state, *allowed),
            )
        return self._write(
            "UPDATE campaign_candidates SET state=?,state_reason=?,updated_utc=? "
            "WHERE campaign_id=? AND candidate_id=?",
            (state, reason, utc_now(), resolved, candidate_id),
        )

    def _terminalize_candidate_in_transaction(self, campaign_id: str, candidate_id: str,
                                              state: str, reason: str, *, leave_parked: bool = False) -> dict:
        if state not in TERMINAL_CANDIDATE_STATES:
            raise ValueError(f"candidate terminal state required, got {state!r}")
        row = self.conn.execute(
            "SELECT state FROM campaign_candidates WHERE campaign_id=? AND candidate_id=? FOR UPDATE",
            (campaign_id, candidate_id),
        ).fetchone()
        if row is None:
            return {"found": False, "state_changed": 0, "jobs_cancelled": 0,
                    "analysis_cancelled": 0, "state": None}
        current = row["state"]
        changed = 0
        final_state = current
        if current not in TERMINAL_CANDIDATE_STATES or (leave_parked and current == "PARKED" and state != current):
            changed = self.conn.execute(
                "UPDATE campaign_candidates SET state=?,state_reason=?,updated_utc=? "
                "WHERE campaign_id=? AND candidate_id=?",
                (state, reason, utc_now(), campaign_id, candidate_id),
            ).rowcount
            final_state = state
        fault_hit("terminal.after_state_before_cancel")
        jobs = self.conn.execute(
            "UPDATE jobs SET status='cancelled',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
            "lease_generation=lease_generation+CASE WHEN status='leased' THEN 1 ELSE 0 END,"
            "updated_utc=?,error=COALESCE(error,?) WHERE campaign_id=? AND candidate_id=? "
            "AND status IN ('queued','leased')",
            (utc_now(), reason, campaign_id, candidate_id),
        ).rowcount
        analyses = self.conn.execute(
            "UPDATE analysis_queue SET status='cancelled',lease_owner=NULL,claim_token=NULL,"
            "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=COALESCE(error,?),"
            "error_class=COALESCE(error_class,'candidate_terminal'),updated_utc=? "
            "WHERE campaign_id=? AND candidate_id=? AND status IN ('queued','leased')",
            (reason, utc_now(), campaign_id, candidate_id),
        ).rowcount
        analyses += self.conn.execute(
            "UPDATE candidate_evidence_rebuilds SET status='cancelled',lease_owner=NULL,"
            "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,"
            "error=COALESCE(error,?),updated_utc=? WHERE campaign_id=? AND candidate_id=? "
            "AND status IN ('queued','leased')",
            (reason, utc_now(), campaign_id, candidate_id),
        ).rowcount
        fault_hit("terminal.after_cancel_before_commit")
        return {"found": True, "state_changed": int(changed),
                "jobs_cancelled": int(jobs), "analysis_cancelled": int(analyses),
                "state": final_state}

    def terminalize_candidate(self, campaign_id: str, candidate_id: str,
                              state: str, reason: str, *, emit: bool = True, leave_parked: bool = False) -> dict:
        owns = not self.conn.in_transaction
        if owns:
            self.begin_transaction(attempts=12)
        try:
            result = self._terminalize_candidate_in_transaction(
                campaign_id, candidate_id, state, reason, leave_parked=leave_parked
            )
            if emit and result["found"] and (result["state_changed"] or
                                               result["jobs_cancelled"] or
                                               result["analysis_cancelled"]):
                self.conn.execute(
                    "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                    ("candidate_terminalized", json.dumps({
                        "campaign_id": campaign_id, "candidate_id": candidate_id,
                        "state": result["state"], "reason": reason,
                        "jobs_cancelled": result["jobs_cancelled"],
                        "analysis_cancelled": result["analysis_cancelled"],
                    }), utc_now()),
                )
            if owns:
                self.conn.execute("COMMIT")
            return result
        except Exception:
            if owns:
                self.conn.rollback_if_open()
            raise

    def quarantine_candidate_identity(self, candidate_id: str, reason: str) -> int:
        self.begin_transaction(attempts=12)
        try:
            memberships = self.conn.execute(
                "SELECT campaign_id FROM campaign_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchall()
            changed = self.conn.execute(
                "UPDATE campaign_candidates SET state='QUARANTINE',state_reason=?,updated_utc=? "
                "WHERE candidate_id=? AND state!='QUARANTINE'",
                (reason, utc_now(), candidate_id),
            ).rowcount
            self.conn.execute(
                "UPDATE jobs SET status='cancelled',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
                "lease_generation=lease_generation+CASE WHEN status='leased' THEN 1 ELSE 0 END,"
                "updated_utc=?,error=? WHERE candidate_id=? AND status IN ('queued','leased')",
                (utc_now(), reason, candidate_id),
            )
            self.conn.execute(
                "UPDATE analysis_queue SET status='cancelled',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=?,error_class='identity',"
                "updated_utc=? WHERE candidate_id=? AND status IN ('queued','leased')",
                (reason, utc_now(), candidate_id),
            )
            self.conn.execute(
                "UPDATE candidate_evidence_rebuilds SET status='cancelled',lease_owner=NULL,"
                "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=NULL,error=?,"
                "updated_utc=? WHERE candidate_id=? AND status IN ('queued','leased')",
                (reason, utc_now(), candidate_id),
            )
            for row in memberships:
                payload = {"campaign_id": row["campaign_id"], "candidate_id": candidate_id,
                           "error": reason, "retry": False}
                self.conn.execute(
                    "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                    ("integrity_failure", json.dumps(payload), utc_now()),
                )
            self.conn.execute("COMMIT")
            return int(changed)
        except Exception:
            self.conn.rollback_if_open()
            raise

    def candidate(self, candidate_id: str, campaign_id: str | None = None) -> dict | None:
        if campaign_id is None:
            rows = self.conn.execute(
                "SELECT * FROM candidates WHERE candidate_id=? ORDER BY created_utc", (candidate_id,)
            ).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
        else:
            row = self.conn.execute(
                "SELECT * FROM candidates WHERE campaign_id=? AND candidate_id=?",
                (campaign_id, candidate_id),
            ).fetchone()
        return dict(row) | {"spec": json.loads(row["spec_json"])} if row else None

    def candidate_campaign_ids(self, candidate_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT campaign_id FROM campaign_candidates WHERE candidate_id=? "
            "UNION SELECT campaign_id FROM candidates WHERE candidate_id=? "
            "ORDER BY campaign_id",
            (str(candidate_id), str(candidate_id)),
        ).fetchall()
        return [str(row["campaign_id"]) for row in rows]

    def candidates(self, campaign_id: str | None = None) -> list[dict]:
        if campaign_id:
            rows = self.conn.execute(
                "SELECT * FROM candidates WHERE campaign_id=? ORDER BY created_utc", (campaign_id,)
            )
        else:
            rows = self.conn.execute("SELECT * FROM candidates ORDER BY created_utc")
        return [dict(r) | {"spec": json.loads(r["spec_json"])} for r in rows]

    def candidates_in_states(self, campaign_id: str, states: set[str] | tuple[str, ...] | list[str],
                             *, limit: int | None = None) -> list[dict]:
        ordered = tuple(sorted(set(str(state) for state in states)))
        if not ordered:
            return []
        marks = ",".join("?" for _ in ordered)
        sql = (
            f"SELECT * FROM candidates WHERE campaign_id=? AND state IN ({marks}) "
            "ORDER BY admission_sequence"
        )
        params: list[object] = [campaign_id, *ordered]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) | {"spec": json.loads(r["spec_json"])} for r in rows]

    def candidate_state_history(self, campaign_id: str, candidate_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT state_event_id,old_state,new_state,old_reason,new_reason,source,created_utc "
            "FROM candidate_state_history WHERE campaign_id=? AND candidate_id=? "
            "ORDER BY state_event_id",
            (campaign_id, candidate_id),
        ).fetchall()
        return [dict(row) | {
            "previous_state": row.get("old_state"),
            "reason": row.get("new_reason"),
        } for row in rows]

    def candidate_state_counts(self, campaign_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT state,COUNT(*) c FROM candidates WHERE campaign_id=? GROUP BY state",
            (campaign_id,),
        ).fetchall()
        return {row["state"]: int(row["c"]) for row in rows}

    def campaign_analysis_contract(self, campaign_id: str) -> str:
        from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
        row = self.conn.execute(
            "SELECT spec_json FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if row is not None:
            declared = str((json.loads(row["spec_json"]) or {}).get("analysis_version") or "")
            if declared:
                return declared
        observed = self.latest_analysis_version(campaign_id)
        return str(observed) if observed else ANALYSIS_VERSION

    def latest_analysis_version(self, campaign_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(analysis_version) AS version FROM rung_summaries WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        return row["version"] if row and row["version"] else None

    def campaign_rung_summaries(self, campaign_id: str, analysis_version: str) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        rows = self.conn.execute(
            "SELECT * FROM rung_summaries WHERE campaign_id=? AND analysis_version=? "
            "ORDER BY candidate_id,n", (campaign_id, analysis_version)
        ).fetchall()
        for row in rows:
            item = dict(row) | {"summary": json.loads(row["summary_json"])}
            grouped.setdefault(row["candidate_id"], []).append(item)
        return grouped

    def stranded_candidates(self, campaign_id: str, analysis_version: str,
                            *, states: tuple[str, ...] | None = None,
                            limit: int = 500) -> list[dict]:
        from graph_scale_dynamics.db.decision_store import held_sql
        from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES
        active_states = tuple(states or sorted(RUNNING_CANDIDATE_STATES))
        placeholders = ",".join("?" for _ in active_states)
        rows = self.conn.execute(
            "SELECT w.*,COUNT(*) FILTER (WHERE w.held) OVER () AS held_total FROM ("
            f"SELECT c.candidate_id,c.state,c.updated_utc,{held_sql('c')} AS held "
            "FROM candidates c WHERE c.campaign_id=? "
            f"AND c.state IN ({placeholders}) "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.campaign_id=c.campaign_id "
            " AND j.candidate_id=c.candidate_id AND j.status IN ('queued','leased')) "
            "AND NOT EXISTS (SELECT 1 FROM analysis_queue a WHERE a.campaign_id=c.campaign_id "
            " AND a.candidate_id=c.candidate_id AND a.analysis_version=? "
            " AND a.status IN ('queued','leased')) "
            "AND NOT EXISTS (SELECT 1 FROM candidate_evidence_rebuilds r "
            "  WHERE r.campaign_id=c.campaign_id AND r.candidate_id=c.candidate_id "
            " AND r.analysis_version=? AND r.status IN ('queued','leased'))"
            ") w ORDER BY w.held,w.updated_utc LIMIT ?",
            (str(campaign_id), *active_states, str(analysis_version),
             str(analysis_version), int(max(1, limit))),
        ).fetchall()
        return [{"candidate_id": str(row["candidate_id"]), "state": row["state"],
                 "updated_utc": row["updated_utc"], "held": bool(row["held"]),
                 "held_total": int(row["held_total"] or 0)} for row in rows]

    def proposal_assessments(self, campaign_id: str,
                             candidate_id: str | None = None) -> list[dict]:
        if candidate_id is None:
            rows = self.conn.execute(
                "SELECT * FROM proposal_assessments WHERE campaign_id=? "
                "ORDER BY created_utc,candidate_id", (campaign_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM proposal_assessments WHERE campaign_id=? AND candidate_id=? "
                "ORDER BY created_utc", (campaign_id, candidate_id),
            ).fetchall()
        return [dict(row) | {"assessment": json.loads(row["assessment_json"])}
                for row in rows]

    def active_analysis_claims(self) -> int:
        now = utc_now()
        return int(self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM analysis_queue WHERE status='leased' "
            "AND lease_expires_utc>=?) + (SELECT COUNT(*) FROM candidate_evidence_rebuilds "
            "WHERE status='leased' AND lease_expires_utc>=?) c", (now, now)
        ).fetchone()["c"])

    def unfiltered_candidate_ids(self, campaign_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=? AND unfiltered",
            (str(campaign_id),),
        ).fetchall()
        return {str(row["candidate_id"]) for row in rows}
