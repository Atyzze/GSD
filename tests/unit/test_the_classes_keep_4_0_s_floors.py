from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.research import noise_floors as NF
from graph_scale_dynamics.research.stability_score import score_block

ROOT = Path(__file__).resolve().parents[2]
SEED = json.loads((ROOT / "calibration" / "seed_table.json").read_text(encoding="utf-8"))
FROZEN = json.loads(NF.FROZEN.read_text(encoding="utf-8"))


def test_the_shipped_5_0_table_reads_4_0_s_floors():
    assert FROZEN["analysis_version"] == "analysis-4.0.0" and FROZEN["estimator_fingerprint"] == "eafb85d317697887"
    assert SEED["estimator_fingerprint"] != FROZEN["estimator_fingerprint"]
    assert NF.noise_floors(SEED) == FROZEN["floors"] and NF.noise_floors(SEED)["d_V"] > 0.01
    by_n = NF.noise_floors_by_n(SEED)["d_V"]
    assert all(NF.floor_at(by_n, n, fallback=None) > 0.01 for n in (64, 256, 1024, 4096))


def test_the_table_s_own_floors_were_empty_under_5_0():
    own = {key: value for key, value in SEED.items() if key != "estimator_fingerprint"}
    assert NF.noise_floors(own)["d_V"] < 1e-12
    assert NF.floor_at(NF.noise_floors_by_n(own)["d_V"], 1024, fallback=None) < 1e-12


def test_a_4_0_table_and_a_table_naming_no_estimator_read_their_own():
    cells = {"a:64:0": {"n": 64, "channels": {"d_V": {"valid": True, "se": 0.5}}}}
    for table in ({"cells": cells}, {"cells": cells, "estimator_fingerprint": FROZEN["estimator_fingerprint"]}):
        assert NF.noise_floors(table)["d_V"] == 0.5 and NF.noise_floors_by_n(table)["d_V"] == {64: 0.5}


def test_a_converging_d_v_converges_again():
    sizes = [64, 256, 1024, 4096]
    values, buckets = [2.05, 2.30, 2.36, 2.37], [None] * 4
    floors, by_n = NF.noise_floors(SEED), NF.noise_floors_by_n(SEED)
    kept = score_block(values, buckets, floor=floors["d_V"], sizes=sizes, floors_by_n=by_n["d_V"],
                       ses=[0.04] * 4)
    own = {key: value for key, value in SEED.items() if key != "estimator_fingerprint"}
    empty = score_block(values, buckets, floor=NF.noise_floors(own)["d_V"], sizes=sizes,
                        floors_by_n=NF.noise_floors_by_n(own)["d_V"], ses=[0.04] * 4)
    assert kept["bucket"] == "CONVERGED" and empty["bucket"] == "UNRESOLVED_AT_TOP_RUNG"
