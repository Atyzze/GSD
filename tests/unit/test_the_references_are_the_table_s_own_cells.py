from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import starts_check as C  # noqa: E402

from graph_scale_dynamics.calibration import fingerprint as FP  # noqa: E402
from graph_scale_dynamics.calibration import start_reading  # noqa: E402
from graph_scale_dynamics.calibration import table as T  # noqa: E402
from graph_scale_dynamics.calibration.cells import (  # noqa: E402
    build_graph, cell_key, family_ladder, measure_cell, measure_the_start_beside, plan_cells, suite_families,
)
from graph_scale_dynamics.measurements import known_answers as K  # noqa: E402
from graph_scale_dynamics.observability import starts_reading as F  # noqa: E402

CUBIC = K.CUBIC_QUOTIENT
LATTICE_STARTS = (K.SQUARE_TORUS, K.TRIANGULAR_TORUS, K.HONEYCOMB_TORUS, K.CUBIC_QUOTIENT, K.BODY_CENTRED_CUBIC,
                  K.FACE_CENTRED_CUBIC, K.TESSERACT_QUOTIENT)
N = 1024


def _parameter(family: str, n: int):
    return next(rung["parameter"] for rung in family_ladder(suite_families([family])[0]) if rung["n"] == n)


@pytest.fixture(scope="module")
def cubic_cells() -> dict:
    cells = {}
    for seed in range(4):
        cells[cell_key(CUBIC, N, seed)] = measure_cell(CUBIC, N, seed, cell_fingerprint=FP.cell_fingerprint(CUBIC),
                                                       science_fingerprint="s")
    return cells


def test_a_start_is_read_beside_its_cell_on_three_seeds_at_the_sizes_a_chain_is_read(cubic_cells):
    assert [("start" in cell) for cell in cubic_cells.values()] == [True, True, True, False]
    assert start_reading.SEEDS == 3 and all(start_reading.current_where_wanted(cell) for cell in cubic_cells.values())
    for family in LATTICE_STARTS:
        assert start_reading.wanted(family, 1024, 0) and start_reading.wanted(family, 1048576, 2), family
        assert not start_reading.wanted(family, 1024, 3) and not start_reading.wanted(family, 256, 0), family
    assert not start_reading.wanted(K.SQUARE_TORUS, 2304, 0), "a torus of 48 by 48 is a size no law runs"
    for family in ("periodic_cubic_lattice", "periodic_hypercubic_lattice_4d", "random_3_regular", "periodic_ring"):
        assert not start_reading.wanted(family, 4096, 0), f"{family} is no start a law is given"
    assert start_reading.READ_FROM_NODES <= F.FROM_N, "a start is read beside its cell wherever a chain is read"


def test_every_lattice_start_is_a_family_of_the_table_at_every_size_it_is_read():
    from graph_scale_dynamics.measurements.calibration import SIZES_A_LAW_RUNS, control_family_edges
    for family in LATTICE_STARTS:
        sizes = {rung["n"] for rung in family_ladder(suite_families([family])[0])}
        assert {n for n in SIZES_A_LAW_RUNS if n >= F.FROM_N} <= sizes, family
        for n in (1024, 4096):
            _n, edges = build_graph(suite_families([family])[0], _parameter(family, n), 0)
            assert [tuple(e) for e in edges] == control_family_edges(family, n), (
                f"the table's {family} at {n:,} is the graph a chain starts from")
    assert set(F.LATTICES) <= set(LATTICE_STARTS)


def test_the_start_s_quantities_are_a_chain_s_and_the_wiring_s_reach_is_the_estimator_s():
    import numpy as np

    from graph_scale_dynamics.measurements.curvature_probe import read as curvature
    from graph_scale_dynamics.measurements.estimators import _measure_graph
    from graph_scale_dynamics.measurements.structure_census import census
    from graph_scale_dynamics.observability import two_chains
    from graph_scale_dynamics.measurements.random_starts import _random_wiring
    for family in (K.FACE_CENTRED_CUBIC, K.HONEYCOMB_TORUS):
        edges = K.edges(family, N)
        beside = start_reading.read(N, edges, 1)
        as_a_chain = two_chains.seed_values({"census": {"empty": census(N, edges)},
                                             "curvature": {"empty": curvature(N, edges)}}, N, "empty")
        assert {key: beside[key] for key in start_reading.COUNTED} == {key: as_a_chain[key]
                                                                       for key in start_reading.COUNTED}, family
        wiring = _random_wiring(N, edges, seed=1)
        measured, _curves = _measure_graph(N, wiring, np.random.default_rng(1))
        assert beside["random_wiring"]["reach"] == measured["half_volume_radius"], family
        assert beside["random_wiring"]["mean_degree"] == 2.0 * len(wiring) / N


