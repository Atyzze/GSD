from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.observability.live_panel import selection_summary
from graph_scale_dynamics.scheduling.limits import estimated_seconds, work_budget

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text(encoding="utf-8"))
SUMMARY = selection_summary(SPEC)
STAGES = {s["sizes"][0]: s for s in SUMMARY["stages"]}
POLICY = Policy.from_spec(SPEC)


def test_the_mechanisms_are_the_engines_rules_and_every_rung_is_an_integer():
    names = [m["name"] for m in SUMMARY["mechanisms"]]
    assert names[:6] == ["budget in work", "over budget", "too dense", "empty", "disconnected", "buy by settling"]
    assert [m["rule"] for m in SUMMARY["mechanisms"]][:6] == [
        "budget", "over_budget", "too_dense", "empty", "disconnected", "d_s_settled"]
    by_rule = {m["rule"]: m["from_n"] for m in SUMMARY["mechanisms"]}
    assert (by_rule["too_dense"], by_rule["empty"], by_rule["budget"], by_rule["over_budget"]) == (
        POLICY.dense_from_n, POLICY.empty_from_n, None, POLICY.base_sizes[1])
    assert all(m["active"] for m in SUMMARY["mechanisms"])
    assert all(".0" not in m["applies_from"] for m in SUMMARY["mechanisms"])
    assert {m["name"]: m["from_n"] for m in SUMMARY["mechanisms"]}["disconnected"] == POLICY.connectivity_from_n


def test_what_holds_everywhere_is_said_once():
    rule = next(r for r in SUMMARY["every_rung"] if "never passes its certificate" in r)
    assert not any("never passes its certificate" in change for s in SUMMARY["stages"] for change in s["changes"]), rule


def test_the_ladder_is_walked_in_order_one_row_per_rung():
    assert [n for s in SUMMARY["stages"] for n in s["sizes"]] == [64, 256, 1024, 4096, 16384, 65536, 262144,
                                                                   1048576]
    assert all(len(stage["sizes"]) == 1 for stage in SUMMARY["stages"])
    assert [STAGES[n]["lane"] for n in (4096, 16384, 1048576)] == ["base", "extension", "extension"]


def test_the_first_rung_says_what_is_special_about_it():
    assert "every admitted law starts here" in " ".join(STAGES[64]["changes"])


def test_each_later_rung_names_only_what_arms_there():
    at_256 = " ".join(STAGES[256]["changes"])
    assert "mean degree reaches 16" in at_256 and "empty" in at_256 and "largest component" not in at_256
    assert "largest component" in " ".join(STAGES[1024]["changes"])
    assert "last base rung" in " ".join(STAGES[4096]["changes"])


def test_each_limit_is_the_budget_the_jobs_get_with_its_hours_beside():
    for n in (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576):
        assert STAGES[n]["limit_units"] == POLICY.work_budget(n) == work_budget(SPEC, n)
        assert STAGES[n]["limit_seconds"] == round(estimated_seconds(SPEC, n), 1)
        assert STAGES[n]["limit"].endswith(("min", " h", " s")) and "units, about" in STAGES[n]["limit"]
        assert "limit_basis" not in STAGES[n], "the header says what the limit is, once"


def test_a_spec_without_the_engine_is_shown_as_refused():
    refused = selection_summary({"name": "old"})
    assert "refused" in refused["headline"] and refused["stages"] == []


def test_the_budget_ends_a_seed_between_chunks_and_stops_no_law():
    from graph_scale_dynamics.observability.live_panel import BUDGET_TEXT
    budget = next(m for m in SUMMARY["mechanisms"] if m["rule"] == "budget")
    assert budget["does"] == BUDGET_TEXT and "no clock ends a seed" in BUDGET_TEXT
    assert any("read and the law decided as any other" in line for line in SUMMARY["every_rung"])
