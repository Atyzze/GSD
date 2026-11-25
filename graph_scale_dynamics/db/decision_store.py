from __future__ import annotations


import json
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager

from graph_scale_dynamics.db.lane_yield import PARKED_UNTIL, parked_sql
from graph_scale_dynamics.decisions import structure_gate as SG
from graph_scale_dynamics.decisions.engine import HOLD, LANE_MERIT, Policy
from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES, CandidateState, utc_now
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

RUNNING = CandidateState.BASE_BLOCK_RUNNING.value
_LIVE_STATES = tuple(sorted(RUNNING_CANDIDATE_STATES))
_IDLE = ("AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.campaign_id=c.campaign_id AND j.candidate_id=c.candidate_id "
         "AND j.status IN ('queued','leased')) "
         "AND NOT EXISTS(SELECT 1 FROM analysis_queue a WHERE a.campaign_id=c.campaign_id "
         "AND a.candidate_id=c.candidate_id AND a.status IN ('queued','leased')) "
         "AND NOT EXISTS(SELECT 1 FROM candidate_evidence_rebuilds r WHERE r.campaign_id=c.campaign_id "
         "AND r.candidate_id=c.candidate_id AND r.status IN ('queued','leased')) ")
_PROBED = ("AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.campaign_id=c.campaign_id AND j.candidate_id=c.candidate_id "
           "AND j.kind='simulate' AND j.status='done' AND NOT EXISTS(SELECT 1 FROM analysis_queue a WHERE "
           "a.campaign_id=j.campaign_id AND a.producer_job=j.job_id AND a.status IN ('done','failed','cancelled'))) ")
_MARK = ("(SELECT COUNT(*)::text || ':' || COALESCE(MAX(j.updated_utc),'') FROM jobs j WHERE "
         "j.campaign_id=c.campaign_id AND j.candidate_id=c.candidate_id AND j.status NOT IN ('queued','leased'))")
LATEST = "engine_decisions_latest"
REDECIDE_MARK = "decide again:"
LAW_IDLE_SQL = ("NOT EXISTS(SELECT 1 FROM jobs j WHERE j.campaign_id=c.campaign_id AND j.candidate_id=c.candidate_id "
                "AND j.status IN ('queued','leased')) "
                "AND NOT EXISTS(SELECT 1 FROM analysis_queue a WHERE a.campaign_id=c.campaign_id "
                "AND a.candidate_id=c.candidate_id AND a.status IN ('queued','leased')) "
                "AND NOT EXISTS(SELECT 1 FROM candidate_evidence_rebuilds r WHERE r.campaign_id=c.campaign_id "
                "AND r.candidate_id=c.candidate_id AND r.status IN ('queued','leased'))")
LONGER_CHAIN_STAGE = "longer"
LONGER_CHAIN_CAP_FACTOR = 4
UNDECIDABLE_PASSES = 5
UNDECIDABLE_SECONDS = 3600.0
_FAILING: dict[tuple[str, str], dict] = {}
_PENDING_SAID: dict[tuple[str, str], tuple] = {}
QUEUE_RANK_STEP = 10_000_000


def queue_priority(queue_order: int, n: int) -> int:
    return int(queue_order) * QUEUE_RANK_STEP + int(n)


_SEEN = (f"(SELECT d.jobs_seen FROM {LATEST} d WHERE d.campaign_id=c.campaign_id "
         "AND d.candidate_id=c.candidate_id)")


_UNSUPERSEDED_FAILED_ANALYSIS = (
    "FROM analysis_queue a WHERE a.campaign_id=? AND a.candidate_id=? AND a.analysis_version=? "
    "AND a.status='failed' AND NOT EXISTS (SELECT 1 FROM analysis_queue b WHERE b.campaign_id=a.campaign_id "
    "AND b.candidate_id=a.candidate_id AND b.analysis_version=a.analysis_version AND b.n=a.n "
    "AND b.seed=a.seed AND b.status='done')")
CANCELLED_ANALYSIS_REQUEUED = "analysis cancelled, queued again"
_CANCELLED_UNSUPERSEDED_ANALYSIS = (
    "analysis_queue.campaign_id=? AND analysis_queue.candidate_id=? AND analysis_queue.analysis_version=? "
    "AND analysis_queue.status='cancelled' "
    "AND EXISTS (SELECT 1 FROM jobs j WHERE j.job_id=analysis_queue.producer_job AND j.kind='simulate' "
    "AND j.status='done') "
    "AND NOT EXISTS (SELECT 1 FROM analysis_queue b WHERE b.campaign_id=analysis_queue.campaign_id "
    "AND b.candidate_id=analysis_queue.candidate_id AND b.analysis_version=analysis_queue.analysis_version "
    "AND b.n=analysis_queue.n AND b.seed=analysis_queue.seed AND b.status IN ('done','queued','leased')) "
    "AND EXISTS (SELECT 1 FROM campaign_candidates c WHERE c.campaign_id=analysis_queue.campaign_id "
    "AND c.candidate_id=analysis_queue.candidate_id AND c.state IN ({live}))")
PENDING_CHECKS = (
    ("simulation queued or leased", "SELECT 1 FROM jobs WHERE campaign_id=? AND candidate_id=? "
     "AND kind='simulate' AND status IN ('queued','leased') LIMIT 1", False),
    ("simulation failed or lost", "SELECT 1 FROM jobs WHERE campaign_id=? AND candidate_id=? "
     "AND kind='simulate' AND status IN ('failed','lost') LIMIT 1", False),
    ("analysis queued or leased", "SELECT 1 FROM analysis_queue WHERE campaign_id=? AND candidate_id=? "
     "AND analysis_version=? AND status IN ('queued','leased') LIMIT 1", True),
    ("analysis failed", "SELECT 1 " + _UNSUPERSEDED_FAILED_ANALYSIS + " LIMIT 1", True),
    ("evidence rebuild not finished", "SELECT 1 FROM candidate_evidence_rebuilds WHERE campaign_id=? "
     "AND candidate_id=? AND analysis_version=? AND status!='done' LIMIT 1", True),
    ("evidence rebuild stale", "SELECT 1 FROM candidate_evidence_rebuilds WHERE campaign_id=? AND candidate_id=? "
     "AND analysis_version=? AND status='done' AND (built_measurement_count<>requested_measurement_count "
     "OR built_newest_utc<>requested_newest_utc) LIMIT 1", True),
)
_REPORTED_FAILURES: dict[tuple[str, str], str] = {}

EARLY_STAGE_FLAG = "gate:early_stage"
AGREEMENTS_TTL_SECONDS = 300.0
_AGREEMENTS: dict[str, tuple[float, int]] = {}


_FIXED_POINTS: dict = {}
_STUDY_SPECS: dict = {}


