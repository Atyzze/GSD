from __future__ import annotations

from graph_scale_dynamics.research import curvature_reading as R
from graph_scale_dynamics.research.graph_trickle import build_graphs_by_rung
from graph_scale_dynamics.research.law_ledger import build_law_ledger
from graph_scale_dynamics.research.structure_reading import curvature_values


def _measurement(law, n, seed, kappa, *, measured=True, seconds=0.5, created="2026-09-30T00:00:00Z"):
    reading = {"measured": measured, "mean": kappa, "positive_share": 0.1, "negative_share": 0.8,
               "degree_weighted_mean": kappa} if measured else {"measured": False, "reason": "x"}
    return {"candidate_id": law, "n": n, "seed": seed, "created_utc": created,
            "metrics": {"curvature": {"empty": reading, "given": None}, "probe_seconds": {"kappa": seconds}}}


def test_a_law_carries_the_mean_of_its_seeds_curvature_per_rung_and_the_latest_measurement_wins():
    rows = [_measurement("a", 4096, 0, -1.0), _measurement("a", 4096, 1, -0.5),
            _measurement("a", 4096, 1, -0.7, created="2026-09-30T01:00:00Z"),
            _measurement("a", 64, 0, None, measured=False)]
    assert R.kappa_by_law(rows) == {"a": {4096: -0.85}}


def test_the_area_under_the_curve_counts_ties_half():
    assert R.auc([3, 2, 1], [True, False, False]) == 1.0
    assert R.auc([1, 1], [True, False]) == 0.5
    assert R.auc([1, 2], [True, True]) is None


def _row(kappa, degree, finite):
    return {"kappa": {"4096": kappa}, "mean_degree": {"4096": degree}, "finite_at_65536": finite}


RULE = {"auc_at_least": 0.7, "beyond_degree_by": 0.05, "min_finite": 2, "min_not_finite": 2}


def test_the_test_is_not_yet_until_both_sides_have_their_laws():
    assert R.judge([_row(0.0, 2.0, True), _row(-1.0, 6.0, False)], RULE)["verdict"] == "NOT YET"


def test_rings_make_the_curvature_hold_without_beating_the_mean_degree():
    rows = [_row(0.0, 2.0, True), _row(0.0, 2.0, True), _row(-1.2, 5.0, False), _row(-1.4, 7.0, False)]
    judged = R.judge(rows, RULE)
    assert (judged["verdict"], judged["beyond_degree"]) == ("HELD", "NO")
    assert judged["auc_curvature"] == judged["auc_mean_degree"] == 1.0


def test_a_flat_law_at_a_high_degree_is_what_beats_the_mean_degree():
    rows = [_row(0.0, 6.0, True), _row(-0.05, 4.0, True), _row(-1.3, 6.0, False), _row(-1.0, 4.2, False),
            _row(-0.9, 2.1, False)]
    judged = R.judge(rows, RULE)
    assert judged["verdict"] == "HELD" and judged["beyond_degree"] == "YES"


def test_report_28_carries_it_in_the_seed_table_the_graphs_by_rung_and_the_ledger():
    from graph_scale_dynamics.research.decision_engine_report import SEED_COLUMNS, _kappa_cells
    at = SEED_COLUMNS.index("kappa_seconds")
    assert SEED_COLUMNS[at:at + 2] == ("kappa_seconds", "kappa_mean")
    assert _kappa_cells(_measurement("a", 64, 0, -0.25)) == (0.5, -0.25)
    assert _kappa_cells({"metrics": {}}) == (None, None)
    seeds = {"columns": ["law", "n", "seed", "simulation_seconds", "final_mean_degree"], "laws": ["a"],
             "rows": [[0, 4096, 0, 10.0, 4.0], [0, 4096, 1, 11.0, 4.0]]}
    measurements = [_measurement("a", 4096, 0, -0.2), _measurement("a", 4096, 1, -0.4)]
    rung = build_graphs_by_rung(seeds, measurements, {})["rungs"][0]
    assert rung["median_curvature"] == -0.3 and rung["curvature_read"] == 2
    ledger = build_law_ledger([{"candidate_id": "a", "spec": {"terms": []}}], seeds, [], cap=16.0,
                              measurements=measurements)
    assert ledger["rows"][0]["kappa"] == {"4096": -0.3}
    assert "finite_at_65536" not in ledger["rows"][0], "a law with no rung at 65,536 has no outcome"


def test_the_structure_reading_carries_it_per_chain():
    metrics = _measurement("a", 64, 0, -0.5)["metrics"]
    assert curvature_values(metrics)["kappa_mean"] == -0.5
    assert curvature_values(metrics, "given") == dict.fromkeys(curvature_values(metrics), None)


def test_the_longer_chains_name_what_each_law_did_next():
    from graph_scale_dynamics.reporting.study_reading import _longer_chains
    rows = []
    for i, (action, rule) in enumerate((("run_next", "salted"), ("stop", "failed"), ("stop", "disconnected"))):
        rows += [{"candidate_id": f"l{i}", "rule": "longer_chain", "created_utc": "1", "decision_id": "a"},
                 {"candidate_id": f"l{i}", "rule": rule, "action": action, "created_utc": "2", "decision_id": "b"}]
    rows.append({"candidate_id": "l9", "rule": "longer_chain", "created_utc": "1", "decision_id": "a"})
    assert _longer_chains(rows) == {"bought": 4, "next": {"read, then run_next: salted": 1, "read, then stop: failed": 1,
                                                          "read, then stop: disconnected": 1, "not decided yet": 1}}
