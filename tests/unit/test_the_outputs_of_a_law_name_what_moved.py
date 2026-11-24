from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import outputs_of_a_law as O  # noqa: E402


def test_a_changed_number_a_lost_key_and_a_new_key_are_each_named():
    before = {"empty": {"given_ended": "cap", "d": 2.0}, "chains": {"given:cubic": [1, 2]},
              "detail": "the chain from empty and the given chain disagree", "kept": ["empty", "given"]}
    assert O.changed(before, json.loads(json.dumps(before))) == []
    moved = json.loads(json.dumps(before))
    moved["empty"]["d"] = 2.5
    del moved["chains"]["given:cubic"]
    moved["chains"]["given:fcc"] = [1]
    moved["kept"] = ["given", "empty"]
    found = {at: what for at, *what in O.changed(before, moved)}
    assert found == {"/empty/d": [2.0, 2.5], "/chains/given:cubic": ["gone"], "/chains/given:fcc": ["new"],
                     "/kept[0]": ["empty", "given"], "/kept[1]": ["given", "empty"]}
    assert O.changed({"a": 1}, {"a": 1.0}) == [("/a", 1, 1.0)], "an integer that became a float is a change"
    assert O.changed({"a": [1]}, {"a": [1, 2]}) == [("/a", "1 items, now 2")]
    assert O.changed({"text": "the same words"}, {"text": "other words"}) == [("/text", "the same words", "other words")]


def test_the_outputs_leave_out_the_clock_and_fold_what_is_long():
    made = O.plain({"wall_seconds": 3.2, "kept": 1, "inner": {"chain_seconds": {"empty": 1.0}, "n": 4},
                    "long": list(range(100)), "points": [{"i": i, "probe_seconds": 0.1} for i in range(60)],
                    "data": "A" * 1000, "said": "word " * 200, "few": [1, 2, 3]})
    assert made["kept"] == 1 and made["inner"] == {"n": 4} and "wall_seconds" not in made
    assert made["long"]["items"] == 100 and len(made["long"]["sha256"]) == 64 and "first" not in made["long"]
    assert made["points"]["first"] == {"i": 0} and made["points"]["last"] == {"i": 59}
    assert made["data"] == {"sha256": made["data"]["sha256"], "characters": 1000}
    assert made["said"] == "word " * 200 and made["few"] == [1, 2, 3], "a sentence is kept to be read"
    assert O.plain({"long": list(range(99)) + [100]})["long"]["sha256"] != made["long"]["sha256"]


def test_the_door_translates_nothing_since_the_engines_speak_today_s_names():
    import inspect

    from graph_scale_dynamics.engine import engine
    assert engine_door.run_simulation is engine.run_simulation
    taken = set(inspect.signature(engine.run_simulation).parameters)
    assert {"given_start", "more_given"} <= taken and "given_capped_alone" not in taken, (
        "every chain ends alone at the cap since 781, so no run is told so")
    assert not hasattr(engine_door, "from_engine") and not hasattr(engine_door, "KEYS")
