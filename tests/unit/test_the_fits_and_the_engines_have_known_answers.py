from __future__ import annotations

import json
import re
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.research import boltzmann_known_answers as B
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import boltzmann_known_answers as boltzmann_tool  # noqa: E402

JUDGE_ADDS = ("kept", "reached", "kept_is_judged", "reached_is_judged", "wrong_measures_refused")


def _json(name: str) -> dict:
    return committed.read(committed.path(name))


def _page(name: str) -> str:
    return (ROOT / "docs" / "readings" / name).read_text(encoding="utf-8")


def _figures(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[A-Za-z']+", "", text))


def _same(again, kept) -> bool:
    return json.loads(json.dumps(again)) == kept


def test_the_exact_measure_and_the_pooled_count_are_what_they_are_by_hand():
    measure = B.exact_measure(np.array([1.0, 1.0 + math.log(2.0), 1.0 + math.log(2.0)]))
    assert measure.tolist() == pytest.approx([0.5, 0.25, 0.25])
    assert B.exact_measure(np.array([0.0, math.log(2.0)]), 2.0).tolist() == pytest.approx([0.8, 0.2])
    even = B.pooled_chi_square([50, 25, 25], measure, 5.0)
    assert (even["cells"], even["chi_square"], even["p"], even["distance"]) == (3, 0.0, 1.0, 0.0)
    off = B.pooled_chi_square([25, 50, 25], measure, 5.0)
    assert off["chi_square"] == 37.5 and off["p"] == pytest.approx(math.exp(-18.75)) and off["distance"] == 0.25
    pooled = B.pooled_chi_square([90, 6, 4], np.array([0.9, 0.06, 0.04]), 5.0)
    assert pooled["cells"] == 2 and pooled["chi_square"] == 0.0
    last = B.pooled_chi_square([96, 2, 2], np.array([0.96, 0.02, 0.02]), 5.0)
    assert last["cells"] == 1 and last["p"] is None, "one pooled cell is no test"


def test_a_graph_and_its_number_are_one_another():
    assert B.graphs(4) == 64 and B.graphs(5) == 1024
    assert B.edges_of(0b100001, 4) == [(0, 1), (2, 3)]
    for mask in (0, 1, 37, 63):
        assert B.mask_of(B.edges_of(mask, 4), 4) == mask
    assert B.mask_of([(3, 2), (1, 0)], 4) == 0b100001
    assert B.taken({"add.local.neg.accepted": 2, "delete.global.pos.accepted": 3, "swap.global.zero.accepted": 4,
                    "add.local.neg.rejected": 9}) == {"local": 2, "global_toggle": 3, "swap": 4}


CRITERION = "boltzmann_known_answers_criterion_4.json"
JUDGED = "boltzmann_known_answers_4_judged"


def test_the_laws_are_drawn_as_the_criterion_says_and_the_same_every_time():
    criterion = _json(CRITERION)
    laws = B.draw_laws(criterion)
    assert laws == B.draw_laws(criterion)
    assert Counter(law["kind"] for law in laws) == {B.DRAWN: 36, B.REACH: 28, B.CONTROL: 2}
    assert len({law["name"] for law in laws}) == len(laws)
    drawn = [law for law in laws if law["kind"] == B.DRAWN]
    assert {law["terms"][0]["op"] for law in drawn if len(law["terms"]) == 1} == set(criterion["terms"])
    strength = criterion["drawn"]["strength"]
    for law in drawn:
        share = len(law["terms"])
        assert all(strength["min"] / share <= term["strength"] <= strength["max"] / share and term["sign"] in (-1, 1)
                   for term in law["terms"])
        assert 0.0 <= law["locality"] < 0.99 and 0.0 <= law["swap"] < 0.99
    law = next(law for law in drawn if law["name"] == "alone_square_count_1")
    spec = B.realise(law, 5, engine.configuration_energy)
    found = B.energies_of(spec, 5, engine.configuration_energy)
    assert found.max() - found.min() == pytest.approx(law["terms"][0]["strength"]), "a coupling is set by its span"
    anchored = next(law for law in drawn if law["name"] == "alone_degree_anchor_1")
    assert B.realise(anchored, 4, engine.configuration_energy)["terms"][0]["params"]["k"] in (1, 2, 3)
    flat = {"name": "flat", "terms": [{"op": "edge_count", "strength": 1.0, "sign": 1, "k_draw": 0.0}],
            "locality": 0.0, "swap": 0.1, "sweeps": 5}
    assert B.realise(flat, 4, lambda spec, n, edges: 0.0) is None, "a term that tells no graph apart builds no law"


def test_the_boltzmann_judgement_in_the_tree_is_the_one_the_rule_gives():
    criterion, kept = _json(CRITERION), _json(f"{JUDGED}.json")
    assert kept["criterion"] == criterion["contract"]
    rows = [{key: value for key, value in cell.items() if key not in JUDGE_ADDS} for cell in kept["cells"]]
    again = B.judge(criterion, rows + kept["not_built"], kept["energies"])
    for key in ("alpha", "tests_judged", "k1_the_measure_is_kept", "k2_the_measure_is_reached",
                "k3_the_energies_agree", "k4_every_kind_of_move_is_taken", "passes", "kept", "reached",
                "accepted_by_engine", "by_term", "wrong_measures", "predictions", "predictions_right", "cells"):
        assert _same(again[key], kept[key]), key
    assert kept["measured_utc"] > criterion["committed_utc"]
    assert len(kept["cells"]) + len(kept["not_built"]) == 66 * 2 * 2
    assert set(kept["by_term"]) == set(criterion["terms"])
    assert _figures(_page(f"{JUDGED}.md")) == _figures(B.render(kept)), (
        "the page committed with the reading holds its figures; its words were its build's")


def test_a_chain_that_keeps_its_measure_agrees_and_one_at_twice_its_energy_does_not():
    criterion = {"seed": 11, "sizes": [4], "terms": ["edge_count"],
                 "engines": {"rust": {"runs": 600, "seed_offset": 0}},
                 "drawn": {"alone_per_term": 1, "mixed": 0, "mixed_term_counts": [2], "complexity_budget": 7,
                           "strength": {"min": 0.5, "max": 3.0}, "locality_below": 0.99, "swap_below": 0.99,
                           "sweeps": 40},
                 "reach": {"localities": [0.0], "swap": 0.15, "sweeps": 100},
                 "controls": [{"name": name, "expected": expected, "beta": beta, "locality": 0.7, "swap": 0.1,
                               "sweeps": 40, "terms": [{"op": "edge_count", "c0": 0.3},
                                                       {"op": "triangle_count", "c0": -0.8}]}
                              for name, expected, beta in (("toggle", "kept", 1.0), ("hot", "refused", 2.0))],
                 "wrong_measures": [2.0], "rule": {"family_wise": 0.01, "pooled_cells_expect_at_least": 5.0}}
    rows, energies = boltzmann_tool.measure(criterion, 1)
    judged = B.judge(criterion, rows, energies)
    cells = {cell["law"]: cell for cell in judged["cells"]}
    assert cells["toggle"]["kept"] and not cells["hot"]["kept"]
    assert cells["hot"]["beta"] == 2.0 and cells["hot"]["given_against_wrong_measures"]["2"] >= judged["alpha"], (
        "the hot chain keeps the measure of its own beta, the energies doubled")
    assert judged["predictions_right"] == 2 and judged["k3_the_energies_agree"]
    assert cells["reach_edge_count_locality_0"]["reached"] and cells["reach_edge_count_locality_0"]["kept"]
    assert judged["passes"] == judged["k4_every_kind_of_move_is_taken"]
    assert not any(cell["ends_off_the_ledger"] for cell in judged["cells"])


def test_the_fourth_reading_on_806_s_engines_passes_every_cell():
    judged, criterion = _json(f"{JUDGED}.json"), _json(CRITERION)
    assert judged["passes"] and judged["predictions_right"] == len(judged["predictions"]) == 8
    assert judged["measured_utc"] > criterion["committed_utc"] and judged["engine_fingerprints"]["rust"].startswith(
        "rs:0.806.0")
    assert judged["kept"] == {"held": 260, "of": 260} and judged["reached"] == {"held": 112, "of": 112}
    assert all(cell["given"]["p"] is not None and cell["empty"]["p"] is not None for cell in judged["cells"])
    hot = [c for c in judged["cells"] if c["law"] == "the_tree_s_law_at_twice_its_energy"]
    assert len(hot) == 4 and all(not c["kept"] and c["given_against_wrong_measures"]["2"] >= judged["alpha"]
                                 for c in hot), "refused against its law's measure, kept against its own"
