from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import quiet_report
from graph_scale_dynamics.operations import study as S

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def test_a_new_folder_starts_four_quadrants_each_with_its_budget(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        first = S.start_study(repo, control.shipped_spec(), search_seed=7, log=lambda *_: None)
        assert first == "1"
        rows = {str(r["campaign_id"]): r for r in repo.active_campaigns()}
        assert sorted(rows) == ["1", "2", "3", "4"]
        assert [S.quadrant_label(rows[c]["spec"]) for c in "1234"] == [
            "zero temperature, mean degree to 16", "zero temperature, mean degree to 32",
            "finite temperature, mean degree to 16", "finite temperature, mean degree to 32"]
        assert [int(rows[c]["search_seed"]) for c in "1234"] == [7, 8, 9, 10]
        assert all(S.law_budget(repo, c) == S.DEFAULT_LAW_BUDGET for c in "1234")
        assert quiet_report.reportable(repo) == ["1", "2", "3", "4"], "the study bundle reports all four"
        events = repo.conn.execute("SELECT COUNT(*) AS c FROM campaign_events WHERE "
                                   "event_type='campaign_law_budget_changed'").fetchone()["c"]
        assert events == 4
        from graph_scale_dynamics.services.api import campaign_manager
        shown = campaign_manager.panel(repo, "2")
        assert shown["available"] and shown["campaign"]["temperature"] == "zero"
        assert shown["campaign"]["mean_degree_window"]["max"] == 32.0
        assert shown["definition"]["dense_cap"] == 32.0 and shown["definition"]["search_seed"] == 8
        assert shown["definition"]["law_budget"]["law_budget"] == S.DEFAULT_LAW_BUDGET
        assert any(row["field"] == "limits" and not row["shipped_default"] for row in shown["frozen"])


def test_a_budget_closes_the_campaign_and_it_is_done_when_nothing_of_it_is_in_flight(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(control.shipped_spec(), search_seed=1)["campaign_id"])
        repo.insert_candidate("law-1", campaign_id, LAW, "metropolis", 1, "BASE_BLOCK_RUNNING")
        repo.insert_candidate("law-2", campaign_id, dict(LAW, terms=[{"kind": "edge_count", "coefficient": 0.4}]),
                              "metropolis", 1, "STOPPED")
        assert S.laws_held(repo, campaign_id) == 2
        assert S.set_law_budget(repo, campaign_id, 2)["ok"]
        assert S.budget_room(repo, campaign_id, S.laws_held(repo, campaign_id)) == 0
        state = S.budget_state(repo, campaign_id)
        assert (state["reached"], state["state"]) == (True, S.AT_BUDGET), "law-1 is still in its base block"
        repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE candidate_id='law-1'")
        assert S.budget_state(repo, campaign_id)["state"] == S.DONE
        assert S.set_law_budget(repo, campaign_id, 3)["ok"] and S.budget_state(repo, campaign_id)["state"] is None, (
            "raised past what it holds: open again")
