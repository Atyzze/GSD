from __future__ import annotations

import json

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.operations.campaign_control import shipped_spec
from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
from graph_scale_dynamics.services.api import campaign_manager as M


class Conn:
    def execute(self, sql, params=()):
        class Result:
            def fetchone(self):
                return {"c": 2468} if "COUNT(*)" in sql else None
        return Result()


class Repo:
    def __init__(self):
        self.flags = {f"{S.LAW_BUDGET_PREFIX}2": "5000"}
        self.conn = Conn()

    def get_flag(self, key, default=None):
        return self.flags.get(key, default)

    def campaign_pending_work(self, campaign_id):
        return False


def test_the_table_row_says_the_temperature_and_the_mean_degree_window():
    labels = [label for label, _ in S.quadrant_specs(shipped_spec())]
    specs = [freeze_campaign_spec(spec) for _, spec in S.quadrant_specs(shipped_spec())]
    assert [M.temperature_of(spec) for spec in specs] == ["zero", "zero", "finite", "finite"], labels
    assert [spec["limits"]["mean_degree_window"]["max"] for spec in specs] == [16.0, 32.0, 16.0, 32.0]
    assert M.temperature_of(shipped_spec()) == "both" and M.temperature_of({}) == "finite"


def test_the_panel_carries_the_definition_the_grid_does_not():
    spec = freeze_campaign_spec(S.quadrant_specs(shipped_spec())[1][1])
    made = M.definition(Repo(), {"campaign_id": "2", "spec": spec, "search_seed": 8})
    assert made["quadrant"] == "zero temperature, mean degree to 32" and made["temperature"] == "zero"
    assert made["mean_degree_window"] == {"min": 0.0, "max": 32.0} and made["dense_cap"] == 32.0
    assert made["ladder"][0] == 64 and made["ladder"][-1] == 1048576
    budgets = {n: (units, seconds) for n, units, seconds in made["work_budgets"]}
    assert budgets[65536][0] == Policy.from_spec(spec).work_budget(65536) and budgets[65536][1] > 0
    assert made["salt"] == 0.1 and made["search_seed"] == 8
    assert (made["law_budget"]["law_budget"], made["law_budget"]["laws_held"]) == (5000, 2468)
    json.dumps(made)
    frozen = {row["field"]: row for row in M.inherited_fields(spec)}
    assert not frozen["limits"]["shipped_default"], "the 32 cap is the one field that sets it apart"
