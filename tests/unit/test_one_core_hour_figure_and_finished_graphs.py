from __future__ import annotations

from graph_scale_dynamics.services.api import campaign_manager as manager


class _Conn:
    def __init__(self, by_sql):
        self.by_sql = by_sql

    def execute(self, sql, params=()):
        rows = self.by_sql[sql]

        class _Result:
            def fetchall(self):
                return rows
        return _Result()


class _Repo:
    def __init__(self, by_sql):
        self.conn = _Conn(by_sql)


def test_the_card_s_core_hours_carry_the_analysis_the_engine_does():
    repo = _Repo({manager._COMPUTE: [{"campaign_id": "1", "simulation_seconds": 9_500_000.0, "analysis_seconds": 0.0,
                                      "unsuccessful_seconds": 0.0}],
                  manager._ANALYSIS_COMPUTE: [{"campaign_id": "1", "analysis_seconds": 2_040_000.0}]})
    card = manager.compute_seconds(repo)["1"]
    assert card["analysis_core_seconds"] == 2_040_000.0 and card["core_seconds"] == 11_540_000.0
    assert "analysis_attempts" in manager._ANALYSIS_COMPUTE


def test_a_finished_graph_is_a_seed_once_however_many_jobs_ran_it():
    sql = manager._LAWS_BY_RUNG
    assert "COUNT(DISTINCT (candidate_id,seed)) FILTER (WHERE status='done' AND result_artifact IS NOT NULL) " \
           "AS finished" in sql
    assert "COUNT(DISTINCT (candidate_id,seed)) AS bought" in sql


def test_report_28_charges_each_part_of_a_rung_once():
    from graph_scale_dynamics.research.decision_engine_report import build_decision_engine_report

    def decision(i, action, rule, at_n, next_n):
        return {"decision_id": f"d{i:03d}", "action": action, "rule": rule, "at_n": at_n, "next_n": next_n,
                "facts": {}}
    decisions = {"law": [decision(1, "run_next", "base_block", 1024, 4096),
                         decision(2, "run_next", "longer_chain", 4096, 4096),
                         decision(3, "run_next", "starts_apart", 4096, 16384),
                         decision(4, "hold", "starts_apart", 16384, None),
                         decision(5, "run_next", "starts_apart", 4096, 16384)]}
    spend = [{"candidate_id": "law", "n": 4096, "core_seconds": 300.0, "longer_seconds": 200.0},
             {"candidate_id": "law", "n": 16384, "core_seconds": 1000.0, "longer_seconds": 0.0}]
    body = build_decision_engine_report({"campaign": {"spec": {}}, "engine_decisions": decisions, "rung_spend": spend})
    bought = {row["rule"]: row["core_seconds_bought"] for row in body["rules"] if row["action"] == "run_next"}
    assert bought == {"base_block": 100.0, "longer_chain": 200.0, "starts_apart": 1000.0}
    assert sum(bought.values()) == sum(row["core_seconds"] for row in spend)
