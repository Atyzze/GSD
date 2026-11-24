from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import two_runs as TR  # noqa: E402

LAWS = ["a" * 64, "b" * 64]
COLUMNS = ["law", "n", "seed", "attempts", "simulation_seconds", "d_s_seconds", "final_edges", "work_units",
           "interrupted", "die"]


def _table(root: Path, name: str, rows: list) -> None:
    with gzip.open(root / "tables" / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _run(tmp_path: Path, tag: str, *, slower: float = 1.0, hours: float = 10.0, edges: int = 40,
         lane: bool = False, state: str = "done", when=None, laws=LAWS, acting: float = 0.1,
         gap: float = 0.0020971503853179) -> Path:
    root = tmp_path / f"study_173_{tag}"
    (root / "tables").mkdir(parents=True)
    part = root / "campaign_1_reports_x"
    part.mkdir()
    (root / "study.json").write_text(json.dumps({"study_id": "173", "campaigns": [
        {"campaign_id": "1", "study_design": {"study": "173"}, "created_utc": "2026-11-22T00:00:00Z",
         "state": state}]}))
    _table(root, "laws.ndjson.gz", [{"campaign_id": "1", "candidate_id": law, "top_n": 1024} for law in LAWS])
    _table(root, "rungs.ndjson.gz", [{"campaign_id": "1", "candidate_id": law, "n": 64, "d_s": 2.0} for law in LAWS])
    _table(root, "draws.ndjson.gz", [{"campaign_id": "1", "stream_index": 0, "draw_index": i} for i in range(2)])
    _table(root, "chains.ndjson.gz", [
        {"campaign_id": "1", "candidate_id": law, "n": 64, "seed": s, "replicate": 0, "chain": "cubic",
         "audit": False, "final_edges": edges if (law, s) == (LAWS[0], 0) else 40, "job_id": f"{tag}{s}",
         "seed_peak_memory_bytes": 10 * s + len(tag)} for law in LAWS for s in range(3)])
    decisions = []
    for i, law in enumerate(laws):
        end = f"2026-11-22T{int((when or [hours] * len(laws))[i]):02d}:00:00Z"
        decisions.append({"campaign_id": "1", "candidate_id": law, "decision_id": f"{tag}{i}0", "at_n": 64,
                          "action": "run_next", "rule": "base_block", "next_n": 256, "reason": "r",
                          "created_utc": end, "facts_json": json.dumps({"lane": {"in_flight": len(tag)},
                                                                        "gap": gap}),
                          "inputs_json": json.dumps({"policy": {"salt_shares": [["empty", 256, acting]] + (
                              [["cut", 256, 1.0]] if len(tag) == 1 else [])}, "learned": {"undecided": len(tag)}})})
        if lane:
            decisions.append({"campaign_id": "1", "candidate_id": law, "decision_id": f"{tag}{i}1", "at_n": 64,
                              "action": "hold", "rule": "deep_lane_full", "next_n": 256, "created_utc": end})
    _table(root, "decisions.ndjson.gz", decisions)
    rows = [[i, 64, s, 1 + int(slower > 1), 100.0 * slower, 20.0 * slower, 40, 5000, 0, (s + len(tag)) % 2]
            for i in range(2) for s in range(3)]
    (part / "evidence").mkdir()
    busy = 16 if len(tag) == 1 else 23
    (part / "evidence" / "performance.json").write_text(json.dumps({"occupancy_series": [
        {"utc": f"2026-11-22T0{i}:00:00Z", "active_simulations": busy - 2 - i % 2, "active_analyses": 2 + i % 2,
         "cpu_percent": 57.0 if busy == 16 else 76.0} for i in range(4)]}))
    (part / "28-decision-engine.json").write_text(json.dumps({"body": {"seeds": {"columns": COLUMNS, "laws": LAWS,
                                                                                 "rows": rows}}}))
    return root


def test_the_same_design_run_twice_on_more_workers_is_the_same_law_by_law_and_its_gain_is_read(tmp_path):
    found = TR.read(_run(tmp_path, "a", hours=10.0), _run(tmp_path, "bb", slower=1.5, hours=6.0, lane=True))
    assert found["same"], found
    assert found["decisions"]["timing_left_out"]["second"] == {"facts.lane": 2, "inputs.learned": 2, "lane rows": 2}
    assert found["decisions"]["timing_left_out"]["first"]["inputs.policy.salt_shares recording"] == 2, (
        "a gate that only records has a share of 1 in one run and none in the other: no difference")
    speed = found["speed"]
    assert speed["gain"] == round(10 / 6, 3) and speed["wall"]["second"]["hours"] == 6.0
    assert speed["by_size"]["64"]["slowdown_median"] == 1.5 and speed["by_size"]["64"]["seeds"] == 6
    assert speed["worker_hours"] == {"first": round(6 * 120 / 3600, 2), "second": round(6 * 180 / 3600, 2)}
    assert speed["slots"]["first"]["busy"] == 16 and speed["slots"]["second"]["busy"] == 23
    assert speed["slots"]["second"]["cpu_percent"] == 76.0 and speed["slots"]["first"]["analyses"] == 2.5
    assert speed["reached"]["decisions"] == 2 and speed["reached"]["marks"]["second"][1.0] == 6.0
    text = TR.render(found)
    assert "the same, law by law" in text and "gain 1.667" in text
    assert "16 busy on average" in text and "23 busy on average" in text
    assert "the 2 decisions both made: first run half by 10.0 h" in text


def test_a_chain_that_ended_otherwise_is_named(tmp_path):
    found = TR.read(_run(tmp_path, "a"), _run(tmp_path, "b", edges=41))
    assert not found["same"] and found["tables"]["chains.ndjson.gz"]["counts"]["differ"] == 1
    assert LAWS[0] in found["tables"]["chains.ndjson.gz"]["differ"][0]
    assert found["decisions"]["same"] and found["seeds"]["same"]


def test_a_reading_apart_by_less_than_one_part_in_10_to_the_8_is_named_and_is_not_a_difference(tmp_path):
    found = TR.read(_run(tmp_path, "a"), _run(tmp_path, "bb", gap=0.0020971503859))
    assert found["same"] and found["decisions"]["last_digits_count"] == 2
    assert "2 laws the same but for readings within 1e-08" in TR.render(found)
    apart = TR.read(_run(tmp_path / "x", "a"), _run(tmp_path / "x", "bb", gap=0.00209716))
    assert not apart["same"] and apart["decisions"]["first_difference"] == {"N=64 facts": 2}


def test_a_share_that_acts_differently_is_a_difference(tmp_path):
    found = TR.read(_run(tmp_path, "a"), _run(tmp_path, "bb", acting=0.01))
    assert not found["same"] and not found["decisions"]["same"] and found["seeds"]["same"]


def test_a_run_stopped_part_way_is_compared_on_what_both_finished_and_its_work_in_the_same_hours(tmp_path):
    first = _run(tmp_path, "a", when=[1.0, 4.0], state="at its law budget")
    second = _run(tmp_path, "bb", when=[1.0, 2.0], slower=1.5, laws=LAWS[:1], state="at its law budget")
    found = TR.read(first, second)
    assert found["compared"] == "what both runs had finished" and found["same"], found
    window = found["speed"]["window"]
    assert window["hours"] == 1.0 and window["work_units"] == {"first": 15000, "second": 15000}
    assert window["gain"] == 1.0 and window["by_size"] == {"64": [15000, 15000]}
    assert found["speed"]["reached"]["by_size"]["64"]["first"][1.0] == 1.0
    assert "gain" not in TR.render(found).split("speed:")[1].split("\n")[0], "no wall gain of runs of other lengths"
    wider = TR.read(_run(tmp_path / "c", "a", when=[1.0, 4.0], state="at its law budget"),
                    _run(tmp_path / "c", "bb", when=[1.0, 1.0], state="at its law budget"))
    assert wider["speed"]["window"]["gain"] == 2.0, "twice the work done in the same hour"
    strict = TR.read(_run(tmp_path / "d", "a"), _run(tmp_path / "d", "bb", laws=LAWS[:1]))
    assert strict["compared"] == "the whole of both runs" and not strict["same"], "done runs must hold the same laws"
