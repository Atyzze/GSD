from __future__ import annotations

import collections
import json
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import replication as R  # noqa: E402

TRIANGULAR_PRISM = [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (0, 3), (1, 4), (2, 5)]


@pytest.mark.parametrize("model,n", [("ktb1", 64), ("ktb1t", 64), ("ktb1c", 64), ("ktb2", 64), ("ktb3", 128)])
def test_every_start_is_in_its_space_and_a_run_keeps_it_there(model, n):
    rng = random.Random(7)
    graph = R.make_graph(model, n, rng)
    graph.check()
    for beta in (0.05, 1.0, 20.0):
        for _ in range(4 * len(graph.edges)):
            graph.step(rng, beta)
        graph.check()
    if model in ("ktb1", "ktb1c"):
        assert graph.observables()["triangles"] == 0, "girth at least 4"


def test_the_connected_space_is_never_left():
    split = False
    for seed in (2, 3, 4):
        kept, free = R.make_graph("ktb1c", 40, random.Random(seed)), R.make_graph("ktb1", 40, random.Random(seed))
        assert R._components(40, kept.edges) == 1
        rng_kept, rng_free = random.Random(seed), random.Random(seed)
        for beta in (0.5, 2.0, 5.0, 20.0):
            for _ in range(60 * len(kept.edges)):
                kept.step(rng_kept, beta)
                free.step(rng_free, beta)
            assert R._components(40, kept.edges) == 1, "a connected run stays connected"
            split = split or R._components(40, free.edges) > 1
        kept.check()
    assert split, "the free space splits on these seeds, so the refusal is what keeps the connected one whole"
    assert R.CubicGraph.from_edges(40, R.ladder_edges(40, False)).connected is False


def test_the_actions_are_their_curvature_actions():
    from graph_scale_dynamics.engine.engine import scaled_curvature
    for d in (4, 6):
        for s in range(0, d - 1):
            assert R.edge_action(d, s) == pytest.approx(-(2 / d) * scaled_curvature(0, s, 0, d, d)), (d, s)
    for t in range(3):
        for s in range(4):
            for p in range(5):
                assert 3 * R.cubic_edge_action3(t, s, p) == -scaled_curvature(t, s, p, 3, 3), (t, s, p)
    assert R.cubic_edge_action3(0, 0, 0) == 2 and R.cubic_edge_action3(0, 1, 0) == 0, "A/N is 1 with no short cycle"


@pytest.mark.parametrize("model,n", [("ktb1", 100), ("ktb1", 102), ("ktb2", 64), ("ktb2", 144), ("ktb3", 216)])
def test_their_classical_configurations_read_zero_action(model, n):
    configurations = R.classical_configurations(model, n)
    assert configurations, (model, n)
    for edges in configurations.values():
        assert len(edges) == n * R.KTB_MODELS[model]["degree"] // 2 and R.configuration_action(model, n, edges) == 0
    if model == "ktb1":
        assert R.CubicGraph.from_edges(n, configurations["prism"]).ladder() == "prism"
        assert R.CubicGraph.from_edges(n, configurations["moebius"]).ladder() == "moebius"
    assert R.torus_edges(3, 64) is None, "a torus of side 4 closes a square around itself"


def test_where_triangles_are_allowed_the_triangular_prism_lies_below_the_ladders():
    prisms = TRIANGULAR_PRISM + [(a + 6, b + 6) for a, b in TRIANGULAR_PRISM]
    graph = R.CubicGraph.from_edges(12, prisms)
    assert graph.violations() == 0 and graph.action == -4 and graph.ladder() is None
    assert R.CubicGraph.from_edges(12, prisms, girth4=True).violations() > 0, "not in the girth-4 space"
    two = R.ladder_edges(20, False) + [(a + 20, b + 20) for a, b in R.ladder_edges(20, True)]
    assert R.CubicGraph.from_edges(40, two, girth4=True).ladder() == "ladders"


@pytest.mark.parametrize("model", ["ktb1", "ktb2"])
def test_every_switch_taken_is_undone_by_a_switch_of_its_two_new_edges(model):
    rng = random.Random(3)
    graph = R.make_graph(model, 64, rng)
    for _ in range(3000):
        before = set(graph.edges)
        if not graph.step(rng, 0.5):
            assert set(graph.edges) == before, "a refused switch leaves the graph as it was"
            continue
        gone, new = sorted(before - set(graph.edges)), sorted(set(graph.edges) - before)
        (a, b), (c, d) = new
        rewirings = [{R._e(a, c), R._e(b, d)}, {R._e(a, d), R._e(b, c)}]
        assert set(gone) in rewirings, "its reverse is a switch of the same two edges"
    graph.check()