def test_the_references_are_made_from_the_cells_and_read_a_chain_as_they_did(cubic_cells):
    refs = F.references_from({"cells": cubic_cells})
    assert list(refs) == [CUBIC] and list(refs[CUBIC]) == [N]
    ref = refs[CUBIC][N]
    start = ref["start"]
    assert ref["seeds"] == {"probes": 4, "start": 3}
    assert (start["mean_degree"]["mean"], start["squares_per_node"]["mean"], start["triangles_per_node"]["mean"],
            start["giant_fraction"]["mean"], start["kappa"]["mean"]) == (6.0, 3.0, 0.0, 1.0, 0.0)
    assert start["reach"] == {"mean": 7.0, "se": 0.0, "seed_sd": 0.0, "seeds": 4, "of": 4, "values": [7.0] * 4}
    assert 4.0 <= ref["random_reach"] < 4.1 and 5.9 < ref["random_degree"] < 6.0
    assert start["d_s"]["seeds"] == 4 and abs(start["d_s"]["mean"] - 3.0) < 0.3
    assert start["d_w"]["refused"] == {"WALK_SATURATED": 4}, "a refusal keeps its code, as a chain's does"
    untouched = C.summary([C.read_graph(N, C.lattice_edges(CUBIC, N), seed=seed, name="cubic") for seed in range(3)])
    assert F.lattice_fate(untouched, CUBIC, N, refs)["fate"] == "unmoved"
    from graph_scale_dynamics.measurements.random_starts import _random_wiring
    wired = C.summary([C.read_graph(N, _random_wiring(N, C.lattice_edges(CUBIC, N), seed=50 + seed), seed=seed,
                                    name="cubic") for seed in range(3)])
    assert F.lattice_fate(wired, CUBIC, N, refs)["fate"] == "melted"
    assert F.lattice_fate(untouched, CUBIC, 4096, refs) == {"fate": None, "why": F.NO_REFERENCE}


def test_cells_read_by_other_probes_or_too_few_starts_make_no_reference(cubic_cells):
    stale = {key: dict(cell, cell_fingerprint="another-analysis") for key, cell in cubic_cells.items()}
    assert F.references_from({"cells": stale}) == {}
    one = {key: (cell if cell["seed"] == 0 else {k: v for k, v in cell.items() if k != "start"})
           for key, cell in cubic_cells.items()}
    assert F.references_from({"cells": one}) == {}, "one start read is no reference: two seeds at least"
    failed = {key: dict(cell, start={"contract": start_reading.CONTRACT, "fingerprint": start_reading.fingerprint(),
                                     "error": "MemoryError: "}) for key, cell in cubic_cells.items()}
    assert F.references_from({"cells": failed}) == {}
    assert F.references_from(None) == {} and F.references_from({}) == {}


def test_a_start_read_by_other_sources_is_measured_again_and_its_probes_are_not(cubic_cells, monkeypatch, tmp_path):
    from graph_scale_dynamics.calibration import suite
    families = suite_families([CUBIC])
    plan = [task for task in plan_cells(families, seeds=4) if task["n"] == N]
    document = T.new_table(families, seeds=4, max_nodes=None, authoritative=False, profile="reduced")
    document["cells"] = json.loads(json.dumps(cubic_cells))
    assert len(T.classify_cells(document, plan)[T.CELL_CURRENT]) == 4
    as_first_read = F.references_from(document)[CUBIC][N]
    before = start_reading.fingerprint()
    monkeypatch.setattr(start_reading, "sources", lambda: {"the census": "edited"})
    assert start_reading.fingerprint() != before
    classes = T.classify_cells(document, plan)
    assert len(classes[T.CELL_STALE]) == 3 and classes[T.CELL_CURRENT] == [cell_key(CUBIC, N, 3)], (
        "the three cells that carry a start are owed its reading; the fourth carries none")
    assert all(T.its_probes_are_current(cell) for cell in document["cells"].values())
    assert F.references_from(document) == {}

    def no_probe_runs(*_, **__):
        raise AssertionError("the probes of a current cell are not measured again for its start")

    monkeypatch.setattr("graph_scale_dynamics.calibration.cells.measure_cell", no_probe_runs)
    run = suite.run_suite(document, tmp_path / "table.json", families, seeds=4, max_nodes=None, workers=0,
                          log=lambda line: None, plan=plan)
    assert run["cells_computed"] == 3 and len(T.classify_cells(document, plan)[T.CELL_CURRENT]) == 4
    for key, cell in document["cells"].items():
        was = cubic_cells[key]
        assert (cell["channels"], cell["computed_utc"], cell["half_volume_radius"]) == (
            was["channels"], was["computed_utc"], was["half_volume_radius"])
        if cell["seed"] < 3:
            assert cell["start"]["fingerprint"] == start_reading.fingerprint() and cell["start"]["measured_beside_utc"]
            assert {k: cell["start"][k] for k in start_reading.COUNTED} == {k: was["start"][k]
                                                                            for k in start_reading.COUNTED}
    assert F.references_from(document)[CUBIC][N] == as_first_read, "read again by the same code, the same reference"


