from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_scale_dynamics.research.density_coupling import density_coupling
from graph_scale_dynamics.research.landscape_audit import _occupancy_for_n
from graph_scale_dynamics.research.refused_rungs import ladder_buckets, masked, refused
from graph_scale_dynamics.research.report_pipeline import _trajectory_rows

ROOT = Path(__file__).resolve().parents[2]
GIVEN = "REFUSED_CHAINS_DISAGREED"
BASE, DEEP = [64, 256, 1024, 4096], [16384, 65536]


def _phenotype(bucket: str | None, *, deep: bool = False) -> dict:
    sizes = BASE + (DEEP if deep else [])
    per_n = {str(n): {"mean_degree": 4.0 + 0.01 * i, "d_s": 3.0, "d_s_bucket": bucket, "d_V": 2.0, "d_V_bucket": bucket,
                      "d_B": 2.0, "d_w": 2.0} for i, n in enumerate(BASE)}
    out = {"base_sizes": BASE, "per_n": per_n, "probe_vectors": {"d_s": [3.0] * 4, "d_V": [2.0] * 4},
           "probe_bucket_vectors": {"d_s": [bucket] * 4, "d_V": [bucket] * 4},
           "mean_degree_vector": [4.0 + 0.01 * i for i in range(4)]}
    if deep:
        out.update(extension_sizes=DEEP, extension_probe_vectors={"d_s": [3.1, 3.2], "d_V": [2.0, 2.0]},
                   extension_probe_bucket_vectors={"d_s": [None, GIVEN], "d_V": [None, None]},
                   extension_mean_degree_vector=[4.1, 4.2], extension_per_n={})
    assert len(sizes) == len(out["probe_vectors"]["d_s"]) + (2 if deep else 0)
    return out


def test_a_refused_bucket_masks_its_value_and_nothing_else():
    assert refused(GIVEN) and refused("REFUSED_COMPUTE_BUDGET") and not refused(None) and not refused("CONVERGED")
    assert masked([1.0, 2.0, 3.0], [None, GIVEN]) == [1.0, None, 3.0], "a value with no bucket beside it stays"
    ph = _phenotype(None, deep=True)
    assert ladder_buckets(ph, "d_s", BASE, DEEP) == [None] * 4 + [None, GIVEN]


def test_the_density_coupling_fits_no_refused_rung():
    rows = [{"candidate_id": f"law-{i}", "sizes": BASE, "mean_degree": [4.0 + 0.1 * i] * 4,
             "probes": {"d_s": [3.0 + 0.1 * i] * 4}, "probe_buckets": {"d_s": [GIVEN] * 4}} for i in range(30)]
    found = density_coupling(rows)
    assert not found["by_rung"] and found["r2_by_rung"] == {}, found["by_rung"]
    for row in rows:
        row["probe_buckets"]["d_s"] = [None] * 4
    assert density_coupling(rows)["by_rung"]["4096"]["readings"] == 30, "read rungs are still read"


def test_the_occupancy_counts_no_refused_rung():
    found = _occupancy_for_n([{"phenotype": _phenotype(GIVEN)}], 4096, 0.25)
    assert found["gate_funnel"].get("d_s_valid", 0) == 0 and found["gate_funnel"].get("d_V_valid", 0) == 0
    assert _occupancy_for_n([{"phenotype": _phenotype(None)}], 4096, 0.25)["gate_funnel"]["d_s_valid"] == 1


def test_a_deepened_law_s_buckets_cover_its_whole_ladder():
    rows = _trajectory_rows({"phenotypes": [{"candidate_id": "deep", "phenotype": _phenotype(None, deep=True)}]})
    assert len(rows[0]["sizes"]) == len(rows[0]["probe_buckets"]["d_s"]) == len(rows[0]["probes"]["d_s"]) == 6
    sys.path.insert(0, str(ROOT))
    from graph_scale_dynamics.reporting.study_reading import _base_block
    found = _base_block({"rungs": [{"n": 4096, "finished": 1}]}, {"trajectories": rows}, {"base_sizes": BASE}, 1)
    assert found["laws_with_a_complete_block"] == 1, "the deepened law is counted, not skipped"
