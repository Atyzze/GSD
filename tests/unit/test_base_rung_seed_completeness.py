from __future__ import annotations

def test_seed_coverage_reports_the_deepest_rung_and_not_only_the_aggregate():
    from graph_scale_dynamics.research.landscape_audit import seed_replication_summary
    phenotypes = [{"phenotype": {"per_n": {
        "64": {"measurement_seed_count": 3}, "256": {"measurement_seed_count": 3},
        "1024": {"measurement_seed_count": 3}, "4096": {"measurement_seed_count": 3},
        "16384": {"measurement_seed_count": 1},
    }}} for _ in range(400)]
    out = seed_replication_summary(phenotypes)
    assert out["candidates_with_any_multi_seed_base_rung"] == 400
    deepest = out["deepest_rung_replication"]
    assert deepest["n"] == 16384
    assert deepest["multiple_seeds"] == 0 and deepest["multiple_seed_fraction"] == 0.0
