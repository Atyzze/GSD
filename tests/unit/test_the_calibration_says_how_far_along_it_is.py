from __future__ import annotations

from graph_scale_dynamics.calibration import extension as X
from graph_scale_dynamics.calibration import suite as S
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import cell_key, suite_families


def _cell(family, parameter, seed, n):
    return {"family": family, "parameter": parameter, "seed": seed, "n": n, "status": "ok",
            "channels": {"d_s": {"valid": True, "value": 1.0}}}


def test_the_backfill_hands_the_pacing_its_count(tmp_path, monkeypatch):
    families = suite_families(["periodic_ring"])
    document = T.new_table(families, seeds=1, max_nodes=300, authoritative=False, profile="reduced")
    for size in (64, 128):
        document["cells"][cell_key("periodic_ring", size, 0)] = _cell("periodic_ring", size, 0, size)
    said = []

    def stand_in(todo, *, finish, task_args, small_target, progress, **_):
        said.append(progress())
        finish(small_target(task_args(todo[0])))
        said.append(progress())
        finish(small_target(task_args(todo[1])))
        said.append(progress())

    monkeypatch.setattr(S, "_run_in_workers", stand_in)
    X.add_structure(document, tmp_path / "table.json", families, gate_seeds=1, gate_max_nodes=300, workers=8,
                    log=lambda *_: None)
    assert said == ["structure: 0 of 2 done", "structure: 1 of 2 done", "structure: 2 of 2 done"]
