from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import content_hash, interrupted_sql, utc_now
from graph_scale_dynamics.db.repo_shared import analyzer_identity


class RecordStore:
    def active_staging_names(self) -> set[str]:
        names: set[str] = set()
        simulation_rows = self.conn.execute(
            "SELECT job_id,attempts,lease_generation FROM jobs WHERE status='leased'"
        ).fetchall()
        for row in simulation_rows:
            names.add(content_hash({
                "job": row["job_id"],
                "attempt": int(row["attempts"]),
                "lease_generation": int(row["lease_generation"]),
            })[:24])
        analysis_rows = self.conn.execute(
            "SELECT campaign_id,input_artifact,lease_owner,claim_token FROM analysis_queue "
            "WHERE status='leased' AND lease_owner IS NOT NULL AND claim_token IS NOT NULL"
        ).fetchall()
        for row in analysis_rows:
            token = content_hash({
                "owner": row["lease_owner"],
                "campaign": row["campaign_id"],
                "artifact": row["input_artifact"],
                "claim": row["claim_token"],
            })[:24]
            names.add("analysis-" + token)
        return names

    def register_external_artifact(self, digest: str, size: int, media_type: str,
                                   meta: dict | None = None) -> None:
        self._write(
            "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (digest, max(0, int(size)), media_type, None, json.dumps(meta or {}, sort_keys=True), utc_now()),
        )

    def auxiliary_attempts(self, campaign_id: str, work_kind: str | None = None) -> list[dict]:
        if work_kind is None:
            rows = self.conn.execute(
                "SELECT * FROM auxiliary_attempts WHERE campaign_id=? "
                "ORDER BY started_utc,auxiliary_attempt_id", (str(campaign_id),)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM auxiliary_attempts WHERE campaign_id=? AND work_kind=? "
                "ORDER BY started_utc,auxiliary_attempt_id",
                (str(campaign_id), str(work_kind)),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            out.append(item)
        return out

    def compute_ledger(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM compute_ledger WHERE campaign_id=? "
            "ORDER BY started_utc,work_id", (str(campaign_id),)
        ).fetchall()
        return [dict(row) for row in rows]

    def record_resource_telemetry(self, sample: dict) -> None:
        self._write(
            "INSERT INTO resource_telemetry("
            "campaign_id,telemetry_contract,build_number,runtime_fingerprint,environment_fingerprint,sampled_utc,phase,interval_seconds,"
            "cpu_percent,gsd_cpu_percent,external_cpu_percent_estimate,"
            "cpu_package_watts,cpu_power_limit_watts,cpu_temperature_celsius,"
            "cpu_frequency_mhz,memory_total_bytes,memory_used_bytes,memory_free_bytes,"
            "memory_bandwidth_json,active_simulations,active_analyses,active_work_json,"
            "quality,source_json,interval_energy_j,active_slot_limit,governor_phase,calibration_id,"
            "aggregated_samples,window_seconds,window_started_utc,aggregation_contract,power_samples_json,"
            "cpu_temperature_max_celsius"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sample["campaign_id"], sample["telemetry_contract"], int(sample["build_number"]),
                sample["runtime_fingerprint"], sample["environment_fingerprint"], sample["sampled_utc"],
                sample["phase"], sample.get("interval_seconds"), sample.get("cpu_percent"),
                sample.get("gsd_cpu_percent"), sample.get("external_cpu_percent_estimate"),
                sample.get("cpu_package_watts"), sample.get("cpu_power_limit_watts"),
                sample.get("cpu_temperature_celsius"), sample.get("cpu_frequency_mhz"),
                sample.get("memory_total_bytes"), sample.get("memory_used_bytes"),
                sample.get("memory_free_bytes"), json.dumps(sample.get("memory_bandwidth")),
                int(sample.get("active_simulations") or 0), int(sample.get("active_analyses") or 0),
                json.dumps(sample.get("active_work") or [], sort_keys=True),
                str(sample.get("quality") or "unknown_interference"),
                json.dumps(sample.get("source") or {}, sort_keys=True),
                sample.get("interval_energy_j"),
                sample.get("active_slot_limit"), sample.get("governor_phase"),
                sample.get("calibration_id"),
                max(1, int(sample.get("aggregated_samples") or 1)),
                sample.get("window_seconds"),
                sample.get("window_started_utc"),
                sample.get("aggregation_contract"),
                json.dumps(sample.get("power_samples") or [], separators=(",", ":")),
                sample.get("cpu_temperature_max_celsius"),
            ),
        )

    def record_report_cycle(self, row: dict) -> None:
        self._write(
            "INSERT INTO report_cycles(cycle_id,campaign_id,build_number,started_utc,"
            "finished_utc,total_seconds,snapshot_seconds,report_seconds_json,"
            "snapshot_decompressed_bytes,api_bytes_transferred,trigger_source,cycle_state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(cycle_id) DO UPDATE SET "
            "finished_utc=EXCLUDED.finished_utc,total_seconds=EXCLUDED.total_seconds,"
            "snapshot_seconds=EXCLUDED.snapshot_seconds,"
            "report_seconds_json=EXCLUDED.report_seconds_json,"
            "snapshot_decompressed_bytes=EXCLUDED.snapshot_decompressed_bytes,"
            "api_bytes_transferred=EXCLUDED.api_bytes_transferred,"
            "trigger_source=EXCLUDED.trigger_source,cycle_state=EXCLUDED.cycle_state",
            (str(row["cycle_id"]), str(row.get("campaign_id") or ""), row.get("build_number"),
             str(row["started_utc"]), row.get("finished_utc"),
             row.get("total_seconds"), row.get("snapshot_seconds"),
             json.dumps(row.get("report_seconds") or {}, sort_keys=True),
             row.get("snapshot_decompressed_bytes"), row.get("api_bytes_transferred"),
             row.get("trigger_source"), row.get("cycle_state")),
        )

    def report_cycles(self, campaign_id: str, *, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM report_cycles WHERE campaign_id=? "
            "ORDER BY started_utc DESC LIMIT ?",
            (str(campaign_id), max(1, int(limit))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["report_seconds"] = json.loads(item.pop("report_seconds_json") or "{}")
            except (TypeError, ValueError):
                item["report_seconds"] = {}
            result.append(item)
        return result

    def resource_governor_events(self, campaign_id: str, *, limit: int = 1000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM resource_governor_events WHERE campaign_id=? "
            "ORDER BY governor_event_id DESC LIMIT ?", (campaign_id, max(1, int(limit))),
        ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except (TypeError, ValueError):
                item["detail"] = {}
                item.pop("detail_json", None)
            result.append(item)
        return result

    def resource_telemetry(self, campaign_id: str, *, since_utc: str | None = None,
                           expand_aggregates: bool = True) -> list[dict]:
        if since_utc:
            rows = self.conn.execute(
                "SELECT * FROM resource_telemetry WHERE campaign_id=? AND sampled_utc>=? "
                "ORDER BY sampled_utc,sample_id", (campaign_id, since_utc),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM resource_telemetry WHERE campaign_id=? "
                "ORDER BY sampled_utc,sample_id", (campaign_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["memory_bandwidth"] = json.loads(item.pop("memory_bandwidth_json") or "null")
            except (TypeError, ValueError):
                item["memory_bandwidth"] = None
                item.pop("memory_bandwidth_json", None)
            try:
                item["active_work"] = json.loads(item.pop("active_work_json") or "[]")
            except (TypeError, ValueError):
                item["active_work"] = []
                item.pop("active_work_json", None)
            try:
                item["source"] = json.loads(item.pop("source_json") or "{}")
            except (TypeError, ValueError):
                item["source"] = {}
                item.pop("source_json", None)
            try:
                power_samples = json.loads(item.pop("power_samples_json") or "[]")
            except (TypeError, ValueError):
                power_samples = []
                item.pop("power_samples_json", None)
            count = max(1, int(item.get("aggregated_samples") or 1))
            item["power_samples"] = power_samples
            if not expand_aggregates or count <= 1:
                result.append(item)
                continue
            from graph_scale_dynamics.observability.telemetry_aggregation import expand_aggregate_row
            result.extend(expand_aggregate_row(item))
        return result

    def rung_attempt_durations(self, campaign_id: str) -> dict[tuple[int, float], list[dict]]:
        rows = self.conn.execute(
            "SELECT j.n AS n, j.exec_sweeps_multiplier AS multiplier, a.wall_seconds AS wall_seconds, "
            "a.exit_code AS exit_code, a.job_id AS job_id, a.number AS number "
            "FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=? AND j.kind='simulate' AND a.wall_seconds IS NOT NULL "
            f"AND NOT {interrupted_sql('a')}",
            (campaign_id,),
        ).fetchall()
        out: dict[tuple[int, float], list[dict]] = {}
        for row in rows:
            multiplier = float(row["multiplier"] or 1)
            out.setdefault((int(row["n"]), multiplier), []).append(
                {"wall_seconds": row["wall_seconds"], "exit_code": row["exit_code"],
                 "job_id": row["job_id"], "number": row["number"]})
        return out

    def interrupted_run_seconds(self, campaign_id: str) -> dict[str, float]:
        return {str(row["job_id"]): float(row["s"] or 0.0) for row in self.conn.execute(
            "SELECT a.job_id AS job_id,COALESCE(SUM(a.wall_seconds),0) AS s FROM attempts a "
            "JOIN jobs j ON j.job_id=a.job_id WHERE j.campaign_id=? AND j.kind='simulate' "
            f"AND {interrupted_sql('a')} GROUP BY a.job_id", (str(campaign_id),)).fetchall()}

    def resumed_run_seconds(self, campaign_id: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in self.conn.execute(
                "SELECT j.job_id,m.metrics_json FROM jobs j JOIN measurements m ON m.campaign_id=j.campaign_id "
                "AND m.input_artifact=j.result_artifact WHERE j.campaign_id=? AND j.kind='simulate' "
                f"AND EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.job_id AND {interrupted_sql('a')})",
                (str(campaign_id),)).fetchall():
            try:
                metrics = json.loads(row["metrics_json"])
            except (TypeError, ValueError):
                continue
            terminal = (((metrics.get("health") or {}).get("rung_terminal") or {})
                        if isinstance(metrics, dict) else {})
            seconds = terminal.get("wall_seconds")
            if (terminal.get("resumed") and isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
                    and seconds > 0):
                out[str(row["job_id"])] = max(float(seconds), out.get(str(row["job_id"]), 0.0))
        return out

    def dashboard_rung_job_states(self, campaign_id: str,
                                  candidate_ids: list[str]) -> dict[str, list[dict]]:
        if not candidate_ids:
            return {}
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = self.conn.execute(
            f"SELECT candidate_id,n,status,error,updated_utc FROM jobs "
            f"WHERE campaign_id=? AND kind='simulate' "
            f"AND candidate_id IN ({placeholders})",
            (campaign_id, *candidate_ids),
        ).fetchall()
        out: dict[str, list[dict]] = {}
        for row in rows:
            out.setdefault(str(row["candidate_id"]), []).append(
                {"n": int(row["n"]), "status": str(row["status"] or ""),
                 "error": row["error"],
                 "updated_utc": row["updated_utc"]})
        return out

    def dashboard_live_candidate_timing(self, campaign_id: str, candidate_ids: list[str]) -> dict:
        ids = [str(candidate_id) for candidate_id in candidate_ids if candidate_id]
        if not ids:
            return {"rung_spend": {}, "current_by_candidate": {}}
        placeholders = ",".join("?" for _ in ids)
        spend_rows = self.conn.execute(
            f"SELECT j.candidate_id,j.n,COALESCE(SUM(a.wall_seconds),0) elapsed_seconds "
            f"FROM jobs j JOIN attempts a ON a.job_id=j.job_id "
            f"WHERE j.campaign_id=? AND j.kind='simulate' AND j.candidate_id IN ({placeholders}) "
            f"GROUP BY j.candidate_id,j.n",
            (campaign_id, *ids),
        ).fetchall()
        rung_spend = {
            (str(row["candidate_id"]), int(row["n"])): float(row["elapsed_seconds"] or 0.0)
            for row in spend_rows
        }
        current_by_candidate: dict[str, list[dict]] = {}
        rows = self.conn.execute(
            f"SELECT j.job_id,j.candidate_id,j.n,j.seed,j.sealed,j.status,j.lease_owner,j.updated_utc,j.spec_json,"
            f"(SELECT MAX(a.started_utc) FROM attempts a WHERE a.job_id=j.job_id AND a.finished_utc IS NULL) AS started_utc "
            f"FROM jobs j WHERE j.campaign_id=? AND j.kind='simulate' "
            f"AND j.status IN ('queued','leased') AND j.candidate_id IN ({placeholders}) "
            f"ORDER BY j.created_utc",
            (campaign_id, *ids),
        ).fetchall()
        for row in rows:
            item = dict(row)
            try:
                item["spec"] = json.loads(item.pop("spec_json") or "{}")
            except (TypeError, ValueError):
                item["spec"] = {}
            current_by_candidate.setdefault(str(item["candidate_id"]), []).append(item)
        compute_by_candidate: dict[str, float] = {}
        for (candidate_id, _n), seconds in rung_spend.items():
            compute_by_candidate[candidate_id] = compute_by_candidate.get(candidate_id, 0.0) + seconds
        return {"rung_spend": rung_spend, "current_by_candidate": current_by_candidate,
                "compute_by_candidate": compute_by_candidate}

    def dashboard_job_snapshot(self, campaign_id: str) -> dict:
        counts = {row["status"]: int(row["count"]) for row in self.conn.execute(
            "SELECT status,COUNT(*) count FROM jobs WHERE campaign_id=? GROUP BY status",
            (campaign_id,),
        ).fetchall()}
        current_by_candidate: dict[str, list[dict]] = {}
        for row in self.conn.execute(
            "SELECT j.job_id,j.candidate_id,j.n,j.seed,j.sealed,j.status,j.lease_owner,j.updated_utc,"
            "(SELECT MAX(a.started_utc) FROM attempts a WHERE a.job_id=j.job_id AND a.finished_utc IS NULL) AS started_utc "
            "FROM jobs j WHERE j.campaign_id=? AND j.status IN ('queued','leased') "
            "ORDER BY created_utc",
            (campaign_id,),
        ).fetchall():
            item = dict(row)
            current_by_candidate.setdefault(item["candidate_id"], []).append(item)
        return {
            "counts": counts,
            "current_by_candidate": current_by_candidate,
        }

    def replay_missing_transient_result(self, *, campaign_id: str, artifact_hash: str,
                                        analysis_version: str, owner: str,
                                        claim_token: str) -> bool:
        self.begin_transaction(attempts=12)
        try:
            row = self.conn.execute(
                "SELECT q.producer_job,q.status,q.lease_owner,q.claim_token,"
                "j.status job_status,j.result_artifact,ar.body_state,ar.detail_json "
                "FROM analysis_queue q JOIN jobs j ON j.job_id=q.producer_job "
                "JOIN artifact_retention ar ON ar.artifact_hash=q.input_artifact "
                "WHERE q.campaign_id=? AND q.input_artifact=? AND q.analysis_version=? "
                "FOR UPDATE OF q,j,ar",
                (campaign_id, artifact_hash, analysis_version),
            ).fetchone()
            if (row is None or str(row["status"]) != "leased"
                    or str(row["lease_owner"] or "") != str(owner)
                    or str(row["claim_token"] or "") != str(claim_token)
                    or str(row["job_status"]) != "done"
                    or str(row["result_artifact"] or "") != str(artifact_hash)
                    or str(row["body_state"]) != "transient"):
                self.conn.rollback_if_open()
                return False
            measured = self.conn.execute(
                "SELECT 1 FROM measurements WHERE campaign_id=? AND input_artifact=? "
                "AND analysis_version=? LIMIT 1",
                (campaign_id, artifact_hash, analysis_version),
            ).fetchone()
            if measured is not None:
                self.conn.rollback_if_open()
                return False
            now = utc_now()
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                detail = {}
            detail.update({
                "eviction_reason": "transient_body_lost_before_analysis",
                "replay_queued": True,
                "body_verified_before_eviction": False,
            })
            self.conn.execute(
                "UPDATE analysis_queue SET status='failed',lease_owner=NULL,claim_token=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,error=?,updated_utc=? "
                "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
                "AND status='leased' AND lease_owner=? AND claim_token=?",
                ("TRANSIENT_RAW_LOST: producer replay queued", now, campaign_id,
                 artifact_hash, analysis_version, owner, claim_token),
            )
            self.conn.execute(
                "UPDATE artifact_retention SET body_state='evicted',evicted_utc=?,detail_json=?,"
                "updated_utc=? WHERE artifact_hash=? AND body_state='transient'",
                (now, json.dumps(detail, sort_keys=True), now, artifact_hash),
            )
            changed = self.conn.execute(
                "UPDATE jobs SET status='queued',result_artifact=NULL,error=?,lease_owner=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,"
                "attempts=GREATEST(0,attempts-1),updated_utc=? "
                "WHERE job_id=? AND status='done' AND result_artifact=?",
                ("transient raw body lost before analysis; exact producer replay queued",
                 now, row["producer_job"], artifact_hash),
            ).rowcount
            if changed != 1:
                self.conn.rollback_if_open()
                return False
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.rollback_if_open()
            raise

    def artifact_retention(self, artifact_hash: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM artifact_retention WHERE artifact_hash=?", (artifact_hash,)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["detail"] = {}
        return item

    def jobs(self, campaign_id: str, **where) -> list[dict]:
        clauses = ["campaign_id=?"]
        args: list = [campaign_id]
        allowed = {"job_id", "candidate_id", "kind", "stage", "n", "seed", "replicate", "status", "sealed"}
        for key, value in where.items():
            if key not in allowed:
                raise ValueError(f"unsupported jobs filter: {key}")
            clauses.append(f"{key}=?")
            args.append(value)
        rows = self.conn.execute(
            f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY created_utc,job_id", args
        )
        return [dict(r) | {"spec": json.loads(r["spec_json"])} for r in rows]

    def job_contexts_for_artifact(self, artifact: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT DISTINCT j.job_id,j.campaign_id,j.candidate_id "
            "FROM artifact_producers ap JOIN jobs j ON j.job_id=ap.job_id "
            "WHERE ap.artifact_hash=? ORDER BY j.campaign_id,j.candidate_id,j.job_id",
            (artifact,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        row = self.conn.execute(
            "SELECT j.job_id,j.campaign_id,j.candidate_id FROM artifacts a "
            "LEFT JOIN jobs j ON j.job_id=a.producer_job WHERE a.artifact_hash=?",
            (artifact,),
        ).fetchone()
        return [dict(row)] if row and row["job_id"] else []

    def evidence_audits(self, candidate_id: str, campaign_id: str | None = None) -> list[dict]:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM evidence_audits WHERE campaign_id=? AND candidate_id=? "
            "ORDER BY audited_utc,artifact_hash", (resolved, candidate_id)
        ).fetchall()
        return [dict(row) | {"detail": json.loads(row["detail_json"] or "{}")}
                for row in rows]

    def measurements(self, candidate_id: str, analysis_version: str,
                     campaign_id: str | None = None) -> list[dict]:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM measurements WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
            "ORDER BY n,seed", (resolved, candidate_id, analysis_version)
        )
        return [dict(r) | {"metrics": json.loads(r["metrics_json"])} for r in rows]

    def base_block_phenotype(self, candidate_id: str, analysis_version: str,
                            campaign_id: str | None = None) -> dict | None:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM four_rung_phenotypes WHERE campaign_id=? AND candidate_id=? "
            "AND analysis_version=?", (resolved, candidate_id, analysis_version)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["phenotype"] = json.loads(item.pop("phenotype_json"))
        return item

    def upsert_base_block_phenotype(self, campaign_id: str, candidate_id: str,
                                   analysis_version: str, contract: str,
                                   phenotype: dict) -> None:
        now = utc_now()
        self._write(
            "INSERT INTO four_rung_phenotypes(campaign_id,candidate_id,analysis_version,"
            "phenotype_contract,phenotype_json,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(campaign_id,candidate_id,analysis_version) DO UPDATE SET "
            "phenotype_contract=excluded.phenotype_contract,"
            "phenotype_json=excluded.phenotype_json,updated_utc=excluded.updated_utc",
            (campaign_id, candidate_id, analysis_version, str(contract),
             json.dumps(phenotype, sort_keys=True), now, now),
        )

    def campaign_base_block_phenotypes(self, campaign_id: str, analysis_version: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM four_rung_phenotypes WHERE campaign_id=? AND analysis_version=? "
            "ORDER BY created_utc,candidate_id", (campaign_id, analysis_version)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["phenotype"] = json.loads(item.pop("phenotype_json"))
            result.append(item)
        return result

    def campaign_locality_audit_results(self, campaign_id: str, analysis_version: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM locality_audit_results WHERE campaign_id=? AND analysis_version=? "
            "ORDER BY created_utc,candidate_id", (campaign_id, analysis_version)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            result.append(item)
        return result

    def locality_audit_result(self, candidate_id: str, analysis_version: str,
                              campaign_id: str | None = None) -> dict | None:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM locality_audit_results WHERE campaign_id=? AND candidate_id=? "
            "AND analysis_version=?", (resolved, candidate_id, analysis_version)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def rung_summaries(self, candidate_id: str, analysis_version: str,
                       campaign_id: str | None = None) -> list[dict]:
        resolved = self._resolve_campaign_for_candidate(candidate_id, campaign_id)
        if resolved is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM rung_summaries WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
            "ORDER BY n", (resolved, candidate_id, analysis_version)
        )
        return [dict(r) | {"summary": json.loads(r["summary_json"])} for r in rows]

    def record_benchmark(self, analysis_version: str, passed: bool, report: dict, *,
                         source_fingerprint: str | None = None,
                         numerical_environment_fingerprint: str | None = None) -> None:
        from graph_scale_dynamics.domain.version import environment_fingerprint
        source = source_fingerprint or analyzer_identity()
        environment = numerical_environment_fingerprint or environment_fingerprint()
        self._write(
            "INSERT INTO analyzer_benchmarks(analysis_version,runtime_fingerprint,"
            "environment_fingerprint,passed,report_json,created_utc) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(analysis_version) DO UPDATE SET "
            "runtime_fingerprint=excluded.runtime_fingerprint,"
            "environment_fingerprint=excluded.environment_fingerprint,"
            "passed=excluded.passed,report_json=excluded.report_json,created_utc=excluded.created_utc",
            (analysis_version, source, environment, int(passed), json.dumps(report), utc_now()),
        )

    def benchmark_any_identity(self, analysis_version: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM analyzer_benchmarks WHERE analysis_version=?",
            (analysis_version,)).fetchone()
        return dict(row) if row else None

    def benchmark(self, analysis_version: str, *, source_fingerprint: str | None = None,
                  numerical_environment_fingerprint: str | None = None) -> dict | None:
        from graph_scale_dynamics.domain.version import environment_fingerprint
        source = source_fingerprint or analyzer_identity()
        environment = numerical_environment_fingerprint or environment_fingerprint()
        row = self.conn.execute(
            "SELECT * FROM analyzer_benchmarks WHERE analysis_version=? "
            "AND runtime_fingerprint=? AND environment_fingerprint=?",
            (analysis_version, source, environment),
        ).fetchone()
        return dict(row) | {"report": json.loads(row["report_json"])} if row else None
