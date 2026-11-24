from __future__ import annotations

import json
from pathlib import Path


from graph_scale_dynamics.calibration import margins as M

ROOT = Path(__file__).resolve().parents[2]


def _the_seed_s(key: str) -> dict:
    return json.loads((ROOT / "calibration" / "seed_table.json").read_text())["cells"][key]


def _task(key: str, cell: dict) -> dict:
    family, parameter, seed = key.split(":")
    d_s = cell["channels"]["d_s"]
    return {"key": key, "family": family, "parameter": int(parameter), "seed": int(seed), "n": cell["n"],
            "stored_d_s": d_s["value"] if d_s["valid"] else None}


def test_a_cell_records_both_margins_and_the_backfill_checks_the_value_it_holds():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration.cells import measure_cell

    key = "periodic_square_lattice:64:1"
    record = measure_cell("periodic_square_lattice", 64, 1, cell_fingerprint="x", science_fingerprint="y")
    found = record["d_s_margins"]
    assert found["contract"] == M.MARGINS_CONTRACT
    assert found["plateau"]["comparable"] and found["plateau"]["delta_aicc"] > 27.0, (
        "a square lattice of 4,096 nodes: a plateau, by a margin inside the band its rung's geometries hold")
    assert found["whole_range"]["delta_aicc"] > 0 and found["whole_range"]["is_power_law"] is True
    held = _the_seed_s(key)
    assert record["channels"] == held["channels"] and found == held["d_s_margins"], (
        "measured here, the cell is the one the host measured, to the last digit")
    again = M.margin_task(_task(key, held))["margins"]
    assert again["matches_the_cell"] is True, "d_s alone, rebuilt from the seed, is the value the cell holds"
    assert again["plateau"] == found["plateau"] and again["whole_range"] == found["whole_range"]
    assert M.margin_task(dict(_task(key, held), stored_d_s=1.0))["margins"]["matches_the_cell"] is False


def test_where_the_balls_are_not_a_power_d_s_is_refused_before_any_plateau_is_compared():
    from graph_scale_dynamics.calibration.cells import measure_cell

    key = "random_3_regular:4096:1"
    record = measure_cell("random_3_regular", 4096, 1, cell_fingerprint="x", science_fingerprint="y")
    found = record["d_s_margins"]
    assert record["channels"]["d_s"]["refusal"] == "EXPONENTIAL_GROWTH" and not record["channels"]["d_s"]["valid"]
    assert found["plateau"] == {"comparable": False, "delta_aicc": None, "is_power_law": None}, (
        "no plateau margin: the verdict on the balls refused the graph first")
    assert found["whole_range"]["delta_aicc"] < 0 and found["whole_range"]["is_power_law"] is False
    held = _the_seed_s(key)
    assert record["channels"] == held["channels"] and found == held["d_s_margins"]
    again = M.margin_task(_task(key, held))["margins"]
    assert again["d_s"] is None and again["matches_the_cell"] is True, "refused here as the cell holds it refused"
    assert M.margin_task(dict(_task(key, held), stored_d_s=1.0))["margins"]["matches_the_cell"] is False


def test_the_backfill_plan_is_every_ok_cell_without_margins_smallest_first():
    from graph_scale_dynamics.calibration.cells import suite_families
    document = {"cells": {
        "periodic_ring:1024:0": {"family": "periodic_ring", "parameter": 1024, "seed": 0, "n": 1024, "status": "ok",
                                 "channels": {"d_s": {"valid": True, "value": 1.0}}},
        "periodic_ring:256:0": {"family": "periodic_ring", "parameter": 256, "seed": 0, "n": 256, "status": "ok",
                                "channels": {"d_s": {"valid": False, "value": None}}},
        "periodic_ring:64:0": {"family": "periodic_ring", "parameter": 64, "seed": 0, "n": 64, "status": "ok",
                               "d_s_margins": {"plateau": {}}},
        "periodic_ring:4096:0": {"family": "periodic_ring", "parameter": 4096, "seed": 0, "n": 4096, "status": "failed"},
    }}
    todo = M.margins_plan(document, suite_families(["periodic_ring"]))
    assert [(t["n"], t["stored_d_s"]) for t in todo] == [(256, None), (1024, 1.0)]
    assert M.margins_plan(document, suite_families(["periodic_ring"]), max_n=512) == todo[:1]


