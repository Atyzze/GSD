from __future__ import annotations

import math

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import structure
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import (
    cell_key, extension_ladder, family_ladder, measure_cell, plan_cells, plan_extension_cells, suite_families,
)
from graph_scale_dynamics.calibration.extension import add_structure, census_plan
from graph_scale_dynamics.measurements.calibration import periodic_ring, periodic_cubic_lattice
from graph_scale_dynamics.measurements.structure_census import census
from graph_scale_dynamics.research.structure_reading import calibration_readings


def test_no_plan_reaches_past_the_campaign_s_top_rung():
    from graph_scale_dynamics.calibration.deviation import CAMPAIGN_RUNGS
    assert C.MAX_NODES == max(CAMPAIGN_RUNGS)
    for family in suite_families():
        top = max(r["n"] for r in family_ladder(family))
        assert top <= C.MAX_NODES, family["name"]
        sizes = [r["n"] for r in extension_ladder(family)]
        assert all(top < n <= C.MAX_NODES for n in sizes), (family["name"], top, sizes)


def test_the_gate_plan_is_the_frozen_one():
    families = suite_families()
    assert len(plan_cells(families, seeds=C.AUTHORITATIVE_SEEDS)) == 2560, (
        "1,550, 529's two families and 765's six: four lattice starts at the eight sizes a law runs (320), the "
        "triangle tiling at seven (70) and the hyperbolic geometric graph at five (50); and 800's four: A4 (110), "
        "D4 (100) and the random graphs of mean degree 16 and 32 (90 each)")
    extension = plan_extension_cells(families, seeds=C.EXTENSION_SEEDS)
    assert extension and all(t["extension"] for t in extension)
    assert not {t["key"] for t in extension} & {t["key"] for t in plan_cells(families, seeds=10)}


def _cell(family, parameter, seed, n, *, value=1.0, structure_record=None):
    cell = {"family": family, "parameter": parameter, "seed": seed, "n": n, "status": "ok",
            "cell_fingerprint": FP.cell_fingerprint(family, None), "elapsed_seconds": 1.0,
            "channels": {ch: {"valid": True, "value": value, "se": 0.01, "reason": None} for ch in C.CHANNELS}}
    if structure_record is not None:
        cell["structure"] = structure_record
    return cell


def test_an_extension_cell_is_charted_and_moves_nothing_the_gate_reads():
    families = suite_families(["periodic_ring"])
    ring = families[0]
    document = T.new_table(families, seeds=1, max_nodes=None, authoritative=True, profile="full")
    for rung in family_ladder(ring):
        document["cells"][cell_key("periodic_ring", rung["parameter"], 0)] = _cell(
            "periodic_ring", rung["parameter"], 0, rung["n"])
    T.refresh(document, families, seeds=1, max_nodes=None)
    before_plan = dict(document["plan"])
    before = document["deviation"]["families"]["periodic_ring"]
    before_verdict, before_rows = document["deviation"]["verdict"], len(before["rows"])
    document["cells"][cell_key("periodic_ring", 4194304, 0)] = _cell("periodic_ring", 4194304, 0, 4194304,
                                                                     value=9.0)
    T.refresh(document, families, seeds=1, max_nodes=None)
    after = document["deviation"]["families"]["periodic_ring"]
    assert document["plan"] == before_plan
    assert document["deviation"]["verdict"] == before_verdict
    assert len(after["rows"]) == before_rows and after["verdict"] == before["verdict"]
    assert not after.get("extension_rows")


def test_the_cells_past_the_ladders_never_move_a_ladder_s_floor():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    import json
    from pathlib import Path

    from graph_scale_dynamics.calibration import extension_cells, gate_cells
    from graph_scale_dynamics.research.stability_score import floor_at, noise_floors, noise_floors_by_n

    seed = json.loads((Path(__file__).resolve().parents[2] / "calibration" / "seed_table.json").read_text())
    from graph_scale_dynamics.calibration.cells import plan_cells, plan_extension_cells, suite_families
    gate = gate_cells(seed)
    assert len(gate) == len(plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)) == 2560
    assert len(extension_cells(seed)) == len(plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)) == 24
    own = {key: value for key, value in seed.items() if key != "estimator_fingerprint"}
    assert noise_floors(own) == noise_floors({"cells": gate})
    with_extension, ladders_only = noise_floors_by_n(own)["d_s"], noise_floors_by_n({"cells": gate})["d_s"]
    assert with_extension == ladders_only, "the ladders decide alone"
    assert max(with_extension) <= C.MAX_NODES
    assert floor_at(ladders_only, 4_194_304, fallback=None) is None


def test_the_ring_census_reads_its_theory_and_the_slopes_read_one_dimension():
    rows = []
    for size in (256, 1024, 4096):
        n, edges = periodic_ring(size)
        record = structure.summary(n, edges)
        assert math.isclose(record["gap"], 1 - math.cos(2 * math.pi / size), rel_tol=1e-6)
        assert record["diameter_lower"] == size // 2 and record["giant_fraction"] == 1.0
        rows.append({"n": size, "structure": structure.rung_structure([{"structure": record}])})
    structure.local_exponents(rows)
    top = rows[-1]["structure"]
    assert abs(top["implied_d_s"] - 1.0) < 0.01 and abs(top["implied_d_f"] - 1.0) < 0.01
    assert "gap_slope" not in rows[0]["structure"]
    reading = calibration_readings({"periodic_ring": {"rows": rows}})["periodic_ring"]
    assert reading["finite_dimension"] is None and "two rungs" in reading["why"]
    for size in (16384, 65536):
        n, edges = periodic_ring(size)
        rows.append({"n": size, "structure": structure.rung_structure([{"structure": structure.summary(n, edges)}])})
    reading = calibration_readings({"periodic_ring": {"rows": rows}})["periodic_ring"]
    assert reading["finite_dimension"] is True and abs(reading["implied_spectral_dimension"] - 1.0) < 0.01