def test_a_run_reads_their_observables_and_ours(monkeypatch):
    monkeypatch.setitem(R.SCHEDULES, "cubic", dict(R.SCHEDULES["cubic"], coarse=2, fine_to=1.2, sweeps=3))
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=4, sweeps=3))
    for model, n in (("ktb1", 60), ("ktb2", 64)):
        row = R.run_one({"model": model, "n": n, "seed": 1, "hysteresis": True})
        assert "error" not in row, row.get("error")
        schedule = R.SCHEDULES[R.KTB_MODELS[model]["space"]]
        assert [r["beta"] for r in row["cooling"]] == R.betas(schedule) == [r["beta"] for r in row["heating"]][::-1]
        assert {"specific_heat", "acceptance", "action_per_node", "flat_share"} <= set(row["cooling"][0])
        assert {"d_s", "giant_share", "curvature", "d_V", "d_B", "d_w"} <= set(row["reading"])
        assert "classical" in row["end"]
        names = {"ktb1": {"prism", "moebius"}, "ktb2": {"torus"}}[model]
        assert set(row["classical_readings"]) == names
        assert all(r["action_per_node"] == 0 for r in row["classical_readings"].values())
        cell = R.summarize([row])[0]
        assert cell["model"] == model and cell["seeds"] == 1 and "largest_loop" in cell
        assert ("ladders" in cell) == (model == "ktb1") and ("log_g_at_half_order" in cell) == (model == "ktb2")
        assert {"d_V", "d_B", "d_w"} <= set(cell) and ("log_g_as_printed_at_half_order" in cell) == (model == "ktb2")
        assert "zero A" in R.render([cell])
    assert R.sweeps_at({"sweeps": "3N/2"}, 1000) == 1500, "the 2021 paper's 3N/2 sweeps at each beta"


def test_the_readings_of_a_cooling():
    cooling = [{"beta": 0.5, "action_per_node": 0.9, "specific_heat": 0.1, "phi": 0.1, "acceptance": 0.6},
               {"beta": 1.0, "action_per_node": 0.6, "specific_heat": 0.9, "phi": 0.4, "acceptance": 0.3},
               {"beta": 1.5, "action_per_node": 0.3, "specific_heat": 0.4, "phi": 0.7, "acceptance": 0.1},
               {"beta": 20.0, "action_per_node": 0.29, "specific_heat": 50.0, "phi": 0.71, "acceptance": 0.001}]
    marks = R.transition(cooling, "cubic")
    assert (marks["beta_at_peak_heat"], marks["peak_heat"], marks["beta_at_half_order"]) == (1.0, 0.9, 1.5)
    assert marks["beta_at_steepest"] == pytest.approx((1.0 * 1.5) ** 0.5, abs=1e-3), "0.3 a step of ln 1.5"
    assert R.transition(cooling, "bipartite")["beta_at_half_order"] == 1.5
    assert R.beta_tilde(2.0, 1000, 3) == pytest.approx(20.0) and R.beta_tilde(2.0, 1000, 2) == 2.0
    assert R.beta_tilde_as_printed(2.0, 1000, 3) == pytest.approx(0.2) and R.beta_tilde_as_printed(2.0, 1000, 2) == 2.0
    assert R.parse_sizes("ktb1:100x50,102;ktb2:200", ["ktb1", "ktb2", "ktb3"]) == {
        "ktb1": [(100, 50), (102, None)], "ktb2": [(200, None)], "ktb3": []}
    assert R.parse_sizes("200,1024", ["ktb1"]) == {"ktb1": [(200, None), (1024, None)]}


