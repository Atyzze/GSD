from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.calibration import contract, rule
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.measurements import calibration as C

OLD_FAMILIES = contract.SUITE_FAMILIES[:17]
NEW_FAMILIES = contract.SUITE_FAMILIES[17:23]
FAMILIES_OF_800 = contract.SUITE_FAMILIES[23:]


def _family(name: str) -> dict:
    return next(family for family in C.CALIBRATION_FAMILIES if family["name"] == name)


def test_what_the_table_holds_is_what_the_rule_gives_and_no_hand_wrote_it():
    assert json.loads(rule.HOLDS.read_text(encoding="utf-8")) == rule.derive(), (
        "python3 tools/table_rule.py --write, never an edit of the file")
    assert not hasattr(C, "CALIBRATION_LADDER_TOLERANCES") and not hasattr(C, "D_V_READS_FROM"), (
        "no tolerance and no size is typed by hand")
    source = (FP.repository_root() / FP.FAMILY_SOURCE).read_text(encoding="utf-8")
    assert '"refusal_gated_from": {' not in source


def test_every_family_of_the_suite_is_held_one_way_or_the_other():
    held = rule.holds()
    for name in contract.SUITE_FAMILIES:
        family = _family(name)
        with_one, without = name in held["with_a_dimension"], name in held["without_a_dimension"]
        assert with_one != without, name
        assert (family["expectation"] == "REFUSE") == without, name
        for probe, band in (held["with_a_dimension"].get(name) or {}).items():
            assert family["theory"][probe] == pytest.approx(band["theory"]), (name, probe)
    assert set(held["with_a_dimension"]) | set(held["without_a_dimension"]) == set(contract.SUITE_FAMILIES)


def test_a_family_without_a_dimension_is_refused_by_every_probe_from_the_size_a_verdict_is_relied_on():
    from graph_scale_dynamics.scaleflow import probes
    for name in rule.holds()["without_a_dimension"]:
        assert _family(name)["refusal_gated_from"] == dict.fromkeys(
            ("d_s", "d_B", "d_w", "d_V"), probes.A_VERDICT_IS_RELIED_ON_FROM_NODES), name
    assert C.refusal_required_from("periodic_ring") == {}


def test_a_probe_is_held_from_where_the_judged_set_read_it_within_the_band_of_the_size_below():
    assert C.ladder_tolerance("periodic_cubic_quotient", "d_s", 1024) == 0.3
    assert C.ladder_tolerance("periodic_cubic_quotient", "d_s", 256) is None, "under the smallest size judged"
    assert C.ladder_tolerance("periodic_cubic_quotient", "d_B", 1024) is None, "refused there in the judged reading"
    assert C.ladder_tolerance("periodic_cubic_quotient", "d_B", 4096) == 0.35
    assert C.ladder_tolerance("periodic_body_centred_cubic_lattice", "d_B", 4096) is None
    assert C.ladder_tolerance("periodic_body_centred_cubic_lattice", "d_B", 16384) == 0.35
    assert C.ladder_tolerance("periodic_cubic_lattice", "d_w", 15625) is None, "reported under 16,384"
    assert C.ladder_tolerance("periodic_cubic_lattice", "d_w", 64000) == 0.25, "the band of 16,384, the size below"
    assert C.ladder_tolerance("periodic_tesseract_quotient", "d_w", 65536) is None
    assert C.ladder_tolerance("periodic_tesseract_quotient", "d_w", 1048576) == 0.25
    assert C.ladder_tolerance("periodic_hypercubic_lattice_4d", "d_V", 1296) == 0.8
    assert C.ladder_tolerance("periodic_ring", "d_V", 1048576) == 0.05, "above the largest size judged, its band"
    assert C.ladder_tolerance("sierpinski_carpet", "d_s", 32768) is None, "held to no band: measured and shown"
    assert C.ladder_tolerance("hyperbolic_geometric_graph", "d_s", 65536) is None


def test_the_rule_rests_on_the_criterion_committed_before_the_table_was_seen_and_its_passing_reading():
    document = rule.rule()
    assert document["rests_on"]["criterion"].endswith("table_known_answers_criterion.json")
    assert document["rests_on"]["judged"].endswith("table_known_answers_judged.json")
    criterion = json.loads((FP.repository_root() / document["rests_on"]["criterion"]).read_text(encoding="utf-8"))
    judged = json.loads((FP.repository_root() / document["rests_on"]["judged"]).read_text(encoding="utf-8"))
    assert criterion["committed_utc"] < judged["judged_utc"] and judged["passes"]
    assert set(criterion["with_a_dimension"]) | set(criterion["without_a_dimension"]) == set(contract.SUITE_FAMILIES)
    with pytest.raises(ValueError, match="passing reading"):
        rule.derive({**document, "rests_on": {**document["rests_on"], "judged": document["rests_on"]["criterion"]}})


