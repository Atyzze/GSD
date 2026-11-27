from __future__ import annotations

import json

from graph_scale_dynamics.operations import modes
from graph_scale_dynamics.operations import zone_search as Z


def _line(steps: dict, *, sign: int = 1, lo: float = 0.0, hi=None, halvings: int = 0, param: str = "beta") -> dict:
    return {"param": param, "path": ["dynamics", "beta"], "sign": sign, "from": 0.19, "lo": lo, "hi": hi,
            "halvings": halvings, "done": False, "why": None,
            "steps": {Z._key(at): {"at": at, "law": law, "verdict": verdict, "why": None}
                      for at, (law, verdict) in steps.items()}}


def test_a_line_waiting_on_its_step_names_the_two_points_it_may_need_next():
    assert Z.ahead(_line({0.1: ("a", None)})) == [0.2, 0.05], "alike: the next step out; another kind: halfway back"
    assert Z.ahead(_line({0.1: ("a", Z.ALIKE), 0.2: ("b", None)}, lo=0.1)) == [0.4, 0.15]
    halving = _line({0.4: ("a", Z.ALIKE), 0.8: ("b", Z.OTHER), 0.6: ("c", None)}, lo=0.4, hi=0.8, halvings=1)
    assert Z.ahead(halving) == [0.7, 0.5], "either half's midpoint"
    last = _line({0.4: ("a", Z.ALIKE), 0.8: ("b", Z.OTHER), 0.6: ("c", Z.OTHER), 0.5: ("d", None)},
                 lo=0.4, hi=0.6, halvings=2)
    assert Z.ahead(last) == [], "its last halving: nothing comes after it"
    down = _line({0.1: ("a", Z.ALIKE), 0.2: ("b", Z.ALIKE), 0.4: ("c", Z.ALIKE), 0.8: ("d", None)}, sign=-1, lo=0.4)
    assert Z.ahead(down) == [0.95, 0.6], "down, no farther than 95% of its value"
    assert Z.ahead(_line({0.1: ("a", Z.ALIKE)}, lo=0.1)) == [], "nothing under way: the line steps as before"
    known = _line({0.1: ("a", None), 0.2: ("b", None)})
    known["steps"][Z._key(0.2)]["ahead"] = True
    assert Z.ahead(known) == [0.05], "a point already run ahead is not run again"


def test_a_point_run_ahead_is_taken_when_the_line_comes_to_it_and_the_other_is_left(monkeypatch):
    monkeypatch.setattr(Z, "reading", lambda repo, campaign, law, n: {"law": law})
    monkeypatch.setattr(Z, "judged", lambda centre, found: (Z.ALIKE, "alike"))
    monkeypatch.setattr(Z, "STEPS_OUT", 2)
    line = _line({0.1: ("a", None), 0.2: ("b", None), 0.05: ("c", None)})
    assert Z._step_line(None, {}, {}, line, {}, "9") == 0
    assert line["lo"] == 0.2 and line["done"] and "no edge this side" in line["why"], (
        "0.1 read alike, then 0.2, already run ahead, read without a new law: the farthest step")
    assert line["steps"][Z._key(0.05)]["verdict"] is None, "the point it did not need is left unread"


def test_the_zone_search_fills_only_the_slots_its_mode_leaves_free(monkeypatch):
    from graph_scale_dynamics.operations import push_ladder

    class Repo:
        def __init__(self, mode, busy):
            self.flags, self.busy = {modes.FLAG: json.dumps(mode)}, busy
            self.conn = self

        def get_flag(self, key, default=""):
            return self.flags.get(key, default)

        def execute(self, sql, params=()):
            busy = self.busy

            class Row:
                def fetchone(self):
                    return {"c": busy}
            return Row()

    monkeypatch.setattr(push_ladder, "workers", lambda repo: 16)
    zone = {"mode": modes.ZONE, "campaigns": ["12", "13", "16"], "laws": []}
    assert Z.free_runs(Repo(zone, 4)) == 12
    assert Z.free_runs(Repo(zone, 20)) == 0
    assert Z.free_runs(Repo(dict(zone, mode=modes.PUSH), 0)) == 0, "only the zone search runs ahead"
    put = []
    monkeypatch.setattr(Z, "free_runs", lambda repo: 7)
    monkeypatch.setattr(Z, "_put", lambda repo, state, current, line, at, campaign, **extra: put.append(
        (line["param"], at, extra)) or None)
    search = {"lines": {"a +": _line({0.1: ("a", None)}, param="a"), "b +": _line({0.1: ("b", None)}, param="b"),
                        "c +": _line({0.1: ("c", Z.ALIKE)}, lo=0.1, param="c")}}
    assert Z._look_ahead(None, {}, {}, search, "16") == 2, "7 free runs, three seeds a point: two points"
    assert put == [("a", 0.2, {"ahead": True}), ("a", 0.05, {"ahead": True})]
