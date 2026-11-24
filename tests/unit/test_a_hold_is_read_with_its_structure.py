from __future__ import annotations

from graph_scale_dynamics.observability import starts_reading as F

CUBIC = "periodic_cubic_quotient"


def _block(mean):
    return {"mean": mean, "seeds": 3, "of": 3, "se": 0.0}


def _graph(reach, degree, squares, triangles, **more):
    return {"reach": _block(reach), "mean_degree": _block(degree), "squares_per_node": _block(squares),
            "triangles_per_node": _block(triangles), "giant_fraction": _block(1.0), "kappa": _block(0.0),
            "ended_at_cap": {"seeds": 0, "of": 3}, **more}


REFS = {CUBIC: {4096: {"start": _graph(12.0, 6.0, 3.0, 0.0), "random_reach": 4.0}}}


def test_a_lattice_kept_by_its_reach_but_rewired_holds_only_without_the_structure():
    rewired = _graph(11.8, 6.0, 0.4, 0.5)
    assert F.lattice_fate(rewired, CUBIC, 4096, REFS)["fate"] == "holds", "the reach alone, as a study that does not ask for the structure reads it"
    read = F.lattice_fate(rewired, CUBIC, 4096, REFS, structure=True)
    assert read["fate"] == "changed" and read["why"] == F.STRUCTURE_MOVED and read["structure_off"] > 0.5


def test_a_lattice_kept_with_its_structure_holds_either_way():
    near = _graph(11.8, 6.02, 3.05, 0.01)
    assert F.lattice_fate(near, CUBIC, 4096, REFS, structure=True)["fate"] == "holds"
    assert F.lattice_fate(near, CUBIC, 4096, REFS)["fate"] == "holds"


def test_the_other_fates_are_as_they_were():
    melted = _graph(5.0, 6.0, 0.1, 0.4)
    assert F.lattice_fate(melted, CUBIC, 4096, REFS, structure=True)["fate"] == "melted"
    start = REFS[CUBIC][4096]["start"]
    assert F.lattice_fate(dict(start), CUBIC, 4096, REFS, structure=True)["fate"] == "unmoved"


def test_the_structure_is_read_where_the_campaign_s_spec_asks_and_said_with_the_reading():
    assert F.hold_structure({"sampling_contract": {"hold_structure": True}})
    assert not F.hold_structure({"sampling_contract": {}}) and not F.hold_structure(None)
    rung = {"n": 4096, "empty": _graph(3.0, 2.0, 0.0, 0.0), "more_given": {}}
    reading = F.law_reading({"rungs": []}, structure=True)
    assert reading["hold_structure"] == F.STRUCTURE_WITHIN
    assert "hold_structure" not in F.law_reading({"rungs": []}), "a reading without it is the reading it was"
    assert F.compact(dict(reading, rungs=[], at_n=None))["hold_structure"] == F.STRUCTURE_WITHIN
    assert "hold_structure" not in F.compact(dict(F.law_reading({"rungs": []}), rungs=[], at_n=None))
    assert rung["n"] == 4096
