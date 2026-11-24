from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import study_map as M
from graph_scale_dynamics.research import neighbourhood as N

ROOT = Path(__file__).resolve().parents[2]
FIRST_TEN = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "study_176_first_ten.json"


def _law(c=(0.5, -0.2), beta=2.0, swap=0.3):
    return {"dsl_version": 1, "init": "empty",
            "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": c[0], "scale": "one"}},
                      {"op": "triangle_count", "params": {}, "coeff": {"c0": c[1], "scale": "one"}}],
            "dynamics": {"kind": "equilibrium", "beta": beta, "sweeps": 30,
                         "move_mix": {"add": (1 - swap) / 2, "delete": (1 - swap) / 2, "swap": swap}}}


def test_each_parameter_moves_alone_a_step_up_and_down_and_a_share_stays_a_share():
    found = N.alone(_law(), 0.1)
    assert [(f["parameter"], f["step"]) for f in found] == [
        ("term 1 c0", 0.1), ("term 1 c0", -0.1), ("term 2 c0", 0.1), ("term 2 c0", -0.1),
        ("beta", 0.1), ("beta", -0.1), ("swap", 0.1), ("swap", -0.1)]
    assert found[0]["spec"]["terms"][0]["coeff"]["c0"] == 0.55 and found[0]["spec"]["terms"][1]["coeff"]["c0"] == -0.2
    assert all(f["spec"]["dynamics"]["beta"] == 2.0 for f in found[:4])
    assert len(N.alone(_law(swap=0.95), 0.1)) == 7, "a swap share pushed past 1 is no law"


def test_a_line_runs_between_two_laws_of_the_same_terms_and_is_halved_where_the_kind_flips():
    a, b = _law(), _law(c=(1.5, -0.2), beta=4.0)
    assert N.between(a, b, 0.0)["terms"][0]["coeff"]["c0"] == 0.5 and N.between(a, b, 1.0)["dynamics"]["beta"] == 4.0
    assert N.between(a, b, 0.5)["terms"][0]["coeff"]["c0"] == 1.0
    assert N.between(a, dict(b, terms=b["terms"][:1]), 0.5) is None, "no line between different terms"
    line = {"lo": 0.0, "hi": 1.0, "lo_kind": "made", "hi_kind": "empty", "halvings": 0, "most": 4}
    assert N.next_point(line) == 0.5
    line = N.narrowed(line, 0.5, "made")
    assert (line["lo"], line["hi"], N.next_point(line)) == (0.5, 1.0, 0.75)
    line = N.narrowed(line, 0.75, "full")
    assert (line["lo"], line["hi"], line["hi_kind"]) == (0.5, 0.75, "full"), "a third kind is a flip too"
    line = N.narrowed(N.narrowed(line, 0.625, "made"), 0.6875, "made")
    assert line["done"] and line["halvings"] == 4 and N.next_point(line) is None
    assert N.narrowed({"lo": 0, "hi": 1, "lo_kind": "x", "hi_kind": "y"}, 0.5, None)["done"]


def test_the_partner_is_the_nearest_law_of_the_same_terms_of_another_kind_and_not_the_law_on_new_numbers():
    holder = _law()
    others = [{"candidate_id": "near", "spec": _law(c=(0.5000000001, -0.2)), "kind_at_4096": "full"},
              {"candidate_id": "same", "spec": _law(c=(0.52, -0.2)), "kind_at_4096": "made"},
              {"candidate_id": "far", "spec": _law(c=(0.9, -0.2)), "kind_at_4096": "empty"},
              {"candidate_id": "other terms", "spec": dict(_law(), terms=_law()["terms"][:1]), "kind_at_4096": "full"}]
    found = N.nearest_of_another_kind(holder, "made", others)
    assert found["candidate_id"] == "far" and found["distance"] > N.MIN_DISTANCE
    assert N.nearest_of_another_kind(holder, None, others) is None


class _Repo:
    def __init__(self):
        self.flags, self.inserted = {}, []

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value

    def insert_candidate(self, law, campaign, spec, dynamics, complexity, state):
        self.inserted.append((law, campaign, state))


def _holder(label, law_id, spec, kind, partner=None):
    return {"label": label, "candidate_id": law_id, "spec": spec, "score": 9, "kind_at_4096": kind, "partner": partner}


