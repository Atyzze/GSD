from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import focus
from graph_scale_dynamics.operations import focus_regions as R

ROOT = Path(__file__).resolve().parents[2]


def _law(c0: float, beta: float = 0.2, *, op: str = "degree_cube_sum", anchor: int | None = None, zero=False) -> dict:
    terms = [{"op": op, "params": {}, "coeff": {"c0": c0, "scale": "one"}}]
    if anchor is not None:
        terms.append({"op": "degree_anchor", "params": {"k": anchor}, "coeff": {"c0": 0.5, "scale": "one"}})
    dynamics = {"kind": "equilibrium", "beta": beta, "locality": 0.3, "sweeps": 30,
                "move_mix": {"add": 0.1, "delete": 0.1, "swap": 0.8}}
    if zero:
        dynamics["zero_temperature"] = True
    return {"dsl_version": 1, "init": "empty", "terms": terms, "dynamics": dynamics}


def test_a_law_is_a_point_on_one_axis_a_term_and_on_the_dynamics_axes():
    found = R.axis_values(_law(1.2, anchor=4))
    assert found == {"coupling degree_cube_sum": 1.2, "coupling degree_anchor k=4": 0.5, "beta": 0.2,
                     "locality": 0.3, "swap share": 0.8, "zero temperature": 0.0}


def test_a_term_a_law_lacks_counts_as_zero_in_a_range_and_in_an_overlap():
    with_anchor = R.ranges([_law(1.0, anchor=4), _law(1.2, anchor=4)])
    without = R.ranges([_law(1.1), _law(1.3)])
    assert with_anchor["coupling degree_anchor k=4"] == [0.5, 0.5]
    assert R.ranges([_law(1.1, anchor=4), _law(1.3)])["coupling degree_anchor k=4"] == [0.0, 0.5]
    assert not R.overlap(with_anchor, without), "absent is 0, and 0 lies outside [0.5, 0.5]"
    assert R.overlap(R.ranges([_law(1.0), _law(1.2)]), without)
    assert not R.overlap(R.ranges([_law(1.1, zero=True)]), without), "zero temperature is its own side"


def test_mapped_laws_are_numbered_in_order_and_one_of_the_same_kind_that_overlaps_joins_it():
    state = {}
    first = R.place(state, {"law": "a", "label": "C1-G1", "kind": "ring", "alike_to": 0.4}, [_law(1.0), _law(1.2)])
    second = R.place(state, {"law": "b", "label": "C2-G2", "kind": "full", "alike_to": 0.1}, [_law(1.1), _law(1.15)])
    joined = R.place(state, {"law": "c", "label": "C3-G3", "kind": "ring", "alike_to": 0.2}, [_law(1.15), _law(1.4)])
    apart = R.place(state, {"law": "d", "label": "C4-G4", "kind": "ring", "alike_to": 0.2}, [_law(-2.0), _law(-1.8)])
    assert (first["name"], second["name"], joined["name"], apart["name"]) == ("GG#1", "GG#2", "GG#1", "GG#3")
    assert first["ranges"]["coupling degree_cube_sum"] == [1.0, 1.4] and first["labels"] == ["C1-G1", "C3-G3"]
    assert first["members"] == 4 and [j["label"] for j in first["joined"]] == ["C3-G3"]
    assert R.name_of(state, "c") == "GG#1" and R.name_of(state, "zz") is None
    assert R.touching(state["regions"]) == [{"regions": ["GG#1", "GG#2"], "kinds": ["ring", "full"]}]


def _state() -> dict:
    found_plan = focus.plan(ROOT)
    return {"contract": focus.CONTRACT, "study": "174", "plan": found_plan, "campaigns": {"N": "12", "S": "13", "D": "14"},
            "contenders": {}, "done": [{"law": "d" * 64, "label": "C2-G64", "stage": focus.MAPPED, "of": "2"}],
            "events": [], "current": {"law": "c" * 64, "label": "C1-G6940", "stage": focus.NEIGHBOURHOOD, "of": "1",
                                      "points": {}, "lines": {}, "radii": [], "score": 19, "kind": "ring"},
            "queue": [{"law": "c" * 64, "label": "C1-G6940", "campaign": "1", "score": 19, "status": "in focus"},
                      {"law": "e" * 64, "label": "C6-G1015", "campaign": "6", "score": 19, "status": "waiting"}]}


class _Flags:
    def __init__(self, state):
        self.flags = {focus.FLAG: json.dumps(state)}

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def test_a_law_is_named_by_its_label_or_the_start_of_its_id_and_never_ambiguously():
    state = _state()
    assert focus.resolve(state, "C6-G1015") == "e" * 64
    assert focus.resolve(state, "cccc") == "c" * 64
    for given in ("", "C9-G1", "zz"):
        with pytest.raises(ValueError):
            focus.resolve(state, given)


def test_a_skipped_law_in_focus_is_set_aside_and_a_skipped_law_waits_until_put_back(monkeypatch):
    monkeypatch.setattr(focus, "_finish", lambda repo, state, current: (state["done"].append(focus._summary(current)),
                                                                        state.update(current=None)))
    repo = _Flags(_state())
    state = focus.skip(repo, "C1-G6940")
    assert state["current"] is None and state["done"][-1]["stage"] == focus.UNCONFIRMED
    assert "skipped on the operator's word" in state["done"][-1]["why"] and "c" * 64 in state["skipped"]
    state = focus.skip(repo, "C6-G1015")
    assert set(state["skipped"]) == {"c" * 64, "e" * 64}
    ranked = [{"candidate_id": "c" * 64, "campaign": "1", "score": 19, "label": "C1-G6940"},
              {"candidate_id": "e" * 64, "campaign": "6", "score": 19, "label": "C6-G1015"}]
    assert focus._chosen(None, state, None, ranked) is None, "nothing left that is not skipped or done"
    state = focus.back(repo, "C6-G1015")
    assert set(state["skipped"]) == {"c" * 64}
    monkeypatch.setattr(focus, "inside", lambda repo, state, entry: None)
    assert focus._chosen(None, state, None, ranked)["candidate_id"] == "e" * 64
    queue = focus.queue_of(state, ranked)
    assert [e["status"] for e in queue] == ["skipped", "waiting"]


