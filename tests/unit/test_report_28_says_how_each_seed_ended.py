from __future__ import annotations

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.research.decision_engine_report import SEED_COLUMNS, _seed_table


def _attempt(law, seed, *, error=None, finished="2026-10-01T00:00:00Z"):
    return {"kind": "simulate", "candidate_id": law, "n": 1024, "seed": seed, "attempt_id": f"{law}-{seed}-{finished}",
            "wall_seconds": 12.0, "user_cpu_seconds": 10.0, "system_cpu_seconds": 1.0, "error_class": error,
            "finished_utc": finished}


def _measurement(law, seed, reason):
    return {"candidate_id": law, "n": 1024, "seed": seed, "created_utc": "2026-10-01T00:01:00Z",
            "metrics": {"health": {"rung_terminal": {"contract": "one-shot-sampling-1", "reason": reason}}}}


def test_each_seed_says_how_its_run_ended():
    snapshot = {"attempts": [_attempt("a", 0), _attempt("a", 1), _attempt("b", 0, error="child_crashed"),
                             _attempt("c", 0, error="preempted_fleet_paused")],
                "measurements": [_measurement("a", 0, "certified"), _measurement("a", 1, "budget")]}
    table = _seed_table(snapshot, Policy())
    at = SEED_COLUMNS.index("ended")
    ended = {(table["laws"][row[0]], row[2]): row[at] for row in table["rows"]}
    assert ended[("a", 0)] == "certified" and ended[("a", 1)] == "budget", "the run's own reason, from its measurement"
    assert ended[("b", 0)] == "child_crashed", "a failed attempt with nothing measured says its error"
    assert ended[("c", 0)] is None, "an interruption is counted, never the seed's run (455)"
    assert table["rows"][-1][SEED_COLUMNS.index("interrupted")] == 1


def test_each_seed_says_whether_it_ended_at_its_budget_and_how_much_of_it_it_used():
    spent = _measurement("a", 1, "budget")
    spent["metrics"]["health"]["rung_terminal"]["work"] = {"units": 900, "budget": 1000}
    snapshot = {"attempts": [_attempt("a", 0), _attempt("a", 1), _attempt("b", 0, error="child_crashed")],
                "measurements": [_measurement("a", 0, "certified"), spent]}
    table = _seed_table(snapshot, Policy())
    at, units, share = (SEED_COLUMNS.index(name) for name in ("budget_ended", "work_units", "budget_fraction"))
    flag = {(table["laws"][row[0]], row[2]): row[at] for row in table["rows"]}
    assert flag == {("a", 0): False, ("a", 1): True, ("b", 0): None}
    row = next(row for row in table["rows"] if (table["laws"][row[0]], row[2]) == ("a", 1))
    assert (row[units], row[share], row[SEED_COLUMNS.index("work_budget")]) == (900, 0.9, 1000)
