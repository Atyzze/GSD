from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import counters_reading as CR  # noqa: E402


def _bundle(tmp_path: Path, decisions: list, laws: list) -> Path:
    root = tmp_path / "study_9_2026-01-01T00-00-00Z"
    (root / "tables").mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"campaigns": [
        {"campaign_id": "1", "study_design": {"campaign": 0}}, {"campaign_id": "2", "study_design": {"campaign": 1}},
        {"campaign_id": "3", "study_design": {"campaign": 2}}, {"campaign_id": "4"}]}))
    for name, rows in (("decisions.ndjson.gz", decisions), ("laws.ndjson.gz", laws)):
        with gzip.open(root / "tables" / name, "wt", encoding="utf-8") as handle:
            handle.writelines(json.dumps(row) + "\n" for row in rows)
    return root


def _row(campaign: str, law: str, fingerprint: str, rule: str = "lt") -> dict:
    return {"campaign_id": campaign, "candidate_id": law, "decision_id": f"d{campaign}{law}", "at_n": 256,
            "action": "run_next", "rule": "start", "facts_json": json.dumps({"salted": ["empty"], "signature": "k5"}),
            "inputs_json": json.dumps({"policy": {"let_through_rule": rule}, "policy_fingerprint": fingerprint})}


def test_a_learning_row_reads_what_the_store_reads():
    row = CR.learning_row(_row("1", "a", "f"))
    assert row["salted"] == ["empty"] and row["signature"] == "k5" and row["at_n"] == 256
    assert CR.learning_row(dict(_row("1", "a", "f"), facts_json="not json"))["salted"] is None


def test_the_batches_read_together_are_the_study_s_on_one_rule(tmp_path):
    decisions = [_row("1", "a", "f"), _row("2", "b", "f"), _row("3", "c", "other"), _row("4", "d", "f")]
    root = _bundle(tmp_path, decisions, [])
    assert CR.batches_of(root, decisions) == {"1": 0, "2": 1}, (
        "a campaign on another policy, or outside the study's design, is read by neither way")


def test_a_bundle_with_nothing_learned_reads_whole_and_changes_nothing(tmp_path):
    laws = [{"campaign_id": "1", "candidate_id": "a", "candidate_number": 1}]
    root = _bundle(tmp_path, [_row("1", "a", "f")], laws)
    found = CR.read(root)
    assert found["learned_decisions"] == 0 and found["C2_per_batch_reproduced"] and found["C3_first_group_alike"]
    assert found["study_wide"]["decisions_that_change_count"] == 0
    assert "the gates' counters" in CR.render(found)