def test_a_census_goes_on_seed_zero_of_a_fixed_graph_and_seeds_zero_to_two_of_a_draw():
    ring, tree = suite_families(["periodic_ring", "uniform_random_tree"])
    assert structure.wanted(ring, 0) and not structure.wanted(ring, 1)
    assert all(structure.wanted(tree, s) for s in range(3)) and not structure.wanted(tree, 3)
    first = measure_cell("periodic_ring", 64, 0, cell_fingerprint="x", science_fingerprint="y")
    second = measure_cell("periodic_ring", 64, 1, cell_fingerprint="x", science_fingerprint="y")
    assert first["status"] == "ok" and first["structure"]["diameter_lower"] == 32
    assert "structure" not in second


def test_the_backfill_adds_the_census_without_touching_a_probe(tmp_path):
    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=2, max_nodes=300, authoritative=False, profile="reduced")
    for size in (64, 128, 256):
        for seed in (0, 1):
            document["cells"][cell_key("periodic_ring", size, seed)] = _cell("periodic_ring", size, seed, size)
    before = {k: dict(v["channels"]) for k, v in document["cells"].items()}
    todo = census_plan(document, families)
    assert [t["key"] for t in todo] == ["periodic_ring:64:0", "periodic_ring:128:0", "periodic_ring:256:0"]
    done = add_structure(document, tmp_path / "table.json", families, gate_seeds=2, gate_max_nodes=300,
                         workers=0, log=lambda *_: None)
    assert done["added"] == 3 and done["failed"] == 0
    assert {k: v["channels"] for k, v in document["cells"].items()} == before
    rows = document["deviation"]["families"]["periodic_ring"]["rows"]
    assert [r["structure"]["diameter_lower"] for r in rows] == [32, 64, 128]
    assert abs(rows[-1]["structure"]["implied_d_s"] - 1.0) < 0.02
    assert census_plan(document, families) == []


def test_the_calibration_census_reads_a_cubic_lattice_by_lanczos_and_the_fleet_census_is_unchanged():
    n, edges = periodic_cubic_lattice(16)
    fleet = census(n, edges)["largest_component"]["spectral_gap"]
    calibration = census(n, edges, shift_invert_below_dimension=2.5)["largest_component"]["spectral_gap"]
    assert calibration["method"] == "lanczos_deflated"
    expected = (1 - math.cos(2 * math.pi / 16)) / 3
    assert math.isclose(calibration["value"], expected, rel_tol=1e-5)
    assert math.isclose(fleet["value"], expected, rel_tol=1e-5)
    ring = census(*periodic_ring(1024), shift_invert_below_dimension=2.5)["largest_component"]["spectral_gap"]
    assert ring["method"] == "shift_invert"


def test_a_census_a_size_limit_cut_short_is_read_again_whole(tmp_path):
    from graph_scale_dynamics.calibration import structure, structure_limits
    assert structure.GAP_MAX_N == structure.CLIQUE_MAX_N == structure.SQUARE_MAX_N == 1_048_576, (
        "the calibration's top rung (638: 4,194,304 until then, which no rung reached)")
    assert structure_limits()["before_531"] == structure.LIMITS_BEFORE_531
    cut = {"n": 2_097_152, "gap": None, "gap_reason": "not computed above N=1048576",
           "triangles_per_node": None, "squares_per_node": None}
    assert structure.cut_off(cut) and structure.cut_off(dict(cut, gap=1e-9, gap_reason=None))
    assert not structure.cut_off(dict(cut, gap=1e-9, gap_reason=None, triangles_per_node=0.0, squares_per_node=0.0))
    assert not structure.cut_off({"error": "boom"})
    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=1, max_nodes=300, authoritative=False, profile="reduced")
    for size in (64, 128):
        document["cells"][cell_key("periodic_ring", size, 0)] = _cell("periodic_ring", size, 0, size)
    add_structure(document, tmp_path / "table.json", families, gate_seeds=1, gate_max_nodes=300,
                  workers=0, log=lambda *_: None)
    assert census_plan(document, families) == []
    cell = document["cells"][cell_key("periodic_ring", 128, 0)]
    assert cell["structure"]["contract"] == "calibration-structure-2"
    cell["structure"].update(gap=None, gap_reason="not computed above N=100")
    assert [t["key"] for t in census_plan(document, families)] == ["periodic_ring:128:0"]


def test_the_census_takes_the_callers_clique_and_square_limits():
    n, edges = periodic_ring(512)
    fleet_like = census(n, edges, clique_max_n=256, square_max_n=256)
    assert fleet_like["cliques"]["triangles"] is None and "above N=256" in fleet_like["cliques"]["reason"]
    assert fleet_like["squares"] is None
    whole = census(n, edges, clique_max_n=512, square_max_n=512)
    assert whole["cliques"]["triangles"] == 0 and whole["squares"] == 0
