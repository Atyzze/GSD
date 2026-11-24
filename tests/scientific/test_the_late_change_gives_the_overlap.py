from __future__ import annotations

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.domain import version
from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.scaleflow import engine_door

LAW = {"dsl_version": 1, "init": "empty",
       "dynamics": {"kind": "equilibrium", "beta": 2.0, "sweeps": 20,
                    "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}},
       "terms": [{"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 1.0, "scale": "one"}}]}
LOCAL = {**LAW, "dynamics": {**LAW["dynamics"], "locality": 0.5}}
COLD = {**LAW, "dynamics": {**LAW["dynamics"], "zero_temperature": True}}
SQUARES = {**LAW, "terms": LAW["terms"] + [{"op": "square_count", "params": {}, "coeff": {"c0": -0.2, "scale": "one"}}]}
STARTS = [{"name": "cubic", "family": "periodic_cubic_quotient"}]


class _Copying(engine.GraphState):
    copies: list = []

    def __setattr__(self, name, value):
        if name == "late" and value is not None and value == (set(), set()) and hasattr(self, "edges"):
            _Copying.copies.append((self, set(self.edges)))
        super().__setattr__(name, value)


def _overlap_by_copy(copy: set, final: set) -> float:
    union = copy | final
    return len(copy & final) / len(union) if union else 1.0


def _more(n: int, seed: int):
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    edges = control_family_edges("periodic_cubic_quotient", n, seed=seed)
    return [dict(STARTS[0], edges=edges)] if edges is not None else None


@pytest.mark.parametrize("law", [LAW, LOCAL, COLD, SQUARES], ids=["global", "local", "zero_temperature", "squares"])
@pytest.mark.parametrize("n", [16, 64])
def test_the_late_change_gives_the_overlap_a_copy_gave_on_every_chain(monkeypatch, law, n):
    monkeypatch.setattr(engine, "GraphState", _Copying)
    for seed in (1, 2):
        _Copying.copies = []
        envelope = engine.run_simulation(law, n, seed, record_points=24, more_given=_more(n, seed))
        assert len(_Copying.copies) == len(CL.blocks(envelope)), "every chain arms its late change once a chunk"
        for block, (_state, copy) in zip(CL.blocks(envelope), _Copying.copies, strict=True):
            final = {tuple(edge) for edge in block["edge_list"]}
            late = block["late_change"]
            assert late["from_move"] == int(engine.LATE_FROM_FRACTION * int(envelope["moves"]))
            assert {tuple(e) for e in late["added"]} == final - copy and {tuple(e) for e in late["removed"]} == copy - final
            assert engine.late_edge_overlap(late, len(final)) == _overlap_by_copy(copy, final), "to the last bit"


@pytest.mark.parametrize("law", [LAW, LOCAL, COLD, SQUARES], ids=["global", "local", "zero_temperature", "squares"])
def test_both_engines_record_the_same_late_change(law):
    n = 64
    for seed in (1, 2):
        python = engine_door.run_simulation(law, n, seed, record_points=24, more_given=_more(n, seed))
        rust = engine_door.simulate_of("rust")(law, n, seed, record_points=24, more_given=_more(n, seed))
        for a, b in zip(CL.blocks(python), CL.blocks(rust), strict=True):
            assert a["start"] == b["start"]
            assert ({k: [tuple(e) for e in v] if isinstance(v, list) else v for k, v in a["late_change"].items()}
                    == {k: [tuple(e) for e in v] if isinstance(v, list) else v for k, v in b["late_change"].items()})


def test_no_copy_of_a_graph_is_kept_at_any_size():
    assert not hasattr(engine, "SNAPSHOT_FRACTIONS") and not hasattr(engine, "SNAPSHOT_MAX_N")
    assert "GSD_SNAPSHOT_MAX_N" not in version.READING_SETTINGS, "no size limit is left to set"
    envelope = engine_door.run_simulation(LAW, 64, 3, record_points=16)
    assert all("snapshots" not in block for block in CL.blocks(envelope))
    assert all(block["late_change"] is not None for block in CL.blocks(envelope)), "every chain, not the chain from empty alone"


def test_the_late_change_rides_a_checkpoint_into_the_next_chunk():
    n = 64
    first = engine_door.run_simulation(LAW, n, 4, record_points=16, target_sweeps=20)
    second = engine_door.run_simulation(LAW, n, 4, record_points=16, target_sweeps=23,
                                        resume_checkpoint=first["sampling_checkpoint"])
    whole = engine_door.run_simulation(LAW, n, 4, record_points=16, target_sweeps=23)
    carried = CL.block(second, CL.FROM_EMPTY)["late_change"]
    assert carried["from_move"] == CL.block(first, CL.FROM_EMPTY)["late_change"]["from_move"], (
        "85% of 23 sweeps falls before the chunk began, so the change from the last chunk's 85% runs on")
    copy = ({tuple(e) for e in CL.block(first, CL.FROM_EMPTY)["edge_list"]}
            - {tuple(e) for e in CL.block(first, CL.FROM_EMPTY)["late_change"]["added"]}
            | {tuple(e) for e in CL.block(first, CL.FROM_EMPTY)["late_change"]["removed"]})
    final = {tuple(e) for e in CL.block(second, CL.FROM_EMPTY)["edge_list"]}
    assert {tuple(e) for e in carried["added"]} == final - copy and {tuple(e) for e in carried["removed"]} == copy - final
    assert CL.block(whole, CL.FROM_EMPTY)["late_change"]["from_move"] == int(0.85 * 23 * n)
