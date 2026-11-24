from __future__ import annotations

import dataclasses
import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gate_variants as V  # noqa: E402


def _fake_replay(inputs: dict):
    policy = inputs["policy"]
    needed = int(policy["fact_sizes_in_a_row"])
    if inputs["empty_sizes"] >= needed and not policy["one_die"]:
        return SimpleNamespace(action="stop", rule="empty")
    return SimpleNamespace(action="run_next", rule="base_block")


def _row(law: str, n: int, empty_sizes: int, action: str, rule: str, campaign: str = "1") -> dict:
    inputs = {"policy": {"fact_sizes_in_a_row": 3, "one_die": False}, "empty_sizes": empty_sizes}
    return {"campaign_id": campaign, "candidate_id": law, "at_n": n, "action": action, "rule": rule,
            "inputs_json": json.dumps(inputs)}


def _bundle(tmp_path: Path) -> Path:
    rows = [_row("law-a", 256, 2, "run_next", "base_block"), _row("law-a", 1024, 3, "stop", "empty"),
            _row("law-b", 256, 1, "run_next", "base_block"), _row("law-b", 1024, 2, "run_next", "base_block"),
            _row("law-c", 1024, 3, "stop", "empty", campaign="2"),
            {"campaign_id": "1", "candidate_id": "law-a", "at_n": None, "action": "run_next", "rule": "start",
             "inputs_json": None}]
    (tmp_path / "tables").mkdir()
    with gzip.open(tmp_path / "tables" / "decisions.ndjson.gz", "wt", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row) + "\n")
    return tmp_path


def test_each_decision_is_replayed_with_one_setting_changed_and_a_law_counted_where_its_fate_first_changes(
        tmp_path, monkeypatch):
    import graph_scale_dynamics.decisions.replay as R
    monkeypatch.setattr(R, "replay", _fake_replay)
    found = V.read(_bundle(tmp_path), ("fact_sizes_in_a_row=1", "fact_sizes_in_a_row=4", "one_die=flip"), {"1"})
    assert found["decisions"] == 4 and found["laws"] == 2
    one = found["variants"]["fact_sizes_in_a_row=1"]
    assert one["recorded"] == {"3": 4}
    assert one["by_size"] == {"256": {"stops": 2, "goes on": 0, "laws_stopping": ["law-a", "law-b"],
                                      "laws_going_on": []}}, "law-a counted at 256, where it would first stop"
    assert one["decisions_moved"] == 3 and one["laws_whose_fate_changes"] == 2
    four = found["variants"]["fact_sizes_in_a_row=4"]
    assert four["by_size"] == {"1024": {"stops": 0, "goes on": 1, "laws_stopping": [], "laws_going_on": ["law-a"]}}
    flipped = found["variants"]["one_die=flip"]
    assert flipped["by_size"]["1024"]["goes on"] == 1 and flipped["moved"] == [
        {"n": 1024, "recorded": "stop:empty", "variant": "run_next:base_block", "decisions": 1}]
    assert "law-c" not in json.dumps(found), "the controls are left out"
    text = V.render(found)
    assert "N=256: 2 would stop that went on, 0 would go on that stopped" in text


def test_a_setting_is_read_as_its_type_and_flip_turns_the_recorded_one_over():
    inputs = {"policy": {"one_die": True, "fact_sizes_in_a_row": 3, "dense_cap": 32.0}}
    assert V.changed_inputs(inputs, "one_die", "flip")["policy"]["one_die"] is False
    assert V.changed_inputs(inputs, "fact_sizes_in_a_row", "4")["policy"]["fact_sizes_in_a_row"] == 4
    assert V.changed_inputs(inputs, "dense_cap", "16.5")["policy"]["dense_cap"] == 16.5
    assert inputs["policy"]["one_die"] is True, "the recorded inputs are left as they were"
    assert V.fate("hold") == "goes on" and V.fate("stop") == "stops" and V.fate("park") == "stops"


def test_the_default_settings_are_the_policy_s_own_fields():
    from graph_scale_dynamics.decisions.engine import Policy
    fields = {field.name for field in dataclasses.fields(Policy)}
    assert {V.parsed_variant(text)[0] for text in V.VARIANTS} <= fields


def test_a_bundle_without_the_decisions_table_is_said(tmp_path, capsys):
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": []}))
    assert V.main([str(tmp_path)]) == 2
    assert "no decisions table" in capsys.readouterr().err
