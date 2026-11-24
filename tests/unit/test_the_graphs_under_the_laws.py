from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.reporting import gate_trees_page as P
from graph_scale_dynamics.research import gate_tree as T
from graph_scale_dynamics.research import graph_trickle as GT
from graph_scale_dynamics.scheduling import memory_hold
from graph_scale_dynamics.services.api import campaign_manager as CM

_ids = iter(range(10_000))


def row(at_n, action, rule):
    return {"decision_id": f"d{next(_ids):05d}", "at_n": at_n, "action": action, "rule": rule, "facts": {}}


DECISIONS = {"A": [row(256, "run_next", "base_block"), row(1024, "run_next", "base_block")],
             "B": [row(256, "stop", "empty")],
             "C": [row(256, "run_next", "base_block")]}
COLUMNS = ["law", "n", "seed", "attempts", "simulation_seconds", "cpu_seconds", "peak_memory_bytes", "final_edges",
           "final_mean_degree", "ended", "window_fraction", "d_s_seconds", "d_V_seconds", "d_B_seconds",
           "d_w_seconds", "interrupted"]


def seed(law, n, s, wall=1.0, degree=3.0):
    return [law, n, s, 1, wall, wall, 1, 10, degree, None, 0.1, 0.1, 0.1, 0.1, 0.1, 0]


SEEDS = {"columns": COLUMNS, "laws": ["A", "B", "C"],
         "rows": [seed(0, 256, s) for s in range(3)] + [seed(1, 256, s) for s in range(3)]
         + [seed(2, 256, s) for s in range(3)] + [seed(0, 1024, s, degree=4.0) for s in range(3)]
         + [seed(2, 1024, 0, degree=5.0), seed(2, 1024, 1, wall=None)]}


def test_each_rung_counts_the_graphs_its_laws_grew_beside_the_laws():
    tree = T.build_gate_tree(DECISIONS, GT.graphs_per_law_rung(SEEDS))
    rungs = {r["n"]: r for r in tree["rungs"]}
    assert rungs[256]["finished"] == 3 and rungs[256]["graphs"] == 9
    assert rungs[256]["graphs_by_branch"] == {"on": 6, "stopped": 3}
    assert rungs[1024]["finished"] == 1 and rungs[1024]["graphs"] == 3
    assert rungs[1024]["graphs_in_progress"] == 1, "C's finished seed at a rung C has not finished"
    assert tree["graphs"] == 13, "every finished simulation, the GRAPHS tile's count"
    plain = T.build_gate_tree(DECISIONS)
    assert "graphs" not in plain and "graphs" not in plain["rungs"][0], "no seed table, no count"


def census(n, degrees, giant):
    histogram = {}
    for d in degrees:
        histogram[str(d)] = histogram.get(str(d), 0) + 1
    return {"degree_histogram": histogram, "largest_component": {"size": giant}}


def test_the_graphs_by_rung_say_what_the_graphs_were():
    measurements = [
        {"candidate_id": "A", "n": 256, "seed": 0, "created_utc": "1",
         "metrics": {"d_s": {"valid": True}, "census": {"empty": census(256, [2] * 256, 256),
                                                        "given": census(256, [2] * 256, 256)}}},
        {"candidate_id": "A", "n": 256, "seed": 1, "created_utc": "1",
         "metrics": {"d_s": {"valid": False}, "census": {"empty": census(256, [2] * 256, 256),
                                                         "given": census(256, [0] * 128 + [1] * 128, 2)}}}]
    reading = GT.build_graphs_by_rung(SEEDS, measurements, DECISIONS)
    assert reading["graphs"] == 13
    rungs = {r["n"]: r for r in reading["rungs"]}
    assert rungs[256]["graphs"] == 9 and rungs[256]["laws"] == 3
    assert rungs[256]["by_branch"] == {"on": 6, "stopped": 3}
    assert rungs[1024]["by_branch"] == {"on": 3, "in_progress": 1}
    assert rungs[1024]["median_mean_degree"] == 4.0
    assert rungs[256]["measured"] == 2 and rungs[256]["d_s_readable_share"] == 0.5
    assert rungs[256]["given_chains"] == 2 and rungs[256]["given_agrees_share"] == 0.5, "the second given chain fell apart"
    assert rungs[256]["median_giant_share"] == 1.0


