from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import study_baseline  # noqa: E402


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "study_9_bundle"
    reports = root / "campaign_1_reports_x_y"
    reports.mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"study_id": "9"}), encoding="utf-8")
    body = {"laws": [{"candidate_id": "a", "action": "stop", "rule": "failed", "at_n": 262144}],
            "every_chain": {"laws": {}},
            "seeds": {"columns": ["law", "n", "cpu_seconds"], "laws": ["a"], "rows": [[0, 64, 3600.0]]},
            "law_ledger": {"rows": [{"candidate_id": "a", "kind": "sees cycles", "spec": {"terms": [["edge_count"]]}}]}}
    (reports / "28-decision-engine.json").write_text(json.dumps({"body": body}), encoding="utf-8")
    (root / "tables").mkdir()
    with gzip.open(root / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as out:
        out.write(json.dumps({"candidate_id": "a", "decision": {"action": "done", "rule": "ladder_complete",
                                                                 "at_n": 262144}}) + "\n")
    return root


def test_a_law_decided_again_after_the_report_ends_as_the_folder_held_it(tmp_path):
    found = study_baseline.read(_bundle(tmp_path))
    assert found["per_law"][0]["end"] == ["done", "ladder_complete", 262144]
    assert found["ends"] == {"ladder_complete": 1} and found["core_hours"] == 1.0


def test_the_baseline_names_its_own_study(tmp_path):
    found = study_baseline.read(_bundle(tmp_path))
    assert found["study"] == "9" and study_baseline.render(found).startswith("# Study 9, the baseline")


def test_each_gate_s_let_through_laws_are_counted_by_how_many_scored(tmp_path, monkeypatch):
    root = _bundle(tmp_path)
    (root / "gates_ledger.json").write_text(json.dumps({"gates": {
        "starts_alike": {"65536": {"label": "A/B", "held": 3, "let_through": 2, "laws": ["1:a", "1:z"]}},
        "empty": {"256": {"label": "A/B", "held": 9, "let_through": 1}}}}), encoding="utf-8")
    laws = [{"campaign": "1", "law": "a", "score": {"score": 71}}, {"campaign": "1", "law": "z", "score": None}]
    rows = study_baseline.gates_scored(root, laws)
    assert rows == [{"gate": "starts_alike", "n": 65536, "label": "A/B", "held": 3, "let_through": 2, "scored": 1,
                     "best": [{"law": "1:a", "score": 71.0}]}], "a counter that lists no laws is not guessed at"
    found = dict(study_baseline.read(root), gates_scored=rows)
    assert "| `starts_alike` | 65,536 | A/B | 3 | 2 | 1 | a 71 |" in study_baseline.render(found)