def test_the_close_packed_4d_lattices_are_held_from_where_their_own_cells_read():
    for name in FAMILIES_OF_800[:2]:
        held = rule.holds()["with_a_dimension"][name]
        assert {probe: band["theory"] for probe, band in held.items()} == {"d_s": 4.0, "d_V": 4.0, "d_B": 4.0, "d_w": 2.0}
    assert C.ladder_tolerance("periodic_a4_lattice", "d_w", 1048576) == 0.25
    assert set(FAMILIES_OF_800[2:]) <= set(rule.holds()["without_a_dimension"])


def test_the_four_lattice_starts_are_the_graphs_the_fleet_builds_at_every_size_a_law_runs():
    from graph_scale_dynamics.decisions import engine
    from graph_scale_dynamics.measurements import known_answers
    assert tuple(engine.Policy().ladder()) == C.SIZES_A_LAW_RUNS
    for name in NEW_FAMILIES[:4]:
        family = _family(name)
        assert family["ladder"] == C.SIZES_A_LAW_RUNS and all(known_answers.reaches(name, n) for n in family["ladder"])
        n, edges = family["build"](1024)
        assert (n, edges) == (1024, known_answers.edges(name, 1024))
        assert C.control_family_edges(name, 1024) == [tuple(edge) for edge in edges]


def test_the_two_hyperbolic_families_are_the_judged_structures():
    from graph_scale_dynamics.research import known_structures, planted_geometries
    for layers in (5, 6, 7):
        built = C.hyperbolic_triangle_tiling(layers)
        assert built == known_structures.hyperbolic_triangles(layers)
        assert C.hyperbolic_triangle_tiling_nodes(layers) == built[0]
    assert [C.hyperbolic_triangle_tiling_nodes(layers) for layers in (7, 11)] == [4264, 200593]
    drawn = C.hyperbolic_geometric_graph(1024, 15)
    assert planted_geometries._largest(*drawn) == known_structures.hyperbolic_geometric_graph(1024, 12.0, 1.0, 15)
    assert _family("hyperbolic_geometric_graph")["build_seeded"](1024, 16) != drawn, "drawn again for each seed"


def test_a_family_s_fingerprint_covers_the_module_its_builder_lives_in(tmp_path):
    for name in OLD_FAMILIES:
        assert FP.modules_a_family_builds_with(name) == [], f"{name} is built inside the family module, as before"
    built_with = {name: FP.modules_a_family_builds_with(name) for name in NEW_FAMILIES}
    for name in NEW_FAMILIES[:4]:
        assert "graph_scale_dynamics.measurements.known_answers" in built_with[name]
    for name in NEW_FAMILIES[4:]:
        assert "graph_scale_dynamics.measurements.hyperbolic_graphs" in built_with[name]
    tree = tmp_path / "tree"
    for relative in (FP.FAMILY_SOURCE, "graph_scale_dynamics/measurements/__init__.py",
                     "graph_scale_dynamics/measurements/known_answers.py",
                     "graph_scale_dynamics/measurements/hyperbolic_graphs.py"):
        (tree / relative).parent.mkdir(parents=True, exist_ok=True)
        (tree / relative).write_text((FP.repository_root() / relative).read_text(encoding="utf-8"), encoding="utf-8")
    FP.clear_caches()
    try:
        before = {name: FP.family_fingerprint(name, str(tree)) for name in contract.SUITE_FAMILIES}
        assert before == {name: FP.family_fingerprint(name) for name in contract.SUITE_FAMILIES}
        builders = tree / "graph_scale_dynamics/measurements/known_answers.py"
        builders.write_text(builders.read_text(encoding="utf-8").replace("SMALLEST_SIDE = 4", "SMALLEST_SIDE = 5"),
                            encoding="utf-8")
        FP.clear_caches()
        after = {name: FP.family_fingerprint(name, str(tree)) for name in contract.SUITE_FAMILIES}
    finally:
        FP.clear_caches()
    moved = {name for name in contract.SUITE_FAMILIES if after[name] != before[name]}
    assert moved == set(NEW_FAMILIES[:4]), "a change to the starts' builders makes their cells stale, and no others"


def test_the_stability_score_matches_a_law_to_the_families_it_always_did():
    from graph_scale_dynamics.calibration import fingerprint
    from graph_scale_dynamics.research import stability_score as S

    def cell(family):
        return {"status": "ok", "family": family, "n": 4096, "science_fingerprint": fingerprint.science_fingerprint(),
                "cell_fingerprint": fingerprint.cell_fingerprint(family),
                "channels": {"d_s": {"valid": True, "value": 3.0, "se": 0.05}}}
    table = {"cells": {name: cell(name) for name in ("periodic_cubic_lattice", "periodic_cubic_quotient")}}
    assert set(S.control_family_reference(table)) == {"periodic_cubic_lattice"}, (
        "a table that holds the six families of 765 changes nothing the stability score reads")