def test_a_region_is_mapped_point_by_point_then_known_with_its_kind_the_size_it_is_spotted_at_and_its_boundary(
        monkeypatch):
    from graph_scale_dynamics.dsl import dsl
    repo = _Repo()
    holder_spec = dsl.normalize(_law())
    holder_id = dsl.fingerprint(holder_spec)
    partner = {"candidate_id": "p" * 64, "spec": _law(c=(0.5, 0.8)), "kind_at_4096": "empty"}
    survey = {"complexity_budget": 6, "operator_whitelist": None}
    monkeypatch.setattr(N, "valid", lambda spec, **_k: None)
    plan = {"top": 1, "step": 0.1, "halvings": 2}
    state = M.begin(repo, "t", "9", plan, [_holder("M01", holder_id, holder_spec, "made", partner)], survey)
    region = state["regions"][holder_id]
    hows = sorted(point["how"] for point in region["points"].values())
    assert hows == ["holder", "line"] + ["variant"] * 8 and len(repo.inserted) == 10
    assert {state for *_x, state in repo.inserted} == {"PROPOSED"}
    line_law = region["lines"]["p" * 64]["points"]["0.5"]
    kinds = {law: {"1024": "made", "4096": "made"} for law in region["points"]}
    kinds[line_law] = {"1024": "empty", "4096": "empty"}
    monkeypatch.setattr(M, "decided", lambda _r, _c, law: law in kinds)
    monkeypatch.setattr(M, "kinds_of", lambda _r, _c, law: {int(n): k for n, k in kinds[law].items()})
    monkeypatch.setattr(M, "_spec", lambda _r, _s, law: holder_spec)
    assert M.advance(repo, state, region) == 1, "the line is halved on the holder's side: one point at 0.25"
    quarter = region["lines"]["p" * 64]["points"]["0.25"]
    assert region["state"] == M.MAPPING and region["lines"]["p" * 64]["hi"] == 0.5
    kinds[quarter] = {"1024": "empty", "4096": "made"}
    assert M.advance(repo, state, region) == 0
    assert region["state"] == M.KNOWN and region["kind"] == "made"
    assert region["spotted_at"] == 4096, "the point at 0.25 is made from 4,096 only: nothing earlier holds for all"
    assert region["boundaries"]["p" * 64] == {"between": [0.25, 0.5], "kinds": ["made", "empty"], "why": None}
    assert region["kinds"] == {"made": 10, "empty": 1}


def test_a_known_region_leaves_the_ten_and_the_next_best_law_not_in_a_region_comes_in(monkeypatch):
    from graph_scale_dynamics.dsl import dsl
    repo = _Repo()
    spec = dsl.normalize(_law())
    state = {"contract": M.CONTRACT, "study": "t", "campaign": "9", "top": 1, "step": 0.1, "halvings": 2,
             "complexity_budget": 6, "whitelist": None, "events": [],
             "regions": {"k" * 64: {"holder": "k" * 64, "state": M.KNOWN, "points": {"v" * 64: {"how": "variant"}},
                                    "lines": {}}}}
    M.save(repo, state)
    monkeypatch.setattr(M, "best", lambda _r, _s: [{"candidate_id": "v" * 64, "campaign": "1", "score": 30, "to_n": 1},
                                                   {"candidate_id": "n" * 64, "campaign": "2", "score": 20, "to_n": 1}])
    monkeypatch.setattr(M, "_spec", lambda _r, _s, law: spec)
    monkeypatch.setattr(M, "kinds_of", lambda *_a: {4096: "ring"})
    monkeypatch.setattr(M, "partner_of", lambda *_a: None)
    monkeypatch.setattr(M, "decided", lambda *_a: False)
    monkeypatch.setattr(N, "valid", lambda spec, **_k: None)
    found = M.step(repo, force=True)
    assert found["entered"] == ["n" * 64] and found["mapping"] == 1 and found["known"] == 1
    entered = M.load(repo)["regions"]["n" * 64]
    assert entered["points"]["n" * 64] == {"how": "holder", "campaign": "2"}, "a study's own law is not run again"
    assert all(law != "n" * 64 for law, *_x in repo.inserted) and len(repo.inserted) == 8
    assert M.step(repo, force=True)["entered"] == [], "the ten are full"


def test_the_first_ten_are_the_baseline_s_best_rebuilt_exactly_each_with_its_partner_or_none():
    from graph_scale_dynamics.dsl import dsl
    found = json.loads(FIRST_TEN.read_text(encoding="utf-8"))
    assert found["score"] == "gsd-law-score-9" and len(found["holders"]) == 10 and found["not_rebuilt"] == []
    assert [h["score"] for h in found["holders"]] == sorted((h["score"] for h in found["holders"]), reverse=True)
    for holder in found["holders"]:
        assert dsl.fingerprint(dsl.normalize(holder["spec"])) == holder["candidate_id"]
        assert holder["score"] > 1, "a still or frozen lattice is never mapped"
        partner = holder["partner"]
        if partner is not None:
            assert partner["kind_at_4096"] != holder["kind_at_4096"] and partner["distance"] >= N.MIN_DISTANCE
            assert N.signature(partner["spec"]) == N.signature(holder["spec"])


def test_nothing_steps_without_a_map():
    assert M.step(_Repo(), force=True) is None and M.reading(_Repo()) is None
    with pytest.raises(KeyError):
        M.points_of({}, step=0.1, halvings=2, complexity_budget=6, whitelist=None)
