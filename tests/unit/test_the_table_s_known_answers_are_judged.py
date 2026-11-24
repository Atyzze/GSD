from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import fingerprint as F
from graph_scale_dynamics.calibration import start_reading as S
from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES
from graph_scale_dynamics.research import table_known_answers as K

ROOT = Path(__file__).resolve().parents[2]
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "table_known_answers_criterion.json"
SEED = ROOT / "calibration" / "seed_table.json"
JUDGED = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "table_known_answers_judged.json"


@pytest.fixture(scope="module")
def criterion() -> dict:
    return json.loads(CRITERION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _stamped(table: dict, criterion: dict) -> dict:
    table = copy.deepcopy(table)
    for cell in table["cells"].values():
        cell["cell_fingerprint"] = criterion["measured_by"]["cell_fingerprints"][cell["family"]]
    return table


def _cell(family: str, parameter, n: int, seed: int, readings: dict, fingerprint: str) -> dict:
    return {"family": family, "parameter": parameter, "n": n, "seed": seed, "status": "ok",
            "cell_fingerprint": fingerprint,
            "channels": {probe: ({"valid": True, "value": value, "se": 0.05, "refusal": None}
                                 if value is not None else
                                 {"valid": False, "value": None, "se": None, "refusal": "WINDOW_TOO_SHORT"})
                         for probe, value in readings.items()}}


def test_the_criterion_names_every_family_of_the_table_once(criterion):
    held = set(criterion["with_a_dimension"]) | set(criterion["without_a_dimension"])
    assert held == set(SUITE_FAMILIES)
    assert not set(criterion["with_a_dimension"]) & set(criterion["without_a_dimension"])
    assert {"erdos_renyi_degree_16", "erdos_renyi_degree_32"} <= set(criterion["without_a_dimension"])
    for family in ("periodic_a4_lattice", "periodic_d4_lattice"):
        assert criterion["with_a_dimension"][family]["held_from"] == K.BY_THE_TABLE
        assert criterion["with_a_dimension"][family]["probes"]["d_w"]["theory"] == 2.0
        assert all(criterion["with_a_dimension"][family]["probes"][probe]["theory"] == 4.0
                   for probe in ("d_s", "d_V", "d_B"))


def test_the_criterion_names_the_probes_of_this_tree(criterion):
    measured_by = criterion["measured_by"]
    assert measured_by["analysis"] == F.analysis_version()
    assert measured_by["estimator_fingerprint"] == F.estimator_fingerprint()
    assert measured_by["start_reading_fingerprint"] == S.fingerprint()
    assert measured_by["cell_fingerprints"] == {name: F.cell_fingerprint(name) for name in SUITE_FAMILIES}


def test_the_criterion_came_before_the_table(criterion):
    assert criterion["committed_utc"] == "2026-11-19T00:02:01Z"
    assert criterion["plan"] == {"seeds": 10, "extension_seeds": 3, "gate_cells": 2560, "extension_cells": 24}


def test_the_installed_seed_is_the_table_the_committed_reading_passed(criterion, seed):
    judged = K.judge(criterion, seed, seed)
    assert judged["misses"] == [] and judged["not_counted"] == []
    assert judged["whole"] and judged["passes"], "every cell of the plan, measured by 801's probes"
    assert judged["predictions"]["the_same_readings"]["true"]
    assert judged["predictions"]["the_same_readings"]["compared"] == 2584
    committed = json.loads(JUDGED.read_text(encoding="utf-8"))
    assert committed["passes"] and committed["holds"] == judged["holds"]
    assert committed["predictions"]["the_same_readings"]["compared"] == 2194, "judged against the seed it replaced"
    cubic = judged["families"]["periodic_cubic_lattice"]
    assert cubic["held"]["d_B"]["from_nodes"] == 4096
    assert min(row["n"] for row in cubic["rows"] if row["probes"]["d_V"]["status"] == "inside") == 1728


def test_a_cell_outside_its_band_and_a_random_graph_read_are_misses(criterion, seed):
    table = _stamped(seed, criterion)
    for key, cell in table["cells"].items():
        if key.startswith("periodic_cubic_lattice:16:"):
            cell["channels"]["d_V"]["value"] = 2.5
        if key == "erdos_renyi_mid:4096:3":
            cell["channels"]["d_s"].update({"valid": True, "value": 2.9, "refusal": None})
        if key == "erdos_renyi_mid:2048:3":
            cell["channels"]["d_s"].update({"valid": True, "value": 2.9, "refusal": None})
    misses = {(miss["family"], miss["n"], miss["probe"], miss["miss"]) for miss in K.judge(criterion, table)["misses"]}
    assert misses == {("periodic_cubic_lattice", 4096, "d_V", "outside its band"),
                      ("erdos_renyi_mid", 4096, "d_s", "read where no dimension exists")}


def test_a_family_held_by_its_own_cells_is_held_from_where_every_seed_reads(criterion):
    stamp = criterion["measured_by"]["cell_fingerprints"]["periodic_a4_lattice"]
    sizes = {1296: [None, 3.4, 3.5], 4096: [3.6, 3.7, 3.65], 65536: [3.9, 3.95, 4.0], 331776: [4.0, 4.01, 3.99]}
    bands = criterion["with_a_dimension"]["periodic_a4_lattice"]["probes"]["d_V"]["bands"]
    by_n = {n: {"seeds": [{"probes": {"d_V": {"value": value}}} for value in values]} for n, values in sizes.items()}
    assert K.held_from_the_table(bands, by_n, "d_V") == 4096
    by_n[331776]["seeds"][0]["probes"]["d_V"]["value"] = None
    assert K.held_from_the_table(bands, by_n, "d_V") is None
    cells = {f"periodic_a4_lattice:{side}:{seed}": _cell("periodic_a4_lattice", side, n, seed,
                                                          {"d_s": 4.0, "d_V": v, "d_B": None, "d_w": None}, stamp)
             for side, n in ((6, 1296), (8, 4096)) for seed, v in enumerate(sizes[n] + [3.6] * 7)}
    found, _absent = K.rungs(criterion, {"cells": cells})
    assert sorted(found["periodic_a4_lattice"]) == [1296, 4096]
    assert [len(rung["seeds"]) for rung in found["periodic_a4_lattice"].values()] == [10, 10]


def test_the_tool_reads_a_zip_and_writes_its_page(tmp_path, criterion, seed):
    import zipfile

    from tools import table_known_answers as tool
    archive = tmp_path / "calibration_box.zip"
    with zipfile.ZipFile(archive, "w") as written:
        written.writestr(tool.TABLE_MEMBER, json.dumps(_stamped(seed, criterion)))
    assert tool.load_table(archive)["cells"].keys() == seed["cells"].keys()
    page, out = tmp_path / "page.md", tmp_path / "judged.json"
    assert tool.main([str(archive), "--against", str(SEED), "--md", str(page), "--json", str(out)]) == 0
    judged = json.loads(out.read_text(encoding="utf-8"))
    assert judged["contract"] == K.CONTRACT and judged["misses"] == [] and judged["passes"]
    assert "It passes" in page.read_text(encoding="utf-8")
    short = {**seed, "cells": {key: cell for key, cell in seed["cells"].items() if cell["family"] != "erdos_renyi_degree_32"}}
    with zipfile.ZipFile(archive, "w") as written:
        written.writestr(tool.TABLE_MEMBER, json.dumps(short))
    assert tool.main([str(archive), "--against", str(SEED), "--md", str(page), "--json", str(out)]) == 1
    assert "It does not pass" in page.read_text(encoding="utf-8"), "a table without a family of the plan is not whole"
