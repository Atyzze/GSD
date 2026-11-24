from __future__ import annotations

from graph_scale_dynamics.reporting import study_reading
from graph_scale_dynamics.research import report_pipeline
from graph_scale_dynamics.research.stability_score import NO_METRIC_STRUCTURE_BUCKET


def test_a_law_that_went_deeper_is_counted_at_the_base_block_s_top():
    flow = {"trajectories": [
        {"sizes": [64, 256, 1024, 4096], "probe_buckets": {"d_s": [None, None, None, "REFUSED_NO_SCALING_WINDOW"]}},
        {"sizes": [64, 256, 1024, 4096, 16384], "probe_buckets": {"d_s": [None, None, None, None, None]}}]}
    out = study_reading._base_block({"rungs": [], "gates": []}, flow, {"base_sizes": [64, 256, 1024, 4096]}, 2)
    assert sum(out["d_s_at_the_top_rung"]["kinds"].values()) == 2, out


def test_report_05_keeps_the_gates_buckets():
    specimens = [{"candidate_id": "a"}]
    landscape = {"a": {"buckets": {"d_s": NO_METRIC_STRUCTURE_BUCKET}, "dimensional_class": "NO_METRIC_STRUCTURE"}}
    taxonomy = report_pipeline._failure_taxonomy(specimens, landscape)
    found = taxonomy.get("by_probe") or taxonomy.get("probes") or taxonomy
    assert found["d_s"][NO_METRIC_STRUCTURE_BUCKET] == 1, taxonomy