def test_the_command_writes_a_document(tmp_path, monkeypatch):
    monkeypatch.setitem(R.SCHEDULES, "cubic", dict(R.SCHEDULES["cubic"], coarse=2, fine_to=1.1, sweeps=2))
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=3, sweeps=2))
    out = tmp_path / "r.json"
    criterion = tmp_path / "c.json"
    criterion.write_text(json.dumps({"predictions": [
        {"id": "x", "model": "ktb1", "sizes": [60], "reading": "classical_share", "rule": {"between": [0, 1]}}]}))
    assert R.main(["--models", "ktb1,ktb2", "--sizes", "ktb1:60x2;ktb2:64", "--seeds", "1", "--first-seed", "5",
                   "--hysteresis-at", "64", "--workers", "1", "--output", str(out), "--judge", str(criterion)]) == 0
    document = json.loads(out.read_text())
    assert document["contract"] == R.REPLICATION_CONTRACT and document["paper"] == "ktb"
    assert sorted((r["model"], r["seed"]) for r in document["rows"]) == [("ktb1", 5), ("ktb1", 6), ("ktb2", 5)]
    assert len(document["cells"]) == 2 and document["sizes"] == {"ktb1": [60], "ktb2": [64]}
    assert [bool(r.get("heating")) for r in document["rows"]] == [False, False, True], "heated back at 64 only"
    assert document["criterion"]["verdicts"][0]["as_expected"]
    assert R.main(["--read", f"{out},{out}", "--judge", str(criterion)]) == 0


def test_a_criterion_is_judged_prediction_by_prediction():
    cells = [{"model": "ktb1", "n": 100, "prism_share": 0.9, "d_s": 1.2},
             {"model": "ktb1", "n": 102, "prism_share": 0.1, "d_s": 1.25},
             {"model": "ktb1", "n": 104, "prism_share": 0.8, "d_s": 1.3}]
    criterion = {"predictions": [
        {"id": "a", "model": "ktb1", "sizes": [100, 102, 104], "reading": "prism_share", "rule": {"alternates": True}},
        {"id": "b", "model": "ktb1", "sizes": [100, 102], "reading": "d_s", "rule": {"between": [1.1, 1.3]}},
        {"id": "c", "model": "ktb1", "sizes": [100, 104], "reading": "d_s", "rule": {"at_most": 1.25}},
        {"id": "d", "model": "ktb1", "sizes": [100, 106], "reading": "d_s", "rule": {"at_least": 1.0}}]}
    criterion["predictions"][2]["expect"] = "missed"
    verdicts = R.judge(cells, criterion)
    assert {v["id"]: v["verdict"] for v in verdicts} == {"a": "held", "b": "held", "c": "missed", "d": "unread"}
    assert [v["as_expected"] for v in verdicts] == [True, True, True, False], "a claim expected to fail, failing"
    assert R.render_verdicts(verdicts, criterion).startswith("3 of 4 as the criterion expected; 2 rules held")


def test_the_kept_connected_model_starts_from_the_free_model_s_graph():
    for n, seed in ((100, 11), (106, 60), (200, 12)):
        free, kept = R.make_graph("ktb1", n, random.Random(seed)), R.make_graph("ktb1c", n, random.Random(seed))
        assert sorted(free.edges) == sorted(kept.edges)


def test_a_slower_schedule_is_its_own_cell_and_judged_against_a_faster_one():
    cells = [{"model": "ktb3", "n": 200, "sweeps": 160, "end_phi": 0.78},
             {"model": "ktb3", "n": 200, "sweeps": 640, "end_phi": 0.84},
             {"model": "ktb3", "n": 200, "sweeps": 2560, "end_phi": 0.83}]
    criterion = {"predictions": [
        {"id": "s1", "model": "ktb3", "sweeps": 640, "sizes": [200], "reading": "end_phi", "rule": {"above": {"sweeps": 160}}},
        {"id": "s2", "model": "ktb3", "sweeps": 2560, "sizes": [200], "reading": "end_phi",
         "rule": {"above": {"sweeps": 640}}},
        {"id": "s3", "model": "ktb3", "sweeps": 2560, "sizes": [200], "reading": "end_phi", "rule": {"at_least": 0.8}},
        {"id": "s4", "model": "ktb3", "sweeps": 40, "sizes": [200], "reading": "end_phi", "rule": {"at_least": 0.8}}]}
    verdicts = {v["id"]: v["verdict"] for v in R.judge(cells, criterion)}
    assert verdicts == {"s1": "held", "s2": "missed", "s3": "held", "s4": "unread"}


def test_the_sweeps_given_reach_every_run_and_its_cost(tmp_path, monkeypatch):
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=3, sweeps=2))
    out = tmp_path / "r.json"
    assert R.main(["--models", "ktb2", "--sizes", "64", "--seeds", "1", "--sweeps", "3", "--workers", "1",
                   "--output", str(out)]) == 0
    document = json.loads(out.read_text())
    assert document["sweeps"] == 3 and [r["sweeps"] for r in document["rows"]] == [3]
    assert document["cells"][0]["sweeps"] == 3
    assert R.cost({"model": "ktb2", "n": 64, "schedule": {"sweeps": 6}}) == 2 * R.cost({"model": "ktb2", "n": 64,
                                                                                         "schedule": {"sweeps": 3}})


