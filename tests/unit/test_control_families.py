import json
from pathlib import Path

import pytest

from graph_scale_dynamics.research.stability_score import (
    WITHHELD_SETTLED_BUCKETS,
    control_family_match, control_family_reference, noise_floors, noise_floors_by_n, score_law,
)

ROOT = Path(__file__).resolve().parents[2]
_TABLE_PATH = ROOT / "calibration" / "probe_calibration.json"
if not _TABLE_PATH.is_file():
    pytest.skip("no durable calibration table on this host; run "
                "`python tools/probe_calibration.py --write` or restore one from "
                "var/calibration/history/", allow_module_level=True)
from tests.support.calibration_table import skip_if_recalibration_owed  # noqa: E402

try:
    skip_if_recalibration_owed()
except pytest.skip.Exception as skipped:
    pytest.skip(str(skipped), allow_module_level=True)
TABLE = json.loads(_TABLE_PATH.read_text())
SIZES = [64, 256, 1024, 4096, 16384]
REF = control_family_reference(TABLE)
FLOORS, FLOORS_BY_N = noise_floors(TABLE), noise_floors_by_n(TABLE)

G70612 = {"d_s": [1.189, 1.086, 1.038, 1.018, 1.007], "d_V": [1.055, 1.272, 1.322, 1.224, 1.097],
          "d_B": [None, 0.898, 1.005, 0.972, 0.964], "d_w": [1.934, 1.931, 1.949, 1.981, 1.983]}
G70612_SE = {"d_s": [1.247, .44, .196, .107, .056], "d_V": [.301, 1.262, 1.429, 1.484, 1.278],
             "d_B": [None, .19, .134, .064, .032], "d_w": [.119, .093, .089, .068, .062]}
G70612_DEGREE = [2.063, 2.029, 2.02, 2.008, 2.004]


def test_the_reference_carries_the_shipped_families_at_the_base_rungs():
    assert {"periodic_ring", "periodic_square_lattice", "periodic_cubic_lattice"} <= set(REF)
    assert all(n in REF["periodic_ring"] for n in SIZES)


def test_g70612_is_a_ring_and_its_probes_score_nothing():
    scored = score_law(G70612, None, floors=FLOORS, floors_by_n=FLOORS_BY_N, sizes=SIZES,
                       mean_degree_vector=G70612_DEGREE, probe_se_vectors=G70612_SE,
                       control_reference=REF)
    assert scored["control_family"]["family"] == "periodic_ring"
    assert scored["control_family"]["rungs_matched"] == 5
    assert "score_8" not in scored
    assert all(scored["blocks"][probe]["score"] == 0.0 for probe in ("d_s", "d_V", "d_B", "d_w"))
    assert "tree_line" not in scored
    assert scored["control_family"]["withheld_points"] == 50.0, "the ring's points are the control's to withhold"
    assert scored["buckets"]["d_B"] == "CONTROL_PERIODIC_RING", "the extender reads buckets"
    assert scored["blocks"]["d_B"]["converged_before_control_gate"]


def test_a_tree_is_not_a_ring_and_a_ring_at_the_wrong_degree_is_not_either():
    tree = {"d_s": [1.25] * 5, "d_V": [None] * 5, "d_B": [None] * 5, "d_w": [None] * 5}
    assert control_family_match(tree, [2.25] * 5, SIZES, REF)["family"] in (None, "erdos_renyi_degree_2")
    without = {family: rows for family, rows in REF.items() if family != "erdos_renyi_degree_2"}
    assert control_family_match(tree, [2.25] * 5, SIZES, without)["family"] is None
    wrong_degree = control_family_match(G70612, [3.0] * 5, SIZES, REF, probe_se_vectors=G70612_SE)
    assert wrong_degree["family"] is None
    assert wrong_degree["candidates"]["periodic_ring"]["disagreed"]


def test_without_a_reference_nothing_is_classified():
    scored = score_law(G70612, None, floors=FLOORS, floors_by_n=FLOORS_BY_N, sizes=SIZES,
                       mean_degree_vector=G70612_DEGREE, probe_se_vectors=G70612_SE)
    assert scored["control_family"]["family"] is None
    assert (scored["blocks"]["d_s"]["score"], scored["blocks"]["mean_degree"]["score"]) == (50.0, 50.0), (
        "with no reference nothing withholds the ring's settled d_s: the tree line that did left at 790")
    assert scored["buckets"]["d_s"] == "CONVERGED" and not WITHHELD_SETTLED_BUCKETS


def test_a_match_must_include_the_top_measured_rung():
    from graph_scale_dynamics.research.stability_score import control_family_match
    ref = {"periodic_square_lattice": {n: {"d_s": {"mean": 2.0, "se": 0.02}} for n in SIZES}}
    passing_through = {"d_s": [1.3, 1.9, 2.0, 2.05, 2.6], "d_V": [None] * 5,
                       "d_B": [None] * 5, "d_w": [None] * 5}
    match = control_family_match(passing_through, [4.0] * 5, SIZES, ref)
    assert match["family"] is None
    assert match["candidates"]["periodic_square_lattice"]["disagreed"]
    settled_early = {"d_s": [None, 2.0, 2.0, 2.02, None], "d_V": [None] * 5,
                     "d_B": [None] * 5, "d_w": [None] * 5}
    match = control_family_match(settled_early, [4.0] * 5, SIZES, ref)
    assert match["family"] == "periodic_square_lattice"
    assert match["candidates"]["periodic_square_lattice"]["top_rung_compared"]