def _study_place(repo, campaign_id: str) -> tuple | None:
    key = (str(getattr(repo, "db_target", "") or id(repo)), str(campaign_id))
    if key not in _STUDY_SPECS:
        from graph_scale_dynamics.decisions.engine import policy_fingerprint
        try:
            spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
            design = spec.get("study_design")
            theirs = Policy.from_spec(spec)
            _STUDY_SPECS[key] = (None if not isinstance(design, dict) or design.get("study") is None else
                                 (str(design["study"]), int(design.get("campaign") or 0), theirs.let_through_rule,
                                  policy_fingerprint(theirs)))
        except (TypeError, ValueError, AttributeError, KeyError):
            _STUDY_SPECS[key] = None
    return _STUDY_SPECS[key]


def study_batches(repo, campaign_id: str, policy: Policy) -> list[tuple[str, int]]:
    from graph_scale_dynamics.decisions.engine import policy_fingerprint
    campaign_id = str(campaign_id)
    own = _study_place(repo, campaign_id)
    if own is None or not policy.let_through_rule:
        return [(campaign_id, 0)]
    rules = policy_fingerprint(policy)
    found = []
    for row in repo.conn.execute("SELECT campaign_id,status,workers_target FROM campaigns ORDER BY campaign_id").fetchall():
        other = str(row["campaign_id"])
        place = _study_place(repo, other)
        if place is None or place[0] != own[0] or place[2] != policy.let_through_rule or place[3] != rules:
            continue
        if other == campaign_id or (str(row["status"] or "") == "active" and row["workers_target"] != 0):
            found.append((other, place[1]))
    return sorted(found, key=lambda pair: (pair[1], int(pair[0]) if pair[0].isdigit() else 0, pair[0]))
LET_THROUGH_TTL_SECONDS = 15.0
LET_THROUGH_OVERLAP_NS = 300 * 10**9
_LET_THROUGH: dict[str, tuple[float, object, set]] = {}


def seed_work_of(work, final_multiplier=None) -> dict:
    work = work if isinstance(work, dict) else {}
    first = work.get("first_chunk") if isinstance(work.get("first_chunk"), dict) else {}
    pairs = {"work_units": work.get("units"), "moves": work.get("moves"), "work_budget": work.get("budget"),
             "first_chunk_units": first.get("units"), "first_chunk_moves": first.get("moves"),
             "first_multiplier": first.get("multiplier"), "final_multiplier": final_multiplier}
    return {key: int(value) for key, value in pairs.items()
            if isinstance(value, int) and not isinstance(value, bool)}


def let_through_campaigns(conn) -> frozenset:
    from graph_scale_dynamics.decisions.engine import Policy
    out = set()
    for row in conn.execute("SELECT campaign_id, spec_json FROM campaigns").fetchall():
        try:
            spec = json.loads(row["spec_json"] or "{}")
            if isinstance(spec, dict) and (spec.get("study_design") or {}).get("kind") == "focus":
                continue
            if Policy.from_spec(spec).let_through_rule:
                out.add(str(row["campaign_id"]))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def ledger_in_law_order(conn, counts_priced: bool = False):
    from graph_scale_dynamics.decisions.let_through import Ledger
    campaigns = sorted(let_through_campaigns(conn))
    ledger = Ledger(counts_priced=bool(counts_priced))
    if not campaigns:
        return ledger
    rows = conn.execute(
        "SELECT d.campaign_id, d.candidate_id, d.decision_id, d.at_n, d.action, d.rule, "
        "CASE WHEN left(d.facts_json,1)='{' THEN d.facts_json::jsonb->'salted' END AS salted, "
        "CASE WHEN left(d.facts_json,1)='{' THEN d.facts_json::jsonb->>'signature' END AS signature "
        "FROM engine_decisions d JOIN campaign_candidates c ON c.campaign_id=d.campaign_id "
        f"AND c.candidate_id=d.candidate_id WHERE d.campaign_id IN ({','.join('?' for _ in campaigns)}) "
        "ORDER BY c.candidate_number, d.campaign_id, d.decision_id", tuple(campaigns)).fetchall()
    for row in rows:
        salted = row["salted"]
        if isinstance(salted, str):
            try:
                salted = json.loads(salted)
            except ValueError:
                salted = None
        ledger.feed({"campaign_id": row["campaign_id"], "candidate_id": row["candidate_id"],
                     "decision_id": row["decision_id"], "at_n": row["at_n"], "action": row["action"],
                     "rule": row["rule"], "salted": salted, "signature": row["signature"]})
    return ledger


def let_through_ledger(conn, key: str = "", *, fresh: bool = False, counts_priced: bool = False):
    from graph_scale_dynamics.decisions.let_through import Ledger
    if fresh:
        return ledger_in_law_order(conn, counts_priced)
    key = f"{key}:priced" if counts_priced else key
    cached = _LET_THROUGH.get(key)
    if cached is not None and time.monotonic() - cached[0] < LET_THROUGH_TTL_SECONDS:
        return cached[1]
    ledger, seen = ((cached[1], cached[2]) if cached is not None
                    else (Ledger(counts_priced=bool(counts_priced)), set()))
    campaigns = let_through_campaigns(conn)
    since = ""
    if ledger.last:
        try:
            stamp = int(ledger.last.split("-", 1)[0]) - LET_THROUGH_OVERLAP_NS
            since = f"{max(0, stamp):020d}"
        except ValueError:
            since = ""
    rows = conn.execute(
        "SELECT campaign_id, candidate_id, decision_id, at_n, action, rule, "
        "CASE WHEN left(facts_json,1)='{' THEN facts_json::jsonb->'salted' END AS salted, "
        "CASE WHEN left(facts_json,1)='{' THEN facts_json::jsonb->>'signature' END AS signature "
        "FROM engine_decisions WHERE decision_id > ? ORDER BY decision_id, campaign_id", (since,)).fetchall()
    for row in rows:
        ident = (str(row["campaign_id"]), str(row["decision_id"]))
        if ident in seen or ident[0] not in campaigns:
            continue
        seen.add(ident)
        salted = row["salted"]
        if isinstance(salted, str):
            try:
                salted = json.loads(salted)
            except ValueError:
                salted = None
        ledger.feed({"campaign_id": row["campaign_id"], "candidate_id": row["candidate_id"],
                     "decision_id": row["decision_id"], "at_n": row["at_n"], "action": row["action"],
                     "rule": row["rule"], "salted": salted, "signature": row["signature"]})
    _LET_THROUGH[key] = (time.monotonic(), ledger, seen)
    return ledger


def early_stage_counts(conn, at_n: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN g.agrees='true' THEN g.law END) AS agree, "
        "COUNT(DISTINCT CASE WHEN g.disagrees='true' THEN g.law END) AS disagree, "
        "COUNT(DISTINCT CASE WHEN g.would='true' THEN g.law END) AS would FROM ("
        "SELECT campaign_id || ':' || candidate_id AS law, "
        "facts_json::jsonb#>>'{gate,early,agrees}' AS agrees, "
        "facts_json::jsonb#>>'{gate,early,disagrees}' AS disagrees, "
        "facts_json::jsonb#>>'{gate,early,would_refuse}' AS would "
        "FROM engine_decisions WHERE at_n=? AND left(facts_json,1)='{' AND facts_json LIKE ?) g",
        (int(at_n), '%"early"%')).fetchone()
    return {"agree": int(row["agree"] or 0), "disagree": int(row["disagree"] or 0),
            "would_refuse": int(row["would"] or 0)} if row else {"agree": 0, "disagree": 0, "would_refuse": 0}


