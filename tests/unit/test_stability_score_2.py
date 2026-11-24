from __future__ import annotations


import json
from pathlib import Path

import pytest

from graph_scale_dynamics.research.stability_score import (
    BLOCK_POINTS, TOLERANCE_MULTIPLIER, floor_at,
    noise_floors, noise_floors_by_n, score_block, score_law,
)
from graph_scale_dynamics.research.survey_reports import build_hang_autopsy

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def table():
    from tests.support.calibration_table import require_table
    return require_table()


def test_tolerance_is_a_constant_of_two():
    assert TOLERANCE_MULTIPLIER == 2.0


def test_floors_are_per_probe_per_n_and_not_flat(table):
    by_n = noise_floors_by_n(table)
    glob = noise_floors(table)
    for probe in ("d_s", "d_V", "d_B", "d_w"):
        assert by_n[probe], probe
        for n in (64, 256, 1024, 4096, 16384):
            assert floor_at(by_n[probe], n, fallback=glob[probe]) is not None
    assert floor_at(by_n["d_s"], 64, fallback=None) > 3 * floor_at(by_n["d_s"], 16384, fallback=None)


def test_a_difference_inside_two_floors_scores_full_marks():
    floors_by_n = {64: 0.10, 256: 0.10, 1024: 0.10, 4096: 0.10}
    sizes = [64, 256, 1024, 4096]
    inside = score_block([1.0, 1.4, 1.5, 1.68], [None] * 4, floor=0.10, sizes=sizes, floors_by_n=floors_by_n)
    assert inside["score"] == BLOCK_POINTS and inside["scored_by_noise_floor"]
    outside = score_block([1.0, 1.4, 1.5, 1.75], [None] * 4, floor=0.10, sizes=sizes, floors_by_n=floors_by_n)
    assert outside["score"] < BLOCK_POINTS
    assert inside["tolerances"][-1] == pytest.approx(0.2)


def test_per_n_floor_uses_the_noisier_of_the_two_rungs():
    floors_by_n = {64: 1.0, 256: 0.05, 1024: 0.05, 4096: 0.05}
    block = score_block([1.0, 1.9, 1.95, 2.0], [None] * 4, floor=0.05, sizes=[64, 256, 1024, 4096],
                        floors_by_n=floors_by_n)
    assert block["tolerances"][0] == pytest.approx(2.0)
    assert block["tolerances"][-1] == pytest.approx(0.1)


def _snapshot(table):
    spec = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    sizes = [64, 256, 1024, 4096, 16384]
    rungs, measurements, spend, cands = [], [], [], []
    for i in range(6):
        cid = f"{i:064x}"
        cands.append({"candidate_id": cid, "spec": {"terms": []}})
        for k, n in enumerate(sizes):
            capped = (i == 0 and k == 4)
            summary = {"connected_fraction": {"mean": 0.95}, "mean_degree": {"mean": 3.0}}
            if capped:
                summary["rung_terminal_classification"] = "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
            else:
                for p in ("d_s", "d_V", "d_B", "d_w"):
                    summary[p] = {"mean": 1.5 + 0.01 * k, "se": 0.02}
            rungs.append({"candidate_id": cid, "n": n, "summary": summary})
            reason = "mean_degree_cap" if capped else "completed"
            measurements.append({"candidate_id": cid, "n": n, "seed": 0, "metrics": {"health": {
                "rung_terminal": {"reason": reason, "classification": summary.get("rung_terminal_classification", "EQUILIBRATED_ACTIVE"), "final_multiplier": 8},
                "sampling_checkpoints": [{"multiplier": 8, "passed": not capped, "failures": [], "mean_degree": 3.0,
                                          "effective_samples": 12, "wall_seconds_so_far": 5}]}}})
            spend.append({"candidate_id": cid, "n": n, "core_seconds": 10.0 * (k + 1) * (2 if i == 0 else 1)})
    return {"campaign": {"spec": spec}, "rungs": rungs, "measurements": measurements, "rung_spend": spend,
            "candidates": cands, "operational_terminals": [], "calibration": table, "phenotypes": []}


