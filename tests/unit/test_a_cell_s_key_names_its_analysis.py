from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import cell_key, measure_cell, plan_cells, suite_families
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

ROOT = Path(__file__).resolve().parents[2]
RING = "periodic_ring"


def _ring_cell(seed: int = 0) -> dict:
    return measure_cell(RING, 64, seed, cell_fingerprint=FP.cell_fingerprint(RING), science_fingerprint="s")


def test_a_cell_says_which_analysis_measured_it_and_the_table_says_it_too():
    cell = _ring_cell()
    assert cell["analysis"] == ANALYSIS_VERSION == FP.analysis_version()
    assert cell["half_volume_radius"] == 16.0, "a ring of 64: half of it lies within 16 steps of any node"
    assert all("refusal" in channel for channel in cell["channels"].values())
    d_s = cell["channels"]["d_s"]
    assert d_s["valid"] and d_s["measured_se"] > 0 and d_s["se"] > 0, "d_s's honest error beside the one its fit gives"
    table = T.new_table(suite_families([RING]), seeds=1, max_nodes=64, authoritative=False, profile="reduced")
    assert table["analysis_version"] == ANALYSIS_VERSION and table["suite_version"] == C.SUITE_VERSION
    assert FP.what_a_cell_was_measured_by(RING)["cell_fingerprint"] == cell["cell_fingerprint"]


def test_another_analysis_is_another_key_so_its_cells_are_measured_again(monkeypatch):
    families = suite_families([RING])
    plan = plan_cells(families, seeds=1, max_nodes=64)
    cell = _ring_cell()
    document = {"cells": {cell_key(RING, 64, 0): cell}}
    assert T.classify_cells(document, plan)[T.CELL_CURRENT] == [plan[0]["key"]] and T.cell_is_current(cell)
    before = FP.cell_fingerprint(RING)
    monkeypatch.setattr(FP, "analysis_version", lambda root=None: "analysis-9.9.9")
    assert FP.cell_fingerprint(RING) != before, "the probes' code is the same and the name is not"
    assert T.classify_cells(document, plan)[T.CELL_STALE] == [plan[0]["key"]] and not T.cell_is_current(cell)


def test_the_analysis_is_read_from_the_tree_whose_cells_are_judged(tmp_path):
    source = tmp_path / FP.ANALYSIS_SOURCE
    source.parent.mkdir(parents=True)
    source.write_text('ANALYSIS_VERSION = "analysis-of-another-tree"\n', encoding="utf-8")
    assert FP.analysis_version(str(tmp_path)) == "analysis-of-another-tree"
    source.write_text("PROBE_STREAM = 1\n", encoding="utf-8")
    FP.analysis_version.cache_clear()
    with pytest.raises(ValueError):
        FP.analysis_version(str(tmp_path))
    FP.analysis_version.cache_clear()


@pytest.mark.parametrize("stored", [None, "", "measured-by-nobody-knows-what"])
def test_a_cell_whose_fingerprint_is_unknown_or_another_tree_s_is_not_current(stored):
    cell = dict(_ring_cell(), cell_fingerprint=stored)
    assert not T.cell_is_current(cell) and not T.its_probes_are_current(cell)
    plan = plan_cells(suite_families([RING]), seeds=1, max_nodes=64)
    assert T.classify_cells({"cells": {plan[0]["key"]: cell}}, plan)[T.CELL_STALE] == [plan[0]["key"]]


def test_a_cell_of_another_analysis_is_never_stamped_as_this_one_s():
    from graph_scale_dynamics.calibration import adopt, rekey
    ours, theirs = _ring_cell(0), dict(_ring_cell(1), analysis="analysis-5.1.0")
    for cell in (ours, theirs):
        cell["cell_fingerprint"] = "before-an-edit-that-moved-nothing"
    document = {"cells": {cell_key(RING, 64, 0): ours, cell_key(RING, 64, 1): theirs}}
    assert adopt.restamp_current(document, "s") == (1, 1)
    assert T.cell_is_current(ours) and theirs["cell_fingerprint"] == "before-an-edit-that-moved-nothing"
    ours["cell_fingerprint"] = "before-an-edit-that-moved-nothing"
    plan = plan_cells(suite_families([RING]), seeds=2, max_nodes=64)
    record = rekey.rekey_document(document, plan, verification={"checked": []}, justification="a test")
    assert record["cells_restamped"] == 1 and T.cell_is_current(ours) and not T.cell_is_current(theirs)


def test_a_rekey_compares_the_reach_and_the_start_beside_the_probes():
    from graph_scale_dynamics.calibration import rekey
    cell = _ring_cell()
    assert rekey.compare_cell(cell, dict(cell)) == []
    assert rekey.compare_cell(cell, dict(cell, half_volume_radius=17.0)) == ["half_volume_radius: 16.0 -> 17.0"]
    moved = rekey.compare_cell(dict(cell, start={"kappa": 0.0}), dict(cell, start={"kappa": 0.5}))
    assert moved == ["start.kappa: 0.0 -> 0.5"]
    assert rekey.classify_observables(["half_volume_radius"])["recorded"] == ["half_volume_radius"]


