from __future__ import annotations

import gzip
import json
from pathlib import Path

from tools import budget_reading as B

COLUMNS = ["law", "n", "seed", "ended", "budget_ended", "budget_fraction", "work_budget", "work_units", "work_parts",
           "simulation_seconds", "final_mean_degree", "interrupted"]
WEIGHTS = {"moves": 1, "evaluations": 0, "changes": 0, "lists": 0, "entries": 0, "tests": 20}


def _seed(law, n, ended, units, moves, seconds, *, cut=False, tests=0, degree=4.0):
    return [law, n, 0, ended, cut, units / 100, 100, units, {"moves": moves, "tests": tests}, seconds, degree, 0]


def _report(laws, rows):
    return {"body": {"budgets": {"in_force": {"64": 100, "256": 100}, "unit": {"weights": WEIGHTS}},
                     "seeds": {"columns": COLUMNS, "laws": laws,
                               "rows": [[laws.index(row[0]), *row[1:]] for row in rows]}}}


def _table(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


def _bundle(tmp: Path) -> Path:
    root = tmp / "study_9_x"
    survey = _report(["A", "B", "C"], [
        _seed("A", 64, "ceiling", 50, 100, 1.0),
        _seed("A", 256, "budget", 90, 90, 9000.0, cut=True),
        _seed("B", 64, "completed", 10, 10, 1.0),
        _seed("B", 256, "budget", 300, 100, 30.0, cut=True, tests=10, degree=0.5),
        _seed("C", 64, "completed", 20, 20, 1.0)])
    controls = _report(["D"], [_seed("D", 256, "budget", 100, 100, 5.0, cut=True)])
    campaigns = []
    for cid, report, extra in (("1", survey, {}), ("2", controls, {"controls": {}})):
        folder = root / f"campaign_{cid}_reports_x"
        folder.mkdir(parents=True)
        (folder / "28-decision-engine.json").write_text(json.dumps(report), encoding="utf-8")
        campaigns.append({"campaign_id": cid, "bundle": folder.name, **extra})
    (root / "study.json").write_text(json.dumps({"study_id": "9", "build_number": 821, "built_utc": "t",
                                                 "campaigns": campaigns}), encoding="utf-8")
    (root / "tables").mkdir()
    _table(root / "tables" / "decisions.ndjson.gz", [
        {"campaign_id": "1", "candidate_id": "C", "at_n": 64, "action": "stop", "rule": "over_budget",
         "facts_json": json.dumps({"first_chunk": {"budget": 100, "predicted": 150}, "mean_degree": 6.0,
                                   "connected_fraction": 1.0, "budget_use": []})},
        {"campaign_id": "1", "candidate_id": "B", "at_n": 64, "action": "run_next", "rule": "salted",
         "facts_json": json.dumps({"salted": ["empty"]})},
        {"campaign_id": "1", "candidate_id": "A", "at_n": 64, "action": "run_next", "rule": "base_block",
         "facts_json": "{}"}])
    _table(root / "tables" / "rungs.ndjson.gz", [
        {"campaign_id": "1", "candidate_id": "A", "n": 256, "connected_fraction": 1.0},
        {"campaign_id": "1", "candidate_id": "B", "n": 256, "connected_fraction": 0.1},
        {"campaign_id": "1", "candidate_id": "C", "n": 64, "connected_fraction": 1.0}])
    return root


def test_every_size_s_cuts_stops_and_what_more_would_buy_are_read_from_the_bundle(tmp_path):
    found = B.read(_bundle(tmp_path))
    assert found["campaigns"] == ["1"] and found["laws"] == 3, "the controls are left out"
    small, large = found["sizes"]
    assert (large["n"], large["budget"], large["seeds_cut"], large["laws_cut"]) == (256, 100, 2, 2)
    assert (large["connected_laws"], large["connected_laws_cut"], large["other_laws_cut"]) == (1, 1, 1)
    assert (small["passed_every_gate"], small["stopped_over_budget"], small["passed_every_gate_then_stopped"]) == \
        (2, 1, 1), "B was judged by a gate at 64, C passed every gate and was stopped by the budget"
    assert small["stopped_would_fit"] == {"2": 1, "4": 1, "8": 1}
    assert large["passed_every_gate"] == 1, "a gate's verdict below a size counts there too"
    more = large["more"]
    assert (more["cut_seeds_estimated"], more["cut_seeds_without_a_ceiling_below"]) == (1, 1)
    assert more["multiple_p50"] == 4.0, "100 moves to the cap below, four times the size, a unit a move, budget 100"
    assert more["reach_their_end"] == {"2": 0.0, "4": 1.0, "8": 1.0}
    assert more["extra_core_hours"]["2"] == round(110 * 100 / 3600, 1)
    assert more["extra_core_hours"]["4"] == more["extra_core_hours"]["8"] == round(310 * 100 / 3600, 1)
    past = found["past_budget"]
    assert (past["seeds"], past["past_twice"], past["past_tenfold"]) == (1, 1, 0)
    assert past["worst"][0]["law"] == "B" and past["worst"][0]["leading_part"] == "tests"
    assert [row["law"] for row in found["stopped"]] == ["C"] and found["stopped"][0]["multiple"] == 1.5


def test_the_page_and_the_json_are_written_from_an_unpacked_bundle(tmp_path):
    root = _bundle(tmp_path)
    out = tmp_path / "reading.json"
    page = tmp_path / "reading.md"
    assert B.main([str(root), "--json", str(out), "--md", str(page)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["contract"] == B.CONTRACT and written["study"] == "9"
    text = page.read_text(encoding="utf-8")
    assert "| 256 | 100 | 0.391 |" in text and "`C`" in text and "| `B` | 256 | 0 | budget | 3.0x |" in text
