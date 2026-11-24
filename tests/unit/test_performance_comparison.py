from __future__ import annotations

from graph_scale_dynamics.research.compute_efficiency import (
    COMPARISON_MIN_ATTEMPTS,
    compare_cost_by_n,
    cost_by_n,
)


def _job(job_id: str, multiplier: float) -> dict:
    return {"job_id": job_id, "kind": "simulate",
            "spec": {"execution": {"sweeps_multiplier": multiplier}}}


def _snapshot(cells: dict[tuple[int, float], list[float]]) -> dict:
    jobs, attempts = [], []
    counter = 0
    for index, ((n, multiplier), walls) in enumerate(sorted(cells.items())):
        job_id = f"job-{index}"
        jobs.append(_job(job_id, multiplier))
        for wall in walls:
            counter += 1
            attempts.append({"attempt_id": f"a-{counter}", "job_id": job_id, "n": n,
                             "wall_seconds": wall, "status": "COMPLETED",
                             "kind": "simulate", "exit_code": 0})
    return {"jobs": jobs, "attempts": attempts}


def test_by_n_carries_the_sweeps_multiplier():
    snap = _snapshot({(4096, 16.0): [10.0, 12.0], (4096, 64.0): [400.0, 420.0]})
    rows = {row["n"]: row for row in cost_by_n(snap)}
    cells = {cell["sweeps_multiplier"]: cell for cell in rows[4096]["by_sweeps_multiplier"]}
    assert set(cells) == {16.0, 64.0}
    assert cells[16.0]["attempts"] == 2 and cells[64.0]["attempts"] == 2
    assert rows[4096]["attempts"] == 4


def test_one_n_bucket_can_hold_two_populations():
    snap = _snapshot({(4096, 16.0): [10.0] * 10, (4096, 64.0): [400.0] * 10})
    row = cost_by_n(snap)[0]
    cells = {c["sweeps_multiplier"]: c for c in row["by_sweeps_multiplier"]}
    assert cells[16.0]["wall_distribution_seconds"]["median"] == 10.0
    assert cells[64.0]["wall_distribution_seconds"]["median"] == 400.0


def _many(value: float) -> list[float]:
    return [value] * (COMPARISON_MIN_ATTEMPTS + 5)


def test_flat_cost_passes():
    base = cost_by_n(_snapshot({(4096, 16.0): _many(10.0)}))
    same = cost_by_n(_snapshot({(4096, 16.0): _many(10.0)}))
    verdict = compare_cost_by_n(base, same)
    assert verdict["passed"] and verdict["compared_cells"] == 1
    assert not verdict["regressions"]


def test_a_real_regression_inside_one_cell_is_caught():
    base = cost_by_n(_snapshot({(4096, 16.0): _many(10.0)}))
    worse = cost_by_n(_snapshot({(4096, 16.0): _many(15.0)}))
    verdict = compare_cost_by_n(base, worse)
    assert not verdict["passed"]
    assert verdict["regressions"][0]["n"] == 4096
    assert verdict["regressions"][0]["change_fraction"] == 0.5


def test_a_shift_in_sampling_mix_is_not_reported_as_a_regression():
    base = cost_by_n(_snapshot({
        (4096, 16.0): _many(10.0) * 3,
        (4096, 64.0): _many(400.0),
    }))
    remixed = cost_by_n(_snapshot({
        (4096, 16.0): _many(10.0),
        (4096, 64.0): _many(400.0) * 3,
    }))

    per_n_before = base[0]["wall_distribution_seconds"]["median"]
    per_n_after = remixed[0]["wall_distribution_seconds"]["median"]
    assert per_n_before != per_n_after, "the per-N view should move, which is the problem"

    verdict = compare_cost_by_n(base, remixed)
    assert verdict["passed"], "per-cell comparison must not read a mix shift as a regression"
    assert verdict["compared_cells"] == 2


def test_cells_absent_on_one_side_are_reported_not_compared():
    base = cost_by_n(_snapshot({(4096, 16.0): _many(10.0), (65536, 64.0): _many(50.0)}))
    partial = cost_by_n(_snapshot({(4096, 16.0): _many(10.0)}))
    verdict = compare_cost_by_n(base, partial)
    assert verdict["passed"]
    assert verdict["unmatched_baseline_cells"] == [{"n": 65536, "sweeps_multiplier": 64.0}]
    assert verdict["unmatched_candidate_cells"] == []
    assert verdict["compared_cells"] == 1


def test_thin_cells_do_not_carry_a_verdict():
    base = cost_by_n(_snapshot({(4194304, 1.0): [3000.0, 3100.0]}))
    worse = cost_by_n(_snapshot({(4194304, 1.0): [9000.0, 9100.0]}))
    verdict = compare_cost_by_n(base, worse)
    assert verdict["passed"]
    assert verdict["compared_cells"] == 0
    assert verdict["too_thin_to_compare"][0]["n"] == 4194304


def test_improvements_are_reported_separately_from_noise():
    base = cost_by_n(_snapshot({(1024, 16.0): _many(20.0)}))
    better = cost_by_n(_snapshot({(1024, 16.0): _many(10.0)}))
    verdict = compare_cost_by_n(base, better)
    assert verdict["passed"]
    assert verdict["improvements"][0]["change_fraction"] == -0.5
    assert not verdict["unchanged"]


def test_small_movement_is_within_tolerance():
    base = cost_by_n(_snapshot({(1024, 16.0): _many(100.0)}))
    jittered = cost_by_n(_snapshot({(1024, 16.0): _many(105.0)}))
    verdict = compare_cost_by_n(base, jittered)
    assert verdict["passed"] and len(verdict["unchanged"]) == 1
