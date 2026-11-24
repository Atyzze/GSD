from __future__ import annotations

import re
import types

import pytest

from graph_scale_dynamics.calibration import admission as A
from graph_scale_dynamics.calibration import extension as X
from graph_scale_dynamics.calibration import structure
from graph_scale_dynamics.calibration import suite as S
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import cell_key, suite_families

GIB = 1024 ** 3


class Host:
    def __init__(self, available_gib: float = 42.0, total_gib: int = 92):
        self.available, self.total = int(available_gib * GIB), total_gib * GIB

    def admission(self) -> A.Admission:
        snapshot = lambda: types.SimpleNamespace(available=self.available, total=self.total)  # noqa: E731
        guard = lambda mem: {"allowed": True, "reasons": [], "min_available_bytes": 10 * GIB}  # noqa: E731
        return A.Admission(snapshot=snapshot, guard=guard)


def _cell(family: str, parameter, seed: int, n: int, **extra) -> dict:
    return {"family": family, "parameter": parameter, "seed": seed, "n": n, "status": "ok",
            "channels": {"d_s": {"valid": True, "value": 1.0}}, **extra}


def test_two_large_censuses_start_together_and_record_what_they_held(tmp_path):
    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=1, max_nodes=300, authoritative=False, profile="reduced")
    for size in (65536, 262144):
        document["cells"][cell_key("periodic_ring", size, 0)] = _cell("periodic_ring", size, 0, size)
    log = []
    done = X.add_structure(document, tmp_path / "table.json", families, gate_seeds=1, gate_max_nodes=300,
                           workers=4, log=log.append, admission=Host().admission())
    assert done["added"] == 2 and done["failed"] == 0 and done["blocked"] == []
    starts = [i for i, line in enumerate(log) if "calibration: started" in line]
    first_end = next(i for i, line in enumerate(log) if line.startswith("structure: ["))
    assert len(starts) == 2 and max(starts) < first_end, "\n".join(log)
    assert "; 2 running" in log[starts[1]]
    for size in (65536, 262144):
        census = document["cells"][cell_key("periodic_ring", size, 0)]["structure"]
        assert census["diameter_lower"] == size // 2
        assert census["peak_rss_bytes"] > 32 * 1024 ** 2, "the census process's own peak"
    assert X.census_plan(document, families) == []


def test_a_census_is_priced_from_what_a_census_holds_not_the_probe_cell(monkeypatch):
    committed = structure.committed_census_memory()
    monkeypatch.setattr(structure, "committed_census_memory", lambda: None)
    document = {"cells": {
        "periodic_ring:4194304:0": _cell("periodic_ring", 4194304, 0, 4194304, peak_rss_bytes=int(11.5 * GIB),
                                         structure={"gap": None}),
        "random_3_regular:4194304:0": _cell("random_3_regular", 4194304, 0, 4194304,
                                            structure={"gap": 0.06, "peak_rss_bytes": 3 * GIB,
                                                       "mean_rss_bytes": 2 * GIB}),
        "random_3_regular:4194304:1": _cell("random_3_regular", 4194304, 1, 4194304,
                                            structure={"error": "boom", "peak_rss_bytes": 30 * GIB}),
    }}
    memory = X.census_memory(document)
    assert "periodic_ring:4194304:0" not in memory and "random_3_regular:4194304:1" not in memory
    price = A.cell_pricing(memory)
    assert price("random_3_regular", 4194304) == (int(1.10 * 3 * GIB), "measured at this size on this family")
    assert A.typical_shares(memory)("random_3_regular")[0] == pytest.approx(2 / 3)
    assert price("periodic_ring", 4194304) == (A.predicted_cell_bytes(4194304), "the 4 KiB per node model")
    if committed is None:
        pytest.skip("no committed census memory in this tree yet")
    monkeypatch.setattr(structure, "committed_census_memory", lambda: committed)
    ring = max((r for r in committed["rows"] if r["family"] == "periodic_ring"), key=lambda r: r["n"])
    cost, basis = A.cell_pricing(X.census_memory(document))("periodic_ring", 4194304)
    assert basis == "measured on this family"
    assert cost == int(A.MEASURED_MARGIN * ring["peak_rss_bytes"] * 4194304 / ring["n"])
    assert cost < 11.5 * GIB / 2, "a ring's census is priced at a fraction of its probe cell"


def test_the_committed_census_memory_covers_every_family_and_says_where_the_census_is_heavy():
    table = structure.committed_census_memory()
    if table is None:
        pytest.skip("no committed census memory in this tree yet")
    from tools.calibrate_census_memory import check
    assert check(table) == []
    per_node = {}
    for row in table["rows"]:
        if abs(row["n"] - 1_048_576) / 1_048_576 < 0.25:
            per_node[row["family"]] = row["peak_rss_bytes"] / row["n"]
    assert per_node["periodic_square_lattice"] > 2 * per_node["periodic_ring"]


def test_a_task_whose_process_failed_is_a_failed_census_and_the_rest_are_kept(tmp_path, monkeypatch):
    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=1, max_nodes=300, authoritative=False, profile="reduced")
    for size in (64, 128):
        document["cells"][cell_key("periodic_ring", size, 0)] = _cell("periodic_ring", size, 0, size)
    seen = {}

    def stand_in(todo, *, finish, task_args, cell_target, small_target, memory, blocked, root, **_):
        seen.update(cell_target=cell_target, small_target=small_target, memory=memory)
        first, second = todo
        finish(S._failed_cell(first, "its process ended with exit code -9 and sent no record", root, ""))
        finish(small_target(task_args(second)))

    monkeypatch.setattr(S, "_run_in_workers", stand_in)
    done = X.add_structure(document, tmp_path / "table.json", families, gate_seeds=1, gate_max_nodes=300,
                           workers=8, log=lambda *_: None)
    assert seen == {"cell_target": X._task_process_main, "small_target": X._task_in_pool,
                    "memory": X.census_memory}
    assert done["added"] == 1 and done["failed"] == 1
    failed = document["cells"][cell_key("periodic_ring", 64, 0)]["structure"]
    assert re.search(r"worker: its process ended with exit code -9", failed["error"])
    assert document["cells"][cell_key("periodic_ring", 128, 0)]["structure"]["diameter_lower"] == 64
    assert [t["key"] for t in X.census_plan(document, families)] == [cell_key("periodic_ring", 64, 0)]