def test_a_plan_runs_every_run_line_of_its_criterion_in_one_pool(tmp_path, monkeypatch):
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=3, sweeps=2))
    earlier = tmp_path / "earlier.json"
    assert R.main(["--models", "ktb2", "--sizes", "64", "--seeds", "1", "--first-seed", "5", "--sweeps", "2",
                   "--workers", "1", "--output", str(earlier)]) == 0
    criterion = {"run": ["uv run python tools/replication.py --models ktb2 --sizes 64 --seeds 1 --first-seed 5 --sweeps 4 "
                         "--workers 4 --output var/readings/a.json",
                         "uv run python tools/replication.py --models ktb2 --sizes 64,80 --seeds 1 --first-seed 5 "
                         "--sweeps 3 --workers 2 --output var/readings/b.json",
                         "python3 tools/replication.py --read x.json --judge y.json"],
                 "predictions": [{"id": "p1", "model": "ktb2", "sweeps": 4, "sizes": [64], "reading": "end_phi",
                                  "rule": {"above": {"sweeps": 2}}}]}
    monkeypatch.setattr(R, "against_rows", lambda c: json.loads(earlier.read_text())["rows"])
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(criterion))
    out = tmp_path / "all.json"
    assert R.main(["--plan", str(plan), "--workers", "1", "--output", str(out)]) == 0
    document = json.loads(out.read_text())
    assert document["complete"] and document["runs_done"] == document["runs_planned"] == 3
    assert sorted((r["n"], r["sweeps"]) for r in document["rows"]) == [(64, 3), (64, 4), (80, 3)]
    assert [v["id"] for v in document["criterion"]["verdicts"]] == ["p1"]
    assert document["criterion"]["verdicts"][0]["verdict"] in ("held", "missed")


HOST_PLAN = {"run": [
    "uv run python tools/replication.py --models ktb3 --sizes 200,280 --seeds 2 --first-seed 21 --sweeps 10240 "
    "--workers 4 --output var/readings/a.json",
    "uv run python tools/replication.py --models ktb3 --sizes 200 --seeds 2 --first-seed 21 --sweeps 163840 "
    "--workers 2 --output var/readings/b.json",
    "uv run python tools/replication.py --models ktb2 --sizes 16384,1048576 --seeds 2 --first-seed 21 --sweeps 160 "
    "--workers 2 --output var/readings/c.json",
    "python3 tools/replication.py --read var/readings/a.json --judge plan.json"]}


def test_a_plan_is_its_run_lines_and_its_earlier_rows_are_read_from_its_against_files(tmp_path):
    tasks, abouts = R.planned(HOST_PLAN)
    by = collections.Counter((t["model"], t["n"], t["schedule"]["sweeps"]) for t in tasks)
    assert by == {("ktb3", 200, 10240): 2, ("ktb3", 280, 10240): 2, ("ktb3", 200, 163840): 2,
                  ("ktb2", 16384, 160): 2, ("ktb2", 1048576, 160): 2}
    assert len(abouts) == 3, "the --read line plans no run"
    earlier = tmp_path / "earlier.json"
    earlier.write_text(json.dumps({"rows": [{"model": "ktb3", "n": 200, "seed": 1}, {"model": "ktb3", "n": 280, "seed": 1}]}))
    assert len(R.against_rows(dict(HOST_PLAN, against=str(earlier)))) == 2
    assert len(R.against_rows(dict(HOST_PLAN, against=[str(earlier), str(earlier)]))) == 4
    assert R.against_rows(HOST_PLAN) == []


def test_a_file_already_there_is_kept_and_only_its_missing_runs_are_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=3, sweeps=2))
    out = tmp_path / "r.json"
    assert R.main(["--models", "ktb2", "--sizes", "64", "--seeds", "1", "--workers", "1", "--output", str(out)]) == 0
    first = json.loads(out.read_text())["rows"][0]
    capsys.readouterr()
    assert R.main(["--models", "ktb2", "--sizes", "64,80", "--seeds", "1", "--workers", "1", "--output", str(out)]) == 0
    printed = capsys.readouterr().out
    document = json.loads(out.read_text())
    assert "holds 1 finished run(s)" in printed and "replication: 1 runs" in printed
    assert "2/2 ktb2 N=80" in printed and "N=64 seed" not in printed
    assert [r["n"] for r in document["rows"]] == [64, 80] and document["rows"][0] == first
    assert document["complete"] and document["runs_done"] == document["runs_planned"] == 2
    assert len(document["resumed_utc"]) == 1


