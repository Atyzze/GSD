from __future__ import annotations

import json
import random

import pytest

from graph_scale_dynamics.db.draw_ledger import insert_proposal_draws, proposal_draws
from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.services.proposer.blind import blind_batch

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "record-contract-v1"}
WHITELIST = ["edge_count", "degree_anchor", "triangle_count", "degree_fourth_sum"]


def test_every_draw_is_stored_once_and_a_law_keeps_its_axes(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        ledger: list = []
        laws = blind_batch(random.Random(9), 5, WHITELIST, None, set(), set(), fingerprint=dsl.fingerprint,
                           physical_identity=dsl.fingerprint, ledger=ledger)
        assert insert_proposal_draws(repo, "camp", 0, ledger) == len(ledger)
        insert_proposal_draws(repo, "camp", 0, ledger)
        stored = proposal_draws(repo, "camp")
        assert len(stored) == len(ledger)
        assert [(r["draw_index"], r["outcome"]) for r in stored] == [(d["draw_index"], d["outcome"]) for d in ledger]
        assert stored[0]["law"] == json.loads(json.dumps(ledger[0]["law"], sort_keys=True))

        law = dict(laws[0])
        law["dynamics"] = dict(law["dynamics"], locality=0.4, zero_temperature=True)
        law = dsl.normalize(law)
        law_id = dsl.fingerprint(law)
        repo.insert_candidate(law_id, "camp", law, "equilibrium", dsl.complexity(law), "PROPOSED")
        row = dict(repo.conn.execute("SELECT regime,beta,locality,local_move,zero_temperature,swap_share,"
                                     "reduced_basis_json FROM candidate_specs WHERE candidate_id=?",
                                     (law_id,)).fetchone())
        assert row["regime"] == "zero_temperature" and row["zero_temperature"] is True
        assert row["locality"] == 0.4 and row["local_move"] == "toggle"
        assert row["beta"] == law["dynamics"]["beta"] and row["swap_share"] is not None
        assert json.loads(row["reduced_basis_json"])
    finally:
        repo.close()


def test_a_study_bundle_carries_every_draw_with_its_stratum(isolated_postgres_schema):
    import gzip

    from graph_scale_dynamics.reporting.study_tables import tables
    from graph_scale_dynamics.research.strata import stratum_of, stratum_shares
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        ledger: list = []
        blind_batch(random.Random(9), 30, WHITELIST, None, set(), set(), fingerprint=dsl.fingerprint,
                    physical_identity=dsl.fingerprint, ledger=ledger)
        for stream in (0, 1):
            insert_proposal_draws(repo, "camp", stream, ledger)
        found = tables(repo, ["camp"])
        rows = [json.loads(line) for line in gzip.decompress(found["draws.ndjson.gz"]).splitlines()]
        assert len(rows) == 2 * len(ledger) and json.loads(found["README.json"])["tables"]["draws.ndjson.gz"]["rows"] \
            == len(rows)
        assert [(r["stream_index"], r["draw_index"]) for r in rows] == sorted((r["stream_index"], r["draw_index"])
                                                                             for r in rows)
        stored = proposal_draws(repo, "camp")
        assert [r["stratum"] for r in rows] == [stratum_of(r["law"]) for r in stored]
        assert stratum_shares(rows) == stratum_shares(stored), "the table reweights as the ledger does"
    finally:
        repo.close()


def test_a_study_bundle_s_laws_carry_their_regime(isolated_postgres_schema):
    import gzip

    from graph_scale_dynamics.reporting.study_tables import tables
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        base = blind_batch(random.Random(9), 4, WHITELIST, None, set(), set(), fingerprint=dsl.fingerprint,
                           physical_identity=dsl.fingerprint, ledger=[])
        settings = [{"zero_temperature": True}, {"locality": 0.6},
                    {"locality": 0.4, "local_move": "toggle"}, {"locality": 0.0}]
        ids = []
        for law, extra in zip(base, settings, strict=True):
            law = dsl.normalize(dict(law, dynamics=dict(law["dynamics"], **extra)))
            ids.append(dsl.fingerprint(law))
            repo.insert_candidate(ids[-1], "camp", law, "equilibrium", dsl.complexity(law), "PROPOSED")
        found = tables(repo, ["camp"])
        laws = {r["candidate_id"]: r for r in map(json.loads, gzip.decompress(found["laws.ndjson.gz"]).splitlines())}
        assert [laws[i]["regime"] for i in ids] == ["zero_temperature", "equilibrium", "equilibrium", "equilibrium"]
        source = json.loads(found["README.json"])["tables"]["laws.ndjson.gz"]["source"]
        assert "regime" in source
    finally:
        repo.close()
