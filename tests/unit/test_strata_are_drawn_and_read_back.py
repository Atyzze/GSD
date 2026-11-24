from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research import strata as S
from graph_scale_dynamics.research.hamiltonian_preflight import ZERO_TEMPERATURE_FOLDED, equilibrium_identity
from graph_scale_dynamics.services.proposer import blind
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
PAPER = {"grid": {"sampler": "blind-sampler-2", "strata": designs.STRATA}}
GRID, WHITELIST, BUDGET = (SURVEY["search_policy"]["grid"], SURVEY["operator_whitelist"],
                           SURVEY["complexity_budget"])


def _law_in(stratum: str) -> dict:
    temperature, kind, count = stratum.split("/")
    ops = ["degree_fourth_sum", "edge_count", "degree_cube_sum"]
    if kind == S.SEES_MORE:
        ops[0] = "triangle_count"
    ops = ops[:1] if count == S.FEW_TERMS else ops
    return {"terms": [{"op": op, "params": {}, "coeff": {"c0": 1.0, "scale": "one"}} for op in ops],
            "dynamics": {"zero_temperature": True} if temperature == S.ZERO_T else {}}


def test_a_law_s_stratum_is_read_from_the_law():
    assert [S.stratum_of(_law_in(h)) for h in S.STRATA] == list(S.STRATA)
    assert len(S.STRATA) == 8 and set(PAPER["grid"]["strata"]["allocation"]) == set(S.STRATA)
    curvature = {"terms": [{"op": "ollivier_curvature"}, {"op": "degree_anchor"}], "dynamics": {}}
    assert S.stratum_of(curvature) == "finiteT/sees more/1-2 terms"


def test_the_paper_s_allocation_draws_as_declared():
    normal = S.allocation_of(PAPER["grid"])
    assert math.isclose(sum(normal.values()), 1.0) and list(normal) == [h for h in S.STRATA if h in normal]
    rng = random.Random(1)
    drawn = Counter(S.draw_stratum(rng, normal) for _ in range(50000))
    for h, share in normal.items():
        assert abs(drawn[h] / 50000 - share) < 5 * math.sqrt(share * (1 - share) / 50000), h


def test_a_survey_grid_with_the_paper_s_strata_is_valid_and_a_629_one_is_not():
    assert blind.validate_grid(dict(GRID, **PAPER["grid"])) == []
    old = dict(GRID, strata=PAPER["grid"]["strata"])
    old.pop("sampler")
    assert any("needs sampler" in p for p in blind.validate_grid(old))


@pytest.mark.parametrize("change,words", [
    ({"strata": {"allocation": {"warm/degree-only/1-2 terms": 1.0}}}, "unknown strata"),
    ({"strata": {"allocation": {"zeroT/degree-only/1-2 terms": -1.0}}}, "non-negative"),
    ({"zero_temperature": [False]}, "zero_temperature never draws it"),
    ({"term_counts": [1, 2]}, "term_counts never draw it"),
])
def test_a_stratum_no_law_can_reach_is_refused(change, words):
    grid = dict(GRID, **PAPER["grid"])
    grid.update(change)
    assert any(words in p for p in blind.validate_grid(grid)), blind.validate_grid(grid)


def test_a_selection_that_sees_only_degrees_cannot_hold_a_sees_more_stratum():
    from graph_scale_dynamics.scheduling import term_selection
    verdict = term_selection.preflight(["degree_square_sum", "degree_fourth_sum"], dict(GRID, **PAPER["grid"]), 7)
    assert any("every selected term sees only degrees" in p for p in verdict["problems"])


def test_a_stratified_batch_holds_each_law_in_the_stratum_its_stream_drew():
    grid = dict(GRID, **PAPER["grid"])
    ledger: list = []
    laws = blind.blind_batch(random.Random(0), 120, WHITELIST, grid, set(), set(), fingerprint=dsl.fingerprint,
                             physical_identity=lambda law: equilibrium_identity(
                                 law, version=ZERO_TEMPERATURE_FOLDED)[0],
                             complexity_budget=BUDGET, streams=lambda i: blind.law_stream(31, i), ledger=ledger)
    assert len(laws) == 120
    allocation = S.allocation_of(grid)
    for index, law in enumerate(laws):
        assert S.stratum_of(law) == S.draw_stratum(blind.law_stream(31, index), allocation), index
    aside = [row for row in ledger if row["outcome"] == "set_aside"]
    assert aside and all(S.stratum_of(row["law"]) != S.stratum_of(laws[row["stream_index"]]) for row in aside)
    assert all(blind.validity_problem(row["law"], complexity_budget=BUDGET, sampler=blind.SAMPLER_631) is None
               for row in aside), "only valid laws are set aside; refusals keep their own codes"
    held = Counter(S.stratum_of(law) for law in laws)
    assert held["zeroT/sees more/3-4 terms"] > 0.3 * 120, "the allocation, not the measure, decides what is held"


