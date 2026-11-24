from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research.hamiltonian_preflight import ZERO_TEMPERATURE_FOLDED, equilibrium_identity
from graph_scale_dynamics.services.proposer import blind
from tests.support.proposer_repo import ProposerRepo, top_up_blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
GRID, WHITELIST, BUDGET = (SURVEY["search_policy"]["grid"], SURVEY["operator_whitelist"],
                           SURVEY["complexity_budget"])


def _identity(law: dict) -> str:
    return equilibrium_identity(law, version=ZERO_TEMPERATURE_FOLDED)[0]


def _draw(splits: list[int], seed=2026) -> list[str]:
    existing, physical, held = set(), set(), []
    for need in splits:
        laws = blind.blind_batch(random.Random(0), need, WHITELIST, GRID, existing, physical,
                                 fingerprint=dsl.fingerprint, physical_identity=_identity,
                                 complexity_budget=BUDGET, streams=lambda i: blind.law_stream(seed, i),
                                 first_index=len(held))
        held.extend(laws)
    return [dsl.fingerprint(law) for law in held]


def test_eight_laws_are_the_same_eight_however_the_top_ups_fall():
    whole = _draw([8])
    assert len(whole) == len(set(whole)) == 8
    assert _draw([4, 4]) == _draw([2, 2, 2, 2]) == _draw([1, 3, 1, 2, 1]) == whole


def test_the_seed_is_the_campaign_s_and_nothing_else():
    assert _draw([8], seed=2027) != _draw([8])
    assert blind.law_stream(5, 3).random() == blind.law_stream("5", 3).random(), "the seed as stored, a string or not"
    assert blind.law_stream(5, 3).random() != blind.law_stream(5, 4).random()


def test_the_proposer_s_own_path_draws_them_by_index():
    one, two = ProposerRepo(), ProposerRepo()
    top_up_blind(one, SURVEY, 8, search_seed=77)
    top_up_blind(two, SURVEY, 3, search_seed=77)
    top_up_blind(two, SURVEY, 5, search_seed=77)
    assert [cid for cid, _ in one.laws] == [cid for cid, _ in two.laws]
    assert len(one.laws) == 8
    ledger = one.ledger("1")
    assert sorted({row["stream_index"] for row in ledger}) == list(range(8))
    assert one.ledger("1") == two.ledger("1"), "the same rows, whichever top-up wrote them"
    for index, (cid, _) in enumerate(one.laws):
        rows = [row for row in ledger if row["stream_index"] == index]
        assert [row["draw_index"] for row in rows] == list(range(len(rows)))
        assert rows[-1]["outcome"] == "admitted" and rows[-1]["candidate_id"] == cid


def test_a_duplicate_is_redrawn_in_its_own_stream():
    first = _draw([4])
    existing = {first[1]}
    laws = blind.blind_batch(random.Random(0), 4, WHITELIST, GRID, set(existing), set(), fingerprint=dsl.fingerprint,
                             physical_identity=dsl.fingerprint, complexity_budget=BUDGET,
                             streams=lambda i: blind.law_stream(2026, i), ledger=(ledger := []))
    drawn = [dsl.fingerprint(law) for law in laws]
    assert drawn[0] == first[0] and drawn[2:] == first[2:] and drawn[1] != first[1]
    assert any(row["outcome"] == "duplicate_law" and row["stream_index"] == 1 for row in ledger)


def test_an_anchor_s_k_is_uniform_over_whole_numbers():
    grid = dict(blind.DEFAULT_GRID, **GRID)
    rng = random.Random(9)
    counts = Counter(blind._draw_term(rng, "degree_anchor", grid)["params"]["k"] for _ in range(62000))
    assert sorted(counts) == list(range(2, 33))
    expected = 62000 / 31
    assert all(abs(count - expected) < 5 * expected ** 0.5 for count in counts.values()), counts
    old = Counter(int(blind.draw_value(rng, GRID["anchor_k"], integer=True)) for _ in range(62000))
    assert old[2] < 0.6 * expected and old[32] < 0.6 * expected, "the 629 draw, for the record"


def test_the_n_multipliers_grow_stay_flat_or_shrink_three_eighths_a_quarter_three_eighths():
    grid = dict(blind.DEFAULT_GRID, **GRID)
    assert GRID["scales"] == ["one", "power", "log_N", "inv_log_N"]
    assert GRID["power_exponents"] == {"min": -2.0, "max": 2.0, "spacing": "linear"}
    rng = random.Random(10)
    direction = Counter()
    for _ in range(40000):
        coeff = blind._draw_term(rng, "edge_count", grid)["coeff"]
        p = {"one": 0.0, "log_N": 1.0, "inv_log_N": -1.0}.get(coeff["scale"], coeff.get("p"))
        direction["grows" if p > 0 else "shrinks" if p < 0 else "flat"] += 1
    assert abs(direction["grows"] / 40000 - 0.375) < 0.01 and abs(direction["shrinks"] / 40000 - 0.375) < 0.01
    assert abs(direction["flat"] / 40000 - 0.25) < 0.01


def test_the_shipped_survey_draws_with_the_631_sampler():
    assert GRID[blind.GRID_SAMPLER] == blind.SAMPLER_631 and blind.validate_grid(GRID) == []
    assert WHITELIST[-1] == "ollivier_curvature" and len(WHITELIST) == 14
    assert BUDGET == 7, "measured at 631: docs/readings/curvature_draw_cost_2026-10-21.json"
    assert SURVEY["search_space_version"] == "hamiltonian-search-2", (
        "the build refuses to run a campaign of another search_space_version (main._scientific_contract_matches_"
        "current), so the sampler is gated on the grid, and a campaign made before it still runs")
    assert "strata" not in GRID and "units" not in GRID, "both are the study's choice, not the survey's"
    rng = random.Random(11)
    laws = [blind.blind_law(rng, WHITELIST, GRID, complexity_budget=BUDGET) for _ in range(400)]
    assert any(t["op"] == "ollivier_curvature" for law in laws for t in law["terms"]), "the curvature is drawn"
    assert all(dsl.complexity(law) <= BUDGET for law in laws)


def test_an_unknown_sampler_is_refused():
    assert any("sampler" in p for p in blind.validate_grid(dict(GRID, sampler="blind-sampler-9")))