def test_a_large_cell_whose_start_alone_was_read_keeps_its_own_time_and_memory():
    from graph_scale_dynamics.calibration import suite

    class Process:
        pid = 4321

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return False

    class Pipe:
        def close(self):
            pass

    measured = {"elapsed_seconds": 900.0, "paused_seconds": 12.0, "mean_rss_bytes": 2 * 1024 ** 3,
                "memory_timeline": [[0.0, 1], [900.0, 3 * 1024 ** 3]], "start": {"kappa": 0.0}}
    for only_its_start, kept in ((True, True), (False, False)):
        cell = suite._LargeCell.__new__(suite._LargeCell)
        cell.process, cell.receive, cell.result = Process(), Pipe(), dict(measured)
        cell.paused_at, cell.paused_seconds, cell.trace = None, 5.0, [(0.0, 1024 ** 2), (40.0, 300 * 1024 ** 2)]
        cell.only_its_start = only_its_start
        record = cell.collect()
        assert (record == measured) is kept, (
            "the time and the memory a cell records are its probes', which price its family's next cells")


def test_a_start_that_could_not_be_read_says_so_and_stays_owed(cubic_cells, monkeypatch):
    def fails(n, edges, seed):
        raise MemoryError("no room")

    monkeypatch.setattr(start_reading, "read", fails)
    cell = measure_the_start_beside(cubic_cells[cell_key(CUBIC, N, 0)])
    assert cell["start"]["error"] == "MemoryError: no room" and cell["channels"] == cubic_cells[cell_key(CUBIC, N, 0)][
        "channels"]
    assert not start_reading.current(cell) and not start_reading.current_where_wanted(cell)


def test_a_folder_reads_its_references_from_its_own_table(cubic_cells, tmp_path, monkeypatch):
    from graph_scale_dynamics import calibration
    from graph_scale_dynamics.calibration import contract
    table = T.new_table(suite_families([CUBIC]), seeds=4, max_nodes=None, authoritative=True, profile="full")
    table["cells"] = cubic_cells
    path = tmp_path / contract.DURABLE_DIR / contract.DURABLE_NAME
    T.write(table, path)
    monkeypatch.setattr(calibration, "durable_artifact_path", lambda root=None: path)
    F.table_references.cache_clear()
    try:
        assert list(F.table_references()[CUBIC]) == [N]
        reading = F.law_reading({"rungs": []})
        assert reading["references"] is True
        path.write_text(json.dumps(dict(table, suite_version=contract.SUITE_VERSION - 1)), encoding="utf-8")
        F.table_references.cache_clear()
        assert F.table_references() == {}, "a table of another suite is no table of this tree's"
        path.unlink()
        F.table_references.cache_clear()
        assert F.table_references() == {}
    finally:
        F.table_references.cache_clear()


def test_the_torus_by_its_sides_and_the_start_are_one_graph_where_their_sizes_meet():
    from graph_scale_dynamics.measurements import calibration
    shared = {("periodic_cubic_lattice", CUBIC): [(4, 64), (16, 4096)],
              ("periodic_hypercubic_lattice_4d", K.TESSERACT_QUOTIENT): [(4, 256), (8, 4096), (16, 65536)]}
    for (torus, start), sizes in shared.items():
        by_side = suite_families([torus])[0]
        for side, n in sizes:
            assert side in by_side["ladder"] and n in calibration.SIZES_A_LAW_RUNS
            assert by_side["build"](side) == (n, K.edges(start, n)), (
                f"{torus} of side {side} and {start} at {n:,} are measured as two families and are one graph")