def _stretched_tree(finished_at_65k: int) -> dict:
    return {"laws": 1000, "graphs": 3000, "gates": [],
            "rungs": [{"n": 256, "finished": 1000, "went_on": 1000, "graphs": 3000, "graphs_in_progress": 0},
                      {"n": 65536, "finished": finished_at_65k, "went_on": finished_at_65k // 2,
                       "stopped": {"no_finite_dimension": finished_at_65k - finished_at_65k // 2},
                       "graphs": 3 * finished_at_65k, "graphs_in_progress": 2}]}


def _page(tmp_path, trees: list[dict]) -> Path:
    page = tmp_path / "gate_trees.html"
    page.write_text(P.render(P.document([{"campaign_id": str(i + 1), "label": "a quadrant", "tree": tree}
                                         for i, tree in enumerate(trees)], title="t", study={}),
                             links={"explorer": None, "front": None}), encoding="utf-8")
    return page


def test_the_page_carries_the_graphs_beside_the_laws_and_where_the_stretch_begins(tmp_path):
    text = _page(tmp_path, [_stretched_tree(10)]).read_text(encoding="utf-8")
    assert '"stretch_from":65536' in text and '"graphs_in_progress":2' in text and '"graphs":3000' in text


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_from_65k_up_a_bar_is_stretched_to_its_own_laws_and_below_it_keeps_the_common_scale(tmp_path):
    below = _stretched_tree(10)
    below["rungs"][1]["n"] = 16384
    below["rungs"][0].update(went_on=999, stopped={"empty": 1})
    for tree, n in ((below, 16384), (above := _stretched_tree(10), 65536)):
        tree["gates"] = [{"gate": "no_finite_dimension", "withheld": 5, "let_through": 0,
                          "by_rung": {str(n): {"withheld": 5, "let_through": 0}}}]
    below["gates"].append({"gate": "empty", "withheld": 1, "let_through": 0, "by_rung": {"256": {"withheld": 1,
                                                                                              "let_through": 0}}})
    page = _page(tmp_path, [above, below])
    check = Path(__file__).resolve().parents[1] / "ui" / "gate_trees_check.js"
    result = subprocess.run([shutil.which("node"), str(check), str(page)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0 and "stretched rungs: 1" in result.stdout, result.stdout[-3000:]


def test_the_campaign_rows_carry_the_graphs_beside_the_laws():
    rows = CM._rung_rows({256: 10, 1024: 4}, {256: 9}, {256: 30, 1024: 11})
    assert [(r["n"], r["laws"], r["graphs"], r["measured"]) for r in rows] == [(256, 10, 30, 9), (1024, 4, 11, 0)]
    assert "graphs" in CM._LAWS_BY_RUNG and "result_artifact IS NOT NULL" in CM._LAWS_BY_RUNG


def test_the_bundle_reads_the_memory_hold_and_its_events():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE control(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE events(event_id INTEGER PRIMARY KEY, topic TEXT, payload_json TEXT, created_utc TEXT)")
    conn.execute("INSERT INTO control VALUES(?,?)", (memory_hold.HOLD_KEY, json.dumps({"state": "ended",
                                                                                         "job_id": "j1"})))
    for topic, payload, at in (
            ("memory_hold_started", {"job_id": "j1", "n": 4194304, "requested_bytes": 20}, "2026-09-29T10:00:00Z"),
            ("memory_hold_ended", {"job_id": "j1", "why": "admitted"}, "2026-09-29T10:20:00Z"),
            ("memory_hold_started", {"job_id": "j2", "n": 1048576}, "2026-09-29T11:00:00Z"),
            ("memory_hold_ended", {"job_id": "j2", "why": "ran out"}, "2026-09-29T12:00:00Z"),
            ("memory_admission_deferred", {"job_id": "j3"}, "2026-09-29T12:00:01Z")):
        conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                     (topic, json.dumps(payload), at))
    reading = memory_hold.reading(conn)
    assert reading["now"] == {"state": "ended", "job_id": "j1"}
    assert reading["started"] == 2 and reading["ended_by_why"] == {"admitted": 1, "ran out": 1}
    assert reading["held_seconds"] == 20 * 60 + 3600
    assert [e["topic"] for e in reading["events"]][0] == "memory_hold_ended", "newest first"
    assert len(reading["events"]) == 4, "only the hold's own events"