def test_a_table_of_another_suite_is_not_resumed_from():
    families = suite_families([RING])
    table = T.new_table(families, seeds=1, max_nodes=64, authoritative=False, profile="reduced")
    assert T.verify(table, families, seeds=1, max_nodes=64)["usable"]
    report = T.verify(dict(table, suite_version=C.SUITE_VERSION - 1), families, seeds=1, max_nodes=64)
    assert not report["usable"] and "is not resumed from" in report["notices"][0]


def _a_folder_with_the_seed(tmp_path, seed: dict) -> Path:
    tree = tmp_path / "study" / "main"
    (tree / C.DURABLE_DIR).mkdir(parents=True)
    (tree / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_text(json.dumps(seed), encoding="utf-8")
    return tree


def test_a_seed_of_another_suite_is_not_resumed_so_a_first_start_measures_a_new_table_whole(tmp_path, monkeypatch):
    from graph_scale_dynamics.calibration import suite

    seed = json.loads((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_text(encoding="utf-8"))
    tree = _a_folder_with_the_seed(tmp_path, dict(seed, suite_version=C.SUITE_VERSION - 1))
    started = {}

    class Measured(Exception):
        pass

    def run(document, path, families, **_):
        started.update(cells=len(document["cells"]), plan=dict(document["plan"]), path=Path(path),
                       created_under=document.get("created_under"), runs=len(document["runs"]),
                       analysis=document["analysis_version"], suite=document["suite_version"])
        raise Measured

    monkeypatch.setattr(suite, "run_suite", run)
    lines: list[str] = []
    with pytest.raises(Measured):
        suite.ensure_calibration(root=tree, var=tree / "var", log=lines.append, profile=C.PROFILE_FULL)
    assert started["cells"] == 0 and started["runs"] == 0 and started["created_under"] is None, (
        "a new table: nothing of the seed's is carried into it")
    assert started["plan"]["missing"] == started["plan"]["total_cells"] > 2000 and started["plan"]["stale"] == 0
    assert (started["analysis"], started["suite"]) == (ANALYSIS_VERSION, C.SUITE_VERSION)
    assert started["path"] == C.durable_artifact_path(tree)
    assert any("is not resumed from" in line for line in lines) and any("every cell will be measured" in line
                                                                        for line in lines), lines


def test_the_seed_is_this_suite_s_so_a_first_start_adopts_it_and_measures_one_cell_a_family(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import suite

    seed = json.loads((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_text(encoding="utf-8"))
    assert seed["suite_version"] == C.SUITE_VERSION and seed["analysis_version"] == ANALYSIS_VERSION
    tree = _a_folder_with_the_seed(tmp_path, seed)

    def run(*_, **__):
        raise AssertionError("a first start on a whole and current seed measures no ladder")

    monkeypatch.setattr(suite, "run_suite", run)
    lines: list[str] = []
    status = suite.ensure_calibration(root=tree, var=tree / "var", log=lines.append, profile=C.PROFILE_FULL)
    families = suite_families()
    whole = plan_cells(families, seeds=C.AUTHORITATIVE_SEEDS)
    assert status["table_source"] == "shipped_seed" and status["computed"] == 0
    assert status["reused"] == len(whole) == status["cells"]["current"] and status["cells"]["complete"]
    assert status["verdict"] == "PASS" and status["authoritative"] and status["adopted"]
    assert status["spot_check"]["sampled"] == len(families), "each family's cheapest cell, measured again here"
    assert status["spot_check"]["moved"] == [], "and none of them reads otherwise than the host read it"
    adopted = json.loads(C.durable_artifact_path(tree).read_text(encoding="utf-8"))
    assert set(adopted["cells"]) == set(seed["cells"]), "the cells past the ladders are carried with the rest"
    assert adopted["origin"]["adopted"] is True, "adopted here, and it says so"
    assert adopted["origin"]["computed_on"] == seed["origin"]["computed_on"], "and still says which host measured it"
    assert any("the archive's seed adopted after verification" in line for line in lines), lines


def test_the_seed_is_whole_and_current_and_nothing_is_owed():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import owed
    from graph_scale_dynamics.calibration.cells import plan_extension_cells
    seed = json.loads((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_text(encoding="utf-8"))
    assert not owed.DECLARATION.exists() and owed.recalibration_owed() is None and owed.stale_cells() == []
    assert all(T.cell_is_current(cell) and cell["status"] == "ok" for cell in seed["cells"].values())
    planned = ({task["key"] for task in plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)}
               | {task["key"] for task in plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)})
    assert set(seed["cells"]) == planned, "every cell of every ladder at ten seeds, and those past the ladders"
    assert {cell["analysis"] for cell in seed["cells"].values()} == {ANALYSIS_VERSION}
    assert seed["estimator_fingerprint"] == FP.estimator_fingerprint()