def test_the_ledger_s_shares_are_the_measure_s():
    grid = dict(GRID, **PAPER["grid"])
    ledger: list = []
    blind.blind_batch(random.Random(0), 150, WHITELIST, grid, set(), set(), fingerprint=dsl.fingerprint,
                      physical_identity=dsl.fingerprint, complexity_budget=BUDGET,
                      streams=lambda i: blind.law_stream(32, i), ledger=ledger)
    shares = S.stratum_shares(ledger)
    rng = random.Random(5)
    plain = Counter(S.stratum_of(blind.blind_law(rng, WHITELIST, GRID, complexity_budget=BUDGET))
                    for _ in range(4000))
    assert shares["streams"] == 150 and shares["valid_draws"] > 150
    for h in S.STRATA:
        row = shares["strata"][h]
        truth = plain[h] / 4000
        spread = math.hypot(row["se"], math.sqrt(truth * (1 - truth) / 4000))
        assert abs(row["share"] - truth) < 4 * spread + 1e-9, (h, row, truth)


def _ledger(streams: list[list[str]], outcome_of=None) -> list[dict]:
    rows = []
    for index, strata in enumerate(streams):
        for position, h in enumerate(strata):
            rows.append({"stream_index": index, "draw_index": position, "law": _law_in(h),
                         "outcome": (outcome_of or (lambda p, n: "admitted" if p == n - 1 else "set_aside"))(
                             position, len(strata))})
    return rows


def test_shares_count_every_valid_draw_and_nothing_refused():
    a, b = "zeroT/sees more/3-4 terms", "finiteT/degree-only/1-2 terms"
    rows = _ledger([[b, b, a], [a], [b, a], [b, b, b, a]])
    rows.append({"stream_index": 0, "draw_index": 9, "law": _law_in(b), "outcome": "invalid:over_budget"})
    rows.append({"stream_index": 1, "draw_index": 9, "law": _law_in(b), "outcome": "duplicate_identity"})
    shares = S.stratum_shares(rows)
    assert shares["valid_draws"] == 11 and shares["streams"] == 4
    assert shares["strata"][a]["share"] == pytest.approx(4 / 11)
    assert shares["strata"][b]["share"] == pytest.approx(7 / 11)
    assert shares["strata"]["zeroT/degree-only/1-2 terms"]["share"] == 0.0
    assert shares["strata"][a]["se"] > 0


def test_the_ratio_estimate_is_consistent_when_every_stream_stops_at_one_stratum():
    a, b = "zeroT/sees more/3-4 terms", "finiteT/sees more/1-2 terms"
    rng = random.Random(7)
    streams = []
    for _ in range(3000):
        run = []
        while True:
            run.append(a if rng.random() < 0.2 else b)
            if run[-1] == a:
                break
        streams.append(run)
    shares = S.stratum_shares(_ledger(streams))
    assert abs(shares["strata"][a]["share"] - 0.2) < 3 * shares["strata"][a]["se"]
    assert 0.002 < shares["strata"][a]["se"] < 0.01


def test_a_rate_reweights_to_the_measure_with_its_error():
    a, b = "zeroT/sees more/3-4 terms", "finiteT/degree-only/1-2 terms"
    rows = _ledger([[b, b, b, a]] * 50 + [[b, a]] * 50)
    result = S.reweighted_rate(rows, {a: (30, 100), b: (2, 200)})
    assert result["rate"] == pytest.approx(1 / 3 * 0.3 + 2 / 3 * 0.01)
    rates = math.sqrt((1 / 3) ** 2 * 0.3 * 0.7 / 100 + (2 / 3) ** 2 * 0.01 * 0.99 / 200)
    assert result["se_rates"] == pytest.approx(rates)
    assert result["se"] > result["se_rates"] and result["se_shares"] > 0
    assert result["by_stratum"][a]["share"] == pytest.approx(1 / 3)


def test_a_stratum_on_the_measure_with_no_law_measured_leaves_the_rate_unknown():
    a, b = "zeroT/sees more/3-4 terms", "finiteT/degree-only/1-2 terms"
    result = S.reweighted_rate(_ledger([[b, a], [a]]), {a: (1, 10)})
    assert result["rate"] is None and result["uncovered"] == [b]
