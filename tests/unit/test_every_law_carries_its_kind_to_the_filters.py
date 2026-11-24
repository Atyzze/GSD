from __future__ import annotations

import json

from graph_scale_dynamics.observability import score_board as B
from graph_scale_dynamics.operations import study_map as M
from graph_scale_dynamics.services.api import landscape_worker as LW


class _Flags:
    def __init__(self):
        self.flags = {}

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def test_the_board_keeps_every_scanned_law_s_kind_scored_or_not():
    repo = _Flags()
    B.keep(repo, "1", {"a" * 64: {"score": 0, "kind": "empty"}, "b" * 64: {"score": 7, "kind": "made"},
                       "c" * 64: {"score": 0}})
    found = B.board(repo, "1")
    assert found["kinds"] == {"a" * 64: "empty", "b" * 64: "made"} and list(found["scores"]) == ["b" * 64]
    assert B.CONTRACT == "gsd-score-board-2", "a board without kinds is read again from the start"


def test_a_landscape_point_says_its_kind_group_batch_and_map_region():
    marks = {"kinds": {"a" * 64: "small_world"}, "group": "B", "batch": "11",
             "regions": {"a" * 64: {"region": "h" * 64, "state": "known", "kind": "made"}}}
    point = LW.marked({"candidate_id": "a" * 64}, marks)
    assert (point["kind"], point["group"], point["batch"]) == ("small_world", "B", "11")
    assert point["region"] == {"of": "h" * 64, "state": "known", "kind": "made"}
    other = LW.marked({"candidate_id": "z" * 64}, marks)
    assert other["kind"] is None and other["region"] is None


def test_the_map_says_which_region_each_law_is_in():
    repo = _Flags()
    repo.set_flag(M.FLAG, json.dumps({"contract": M.CONTRACT, "regions": {
        "h": {"state": "known", "kind": "ring", "points": {"p": {}, "q": {}}},
        "k": {"state": "mapping", "points": {"r": {}}}}}))
    found = M.regions_of_laws(repo)
    assert found["p"] == found["h"] == {"region": "h", "state": "known", "kind": "ring"}
    assert found["r"]["state"] == "mapping" and M.regions_of_laws(_Flags()) == {}
