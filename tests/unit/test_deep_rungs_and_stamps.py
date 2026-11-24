

from graph_scale_dynamics.research.compute_efficiency import (
    UNSTAMPED_ENGINE, _engine_name)
from graph_scale_dynamics.research.stability_score import score_phenotype

PROBES = ("d_s", "d_V", "d_B", "d_w")
BASE = [64, 256, 1024, 4096, 16384]
FLOORS = {"d_s": 0.2433, "d_B": 0.1355, "d_V": 0.0545, "d_w": 0.0792}


def _pheno(deep=()):
    ds = [2.0, 2.2, 2.4, 2.5, 2.6]
    pheno = {
        "base_sizes": list(BASE),
        "per_n": {str(n): {"mean_degree": 3.0, "connected_fraction": 1.0,
                           "half_volume_radius": 4.0 + i, "clustering": None,
                           "probes": {p: {"value": ds[i] if p == "d_s" else None,
                                          "bucket": None, "se": 0.05}
                                      for p in PROBES}}
                  for i, n in enumerate(BASE)},
        "probe_vectors": {"d_s": list(ds), **{p: [None] * 5 for p in PROBES if p != "d_s"}},
        "probe_bucket_vectors": {p: [None] * 5 for p in PROBES},
        "probe_se_vectors": {p: [0.05] * 5 for p in PROBES},
        "connected_fraction_vector": [1.0] * 5,
        "half_volume_radius_vector": [4.0, 5.0, 6.0, 7.0, 8.0],
        "clustering_vector": [None] * 5,
    }
    if not deep:
        return pheno
    sizes = [65536, 262144][:len(deep)]
    pheno["extension_sizes"] = list(sizes)
    pheno["extension_per_n"] = {
        str(n): {"n": n, "mean_degree": 3.0, "connected_fraction": 1.0,
                 "half_volume_radius": 9.0 + i, "clustering": None,
                 "rung_terminal_classification": "EQUILIBRATED_ACTIVE",
                 "chains_verdict": None,
                 "probes": {p: {"value": deep[i] if p == "d_s" else None,
                                "bucket": None if p == "d_s" else "REFUSED_NO_SCALING_WINDOW",
                                "se": 0.05, "valid_fraction": 1.0 if p == "d_s" else 0.0}
                            for p in PROBES}}
        for i, n in enumerate(sizes)}
    pheno["extension_probe_vectors"] = {
        "d_s": list(deep), **{p: [None] * len(sizes) for p in PROBES if p != "d_s"}}
    pheno["extension_probe_bucket_vectors"] = {
        "d_s": [None] * len(sizes),
        **{p: ["REFUSED_NO_SCALING_WINDOW"] * len(sizes) for p in PROBES if p != "d_s"}}
    pheno["extension_probe_se_vectors"] = {p: [0.05] * len(sizes) for p in PROBES}
    pheno["extension_connected_fraction_vector"] = [1.0] * len(sizes)
    pheno["extension_half_volume_radius_vector"] = [9.0 + i for i in range(len(sizes))]
    pheno["extension_clustering_vector"] = [None] * len(sizes)
    pheno["extension_mean_degree_vector"] = [3.0] * len(sizes)
    return pheno


def test_the_score_reads_the_rungs_above_the_base_block():
    shallow = score_phenotype(_pheno(), floors=FLOORS)
    deep = score_phenotype(_pheno(deep=(2.61, 2.615)), floors=FLOORS)
    assert shallow["valid_rungs"]["d_s"] == 5
    assert deep["valid_rungs"]["d_s"] == 7, "the deep rungs did not reach the score"


def test_a_law_with_no_extension_scores_exactly_as_it_did():
    assert score_phenotype(_pheno(), floors=FLOORS) == score_phenotype(
        {k: v for k, v in _pheno().items()}, floors=FLOORS)


def test_a_pre_384_phenotype_still_scores_on_its_base_block():
    stale = _pheno(deep=(2.61, 2.615))
    for key in list(stale):
        if key.startswith("extension_") and key not in ("extension_sizes", "extension_per_n"):
            del stale[key]
    scored = score_phenotype(stale, floors=FLOORS)
    assert scored["valid_rungs"]["d_s"] == 7


def test_a_missing_engine_stamp_is_its_own_class():
    assert _engine_name({}) == UNSTAMPED_ENGINE
    assert "python" not in _engine_name({}).lower()
    assert _engine_name({"resource_json": {"engine": {"name": "rust"}}}) == "rust"
    assert _engine_name({"resource_json": '{"engine": {"name": "python"}}'}) == "python"


def test_a_law_is_placed_at_its_deepest_measured_rung():
    from graph_scale_dynamics.research.stability_score import build_stability_report

    pheno = dict(_pheno(deep=(2.61, 2.615)), contract="rung-phenotype-3")
    report = build_stability_report(
        [{"candidate_id": "a" * 64, "phenotype": pheno}], None, connectivity_floor=0.9)
    from graph_scale_dynamics.research.every_law import EVERY_LAW_COLUMNS
    top = report["every_law"]["rows"][0][EVERY_LAW_COLUMNS.index("top_measured_rung")]
    assert top == 262144, f"placed at {top} while holding a 262,144 reading"
