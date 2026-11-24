from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.scheduling.reach import describe, reach  # noqa: E402

SPEC = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))


def test_the_shipped_spec_reaches_every_rung_it_declares():
    r = reach(SPEC)
    assert r["reachable"], r["problems"]
    assert r["problems"] == []
    assert all(row["work_budget"] > 0 and row["estimated_seconds"] > 0 for row in r["rungs"]), r["rungs"]
    assert [row["work_budget"] for row in r["rungs"]] == sorted(row["work_budget"] for row in r["rungs"])
    assert r["deepest_rung"] == 1048576


def test_a_ceiling_below_the_ladder_is_caught():
    spec = deepcopy(SPEC)
    spec["budgets"]["max_n"] = 16384
    r = reach(spec)
    assert not r["reachable"]
    assert any("budgets.max_n" in p and "forbidden" in p for p in r["problems"]), r["problems"]


def test_a_rung_nothing_will_ever_buy_is_caught():
    spec = deepcopy(SPEC)
    spec["extension_ladder"] = [65536, 262144]
    r = reach(spec)
    assert any("nothing will ever buy it" in p for p in r["problems"]), r["problems"]


def test_the_report_says_the_spec_is_frozen():
    text = describe(SPEC)
    assert "frozen at creation" in text and "never adapted" in text
    assert "N=1048576" in text