def test_settings_apply_from_the_next_law_and_refuse_what_would_break_a_reading():
    repo = _Flags(_state())
    state = focus.set_next(repo, {"radii": [[0.1, 8], [1e-9, 2], [0.3, 4]], "contenders": 3, "confirm_share": 0.75})
    assert state["plan"]["neighbourhood"]["radii"] != state["next_plan"]["neighbourhood"]["radii"]
    assert focus.settings_of(state["next_plan"])["radii"] == [[1e-9, 2], [0.1, 8], [0.3, 4]]
    assert state["next_plan"]["depth"]["contenders"] == 3 and state["plan"]["depth"]["contenders"] == 5
    for given, says in ((({"radii": [[0.2, 8]]}), "keep the ring at 0.1"), ({"radii": [[0.1, 99]]}, "laws"),
                        ({"radii": [[1.5, 8], [0.1, 8]]}, "radius"), ({"contenders": 50}, "contenders"),
                        ({"confirm_share": 0.2}, "confirm"), ({"wild": 1}, "no such setting"), ({}, "send")):
        with pytest.raises(ValueError, match=says):
            focus.set_next(repo, given)


def test_the_next_law_takes_the_settings_and_they_are_said(monkeypatch):
    state = _state()
    state["current"] = None
    state["next_plan"] = focus.settled(state["plan"], {"radii": [[0.1, 2]]})
    monkeypatch.setattr(focus, "_spec_of", lambda repo, campaign, law: {})
    monkeypatch.setattr(focus, "verdict", lambda *a: "ring")
    monkeypatch.setattr(focus, "label", lambda repo, campaign, law: "C6-G1015")
    monkeypatch.setattr(focus, "_insert", lambda repo, campaign, spec: "x")
    monkeypatch.setattr(focus, "neighbours", lambda state, law, spec, radii: ([], []))
    monkeypatch.setattr(focus, "contenders", lambda repo, state, ranked=None: [])
    current = focus.start_next(None, state, chosen={"candidate_id": "e" * 64, "campaign": "6", "score": 19})
    assert current["radii"] == [[0.1, 2]] and "next_plan" not in state
    assert state["events"][0]["settings"]["radii"] == [[0.1, 2]]


def test_an_action_the_focus_does_not_know_is_refused_by_name():
    with pytest.raises(ValueError, match="do must be one of start, law, skip, back, stop, settings, split"):
        focus.act(_Flags(_state()), {"do": "explode"})


def test_a_mapped_law_gets_its_region_from_the_laws_that_read_its_kind(monkeypatch):
    specs = {("1", "c" * 64): _law(1.0), ("12", "n1"): _law(1.1), ("12", "n2"): _law(1.3), ("12", "n3"): _law(-3.0)}
    monkeypatch.setattr(focus, "_spec_of", lambda repo, campaign, law: deepcopy(specs.get((campaign, law), {})))
    state = _state()
    current = dict(state["current"], stage=focus.MAPPED, alike_to=0.2, read={"n1": "ring", "n2": "ring", "n3": "full"},
                   points={"n1": {"how": "neighbour", "radius": 0.1}, "n2": {"how": "line", "at": 0.5},
                           "n3": {"how": "neighbour", "radius": 0.2}})
    state["current"] = current
    focus._finish(None, state, current)
    assert state["done"][-1]["region"] == "GG#1" and state["current"] is None
    assert state["regions"][0]["ranges"]["coupling degree_cube_sum"] == [1.0, 1.3]
    assert state["regions"][0]["members"] == 3, "the law and the two of its kind, not the one of another"


def test_the_command_says_the_regions_and_a_stopped_focus():
    state = _state()
    state["stopped"] = True
    R.place(state, {"law": "d" * 64, "label": "C2-G64", "kind": "ring"}, [_law(1.0), _law(1.2)])
    text = focus.words(focus.reading_of(state))
    assert "stopped: its three campaigns are paused" in text
    assert "GG#1 (ring): from C2-G64, 2 laws read its kind; coupling degree_cube_sum 1 to 1.2" in text


def test_the_study_s_best_laws_are_ordered_by_score_then_campaign_and_graph_number(monkeypatch):
    from graph_scale_dynamics.observability import score_board
    boards = {"2": {"scores": {"b" * 64: {"score": 19}, "z" * 64: {"score": 0}}},
              "10": {"scores": {"a" * 64: {"score": 19}}}, "1": {"scores": {"c" * 64: {"score": 18}, "d" * 64: {"score": 19}}}}
    graphs = {("2", "b" * 64): 64, ("10", "a" * 64): 5, ("1", "c" * 64): 7363, ("1", "d" * 64): 6940}
    monkeypatch.setattr(focus, "own_campaigns", lambda repo, study: ["2", "10", "1"])
    monkeypatch.setattr(score_board, "board", lambda repo, campaign: boards[campaign])
    monkeypatch.setattr(focus, "graph_number", lambda repo, campaign, law: graphs.get((campaign, law)))
    ranked = focus.best(None, "174")
    assert [e["label"] for e in ranked] == ["C1-G6940", "C2-G64", "C10-G5", "C1-G7363"]