def test_hang_autopsy_ranks_by_spend_and_names_the_limit(table):
    report = build_hang_autopsy(_snapshot(table))
    assert report["laws"] == 6
    assert report["ranked"][0]["candidate_id"] == f"{0:064x}"
    assert report["ranked"][0]["limit_hits"] == [16384]
    assert report["worst_reason_counts"]["mean_degree_cap"] == 1
    assert report["worst_reason_counts_by_rung"]["16384"]["mean_degree_cap"] == 1


def test_a_probe_refused_at_the_top_rung_cannot_be_converged():
    values = [None, 2.085, 1.977, 1.935, None]
    buckets = [None, None, None, None, "REFUSED_NO_SCALING_WINDOW"]
    block = score_block(values, buckets, floor=0.08, sizes=[64, 256, 1024, 4096, 16384])
    assert block["score"] == 0.0 and block["bucket"] == "DEGRADED_WITH_N"
    assert block["top_rung_bucket"] == "REFUSED_NO_SCALING_WINDOW"
    assert block["top_rung_refused"] is True


def test_top_rung_uncertainty_above_the_tolerance_is_unresolved():
    values = [1.0, 1.01, 1.02, 1.01]
    block = score_block(values, [None] * 4, floor=0.05, sizes=[64, 256, 1024, 4096],
                        ses=[3.0, 1.2, 0.4, 0.9])
    assert block["score"] == 0.0 and block["bucket"] == "UNRESOLVED_AT_TOP_RUNG"
    fine = score_block(values, [None] * 4, floor=0.05, sizes=[64, 256, 1024, 4096],
                       ses=[3.0, 1.2, 0.4, 0.05])
    assert fine["score"] == BLOCK_POINTS


def test_rungs_below_the_connectivity_floor_are_not_points(table):
    floors, by_n = noise_floors(table), noise_floors_by_n(table)
    vec = {"d_s": [None, 0.887, 1.056, 1.025, 1.066], "d_V": [None, 0.854, 1.059, 1.411, None],
           "d_B": [None, None, 0.998, 0.968, 1.150], "d_w": [None, 2.085, 1.977, 1.935, None]}
    ses = {"d_s": [None, 3.385, 1.218, 0.378, 0.077], "d_V": [None, 0.404, 1.655, 4.480, None],
           "d_B": [None, None, 0.512, 0.244, 0.070], "d_w": [None, 0.067, 0.245, 0.102, None]}
    bk = {"d_s": ["REFUSED_NO_SCALING_WINDOW", None, None, None, None],
          "d_V": ["REFUSED_NO_SCALING_WINDOW", None, None, None, "REFUSED_NO_SCALING_WINDOW"],
          "d_B": ["REFUSED_NO_SCALING_WINDOW", "REFUSED_NO_SCALING_WINDOW", None, None, None],
          "d_w": ["REFUSED_NO_SCALING_WINDOW", None, None, None, "REFUSED_NO_SCALING_WINDOW"]}
    conn = [0.109, 0.105, 0.135, 0.344, 0.968]
    sizes = [64, 256, 1024, 4096, 16384]
    without = score_law(vec, bk, floors=floors, sizes=sizes, floors_by_n=by_n, probe_se_vectors=ses)
    assert without["demonstrates_instability"] is True
    assert set(without["penalised_probes"]) == {"d_V", "d_w"}
    with_floor = score_law(vec, bk, floors=floors, sizes=sizes, floors_by_n=by_n, probe_se_vectors=ses,
                           connectivity_vector=conn, connectivity_floor=0.9)
    assert all(block["score"] == 0.0 for name, block in with_floor["blocks"].items() if name != "mean_degree")
    assert with_floor["buckets"]["d_s"] == "REFUSED_BELOW_CONNECTIVITY_FLOOR"
