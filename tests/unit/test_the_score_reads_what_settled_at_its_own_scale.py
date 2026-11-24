from __future__ import annotations

import math

import pytest

from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.observability import two_chains as T
from graph_scale_dynamics.scaleflow import equilibration as EQ

SIZES = (4096, 16384, 65536)


def _seed(n: int, seed: int, *, classification: str = EQ.EQUILIBRATED_ACTIVE, frozen: bool = False, d: float = 2.0,
          reach: float | None = None, giant: float = 1.0) -> dict:
    return {"n": n, "seed": seed, "metrics": {
        "health": {"equilibration": {"sweeps_multiplier": 1, "chains": {"empty": {"activity": {"frozen": frozen}}}},
                   "rung_terminal": {"reason": "completed", "classification": classification}},
        "census": {"empty": {"edges": 2 * n, "largest_component": {"size": int(giant * n)}}},
        "half_volume_radius": 0.5 * n ** (1.0 / d) if reach is None else reach,
        "d_s": {"valid": True, "d_s": d}, "d_V": {"valid": True, "d_V_window": d},
        "d_B": {"valid": True, "d_B": d}, "d_w": {"valid": True, "d_w": 2.0}}}


def _score(rows) -> dict:
    return L.score(T.chains_per_rung(rows), references={})


def _law(**at_every_seed) -> list[dict]:
    return [_seed(n, s, **at_every_seed) for n in SIZES for s in (1, 2, 3)]


def test_a_plane_whose_seeds_certified_scores_what_it_scored_before():
    found = _score(_law())
    assert (found["score"], found["by"], found["points"]) == (57, "empty", L.POINTS)
    assert L.CONTRACT == "gsd-law-score-8"


@pytest.mark.parametrize("classification", [EQ.RELAXING_AT_CEILING, EQ.METASTABLE_OR_NONMIXING,
                                            EQ.INSUFFICIENT_EFFECTIVE_SAMPLES, EQ.OPERATIONAL_UNRESOLVED])
def test_a_seed_whose_chain_never_stopped_changing_is_not_read(classification):
    assert _score(_law(classification=classification))["score"] == 0


@pytest.mark.parametrize("classification", [EQ.EQUILIBRATED_LOW_ACTIVITY, EQ.AT_REST, EQ.FROZEN_OR_ABSORBING])
def test_a_seed_that_settled_or_rests_is_read(classification):
    assert _score(_law(classification=classification))["score"] == 57


def test_a_chain_frozen_by_its_own_last_chunk_is_read_though_its_rung_did_not_certify():
    assert _score(_law(classification=EQ.RELAXING_AT_CEILING, frozen=True))["score"] == 57


def test_more_than_half_the_seeds_must_read_and_have_settled():
    one_of_three = [_seed(n, s, classification=EQ.AT_REST if s == 1 else EQ.RELAXING_AT_CEILING)
                    for n in SIZES for s in (1, 2, 3)]
    two_of_three = [_seed(n, s, classification=EQ.AT_REST if s < 3 else EQ.RELAXING_AT_CEILING)
                    for n in SIZES for s in (1, 2, 3)]
    assert _score(one_of_three)["score"] == 0 and _score(two_of_three)["score"] == 57
    rung = T.chains_per_rung(one_of_three)["rungs"][0]
    assert rung["empty"]["counted"]["seeds"] == 1 and rung["empty"]["counted"]["of"] == 3
    assert rung["empty"]["d_V"]["seeds"] == 3, "the readings every other reader uses are left as they were"


def test_a_largest_piece_under_half_the_graph_is_not_read_even_when_it_holds_4096_nodes():
    assert _score(_law(giant=0.4))["score"] == 0
    half = _score(_law(giant=0.5))
    assert half["score"] > 0 and [size["n"] for size in half["sizes"] if "empty" in size["chains"]] == [65536], "half of 4,096 is under 4,096 nodes"


def test_a_strip_that_reads_two_dimensions_but_grows_as_a_line_does_not_settle():
    def strip(n: int) -> float:
        return 1.3 * n / 64 / 4
    found = _score([_seed(n, s, reach=strip(n)) for n in SIZES for s in (1, 2, 3)])
    assert found["score"] == round(100 * L.depth(16384) * 5 / L.POINTS), "each probe and the relation read, none settles"
    top = found["sizes"][-1]["chains"]["empty"]
    assert top["settled"] == [] and top["scale"]["holds"] is False and top["scale"]["growth_d"] == pytest.approx(1.0)
    assert "its reach grows as d 1" in top["how"]


def test_a_ring_whose_reach_grows_with_n_settles_and_a_ring_that_stopped_growing_does_not():
    grows = _score([_seed(n, s, d=1.0, reach=n / 4) for n in SIZES for s in (1, 2, 3)])
    stopped = _score([_seed(n, s, d=1.0, reach=min(n, 9000) / 4) for n in SIZES for s in (1, 2, 3)])
    assert grows["score"] == 57 and grows["d"] == 1.0
    assert stopped["score"] < grows["score"] and stopped["sizes"][-1]["chains"]["empty"]["scale"]["holds"] is False


def test_the_scale_allows_half_a_step_of_the_reach_and_two_errors_of_its_seeds():
    rule = L.reach_rule()
    assert rule["z"] == 2.0 and rule["half_step"] == 0.5 and rule["q"] == 0.2
    lattice = {"reach": {"mean": 8.0, "se": 0.0, "seeds": 3, "of": 3},
               **{p: {"mean": 4.0, "se": 0.0, "seeds": 3, "of": 3} for p in L.PROBES}}
    bigger = dict(lattice, reach={"mean": 10.0, "se": 0.0, "seeds": 3, "of": 3})
    found = L.scale_at(lattice, bigger, 20736, 65536)
    expected = math.log(65536 / 20736) / 4.0
    assert found["holds"] and found["allowed"] == pytest.approx(0.2 * expected + 0.5 / 8 + 0.5 / 10, abs=1e-4)
    assert L.scale_at(lattice, {p: v for p, v in bigger.items() if p != "reach"}, 20736, 65536)["holds"] is False


def test_a_step_whose_next_step_breaks_its_scale_settled_nothing():
    def tree(n: int) -> float:
        return {4096: 200.0, 16384: 480.0, 65536: 760.0}[n]
    rows = [_seed(n, s, d=1.33, reach=tree(n)) for n in SIZES for s in (1, 2, 3)]
    chains = T.chains_per_rung(rows)
    found = L.score(chains, references={})
    first = found["sizes"][0]["chains"]["empty"]
    assert first["scale"]["holds"] is False and first["scale"]["broken_after"]["n"] == 65536
    assert "was on its way" in first["how"] and first["settled"] == []
    alone = L.score(chains, references={}, next_breaks=False)
    assert alone["sizes"][0]["chains"]["empty"]["settled"], "without the next step the first pair settles"
