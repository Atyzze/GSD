from __future__ import annotations

import json


class ProposerRepo:
    def __init__(self):
        self.flags: dict[str, str] = {}
        self.events: list[tuple[str, dict]] = []
        self.laws: list[tuple[str, dict]] = []
        self.draws: dict[tuple[str, int, int], dict] = {}
        self.assessments: dict[str, dict] = {}
        self.conn = _Conn(self)

    def get_flag(self, key: str, default: str = "") -> str:
        return self.flags.get(key) or default

    def set_flag(self, key: str, value: str) -> None:
        self.flags[key] = value

    def emit(self, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))

    def _write(self, sql: str, params: tuple) -> None:
        assert sql.startswith("INSERT INTO proposal_draws"), sql
        for start in range(0, len(params), 7):
            campaign, stream, index, outcome, candidate, law_json, _ = params[start:start + 7]
            self.draws.setdefault((campaign, int(stream), int(index)),
                                  {"campaign_id": campaign, "stream_index": int(stream), "draw_index": int(index),
                                   "outcome": outcome, "candidate_id": candidate, "law_json": law_json,
                                   "law": json.loads(law_json)})

    def ledger(self, campaign_id: str) -> list[dict]:
        return [row for key, row in sorted(self.draws.items()) if key[0] == campaign_id]

    def insert_proposal_exposure(self, campaign_id: str, row: dict) -> None:
        pass

    def insert_candidate(self, candidate_id: str, campaign_id: str, spec: dict, *args, **kwargs) -> None:
        self.laws.append((candidate_id, spec))

    def insert_proposal_assessment(self, campaign_id, candidate_id, version, source, mode, assessment) -> None:
        self.assessments[candidate_id] = assessment

    def candidates(self) -> list[dict]:
        return [{"candidate_id": cid, "spec": spec} for cid, spec in self.laws]


class _Conn:
    def __init__(self, repo: ProposerRepo):
        self.repo = repo

    def _rows(self, campaign: str, keep) -> list[dict]:
        return [{k: v for k, v in row.items() if k != "law"} for key, row in sorted(self.repo.draws.items())
                if key[0] == campaign and keep(row)]

    def execute(self, sql: str, params: tuple):
        held = {cid for cid, _ in self.repo.laws}
        if sql.startswith("SELECT MAX(stream_index) AS m FROM proposal_draws WHERE campaign_id=? AND (outcome=? OR "):
            campaign, admitted, pattern = params
            rows = self._rows(campaign, lambda r: r["outcome"] == admitted or r["outcome"].startswith(
                pattern.rstrip("%")))
            return _Rows([{"m": max((r["stream_index"] for r in rows), default=None)}])
        if sql.startswith("SELECT d.* FROM proposal_draws d WHERE d.campaign_id=? AND d.outcome=? AND NOT EXISTS"):
            campaign, admitted = params
            return _Rows(self._rows(campaign, lambda r: r["outcome"] == admitted and r["candidate_id"] not in held))
        campaign, pattern = params
        prefix = pattern.rstrip("%")
        rows = self._rows(campaign, lambda r: r["outcome"].startswith(prefix))
        if sql.startswith("SELECT COUNT(*) AS c FROM proposal_draws WHERE campaign_id=? AND outcome LIKE ?"):
            return _Rows([{"c": len(rows)}])
        if sql.startswith("SELECT candidate_id FROM proposal_draws WHERE campaign_id=? AND outcome LIKE ?"):
            return _Rows([{"candidate_id": r["candidate_id"]} for r in rows])
        assert sql.startswith("SELECT * FROM proposal_draws WHERE campaign_id=? AND outcome LIKE ?"), sql
        return _Rows(rows)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class QuietLog:
    def write(self, *args, **kwargs) -> None:
        pass


def top_up_blind(repo: ProposerRepo, spec: dict, need: int, *, search_seed=631, campaign_id: str = "1") -> list:
    import random

    from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
    from graph_scale_dynamics.services.proposer import main as proposer
    from graph_scale_dynamics.services.proposer.blind import identity_version

    candidates = repo.candidates()
    version = identity_version((spec.get("search_policy") or {}).get("grid"))
    campaign = {"campaign_id": campaign_id, "spec": spec, "search_seed": search_seed}
    rng = random.Random(proposer.campaign_rng_seed(search_seed, len(candidates)))
    before = len(repo.laws)
    proposer._top_up_blind(repo, QuietLog(), campaign, candidates, need, rng,
                           {c["candidate_id"] for c in candidates},
                           {equilibrium_identity(c["spec"], version=version)[0] for c in candidates})
    return [spec for _, spec in repo.laws[before:]]
