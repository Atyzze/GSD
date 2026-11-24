from __future__ import annotations

from graph_scale_dynamics.observability import law_score as L

SIZES = (4096, 16384, 65536)


def _side(**values) -> dict:
    return {key: {"mean": value, "se": 0.0, "seeds": 3, "of": 3} for key, value in values.items()}


def _cubic(n: int) -> dict:
    return _side(d_s=3.0, d_V=3.0, d_B=3.0, d_w=2.0, giant_fraction=1.0, reach=0.8 * n ** (1 / 3))


def _chains() -> dict:
    return {"rungs": [{"n": n, "seeds": 3, "empty": _side(d_s=None), "given": _side(d_s=None),
                       "more_given": {"cubic": _cubic(n)}} for n in SIZES],
            "every_chain": [{"name": "empty", "key": "empty", "start": "the empty graph"},
                            {"name": "random", "key": "given", "start": "random_at_drawn_degree"},
                            {"name": "cubic", "key": "cubic", "start": "periodic_cubic_quotient"}]}


def test_a_lattice_chain_whose_fate_was_not_read_counts_as_kept_not_as_changed():
    unread = {"rungs": [{"n": n, "fates": {}} for n in SIZES]}
    found = L.score(_chains(), unread, references={})
    assert found["by"] == "kept" and found["score"] == round(100 * L.KEPT * L.depth(65536))
    assert found["sizes"][-1]["chains"]["cubic"]["kind"] == "kept" and "fate" not in found["sizes"][-1]["chains"]["cubic"]


def test_a_lattice_chain_that_holds_is_kept_one_unmoved_is_frozen_and_any_other_fate_changed_it():
    for fate, kind in (("holds", "kept"), ("unmoved", "frozen"), ("loses", "lattice"), ("converts", "lattice")):
        five = {"rungs": [{"n": n, "fates": {"cubic": {"fate": fate}}} for n in SIZES]}
        found = L.score(_chains(), five, references={})
        assert found["by"] == kind, fate


def test_a_frozen_lattice_scores_1_the_lowest_score_there_is_and_says_so():
    def scored(fate):
        five = {"rungs": [{"n": n, "fates": {"cubic": {"fate": fate}}} for n in SIZES]}
        return L.score(_chains(), five, references={})
    frozen, held = scored("unmoved"), scored("holds")
    assert (frozen["score"], frozen["by"], frozen["chain"]) == (L.FROZEN_SCORE, "frozen", "cubic") and L.FROZEN_SCORE == 1
    assert held["score"] == round(100 * L.KEPT * L.depth(65536)) > frozen["score"], (
        "a law that changes no edge only lets its start go on existing")
    said = frozen["sizes"][-1]["chains"]["cubic"]["how"]
    assert "frozen: no edge changed" in said and "the lowest score" in said
    assert frozen["points"] == held["points"], "the probes settle alike; what differs is whether the law did anything"
    mixed = {"rungs": [{"n": n, "fates": {"cubic": {"fate": "unmoved" if n < SIZES[-1] else "holds"}}} for n in SIZES]}
    assert L.score(_chains(), mixed, references={})["by"] == "kept", "a chain that moves at the size it scores is kept"
