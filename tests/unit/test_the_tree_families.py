from __future__ import annotations

import pytest

from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES
from graph_scale_dynamics.measurements.calibration import (
    CALIBRATION_FAMILIES, CRT_DF, CRT_DS, CRT_DW, balanced_tree, erdos_renyi_graph, uniform_random_tree)
from graph_scale_dynamics.research.family_classification import classify_law
from graph_scale_dynamics.research.stability_score import gate_bucket_names, population_summary

SIZES = [64, 256, 1024, 4096, 16384]


def test_a_uniform_random_tree_is_a_tree():
    for n in (64, 1024, 8192):
        count, edges = uniform_random_tree(n, seed=3)
        assert count == n
        assert len(edges) == n - 1, "a tree has exactly n-1 edges"
        assert len(set(edges)) == len(edges), "no repeated edge"
        mean_degree = 2 * len(edges) / n
        assert mean_degree < 2.0
        assert (mean_degree - 1.0) < 1.0, "the branching line for any tree is below 1"


def test_uniform_random_trees_are_connected_and_vary_with_the_seed():
    from graph_scale_dynamics.measurements.estimators import (
        build_adjacency, largest_component)
    first = uniform_random_tree(512, seed=1)[1]
    second = uniform_random_tree(512, seed=2)[1]
    assert first != second, "the family declares graph_varies_per_seed"
    assert uniform_random_tree(512, seed=1)[1] == first, "and is a pure function of the seed"
    count, edges = uniform_random_tree(512, seed=1)
    assert len(largest_component(count, build_adjacency(count, edges))) == count


def test_balanced_tree_shape():
    count, edges = balanced_tree(2, 5)
    assert count == 2 ** 6 - 1
    assert len(edges) == count - 1


def test_erdos_renyi_hits_its_mean_degree():
    for mean_degree in (2.5, 3.0, 4.0):
        count, edges = erdos_renyi_graph(4096, mean_degree, seed=1)
        assert abs(2 * len(edges) / count - mean_degree) < 0.01
        assert all(a < b for a, b in edges), "edges are normalised and simple"


def test_the_suite_covers_trees_random_graphs_and_four_dimensions():
    for required in ("uniform_random_tree", "balanced_binary_tree",
                     "erdos_renyi_sparse", "erdos_renyi_mid", "erdos_renyi_dense",
                     "random_3_regular", "random_4_regular",
                     "periodic_hypercubic_lattice_4d"):
        assert required in SUITE_FAMILIES, f"{required} must be in the authoritative suite"
    assert len(SUITE_FAMILIES) >= 15
    assert len(set(SUITE_FAMILIES)) == len(SUITE_FAMILIES), "no family declared twice"


def test_every_suite_family_is_declared_and_buildable():
    declared = {f["name"]: f for f in CALIBRATION_FAMILIES}
    for name in SUITE_FAMILIES:
        assert name in declared, f"{name} is in the suite but not declared"
        family = declared[name]
        assert family["ladder"], f"{name} has no ladder"
        assert family["expectation"] in ("MEASURE", "REFUSE")
        assert family.get("why"), f"{name} must say why it is in the table"
        if family["expectation"] == "MEASURE":
            assert family["theory"], f"{name} is MEASURE and must carry theory"
        smallest = min(family["ladder"], key=lambda p: family["size"](p))
        count, edges = family["build"](smallest)
        assert count > 0 and edges, f"{name} built nothing at its smallest rung"
        assert count == family["size"](smallest), f"{name}'s declared size is wrong"


def test_the_crt_carries_three_distinct_exact_dimensions():
    crt = next(f for f in CALIBRATION_FAMILIES if f["name"] == "uniform_random_tree")
    assert crt["theory"]["d_s"] == pytest.approx(4 / 3)
    assert crt["theory"]["d_B"] == pytest.approx(2.0)
    assert crt["theory"]["d_w"] == pytest.approx(3.0)
    assert CRT_DS == pytest.approx(2 * CRT_DF / CRT_DW), "Alexander-Orbach must hold"
    assert len({CRT_DS, CRT_DF, CRT_DW}) == 3


def test_the_population_histogram_counts_every_law():
    scored = [
        {"score": 0.0, "buckets": {"d_s": "NO_METRIC_STRUCTURE", "d_V": "NOT_ATTEMPTED",
                                   "d_B": "NOT_ATTEMPTED", "d_w": "NOT_ATTEMPTED"}},
        {"score": 0.0, "buckets": {"d_s": "NO_METRIC_STRUCTURE", "d_V": "NO_METRIC_STRUCTURE",
                                   "d_B": "CONTROL_PERIODIC_RING", "d_w": "NOT_ATTEMPTED"}},
        {"score": 25.0, "buckets": {"d_s": "CONVERGED", "d_V": "DEGRADED_WITH_N",
                                    "d_B": "NOT_ATTEMPTED", "d_w": "NOT_ATTEMPTED"}},
    ]
    summary = population_summary(scored)
    for probe, row in summary["bucket_counts_reconcile"].items():
        assert row["balanced"], f"{probe} column does not sum to the population"
        assert row["counted"] == len(scored)
    assert summary["bucket_counts_unaccounted"] == {}
    assert summary["settled_then_withheld_by_probe"]["d_s"] == 2
    assert summary["bucket_counts_by_probe"]["d_s"]["NO_METRIC_STRUCTURE"] == 2


def test_an_unknown_bucket_is_reported_rather_than_dropped():
    scored = [{"score": 0.0, "buckets": {"d_s": "SOMETHING_NEW", "d_V": "NOT_ATTEMPTED",
                                         "d_B": "NOT_ATTEMPTED", "d_w": "NOT_ATTEMPTED"}}]
    summary = population_summary(scored)
    assert summary["bucket_counts_unaccounted"] == {"d_s:SOMETHING_NEW": 1}
    assert summary["bucket_counts_reconcile"]["d_s"]["balanced"] is False


def test_gate_bucket_names_covers_every_gate():
    names = set(gate_bucket_names())
    assert "NO_METRIC_STRUCTURE" in names and "ON_BRANCHING_LINE" not in names, "the tree line left at 790"
    assert any(n.startswith("CONTROL_") for n in names)


def test_a_lattice_classifies_as_a_lattice():
    result = classify_law({"d_s": 2.02, "d_V": 1.94, "d_B": 2.10, "d_w": 2.05},
                          n=16384, mean_degree=4.0)
    assert result["nearest_geometry"]["family"].startswith("periodic_")
    assert result["nearest_geometry"]["match"] == "match"
    assert "branching_line" not in result


def test_a_real_tree_classifies_as_the_tree_family():
    result = classify_law({"d_s": 1.26, "d_V": 1.77, "d_B": 1.55, "d_w": 2.58},
                          n=16384, mean_degree=2.0)
    tree = next(found for found in result["geometries"] if found["family"] == "uniform_random_tree")
    assert tree["match"] == "match" and tree in result["geometries"][:2], (
        "on theory alone a tree's four readings lie inside the gasket's bands too; the table's measured anchors "
        "part them, and the table holds a tree by d_s only")


def test_classification_declines_without_enough_probes():
    result = classify_law({"d_s": 2.0}, n=16384, mean_degree=4.0)
    assert result["nearest_geometry"] is None


def test_the_declared_licence_file_exists():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    licence = root / "LICENSE"
    assert licence.is_file(), "pyproject.toml declares license = {file = 'LICENSE'}"
    text = licence.read_text(encoding="utf-8")
    assert "LGPL" in text, "the bundled glibc must be attributed"
    assert "util-linux" in text, "the bundled unshare must be attributed"
