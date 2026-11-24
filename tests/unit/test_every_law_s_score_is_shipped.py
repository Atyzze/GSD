from __future__ import annotations

from graph_scale_dynamics.research.every_law import EVERY_LAW_COLUMNS, every_law_families
from graph_scale_dynamics.research.stability_score import build_stability_report

from tests.unit.test_the_reports_read_one_landscape import _phenotype


def _laws(count: int) -> list[dict]:
    laws = []
    for i in range(count):
        phenotype = _phenotype(1.0, drift=0.02 * i)
        phenotype["contract"] = "rung-phenotype-3"
        laws.append({"candidate_id": f"law-{i}", "phenotype": phenotype})
    return laws


def test_report_22_ships_every_scored_law_s_family_and_no_score():
    body = build_stability_report(_laws(5), None)
    assert body["laws_scored"] == 5 and "ranked" not in body
    assert body["every_law"]["columns"] == list(EVERY_LAW_COLUMNS)
    families = every_law_families(body)
    assert set(families) == {f"law-{i}" for i in range(5)}
    assert all(set(f) == {"family", "ambiguous_with"} for f in families.values())
    assert "score" not in body["population"]


def test_the_bundle_reading_counts_families_over_every_law():
    from graph_scale_dynamics.reporting.study_reading import _families
    body = {"every_law": {"columns": list(EVERY_LAW_COLUMNS),
                          "rows": [["a", "square_lattice", [], False, 4096], ["b", None, ["x", "y"], False, 4096],
                                   ["c", None, [], False, 4096]]},
            "control_families": {"matched": {"square_lattice": 1}}, "laws_scored": 3}
    decisions = [{"candidate_id": law, "rule": "d_s_settled"} for law in ("a", "b", "c", "d")]
    families, standing = _families(body, decisions)
    assert standing == {"a": ("named", "square_lattice"), "b": ("ambiguous", None), "c": ("none", None)}
    assert families["d_s_settled_laws"] == {"laws": 4, "named": 1, "ambiguous": 1, "none": 1, "unranked": 1}
    assert "top" not in families


def _deep(i: int, degrees: list) -> dict:
    sizes = [64, 256, 1024, 4096, 16384]
    phenotype = {"contract": "rung-phenotype-3", "base_sizes": sizes[:4], "extension_sizes": sizes[4:],
                 "per_n": {str(n): {"mean_degree": d} for n, d in zip(sizes[:4], degrees[:4], strict=True)},
                 "extension_per_n": {str(sizes[4]): {"mean_degree": degrees[4]}}}
    return {"candidate_id": f"deep-{i}", "phenotype": phenotype}


def test_the_precision_basis_is_measured_on_the_campaign_s_own_laws():
    from graph_scale_dynamics.research.stability_report_parts import next_rung_precision
    settled = [_deep(i, [3.0, 3.6, 3.62, 3.62, 3.63]) for i in range(3)]
    moved = [_deep(10 + i, [3.0, 3.6, 3.62, 3.62, 4.4]) for i in range(2)]
    flowing = [_deep(20, [1.0, 2.0, 4.0, 8.0, 16.0])]
    base_only = [{"candidate_id": "base", "phenotype": {"base_sizes": [64, 256, 1024, 4096],
                                                        "per_n": {str(n): {"mean_degree": 3.0}
                                                                  for n in (64, 256, 1024, 4096)}}}]
    read = next_rung_precision(settled + moved + flowing + base_only)
    assert read["laws"] == 6 and read["truly_settled"] == 3 and read["base_rate"] == 0.5
    assert read["steps"] == {"4096->16384": 6}
    assert read["settled"] == 0.6 and read["laws_meeting"]["settled"] == 5, "the flat laws, three held"
    assert "424" not in read["basis"] and "6 laws" in read["basis"]
    assert next_rung_precision(base_only)["base_rate"] is None
    body = build_stability_report(settled + moved, None)
    assert body["density"]["measured_precision_at_the_next_rung"]["laws"] == 5
