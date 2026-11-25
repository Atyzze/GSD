from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import focus

ROOT = Path(__file__).resolve().parents[2]
SPEC = {"dsl_version": 1, "init": "empty",
        "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                     "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
        "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                  {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}
KIND, OTHER = "ring", "stopped: starts_alike at 4,096"


class World:
    def __init__(self, monkeypatch, *, seeds="read", depth=None):
        self.verdicts, self.specs, self.made = {}, {"holder": deepcopy(SPEC)}, 0
        self.seeds = {"own": {}, "more": {}, "reproduced": True, "other": [], "of": 6} if seeds == "read" else seeds
        self.depth = depth or {"kinds": {}, "own": {}, "deepest": 65536, "holds_to": 65536, "invalidated_at": None}
        monkeypatch.setattr(focus, "verdict", lambda repo, campaign, law, read_n: self.verdicts.get(law))
        monkeypatch.setattr(focus, "depth_of", lambda repo, state, law, campaign: dict(self.depth))
        monkeypatch.setattr(focus, "seeds_of", lambda repo, state, current: self.seeds)
        monkeypatch.setattr(focus, "_spec_of", lambda repo, campaign, law: self.specs[law])
        monkeypatch.setattr(focus, "_insert", self.insert)

    def insert(self, repo, campaign_id, spec):
        self.made += 1
        law = f"law{self.made:03d}"
        self.specs[law] = deepcopy(spec)
        return law

    def state(self):
        state = {"contract": focus.CONTRACT, "study": "174", "plan": focus.plan(ROOT), "contenders": {},
                 "campaigns": {focus.NEIGHBOURS: "12", focus.SEEDS: "13", focus.DEPTH: "14"},
                 "complexity_budget": 7, "whitelist": None, "done": [], "events": [], "seeds": 3}
        radii = [[float(r), int(c)] for r, c in state["plan"]["neighbourhood"]["radii"]]
        state["current"] = {"law": "holder", "of": "3", "label": "C3-G1", "score": 9, "kind": KIND,
                            "stage": focus.NEIGHBOURHOOD, "points": {}, "lines": {}, "radii": radii}
        found, refused = focus.neighbours(state, "holder", SPEC, radii)
        assert not refused
        focus._add(None, state, state["current"], found)
        return state

    def read(self, state, kind_of=lambda law, point: KIND):
        for law, point in state["current"]["points"].items():
            self.verdicts.setdefault(law, kind_of(law, point))


def test_every_ring_is_drawn_from_the_law_and_the_tiny_ones_move_it_by_no_more_than_their_radius(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    rings = {}
    for law, point in state["current"]["points"].items():
        rings.setdefault(point["radius"], []).append(law)
        moved = [abs(a - b) / max(abs(b), 1e-300) for a, b in zip(
            [t["coeff"]["c0"] for t in world.specs[law]["terms"]], [t["coeff"]["c0"] for t in SPEC["terms"]], strict=True)]
        assert 0 < max(moved) <= point["radius"] * 1.01
    assert {r: len(v) for r, v in rings.items()} == {1e-9: 4, 1e-6: 4, 1e-3: 4, 0.01: 8, 0.1: 8, 0.2: 8, 0.4: 8}


def test_seeds_that_disagree_moves_that_disagree_and_neither_are_told_apart():
    rows = lambda other: {"1e-09": {"laws": 4, "alike": 4 - other, "other": other, "waiting": 0},
                          "1e-06": {"laws": 4, "alike": 4, "other": 0, "waiting": 0},
                          "0.001": {"laws": 4, "alike": 4, "other": 0, "waiting": 0},
                          "0.1": {"laws": 8, "alike": 2, "other": 6, "waiting": 0}}
    found_plan = focus.plan(ROOT)
    agree, apart = {"other": [], "of": 6}, {"other": [4], "of": 6}
    assert focus.sensitivity(found_plan, rows(0), agree)["on"] == focus.ROBUST
    assert focus.sensitivity(found_plan, rows(3), agree)["on"] == focus.ITS_DIGITS
    assert focus.sensitivity(found_plan, rows(3), apart)["on"] == focus.ITS_SEEDS
    found = focus.sensitivity(found_plan, rows(0), apart)
    assert found["on"] == focus.ITS_SEEDS and found["words"].startswith("1 of its 6 seeds")
    assert focus.sensitivity(found_plan, rows(0), None) is None
    waiting = rows(0)
    waiting["1e-06"]["waiting"] = 1
    assert focus.sensitivity(found_plan, waiting, agree) is None


def test_a_neighbourhood_under_two_thirds_alike_at_a_tenth_ends_unconfirmed(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    assert focus.advance(None, state) == 0 and state["current"]["stage"] == focus.NEIGHBOURHOOD
    world.read(state, lambda law, point: KIND if point["radius"] != 0.1 or law[-1] in "0123" else OTHER)
    focus.advance(None, state)
    assert state["current"]["stage"] == focus.UNCONFIRMED
    assert "neighbours at radius 0.1" in state["current"]["why"]


def test_the_depth_reading_another_kind_ends_it_invalidated_whatever_the_neighbours_say(monkeypatch):
    world = World(monkeypatch, depth={"kinds": {"262144": "full"}, "own": {"65536": KIND}, "deepest": 262144,
                                      "holds_to": 65536, "invalidated_at": 262144})
    state = world.state()
    focus.advance(None, state)
    assert state["current"]["stage"] == focus.INVALIDATED
    assert "262,144" in state["current"]["why"] and "'full'" in state["current"]["why"]


def test_it_waits_for_the_depth_and_the_seeds_then_rings_outward_until_one_differs_or_0_8(monkeypatch):
    world = World(monkeypatch, seeds=None)
    world.depth["holds_to"] = None
    state = world.state()
    world.read(state)
    assert focus.advance(None, state) == 0 and state["current"]["stage"] == focus.NEIGHBOURHOOD
    world.depth["holds_to"] = 65536
    assert focus.advance(None, state) == 0, "the seeds are not read yet"
    world.seeds = {"own": {}, "more": {}, "reproduced": True, "other": [], "of": 6}
    assert focus.advance(None, state) == 8
    assert state["current"]["radii"][-1] == [0.8, 8] and state["current"]["sensitivity"]["on"] == focus.ROBUST
    world.read(state)
    assert focus.advance(None, state) == 0
    assert state["current"]["stage"] == focus.MAPPED and "radius 0.8" in state["current"]["why"]


def test_a_neighbour_of_another_kind_is_joined_by_a_line_halved_four_times(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    partner = next(law for law, p in state["current"]["points"].items() if p["radius"] == 0.2)
    tiny = next(law for law, p in state["current"]["points"].items() if p["radius"] == 1e-9)
    world.read(state, lambda law, point: OTHER if law in (partner, tiny) else KIND)
    assert focus.advance(None, state) == 1
    current = state["current"]
    assert current["stage"] == focus.BOUNDARIES and list(current["lines"]) == [partner], \
        "a move of 1e-9 that reads another kind is the law's seeds or digits, never a boundary"
    assert current["sensitivity"]["on"] == focus.ITS_DIGITS
    flips = []
    while current["stage"] == focus.BOUNDARIES:
        line = current["lines"][partner]
        waiting = [law for law in line["points"].values() if law not in world.verdicts]
        for law in waiting:
            at = current["points"][law]["at"]
            world.verdicts[law] = KIND if at < 0.3 else OTHER
            flips.append(at)
        focus.advance(None, state)
    assert flips == [0.5, 0.25, 0.375, 0.3125]
    line = current["lines"][partner]
    assert (line["lo"], line["hi"], line["halvings"]) == (0.25, 0.3125, 4) and line["done"]
    assert current["stage"] == focus.MAPPED
    summary = focus._summary(current)
    assert summary["boundaries"][partner]["between"] == [0.25, 0.3125]


def test_a_ring_with_no_valid_law_is_named_not_raised(monkeypatch):
    from graph_scale_dynamics.research import perturb
    world = World(monkeypatch)
    state = world.state()
    monkeypatch.setattr(perturb, "variants", lambda *a, **k: (_ for _ in ()).throw(ValueError("no valid variant")))
    found, refused = focus.neighbours(state, "holder", SPEC, [[0.8, 8]])
    assert found == [] and refused == [{"radius": 0.8, "why": "no valid variant"}]


def test_a_law_s_kind_waits_for_every_seed_of_a_size(monkeypatch):
    rows = [{"n": 16384, "seed": s} for s in (0, 1, 2)] + [{"n": 65536, "seed": 0}]
    seen = []
    monkeypatch.setattr(focus, "_rows", lambda repo, campaign, law: (rows, None))
    monkeypatch.setattr(focus, "_kinds_of", lambda found, starts: seen.append(sorted({r["n"] for r in found})) or {})
    focus.kinds(None, "14", "holder", whole=3)
    focus.kinds(None, "14", "holder")
    assert seen == [[16384], [16384, 65536]]


@pytest.mark.parametrize("n, own, want", [(16384, {4096: "made", 16384: KIND}, KIND),
                                          (262144, {16384: "made", 65536: KIND}, KIND),
                                          (65536, {}, None)])
def test_the_depth_is_held_to_the_law_s_own_kind_at_each_size_or_its_deepest(n, own, want):
    assert focus.expected(own, n) == want


def test_a_region_reaches_as_far_as_every_ring_from_a_hundredth_reads_its_kind():
    found_plan = focus.plan(ROOT)
    row = lambda other, waiting=0: {"laws": 8, "alike": 8 - other - waiting, "other": other, "waiting": waiting}
    rows = {"1e-09": row(3), "0.01": row(0), "0.1": row(0), "0.2": row(1), "0.4": row(0)}
    assert focus.alike_to(found_plan, rows) == 0.1, "the tiny rings are seeds or digits, not the region's edge"
    assert focus.alike_to(found_plan, dict(rows, **{"0.01": row(0, 1)})) is None
    assert focus.alike_to(found_plan, {"0.01": row(0), "0.1": row(0), "0.2": row(0), "0.4": row(0)}) == 0.4


def test_the_next_law_by_score_is_passed_over_when_it_lies_inside_a_mapped_region(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    near = deepcopy(SPEC)
    near["terms"][0]["coeff"]["c0"] *= 1.02
    far = deepcopy(SPEC)
    far["terms"][0]["coeff"]["c0"] *= 1.5
    world.specs.update(near=near, far=far, other_kind=deepcopy(near))
    world.verdicts.update(holder=KIND, near=KIND, far=KIND, other_kind=OTHER)
    ranked = [{"candidate_id": law, "campaign": "2", "score": 19 - i} for i, law in
              enumerate(("holder", "near", "other_kind", "far"))]
    monkeypatch.setattr(focus, "best", lambda repo, study: ranked)
    monkeypatch.setattr(focus, "label", lambda repo, campaign, law: f"C{campaign}-{law}")
    state["done"] = [{"law": "holder", "of": "3", "label": "C3-G1", "stage": focus.MAPPED, "kind": KIND,
                      "alike_to": 0.1}]
    assert focus._chosen(None, state, None)["candidate_id"] == "other_kind", "another kind is another region"
    assert state["inside"]["near"]["region_of"] == "C3-G1" and state["inside"]["near"]["distance"] < 0.05
    state["done"].append({"law": "other_kind", "stage": focus.UNCONFIRMED})
    assert focus._chosen(None, state, None)["candidate_id"] == "far"
    state["done"].append({"law": "far", "stage": focus.MAPPED})
    assert focus._chosen(None, state, None) is None, "every scoring law mapped or inside: the outliers' turn (862)"
    assert "passed over: C2-near, inside the region of C3-G1" in focus.words(
        dict(focus.reading_of(state), contenders={}))


def test_a_neighbour_once_read_is_not_read_again(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    asked = []
    monkeypatch.setattr(focus, "verdict", lambda repo, campaign, law, read_n: asked.append(law) or world.verdicts.get(law))
    world.read(state, lambda law, point: KIND if point["radius"] != 1e-9 else None)
    focus.advance(None, state)
    first = len(asked)
    focus.advance(None, state)
    assert first == len(state["current"]["points"]) and len(asked) - first == 4, "only the four still undecided"


def test_each_term_switched_off_says_whether_it_bears_the_law_s_kind_and_the_law_waits_for_them(monkeypatch):
    world = World(monkeypatch)
    state = world.state()
    off, kept = focus.knockouts(state, SPEC)
    assert [p["term"] for p in off] == ["degree_cube_sum", "square_edge_overlap"] and not kept
    assert all(len(p["spec"]["terms"]) == 1 for p in off)
    focus._add(None, state, state["current"], off)
    world.read(state, lambda law, point: KIND if point["how"] != focus.KNOCKOUT else None)
    focus.advance(None, state)
    assert state["current"]["stage"] == focus.NEIGHBOURHOOD and state["current"]["core"] is None, (
        "a law is not mapped while a term switched off is unread")
    world.verdicts.update({law: (OTHER if point["term"] == "square_edge_overlap" else KIND)
                           for law, point in state["current"]["points"].items() if point["how"] == focus.KNOCKOUT})
    focus.advance(None, state)
    terms = state["current"]["terms"]
    assert terms["square_edge_overlap"]["load_bearing"] is True and terms["degree_cube_sum"]["load_bearing"] is False
    assert state["current"]["core"] == ["square_edge_overlap"]
    alone = dict(SPEC, terms=SPEC["terms"][:1])
    assert focus.knockouts(state, alone) == ([], [{"term": "degree_cube_sum", "why": "no term left"}])
