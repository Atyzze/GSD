from __future__ import annotations

import ast
from pathlib import Path

import pytest

from graph_scale_dynamics.research.report_pipeline import _trajectory_rows
from graph_scale_dynamics.decisions import evidence

ROOT = Path(__file__).resolve().parents[2]
BASE = [64, 256, 1024, 4096, 16384]
PHENOTYPE_EXTENSION_FIELDS = ("extension_sizes", "extension_per_n", "extension_probe_vectors")


def _pheno(deep=True):
    p = {"base_sizes": list(BASE),
         "probe_vectors": {"d_s": [None, 2.43, 2.10, 2.09, 2.00],
                           "d_V": [None] * 5, "d_B": [None] * 5, "d_w": [None] * 5},
         "per_n": {str(n): {"mean_degree": 3.0} for n in BASE}}
    if deep:
        p.update({
            "extension_sizes": [65536, 262144],
            "extension_probe_vectors": {"d_s": [1.99, 1.98], "d_V": [None] * 2,
                                        "d_B": [None] * 2, "d_w": [None] * 2},
            "extension_per_n": {"65536": {"mean_degree": 3.0},
                                "262144": {"mean_degree": 3.0}}})
    return p


def test_a_trajectory_row_carries_the_full_ladder():
    row = _trajectory_rows({"phenotypes": [{"candidate_id": "d", "phenotype": _pheno()}]})[0]
    assert row["sizes"] == BASE + [65536, 262144]
    assert len(row["probes"]["d_s"]) == 7
    assert len(row["mean_degree"]) == 7, (
        "the ladder, the probe vector and the mean degree vector must stay the "
        "same length or the rung label points at the wrong reading")


def test_a_law_without_an_extension_is_unchanged():
    row = _trajectory_rows({"phenotypes": [
        {"candidate_id": "b", "phenotype": _pheno(deep=False)}]})[0]
    assert row["sizes"] == BASE
    assert len(row["probes"]["d_s"]) == 5


def _summaries(sizes):
    return {n: {"n": n, "seeds": 3,
                "d_s": {"mean": 2.0, "se": 0.09, "n_seeds": 3},
                "d_V": {"mean": None, "n_seeds": 0},
                "d_B": {"mean": None, "n_seeds": 0},
                "d_w": {"mean": None, "n_seeds": 0},
                "mean_degree": {"mean": 3.0, "se": 0.0, "n_seeds": 3},
                "connected_fraction": {"mean": 1.0, "n_seeds": 3},
                "clustering": {"mean": 0.0006, "n_seeds": 3},
                "two_core_fraction": {"mean": 1.0, "n_seeds": 3},
                "degree_heterogeneity": {"mean": 0.02, "n_seeds": 3},
                "half_volume_radius": {"mean": 7.0, "n_seeds": 3},
                "density": {"mean": 0.0002, "n_seeds": 3},
                "effective_samples": {"mean": 40.0, "n_seeds": 3},
                "iat_sweeps": {"mean": 1.3, "n_seeds": 3},
                "stationarity_drift": {"mean": -1e-5, "n_seeds": 3},
                "probe_refusals": {"d_V": {"EXPONENTIAL_GROWTH": 3}}}
            for n in sizes}


def _extension_fixture():
    spec = {"ladder": list(BASE),
            "base_block": {"contract": "rung-phenotype-3", "sizes": list(BASE)},
            "limits": {"mean_degree_window": {"min": 1.5, "max": 8},
                       "connectivity_floor": 0.9}}
    summaries = _summaries(BASE + [65536])
    states = {n: evidence._b143_rung_sampling_state(spec, n, summaries[n], []) for n in summaries}
    pheno = evidence._build_four_rung_phenotype(spec, summaries, states)
    return pheno, pheno["extension_per_n"]["65536"], pheno["per_n"][str(BASE[-1])]


def test_every_field_on_an_extension_cell_comes_back_populated():
    _, cell, base_cell = _extension_fixture()
    walked = {"mean_degree", "connected_fraction", "clustering", "half_volume_radius",
              "two_core_fraction", "degree_heterogeneity", "rung_terminal_classification",
              "chains_verdict", "probes"}
    missing = sorted(walked - set(cell))
    assert not missing, (
        f"a base-block cell carries these and the extension does not: {missing}. "
        "Every reader that walks a rung walks both.")
    assert walked <= set(base_cell) | {"chains_verdict"}, (
        "this list has drifted from the base-block cell it mirrors")
    unsourced = sorted(k for k, v in cell.items()
                       if k != "probes" and v is None and base_cell.get(k) is not None)
    assert not unsourced, f"null on the extension and populated on the base block: {unsourced}"
    assert cell["degree_heterogeneity"] == pytest.approx(0.02)


def test_an_extension_probe_cell_carries_a_bucket():
    _, cell, base_cell = _extension_fixture()
    for probe in ("d_s", "d_V", "d_B", "d_w"):
        assert set(base_cell["probes"][probe]) <= set(cell["probes"][probe]), (
            f"{probe}: extension probe cell is missing keys a base one has")
    assert cell["probes"]["d_V"]["bucket"] is not None
    assert cell["d_V_bucket"] == cell["probes"]["d_V"]["bucket"]
    assert cell["probes"]["d_s"]["value"] is not None
    assert cell["probes"]["d_s"]["bucket"] is None


def _names_read_in(tree: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def test_every_phenotype_extension_field_has_a_reader_outside_its_writer():
    writers = {"graph_scale_dynamics/decisions/evidence.py",
               "graph_scale_dynamics/research/phenotype_rebuild.py"}
    sources = [p for p in (ROOT / "graph_scale_dynamics").rglob("*.py")
               if str(p.relative_to(ROOT)) not in writers]
    read_names: set[str] = set()
    for path in sources:
        try:
            read_names |= _names_read_in(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:  # pragma: no cover
            continue
    unread = [f for f in PHENOTYPE_EXTENSION_FIELDS if f not in read_names]
    assert not unread, (
        f"written by the phenotype and read by nothing: {unread}. Either wire a "
        "consumer or stop writing the field.")