def evidence_pending_reasons(conn, campaign_id: str, law: str, analysis_version: str) -> list[str]:
    reasons = []
    for name, sql, versioned in PENDING_CHECKS:
        args = (str(campaign_id), str(law)) + ((str(analysis_version),) if versioned else ())
        if conn.execute(sql, args).fetchone() is not None:
            reasons.append(name)
    return reasons


def decision_backlog(conn, campaign_id: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS awaiting, MIN(w.since) AS oldest FROM ("
        f"SELECT {_MARK} AS mark, {_SEEN} AS seen, "
        "GREATEST(c.updated_utc, COALESCE((SELECT MAX(j.updated_utc) FROM jobs j WHERE j.campaign_id=c.campaign_id "
        "AND j.candidate_id=c.candidate_id AND j.status NOT IN ('queued','leased')),''), "
        "COALESCE((SELECT MAX(a.updated_utc) FROM analysis_queue a WHERE a.campaign_id=c.campaign_id "
        "AND a.candidate_id=c.candidate_id),'')) AS since "
        "FROM campaign_candidates c WHERE c.campaign_id=? "
        f"AND c.state IN ({','.join('?' for _ in _LIVE_STATES)}) " + _IDLE + _PROBED
        + ") w WHERE w.seen IS DISTINCT FROM w.mark", (str(campaign_id), *_LIVE_STATES)).fetchone()
    return {"awaiting": int(row["awaiting"] or 0) if row else 0, "oldest_since_utc": row["oldest"] if row else None}


def _facts(alias: str) -> str:
    return f"(CASE WHEN left({alias}.facts_json,1)='{{' THEN {alias}.facts_json::jsonb END)"


def lane_rank_sql(alias: str) -> str:
    return f"(({_facts(alias)}#>>'{{lane,rank}}')::int)"


def lane_tier_sql(alias: str) -> str:
    return f"(({_facts(alias)}#>>'{{lane,tier}}')::int)"


def lane_score_sql(alias: str) -> str:
    return f"(({_facts(alias)}#>>'{{lane,law_score}}')::double precision)"


def audit_traffic_sql(alias: str) -> str:
    return f"(({_facts(alias)}#>>'{{lane,audit}}')::boolean)"


def held_sql(alias: str = "c") -> str:
    return (f"(SELECT e.action FROM {LATEST} e WHERE e.campaign_id={alias}.campaign_id AND "
            f"e.candidate_id={alias}.candidate_id) IS NOT DISTINCT FROM '{HOLD}'")


def best_runs(measurements: list) -> list:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    return select_best_runs([m for m in measurements
                             if not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {})
                                     .get("sampler_audit"))])