def test_the_bands_say_where_each_kind_sits_and_a_margin_is_placed_against_them():
    rows = [{"family": "periodic_square_lattice", "expectation": "MEASURE", "n": 4096, "valid": True,
             "plateau": 93.0, "whole_range": 208.0},
            {"family": "periodic_hypercubic_lattice_4d", "expectation": "MEASURE", "n": 4096, "valid": True,
             "plateau": 56.6, "whole_range": 70.5},
            {"family": "random_3_regular", "expectation": "REFUSE", "n": 4096, "valid": True,
             "plateau": 9.7, "whole_range": -8.2},
            {"family": "balanced_binary_tree", "expectation": "REFUSE", "n": 4095, "valid": True,
             "plateau": 40.4, "whole_range": 76.1},
            {"family": "random_4_regular", "expectation": "REFUSE", "n": 4096, "valid": False,
             "plateau": 0.2, "whole_range": -19.4}]
    band = M.bands(rows)["4096"]
    assert band["plateau"]["geometry"] == [56.6, 93.0] and band["plateau"]["no_finite_dimension"] == [0.2, 40.4]
    assert band["plateau"]["separated"] is True, "on the plateau margin every geometry cell scored above every null"
    assert band["whole_range"]["separated"] is False, "the whole range does not: the tree passes it at +76"
    assert band["null_families_reported"] == {"balanced_binary_tree": [40.4, 40.4], "random_3_regular": [9.7, 9.7]}
    table = {"bands": M.bands(rows)}
    assert M.place(9.0, 4096, table) == "reported, where only families with no finite dimension sit"
    assert M.place(48.0, 4096, table) == "reported, between the two kinds"
    assert M.place(80.0, 4096, table) == "reported, where only geometry families sit"
    assert M.place(1.5, 4096, table) == "not reported (2 or less)" and M.place(None, 4096, table) == "no comparison"
    assert M.place(30.0, 1048576, table) == "reported, no band at this rung"
    assert M.survey_rung(4095) == M.survey_rung(3282) == 4096 and M.survey_rung(15625) == 16384


def test_the_committed_bands_are_the_seed_s_and_carry_the_finding():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import owed
    from graph_scale_dynamics.scaleflow.probes import A_VERDICT_IS_RELIED_ON_FROM_NODES
    table = M.committed_bands()
    assert table is not None and table["contract"] == M.BANDS_CONTRACT
    assert table == M.seed_bands(ROOT), "the seed moved: python3 tools/calibrate_margins.py --write"
    seed = json.loads((ROOT / "calibration" / "seed_table.json").read_text())
    assert table["source"]["estimator_fingerprint"] == seed["estimator_fingerprint"]
    assert owed.recalibration_owed() is None and table["cells_with_margins"] == len(seed["cells"])
    assert set(table["bands"]) == {str(rung) for rung in M.SURVEY_RUNGS}, "a band at every size a law runs"
    for rung, entry in table["bands"].items():
        plateau = entry["plateau"]
        assert plateau["geometry"] and plateau["geometry"][0] > 2.0, "every geometry cell is a plateau, and reported"
        if int(rung) >= A_VERDICT_IS_RELIED_ON_FROM_NODES:
            assert plateau["cells"]["no_finite_dimension"] == 0 and plateau["no_finite_dimension"] is None, (
                rung, "from the size a verdict is relied on, no family without a dimension reaches the comparison")
            assert plateau["separated"] is None and entry["null_families_reported"] == {}
            assert M.place(plateau["geometry"][0], int(rung), table) == "reported, no band at this rung"
    small = table["bands"]["1024"]
    assert sorted(small["null_families_reported"]) == ["hyperbolic_geometric_graph", "hyperbolic_triangle_tiling"], (
        "under that size the two hyperbolic families are read on some seeds, kept and not relied on")
    low, high = small["plateau"]["no_finite_dimension"]
    assert small["plateau"]["geometry"][0] < low and high < small["plateau"]["geometry"][1], (
        "and their plateaus lie inside the geometries' band: the margin does not part them")
    assert small["plateau"]["separated"] is False
    assert all(entry["whole_range"]["cells"]["no_finite_dimension"] > 0 for entry in table["bands"].values()), (
        "the whole-range margin is compared on every graph, refused or not")


def test_the_backfill_gives_old_cells_their_margins_without_touching_a_probe(tmp_path):
    from graph_scale_dynamics.calibration import table as T
    from graph_scale_dynamics.calibration.cells import cell_key, measure_cell, suite_families
    from graph_scale_dynamics.calibration.extension import add_margins

    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=1, max_nodes=300, authoritative=False, profile="reduced")
    for size in (64, 128, 256):
        cell = measure_cell("periodic_ring", size, 0, cell_fingerprint="x", science_fingerprint="y")
        cell.pop("d_s_margins")
        document["cells"][cell_key("periodic_ring", size, 0)] = cell
    document["cells"][cell_key("periodic_ring", 256, 0)]["channels"]["d_s"]["value"] = 9.0
    before = {k: json.dumps(v["channels"], sort_keys=True) for k, v in document["cells"].items()}
    done = add_margins(document, tmp_path / "table.json", families, gate_seeds=1, gate_max_nodes=300,
                       workers=0, log=lambda *_: None)
    assert done["added"] == 3 and done["failed"] == 0 and done["mismatched"] == [cell_key("periodic_ring", 256, 0)]
    assert {k: json.dumps(v["channels"], sort_keys=True) for k, v in document["cells"].items()} == before
    ring = document["cells"][cell_key("periodic_ring", 128, 0)]["d_s_margins"]
    assert ring["plateau"]["delta_aicc"] > 38 and ring["whole_range"]["is_power_law"] is True
    moved = document["cells"][cell_key("periodic_ring", 256, 0)]["d_s_margins"]
    assert moved["mismatch"]["cell_d_s"] == 9.0
    assert M.margins_plan(document, families) == []
