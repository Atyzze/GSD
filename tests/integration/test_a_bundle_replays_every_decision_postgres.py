from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.db.decision_store import DecisionStore
from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.decisions import decider as D
from graph_scale_dynamics.decisions.engine import Policy, Rung, Seed, decide
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.reporting import study_tables as T

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

ROOT = Path(__file__).resolve().parents[2]
SPEC = {"mode": "bounded", "ladder": [64, 256], "analysis_version": "record-contract-v1"}


def _tool():
    spec = importlib.util.spec_from_file_location("replay_bundle_under_test", ROOT / "tools" / "replay_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bundle_carries_every_decision_with_its_inputs_and_each_replays_from_them(isolated_postgres_schema,
                                                                                     monkeypatch, tmp_path):
    monkeypatch.setattr(T, "PAGE", 2)
    init_db(isolated_postgres_schema.dsn)
    policy = Policy()
    with Repo(isolated_postgres_schema.dsn) as repo:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        store = DecisionStore(repo, None, {"campaign_id": "camp", "spec": {}})
        for k in range(5):
            law = f"law{k}".ljust(64, "0")
            rungs = [Rung(n=64, mean_degree=float(k), connected_fraction=1.0, seeds=(Seed(termination="completed"),) * 3)]
            decision = decide(law, rungs, policy)
            store.record_decision("camp", dict(decision.as_dict(), inputs=D.decision_inputs(law, rungs, policy)))
        store.record_decision("camp", {"law": "law0".ljust(64, "0"), "at_n": 64, "next_n": 256, "action": "run_next",
                                       "rule": "held", "reason": "a hold let go", "released_hold": True,
                                       "engine": "decision-engine-2"})
        stored = {row["decision_id"]: row["inputs_json"] for row in repo.conn.execute(
            "SELECT decision_id,inputs_json FROM engine_decisions WHERE campaign_id='camp'").fetchall()}
        found = T.tables(repo, ["camp"])
    rows = [json.loads(line) for line in gzip.decompress(found["decisions.ndjson.gz"]).splitlines()]
    assert len(rows) == 6 == json.loads(found["README.json"])["tables"]["decisions.ndjson.gz"]["rows"]
    assert [r["decision_id"] for r in rows] == sorted(stored), "every row once, in order, across pages of two"
    assert {r["decision_id"]: r["inputs_json"] for r in rows} == stored, "the inputs as the decider stored them"
    tool = _tool()
    folder = tmp_path / "study" / "tables"
    folder.mkdir(parents=True)
    (folder / "decisions.ndjson.gz").write_bytes(found["decisions.ndjson.gz"])
    (tmp_path / "study" / "study.json").write_text("{}", encoding="utf-8")
    whole = tool.replay_rows(tool.rows_of(tmp_path / "study"))
    assert whole["counts"] == {"replays": 5, "released hold": 1} and whole["whole"]
    assert whole["by_campaign"]["camp"]["same_rules"] == {"true": 5}
    assert tool.main([str(tmp_path / "study")]) == 0
    rows[0]["facts_json"] = json.dumps({"moved": 1})
    broken = tool.replay_rows(rows)
    assert broken["counts"]["differs"] == 1 and not broken["whole"]
    assert broken["mismatches"][0]["decision_id"] == rows[0]["decision_id"]
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "study.json").write_text("{}", encoding="utf-8")
    assert tool.main([str(tmp_path / "bare")]) == 2, "a bundle without the table is refused, not read as whole"