class DecisionStore:
    def __init__(self, repo, log, campaign: dict):
        self.repo, self.log, self.campaign = repo, log, campaign
        self.spec = campaign.get("spec") or {}
        self.policy = Policy.from_spec(self.spec)
        self._marks: dict[str, str] = {}
        self._measurements: dict[str, list] = {}
        self._contracts: dict[str, str] = {}
        self.scored: dict[str, dict] = {}
        self.learning: set = set()

    def laws_awaiting_decision(self, campaign_id: str, limit: int = 512) -> list:
        rows = self.repo.conn.execute(
            "SELECT w.candidate_id, w.mark FROM ("
            f"SELECT c.candidate_id, {_MARK} AS mark, {_SEEN} AS seen "
            "FROM campaign_candidates c WHERE c.campaign_id=? "
            f"AND c.state IN ({','.join('?' for _ in _LIVE_STATES)}) " + _IDLE + _PROBED
            + ") w WHERE w.seen IS DISTINCT FROM w.mark ORDER BY w.candidate_id LIMIT ?",
            (str(campaign_id), *_LIVE_STATES, int(limit))).fetchall()
        awaiting = []
        for row in rows:
            self._marks[str(row["candidate_id"])] = row["mark"]
            awaiting.append(str(row["candidate_id"]))
        return awaiting

    def _law_measurements(self, campaign_id: str, law: str) -> list:
        if law not in self._measurements:
            self._measurements[law] = self.repo.measurements(law, ANALYSIS_VERSION, campaign_id)
        return self._measurements[law]

    def analysis_contract(self, campaign_id: str) -> str:
        if campaign_id not in self._contracts:
            self._contracts[campaign_id] = str(self.repo.campaign_analysis_contract(str(campaign_id)))
        return self._contracts[campaign_id]

    def law_evidence(self, campaign_id: str, law: str) -> dict:
        from graph_scale_dynamics.decisions.evidence import (
            _b143_rung_sampling_state, _build_four_rung_phenotype, _rung_cell)
        from graph_scale_dynamics.scheduling.base_block import base_sizes
        failed = {int(r["n"]): int(r["c"]) for r in self.repo.conn.execute(
            "SELECT n,COUNT(*) c FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "AND status='failed' GROUP BY n", (str(campaign_id), str(law))).fetchall()}
        unanalysed = {int(r["n"]): int(r["c"]) for r in self.repo.conn.execute(
            "SELECT a.n,COUNT(*) c " + _UNSUPERSEDED_FAILED_ANALYSIS + " GROUP BY a.n",
            (str(campaign_id), str(law), self.analysis_contract(campaign_id))).fetchall()}
        if failed or unanalysed:
            return {"entries": {}, "phenotype": None, "failed_seeds": failed, "failed_analyses": unanalysed}
        if self.requeue_cancelled_analyses(campaign_id, law):
            return {"pending": True, "pending_reasons": [CANCELLED_ANALYSIS_REQUEUED]}
        rebuild = self.repo.conn.execute(
            "SELECT attempts, error FROM candidate_evidence_rebuilds WHERE campaign_id=? AND candidate_id=? "
            "AND analysis_version=? AND status='failed' LIMIT 1",
            (str(campaign_id), str(law), ANALYSIS_VERSION)).fetchone()
        if rebuild is not None:
            return {"entries": {}, "phenotype": None,
                    "evidence_failed": (f"its evidence rebuild failed for good after {int(rebuild['attempts'] or 0)} "
                                        f"attempts: {str(rebuild['error'] or 'no error recorded')[:300]}")}
        reasons = evidence_pending_reasons(self.repo.conn, campaign_id, law, ANALYSIS_VERSION)
        if reasons:
            return {"pending": True, "pending_reasons": reasons}
        summaries = {int(r["n"]): r["summary"] for r in self.repo.rung_summaries(law, ANALYSIS_VERSION, campaign_id)}
        if not summaries:
            return {"entries": {}, "phenotype": None}
        history = [m.get("metrics") or {} for m in best_runs(self._law_measurements(campaign_id, law))]
        declared = [int(n) for n in base_sizes(self.spec)]
        states = {n: _b143_rung_sampling_state(self.spec, n, summaries[n], history) for n in summaries}
        if not set(declared) <= set(summaries):
            landed = [n for n in declared if n in summaries]
            return {"entries": {n: _rung_cell(self.spec, n, summaries[n], states[n]) for n in landed},
                    "phenotype": None, **self.law_chains(campaign_id, law, states, landed),
                    **self.law_starts_reading(campaign_id, law)}
        phenotype = _build_four_rung_phenotype(self.spec, summaries, states)
        cells = dict(phenotype.get("per_n") or {})
        cells.update(phenotype.get("extension_per_n") or {})
        five = self.law_starts_reading(campaign_id, law)
        return {"entries": {int(n): cell for n, cell in cells.items() if int(n) in summaries},
                "phenotype": phenotype, "standing": self.law_standing(law, phenotype),
                "structure": self.law_structure(campaign_id, law),
                "longer_chains": self.longer_chains(campaign_id, law),
                **self.law_chains(campaign_id, law, states, [int(n) for n in cells if int(n) in summaries]),
                **five}

    def requeue_cancelled_analyses(self, campaign_id: str, law: str) -> int:
        sql = _CANCELLED_UNSUPERSEDED_ANALYSIS.format(live=",".join("?" for _ in _LIVE_STATES))
        return int(self.repo.conn.execute(
            "UPDATE analysis_queue SET status='queued',attempts=0,lease_owner=NULL,claim_token=NULL,"
            "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,error_class=NULL,"
            "updated_utc=? WHERE " + sql,
            (utc_now(), str(campaign_id), str(law), self.analysis_contract(campaign_id), *_LIVE_STATES)).rowcount or 0)

    def law_chains(self, campaign_id: str, law: str, states: dict, rungs) -> dict:
        if not self.policy.every_chain:
            return {}
        from graph_scale_dynamics.decisions.every_chain import chain_cells
        by_n: dict = {}
        for m in best_runs(self._law_measurements(campaign_id, law)):
            by_n.setdefault(int(m["n"]), []).append(m.get("metrics") or {})
        wanted = [int(n) for n in rungs if int(n) in by_n and int(n) in states]
        return {"chains": chain_cells(self.spec, {n: by_n[n] for n in wanted}, {n: states[n] for n in wanted})}

    def longer_chains(self, campaign_id: str, law: str) -> list:
        rows = self.repo.conn.execute(
            "SELECT DISTINCT n FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND stage LIKE ?",
            (str(campaign_id), str(law), f"{LONGER_CHAIN_STAGE}_n%")).fetchall()
        return sorted(int(r["n"]) for r in rows)

    def law_structure(self, campaign_id: str, law: str) -> dict:
        return SG.rung_structure(self._law_measurements(campaign_id, law))

    def gate_context(self, campaign_id: str) -> dict:
        switch = self.repo.get_flag(EARLY_STAGE_FLAG, "") == "on"
        agreements = None
        if switch:
            key = str(getattr(self.repo, "db_path", "") or id(self.repo))
            cached = _AGREEMENTS.get(key)
            if cached is None or time.monotonic() - cached[0] > AGREEMENTS_TTL_SECONDS:
                cached = (time.monotonic(), early_stage_counts(self.repo.conn, self.policy.gate_at_n)["agree"])
                _AGREEMENTS[key] = cached
            agreements = cached[1]
        row = self.repo.conn.execute(
            f"SELECT COUNT(*) c FROM {LATEST} WHERE campaign_id=? AND rule='gate_audit' AND action='run_next'",
            (str(campaign_id),)).fetchone()
        followed = self.repo.conn.execute(
            f"SELECT candidate_id FROM {LATEST} WHERE campaign_id=? AND rule='plateau_follow' AND action='run_next'",
            (str(campaign_id),)).fetchall()
        return {"contract": SG.GATE_CONTRACT, "early_stage_switch": switch, "early_agreements": agreements,
                "audit_in_flight": int(row["c"] or 0) if row else 0,
                "plateau_follow_laws": sorted(str(r["candidate_id"]) for r in followed)}

    def let_through_ledger(self):
        return let_through_ledger(self.repo.conn, str(getattr(self.repo, "db_target", "") or id(self.repo)),
                                  counts_priced=bool(self.policy.ledger_counts_priced))

    def fixed_points(self, campaign_id: str):
        from graph_scale_dynamics.decisions.let_through import FixedPoints
        key = (str(getattr(self.repo, "db_target", "") or id(self.repo)), str(campaign_id), self.rules_of_learning())
        batches = self.study_batches(campaign_id)
        laws = self.learning_laws(campaign_id, batches)
        return _FIXED_POINTS.setdefault(key, FixedPoints()).refresh(
            laws, self.policy, own=str(campaign_id), read=batches,
            drawing=self.batches_drawing(batches, laws) if len(batches) > 1 else None)

    def study_batches(self, campaign_id: str) -> list[tuple[str, int]]:
        return study_batches(self.repo, str(campaign_id), self.policy)

    def batches_drawing(self, batches: list, laws: list) -> dict:
        from graph_scale_dynamics.operations.study import LAW_BUDGET_PREFIX
        drawing = {}
        for batch, _place in batches:
            held = [int(law["number"]) for law in laws if law["campaign_id"] == batch]
            raw = str(self.repo.get_flag(f"{LAW_BUDGET_PREFIX}{batch}", "") or "").strip()
            budget = int(raw) if raw.isdigit() else None
            drawing[batch] = {"top": max(held, default=0),
                              "finished": budget is not None and len(held) >= budget}
        return drawing

    def rules_of_learning(self) -> str:
        from graph_scale_dynamics.decisions.engine import policy_fingerprint
        return policy_fingerprint(self.policy)

    def learning_laws(self, campaign_id: str, batches: list | None = None) -> list[dict]:
        from graph_scale_dynamics.decisions.let_through import NOT_A_VERDICT
        from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, CandidateState
        terminal = sorted(TERMINAL_CANDIDATE_STATES)
        quiet = sorted(NOT_A_VERDICT)
        out = []
        for batch, order in (batches if batches is not None else self.study_batches(campaign_id)):
            rows = self.repo.conn.execute(
                "SELECT c.candidate_id, c.candidate_number, c.state, (SELECT MAX(d.at_n) FROM engine_decisions d "
                "WHERE d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
                f"AND d.rule NOT IN ({','.join('?' for _ in quiet)})) AS verdict_past "
                "FROM campaign_candidates c WHERE c.campaign_id=? AND c.candidate_number IS NOT NULL",
                (*quiet, batch)).fetchall()
            out += [{"campaign_id": batch, "candidate_id": str(row["candidate_id"]),
                     "number": int(row["candidate_number"]), "campaign_order": int(order),
                     "ended": str(row["state"]) in terminal, "held": str(row["state"]) == CandidateState.HELD.value,
                     "verdict_past": None if row["verdict_past"] is None else int(row["verdict_past"])} for row in rows]
        return out

    def learning_rows(self, keys: list) -> list[dict]:
        if not keys:
            return []
        rows = []
        by_campaign: dict = {}
        for campaign, law in keys:
            by_campaign.setdefault(str(campaign), []).append(str(law))
        for campaign, laws in by_campaign.items():
            rows += self.repo.conn.execute(
                "SELECT campaign_id, candidate_id, decision_id, at_n, action, rule, "
                "CASE WHEN left(facts_json,1)='{' THEN facts_json::jsonb->'salted' END AS salted, "
                "CASE WHEN left(facts_json,1)='{' THEN facts_json::jsonb->>'signature' END AS signature "
                f"FROM engine_decisions WHERE campaign_id=? AND candidate_id IN ({','.join('?' for _ in laws)}) "
                "ORDER BY decision_id", (campaign, *laws)).fetchall()
        place = {(str(campaign), str(law)): index for index, (campaign, law) in enumerate(keys)}
        out = []
        for row in sorted(rows, key=lambda r: (place[(str(r["campaign_id"]), str(r["candidate_id"]))],
                                               str(r["decision_id"]))):
            salted = row["salted"]
            if isinstance(salted, str):
                try:
                    salted = json.loads(salted)
                except ValueError:
                    salted = None
            out.append({"campaign_id": row["campaign_id"], "candidate_id": row["candidate_id"],
                        "decision_id": row["decision_id"], "at_n": row["at_n"], "action": row["action"],
                        "rule": row["rule"], "salted": salted, "signature": row["signature"]})
        return out

    def law_standing(self, law: str, phenotype: dict | None) -> dict:
        found = (self.scored.get(str(law)) or {}).get("score")
        standing = {"control_family": None, "law_score": found}
        if not phenotype:
            return standing
        try:
            if not hasattr(self, "_calibration"):
                from graph_scale_dynamics.calibration import durable_artifact_path, load_table
                self._calibration = load_table(durable_artifact_path())
            standing["control_family"] = self.control_family(phenotype)
        except Exception as error:  # noqa: BLE001
            self.log.write("law_standing_unavailable", error=f"{type(error).__name__}: {error}"[:300])
        return standing

    def control_family(self, phenotype: dict) -> str | None:
        from graph_scale_dynamics.research.score_door import score_evidence
        from graph_scale_dynamics.research.stability_score import (
            control_family_reference, noise_floors, noise_floors_by_n)
        from graph_scale_dynamics.scheduling.limits import connectivity_floor
        if not hasattr(self, "_control_reference"):
            self._control_reference = control_family_reference(self._calibration)
        if not self._control_reference:
            return None
        scored = score_evidence(phenotype=phenotype, floors=noise_floors(self._calibration),
                                floors_by_n=noise_floors_by_n(self._calibration),
                                connectivity_floor=connectivity_floor(self.spec),
                                control_reference=self._control_reference)
        family = (scored.get("control_family") or {}).get("family")
        return str(family) if family else None

    def laws_in_flight_at(self, campaign_id: str, n: int) -> int:
        from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES
        terminal = sorted(TERMINAL_CANDIDATE_STATES)
        marks = ",".join("?" * len(terminal))
        alive = ("NOT EXISTS (SELECT 1 FROM campaign_candidates cc WHERE cc.campaign_id={t}.campaign_id "
                 f"AND cc.candidate_id={{t}}.candidate_id AND cc.state IN ({marks}))")
        row = self.repo.conn.execute(
            f"SELECT COUNT(DISTINCT law) c FROM (SELECT l.candidate_id law FROM {LATEST} l WHERE l.campaign_id=? "
            f"AND l.action='run_next' AND l.next_n=? AND {alive.format(t='l')} "
            "UNION SELECT j.candidate_id FROM jobs j WHERE j.campaign_id=? AND j.kind='simulate' AND j.n=? "
            f"AND j.status IN ('queued','leased') AND NOT {parked_sql('j')} AND {alive.format(t='j')}) AS lane",
            (str(campaign_id), int(n), *terminal, str(campaign_id), int(n), *terminal)).fetchone()
        return int(row["c"] or 0) if row else 0

    def laws_waiting_for_the_lane(self, campaign_id: str, n: int, limit: int, *, merit_only: bool = False) -> list:
        if int(limit) <= 0:
            return []
        rows = self.repo.conn.execute(
            f"SELECT latest.candidate_id FROM {LATEST} latest JOIN campaign_candidates c "
            "ON c.campaign_id=latest.campaign_id AND c.candidate_id=latest.candidate_id "
            f"AND c.state IN ({','.join('?' for _ in _LIVE_STATES)}) "
            "WHERE latest.campaign_id=? AND latest.action='hold' "
            "AND latest.rule='deep_lane_full' AND latest.next_n=? "
            + (f"AND {lane_rank_sql('latest')}={LANE_MERIT} " if merit_only else "")
            + f"ORDER BY {lane_rank_sql('latest')}, {lane_tier_sql('latest')} NULLS FIRST, "
            f"{lane_score_sql('latest')} DESC NULLS LAST, latest.decision_id "
            "LIMIT ?", (*_LIVE_STATES, str(campaign_id), int(n), int(limit))).fetchall()
        return [str(row["candidate_id"]) for row in rows]

    def audit_laws_in_flight_at(self, campaign_id: str, n: int) -> list:
        rows = self.repo.conn.execute(
            f"SELECT latest.candidate_id, latest.at_n, latest.priority, latest.facts_json FROM {LATEST} latest "
            "WHERE latest.campaign_id=? AND latest.action='run_next' AND latest.next_n=? "
            f"AND {audit_traffic_sql('latest')} AND EXISTS(SELECT 1 FROM jobs j WHERE j.campaign_id=latest.campaign_id "
            "AND j.candidate_id=latest.candidate_id AND j.kind='simulate' AND j.n=latest.next_n "
            f"AND j.status IN ('queued','leased') AND NOT {parked_sql('j')}) "
            "ORDER BY latest.decision_id DESC", (str(campaign_id), int(n))).fetchall()
        out = []
        for row in rows:
            try:
                facts = json.loads(row["facts_json"] or "{}")
            except ValueError:
                facts = {}
            out.append({"law": str(row["candidate_id"]), "at_n": row["at_n"], "priority": row["priority"],
                        "facts": facts if isinstance(facts, dict) else {}})
        return out

    def latest_decision(self, campaign_id: str, law: str) -> dict | None:
        row = self.repo.conn.execute(
            f"SELECT at_n, next_n, action, rule, priority, facts_json FROM {LATEST} WHERE campaign_id=? "
            "AND candidate_id=?", (str(campaign_id), str(law))).fetchone()
        if row is None:
            return None
        try:
            facts = json.loads(row["facts_json"] or "{}")
        except ValueError:
            facts = {}
        return {"at_n": row["at_n"], "next_n": row["next_n"], "action": row["action"], "rule": row["rule"],
                "priority": row["priority"], "facts": facts if isinstance(facts, dict) else {}}

    def park_lane_seeds(self, campaign_id: str, law: str, n: int) -> dict:
        parked = self.repo.conn.execute(
            "UPDATE jobs SET next_attempt_utc=?, updated_utc=? WHERE campaign_id=? AND candidate_id=? "
            "AND kind='simulate' AND n=? AND status='queued'",
            (PARKED_UNTIL, utc_now(), str(campaign_id), str(law), int(n))).rowcount
        running = self.repo.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND n=? "
            "AND status='leased'", (str(campaign_id), str(law), int(n))).fetchone()
        return {"parked": int(parked or 0), "stopping": int(running["c"] or 0) if running else 0}

    def parked_rung(self, campaign_id: str, law: str) -> int | None:
        row = self.repo.conn.execute(
            f"SELECT MAX(j.n) n FROM jobs j WHERE j.campaign_id=? AND j.candidate_id=? AND j.kind='simulate' "
            f"AND {parked_sql('j')}", (str(campaign_id), str(law))).fetchone()
        return int(row["n"]) if row is not None and row["n"] is not None else None

    def wake_lane_seeds(self, campaign_id: str, law: str, n: int) -> int:
        return int(self.repo.conn.execute(
            f"UPDATE jobs SET next_attempt_utc=NULL, updated_utc=? WHERE campaign_id=? AND candidate_id=? "
            f"AND kind='simulate' AND n=? AND {parked_sql('jobs')}",
            (utc_now(), str(campaign_id), str(law), int(n))).rowcount or 0)

    def wake_stray_seeds(self, campaign_id: str) -> int:
        return int(self.repo.conn.execute(
            f"UPDATE jobs SET next_attempt_utc=NULL, updated_utc=? WHERE campaign_id=? AND {parked_sql('jobs')} "
            f"AND EXISTS(SELECT 1 FROM {LATEST} d WHERE d.campaign_id=jobs.campaign_id "
            "AND d.candidate_id=jobs.candidate_id AND d.action='run_next' AND d.next_n=jobs.n)",
            (utc_now(), str(campaign_id))).rowcount or 0)

    def record_failure(self, campaign_id: str, law: str, error: str) -> None:
        self.log.write("engine_decision_failed", campaign=str(campaign_id)[:17], candidate=str(law)[:12],
                       error=str(error)[:500])
        key = (str(campaign_id), str(law))
        if _REPORTED_FAILURES.get(key) != str(error):
            _REPORTED_FAILURES[key] = str(error)
            try:
                self.repo.emit("engine_decision_failed", {"campaign_id": str(campaign_id), "candidate_id": str(law),
                                                          "error": str(error)[:500]})
            except Exception as unrecorded:
                self.log.write("engine_decision_failure_unrecorded", error=str(unrecorded)[:200])

    def record_pending(self, campaign_id: str, law: str, reasons: list) -> None:
        key, said = (str(campaign_id), str(law)), tuple(sorted(str(r) for r in reasons or ()))
        if "learning" in said:
            self.learning.add(str(law))
        if _PENDING_SAID.get(key) == said:
            return
        _PENDING_SAID[key] = said
        try:
            self.repo.emit("engine_decision_pending", {"campaign_id": str(campaign_id), "candidate_id": str(law),
                                                       "reasons": list(said)})
        except Exception as unrecorded:  # noqa: BLE001
            self.log.write("engine_decision_pending_unrecorded", error=str(unrecorded)[:200])

    def count_failure(self, campaign_id: str, law: str, error: str) -> None:
        key = (str(campaign_id), str(law))
        failing = _FAILING.get(key)
        if failing is None or failing["error"] != str(error):
            _FAILING[key] = {"error": str(error), "passes": 1, "since": time.monotonic()}
        else:
            failing["passes"] += 1

    def undecidable(self, campaign_id: str, law: str) -> str | None:
        entry = _FAILING.get((str(campaign_id), str(law)))
        if (not entry or entry["passes"] < UNDECIDABLE_PASSES
                or time.monotonic() - entry["since"] < UNDECIDABLE_SECONDS):
            return None
        return (f"reading it failed the same way on {entry['passes']} passes over "
                f"{(time.monotonic() - entry['since']) / 3600.0:.1f} h: {entry['error'][:300]}")

    def record_phenotype(self, campaign_id: str, law: str, phenotype) -> None:
        contract = str((self.spec.get("base_block") or {}).get("contract") or "rung-phenotype-3")
        self.repo.upsert_base_block_phenotype(campaign_id, law, ANALYSIS_VERSION, contract, phenotype)

    def seed_rows(self, campaign_id: str, law: str) -> dict:
        found: dict = defaultdict(dict)
        for m in best_runs(self._law_measurements(campaign_id, law)):
            metrics = m.get("metrics") or {}
            terminal = ((metrics.get("health") or {}).get("rung_terminal")) or {}
            key = (int(m["n"]), str(m.get("seed")))
            found[key[0]][key[1]] = {"ended": terminal.get("reason"),
                                     "given_at_cap": bool(metrics.get("ended_at_cap") or metrics.get("given_ended_at_cap")),
                                     **seed_work_of(terminal.get("work"), terminal.get("final_multiplier"))}
        return {n: [seeds[s] for s in sorted(seeds)] for n, seeds in found.items()}

    def enqueue_seeds(self, campaign_id: str, law: str, n: int, *, seeds: int, work_budget: int,
                      queue_order: int, longer: bool = False, budget_scale: float = 1.0) -> int:
        from graph_scale_dynamics.scheduling.job_creation import enqueue_simulation_rung
        from graph_scale_dynamics.scheduling.limits import work_budget as budget_of
        scale = float(budget_scale or 1.0)
        if int(budget_of(self.spec, int(n)) * scale) != int(work_budget):
            raise RuntimeError(f"N={n}: the job's budget in work and the engine's disagree")
        stretched = {"budget_scale": scale} if scale != 1.0 else {}
        if longer:
            wanted = list(range(int(seeds)))
            how = self._longer_chain(campaign_id, law, int(n))
        else:
            done = {str(j.get("seed")) for j in self.repo.jobs(campaign_id, candidate_id=law, n=int(n))
                    if int(j.get("n") or 0) == int(n) and j.get("status") == "done"}
            wanted, how = [s for s in range(int(seeds)) if str(s) not in done], {}
        candidate = self.repo.candidate(law, campaign_id)
        state = self._law_state(campaign_id, law)
        revive = state in RUNNING_CANDIDATE_STATES or state == CandidateState.PARKED.value
        return int(enqueue_simulation_rung(self.repo, self.log, self.campaign, candidate, int(n), wanted, "decider",
                                           queue_priority=queue_priority(queue_order, n), revive_cancelled=revive,
                                           **how, **stretched) or 0)

    def _longer_chain(self, campaign_id: str, law: str, n: int) -> dict:
        from graph_scale_dynamics.scheduling.job_creation import initial_sweeps_multiplier, one_shot_policy
        ran = max([int((((m.get("metrics") or {}).get("health") or {}).get("rung_terminal") or {})
                       .get("final_multiplier") or 1)
                   for m in best_runs(self._law_measurements(campaign_id, law)) if int(m.get("n") or 0) == int(n)]
                  + [initial_sweeps_multiplier(self.spec, int(n))])
        one_shot = one_shot_policy(self.spec, int(n), law, (self.repo.candidate(law, campaign_id) or {}).get("spec"))
        initial = 2 * max(1, ran)
        one_shot["max_sweeps_multiplier"] = max(initial, LONGER_CHAIN_CAP_FACTOR * int(one_shot["max_sweeps_multiplier"]))
        return {"sweeps_multiplier": initial, "stage_prefix": LONGER_CHAIN_STAGE,
                "execution_overrides": {"one_shot": one_shot}}

    def _law_state(self, campaign_id: str, law: str, *, lock: bool = False) -> str | None:
        row = self.repo.conn.execute(
            "SELECT state FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?"
            + (" FOR UPDATE" if lock else ""),
            (str(campaign_id), str(law))).fetchone()
        return str(row["state"]) if row is not None else None

    def law_refuses_running(self, campaign_id: str, law: str, *, parked_ok: bool = False) -> str | None:
        state = self._law_state(campaign_id, law, lock=self.repo.conn.in_transaction)
        if state in RUNNING_CANDIDATE_STATES or (parked_ok and state == CandidateState.PARKED.value):
            return None
        return state or "missing"

    @contextmanager
    def one_transaction(self):
        if self.repo.conn.in_transaction:
            yield
            return
        self.repo.begin_transaction(attempts=12)
        try:
            yield
        except BaseException:
            self.repo.conn.rollback_if_open()
            raise
        self.repo.conn.execute("COMMIT")

    def set_law_state(self, campaign_id: str, law: str, state: str, *, rule: str, next_n,
                      parked_ok: bool = False) -> int:
        if state in RUNNING_CANDIDATE_STATES:
            allowed = set(RUNNING_CANDIDATE_STATES) | ({CandidateState.PARKED.value} if parked_ok else set())
            return int(bool(self.repo.set_candidate_state(law, state, f"decision engine: {rule}", campaign_id,
                                                          only_from=allowed)))
        result = self.repo.terminalize_candidate(campaign_id, law, state, f"decision engine: {rule}",
                                                 leave_parked=True) or {}
        return int(bool(result.get("state_changed") or result.get("jobs_cancelled")
                        or result.get("analysis_cancelled")))

    def _mark_now(self, campaign_id: str, law: str) -> str:
        row = self.repo.conn.execute(
            f"SELECT {_MARK} AS mark FROM campaign_candidates c WHERE c.campaign_id=? AND c.candidate_id=?",
            (str(campaign_id), str(law))).fetchone()
        return row["mark"] if row else ""

    def law_has_work(self, campaign_id: str, law: str) -> bool:
        row = self.repo.conn.execute(
            f"SELECT {LAW_IDLE_SQL} AS idle FROM campaign_candidates c WHERE c.campaign_id=? AND c.candidate_id=?",
            (str(campaign_id), str(law))).fetchone()
        return row is not None and not bool(row["idle"])

    def largest_graph_n(self, campaign_id: str, law: str) -> int | None:
        row = self.repo.conn.execute(
            "SELECT MAX(n) AS n FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate'",
            (str(campaign_id), str(law))).fetchone()
        return int(row["n"]) if row is not None and row["n"] is not None else None

    def size_is_read(self, campaign_id: str, law: str, n: int) -> bool:
        return self.repo.conn.execute(
            "SELECT 1 FROM rung_summaries WHERE campaign_id=? AND candidate_id=? AND analysis_version=? AND n=? LIMIT 1",
            (str(campaign_id), str(law), ANALYSIS_VERSION, int(n))).fetchone() is not None

    def bought_the_same_with_no_work(self, campaign_id: str, law: str, next_n: int, rule: str) -> bool:
        row = self.repo.conn.execute(
            f"SELECT action,next_n,rule,jobs_created FROM {LATEST} WHERE campaign_id=? AND candidate_id=?",
            (str(campaign_id), str(law))).fetchone()
        return (row is not None and row["action"] == "run_next" and row["next_n"] is not None
                and int(row["next_n"]) == int(next_n) and row["rule"] == rule and not int(row["jobs_created"] or 0))

    def record_decision(self, campaign_id: str, row: dict) -> None:
        from graph_scale_dynamics.decisions.decider import DECIDE_AGAIN, MADE_NO_WORK
        law = str(row["law"])
        now = utc_now()
        seen = self._marks.pop(law, None)
        if row.get("made_no_work") == DECIDE_AGAIN:
            seen = f"{REDECIDE_MARK}{now}"
        elif row.get("made_no_work") == MADE_NO_WORK:
            self.repo.conn.execute(
                "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                ("buy_made_no_work", json.dumps({"campaign_id": str(campaign_id), "candidate_id": law,
                                                 "rule": row.get("rule"), "next_n": row.get("next_n")}), now))
        self.repo.conn.execute(
            "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
            "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc,"
            "inputs_json,context_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(campaign_id), self._decision_id(campaign_id, law), law, row.get("at_n"), row.get("next_n"),
             row["action"], row["rule"], row["reason"], row.get("priority"), row.get("queue_order"),
             int(row.get("jobs_created") or 0), int(row.get("rows_changed") or 0), bool(row.get("released_hold")),
             seen if seen is not None else self._mark_now(campaign_id, law), row["engine"],
             json.dumps(row.get("facts") or {}, sort_keys=True, default=str), now,
             None if row.get("inputs") is None else json.dumps(row["inputs"], sort_keys=True, default=str),
             None if row.get("context") is None else json.dumps(row["context"], sort_keys=True, default=str)))
        _FAILING.pop((str(campaign_id), law), None)

    def _decision_id(self, campaign_id: str, law: str) -> str:
        stamp = time.time_ns()
        row = self.repo.conn.execute(f"SELECT decision_id FROM {LATEST} WHERE campaign_id=? AND candidate_id=?",
                                     (str(campaign_id), str(law))).fetchone()
        if row is not None and row["decision_id"]:
            try:
                stamp = max(stamp, int(str(row["decision_id"]).split("-", 1)[0]) + 1)
            except ValueError:
                pass
        return f"{stamp:020d}-{uuid.uuid4().hex[:8]}"

    def queue_depth(self, campaign_id: str) -> int:
        row = self.repo.conn.execute("SELECT COUNT(*) c FROM jobs WHERE campaign_id=? AND kind='simulate' "
                                     "AND status='queued'", (str(campaign_id),)).fetchone()
        return int(row["c"])

    def decision_rules_fingerprint(self, campaign_id: str) -> str:
        return self.repo.get_flag(f"decision_rules:{campaign_id}", "")

    def record_decision_rules_fingerprint(self, campaign_id: str, fingerprint: str) -> None:
        self.repo.set_flag(f"decision_rules:{campaign_id}", str(fingerprint))
        self.repo.set_flag(f"decision_rules_redo:{campaign_id}", "")

    def rules_redo_left(self, campaign_id: str, fingerprint: str) -> set | None:
        raw = self.repo.get_flag(f"decision_rules_redo:{campaign_id}", "")
        try:
            kept = json.loads(raw) if raw else None
        except ValueError:
            return None
        if not isinstance(kept, dict) or kept.get("rules") != str(fingerprint):
            return None
        return {str(law) for law in kept.get("left") or []}

    def record_rules_redo_left(self, campaign_id: str, fingerprint: str, laws: list) -> None:
        self.repo.set_flag(f"decision_rules_redo:{campaign_id}",
                           json.dumps({"rules": str(fingerprint), "left": [str(law) for law in laws]}))

    def parked_laws(self, campaign_id: str, limit: int = 100000) -> list:
        from graph_scale_dynamics.decisions.engine import PARKING_RULES
        rules = sorted(PARKING_RULES)
        rows = self.repo.conn.execute(
            f"SELECT d.candidate_id FROM {LATEST} d JOIN campaign_candidates c ON c.campaign_id=d.campaign_id "
            "AND c.candidate_id=d.candidate_id AND c.state=? WHERE d.campaign_id=? AND d.action='stop' "
            f"AND d.rule IN ({','.join('?' for _ in rules)}) "
            + _IDLE + "ORDER BY d.created_utc LIMIT ?",
            (CandidateState.PARKED.value, str(campaign_id), *rules, int(limit))).fetchall()
        return [str(r["candidate_id"]) for r in rows]

    def run_on_laws(self, campaign_id: str) -> dict[str, dict]:
        from graph_scale_dynamics.decisions import by_word
        named = by_word.entries_of(self.repo.get_flag(by_word.FLAG, ""), str(campaign_id))
        if not named:
            return {}
        rows = self.repo.conn.execute(
            f"SELECT d.candidate_id, d.rule, d.at_n FROM {LATEST} d JOIN campaign_candidates c "
            "ON c.campaign_id=d.campaign_id AND c.candidate_id=d.candidate_id AND c.state=? "
            f"WHERE d.campaign_id=? AND d.action='stop' AND d.candidate_id IN ({','.join('?' for _ in named)}) "
            + _IDLE + "ORDER BY d.candidate_id",
            (CandidateState.PARKED.value, str(campaign_id), *sorted(named))).fetchall()
        return {str(row["candidate_id"]): named[str(row["candidate_id"])] for row in rows
                if str(row["rule"]) == str(named[str(row["candidate_id"])]["gate"])
                and row["at_n"] is not None and int(row["at_n"]) == int(named[str(row["candidate_id"])]["at_n"])}

    def law_starts_reading(self, campaign_id: str, law: str) -> dict:
        from graph_scale_dynamics.observability import starts_reading, two_chains
        starts = ((self.spec or {}).get("sampling_contract") or {}).get("given_starts")
        if not self.policy.every_chain:
            self._keep_score(law, starts, lambda: (
                two_chains.chains_per_rung(self._law_measurements(campaign_id, law), starts), None))
            return {}
        chains = two_chains.chains_per_rung(self._law_measurements(campaign_id, law), starts)
        reading = starts_reading.law_reading(chains, starts, structure=starts_reading.hold_structure(self.spec))
        self._keep_score(law, starts, lambda: (chains, reading))
        compact = starts_reading.compact(reading)
        if self.policy.dimension_extends:
            from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS, chain_values
            from graph_scale_dynamics.research.dimension_rule import block
            compact = dict(compact, dimension=block(chain_values(chains), list(VALUE_COLUMNS),
                                                    compact.get("fates") or {}, read_at_top=True))
        if self.policy.steady_chain_gate:
            from graph_scale_dynamics.decisions import steady_chain
            from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS, chain_values
            found = steady_chain.block(chain_values(chains), list(VALUE_COLUMNS))
            compact = dict(compact, **({"steady": found} if found else {}))
        return {"starts_reading": compact}

    def _keep_score(self, law: str, starts, read) -> None:
        from graph_scale_dynamics.observability import starts_reading, law_score
        try:
            chains, reading = read()
            self.scored[str(law)] = law_score.compact(law_score.score(
                chains, reading, starts=starts, first_given=self._first_given(law),
                structure=starts_reading.hold_structure(self.spec)))
        except Exception:  # noqa: BLE001
            self.scored.pop(str(law), None)

    def law_score(self, campaign_id: str, law: str) -> dict:
        from graph_scale_dynamics.observability import starts_reading, law_score, two_chains
        rows = self.repo.measurements(law, ANALYSIS_VERSION, campaign_id)
        top = max((int(r["n"]) for r in rows if r.get("n") is not None), default=None)
        if top is None or top < law_score.LADDER[0]:
            return law_score.zero(top)
        from graph_scale_dynamics.observability import law_kind
        starts = ((self.spec or {}).get("sampling_contract") or {}).get("given_starts")
        chains = two_chains.chains_per_rung(rows, starts)
        found = law_score.compact(law_score.score(chains, starts=starts, first_given=self._first_given(law),
                                                  structure=starts_reading.hold_structure(self.spec)))
        kinds = law_kind.kinds(chains)
        return dict(found, kind=law_kind.deepest(kinds), kind_at_4096=law_kind.at(kinds))

    def _first_given(self, law: str) -> str | None:
        from graph_scale_dynamics.observability import law_score
        campaign_id = str(self.campaign.get("campaign_id"))
        return law_score.given_family(self.spec, str(law),
                                     lambda: (self.repo.candidate(str(law), campaign_id) or {}).get("spec"))

    def held_laws(self, campaign_id: str, limit: int = 256) -> list:
        rows = self.repo.conn.execute(
            f"SELECT d.candidate_id,d.at_n,d.next_n,d.priority,d.created_utc FROM {LATEST} d "
            "JOIN campaign_candidates c ON c.campaign_id=d.campaign_id AND c.candidate_id=d.candidate_id "
            f"AND c.state IN ({','.join('?' for _ in _LIVE_STATES)}) WHERE d.campaign_id=? AND d.action='hold' "
            + _IDLE + "ORDER BY d.created_utc LIMIT ?",
            (*_LIVE_STATES, str(campaign_id), int(limit))).fetchall()
        return [{"law": r["candidate_id"], "at_n": r["at_n"], "next_n": r["next_n"], "priority": r["priority"],
                 "since": r["created_utc"]} for r in rows]