def test_a_file_that_is_not_a_replication_is_never_written_over(tmp_path):
    out = tmp_path / "r.json"
    out.write_text('{"something": "else"}')
    with pytest.raises(SystemExit):
        R.main(["--models", "ktb2", "--sizes", "64", "--seeds", "1", "--workers", "1", "--output", str(out)])
    assert out.read_text() == '{"something": "else"}'


def test_the_shortest_runs_start_first_and_the_sizes_can_be_held_back():
    tasks, _ = R.planned(HOST_PLAN)
    shortest = sorted(tasks, key=R.cost)
    assert shortest[0]["n"] in (200, 16384) and shortest[-1]["n"] == 1048576
    assert R.run_key({"model": "ktb2", "n": 64, "seed": 3}) == ("ktb2", 64, 3, 160)
    assert R.run_key({"model": "ktb2", "n": 64, "seed": 3, "schedule": {"sweeps": 9}}) == ("ktb2", 64, 3, 9)


def test_log_g_is_the_paper_s_coupling_grown_as_n_to_one_minus_two_over_d(tmp_path, monkeypatch):
    assert R.log_g(0.13, 200, 3) == pytest.approx(-math.log(0.13 * 200 ** (1 / 3)), abs=1e-3)
    assert R.log_g(0.13, 200, 3) == pytest.approx(0.274, abs=1e-3), "the 3D crossing near +0.3, not the paper's -1"
    assert R.log_g(0.146, 200, 2) == R.log_g(0.146, 200, 2, R.beta_tilde_as_printed), "the same in two dimensions"
    assert R.log_g(None, 200, 3) is None
    monkeypatch.setitem(R.SCHEDULES, "bipartite", dict(R.SCHEDULES["bipartite"], steps=3, sweeps=2))
    out = tmp_path / "r.json"
    assert R.main(["--models", "ktb2", "--sizes", "64,80", "--seeds", "2", "--workers", "1", "--output", str(out)]) == 0
    cells = R.summarize(json.loads(out.read_text())["rows"])
    assert [cell["n"] for cell in cells] == [64, 80]
    for cell in cells:
        half, n, d = cell["beta_at_half_order"], cell["n"], cell["dimension"]
        assert cell["log_g_at_half_order"] == R.log_g(half, n, d)
        assert cell["log_g_as_printed_at_half_order"] == R.log_g(half, n, d, R.beta_tilde_as_printed)


def test_a_criterion_s_predictions_are_read_on_its_cells_and_said_in_one_line():
    criterion = {"run": ["uv run python tools/replication.py --models ktb2 --sizes 16384,65536,262144,1048576 --seeds 2 "
                         "--first-seed 21 --sweeps 160 --workers 2 --output var/readings/ladder.json"],
                 "predictions": [{"id": "H5", "model": "ktb2", "sweeps": 160, "reading": "d_s",
                                  "sizes": [16384, 65536, 262144, 1048576], "rule": {"between": [1.6, 2.4]}},
                                 {"id": "H6", "model": "ktb2", "sweeps": 160, "reading": "giant_share",
                                  "sizes": [16384, 65536, 262144, 1048576], "rule": {"at_least": 0.9}}]}
    tasks, _ = R.planned(criterion)
    assert collections.Counter((t["model"], t["n"], t["schedule"]["sweeps"]) for t in tasks) == {
        ("ktb2", 16384, 160): 2, ("ktb2", 65536, 160): 2, ("ktb2", 262144, 160): 2, ("ktb2", 1048576, 160): 2}
    assert sorted(t["seed"] for t in tasks if t["n"] == 16384) == [21, 22]
    assert R.against_rows(criterion) == []
    sizes = [16384, 65536, 262144, 1048576]
    cells = [{"model": "ktb2", "n": n, "sweeps": 160, "d_s": 2.1, "giant_share": 1.0} for n in sizes]
    verdicts = R.judge(cells, criterion)
    assert [(v["id"], v["verdict"], v["as_expected"]) for v in verdicts] == [("H5", "held", True), ("H6", "held", True)]
    cells[0]["d_s"] = 2.6
    assert [v["verdict"] for v in R.judge(cells, criterion)] == ["missed", "held"]
    assert [v["verdict"] for v in R.judge([], criterion)] == ["unread", "unread"]
    assert R.render_verdicts(verdicts, criterion).startswith("2 of 2 as the criterion expected")
