from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("holds_reading", ROOT / "tools" / "holds_reading.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def law(cls, at_n, decision, **fates):
    return {"class": cls, "at_n": at_n, "decision": decision,
            "fates": {"cubic": "melted", "honeycomb": "melted", "tesseract": "melted", **fates}}


THEN = {"a" * 64: law("selects", 4096, ["run_next", "longer_chain", 4096], tesseract="holds"),
        "b" * 64: law("selects", 4096, ["run_next", "starts_shape", 4096], honeycomb="holds"),
        "c" * 64: law("holds", 16384, ["run_next", "longer_chain", 16384], cubic="holds", tesseract="holds"),
        "d" * 64: law("forgets", 4096, ["run_next", "longer_chain", 4096]),
        "e" * 64: law("selects", 4096, ["run_next", "longer_chain", 4096], tesseract="holds")}
NOW = {"a" * 64: law("remembers", 4096, ["stop", "disconnected", 4096], tesseract="partly"),
       "b" * 64: law("remembers", 16384, ["run_next", "longer_chain", 16384]),
       "c" * 64: law("holds", 16384, ["stop", "empty", 16384], tesseract="holds"),
       "d" * 64: law("grows", 4096, ["run_next", "starts_shape", 4096], honeycomb="holds"),
       "e" * 64: law("selects", 4096, ["run_next", "longer_chain", 4096], tesseract="holds"),
       "f" * 64: law("selects", 1024, ["run_next", "base_block", 1024], cubic="holds")}


def test_each_hold_lost_or_gained_is_read_with_where():
    s = H.step(THEN, NOW)
    assert s["holders"] == [4, 4]
    assert {(x["law"][0], x["where"]) for x in s["lost"]} == {("a", "on a longer chain at the same size"),
                                                              ("b", "at the next size")}
    assert {(x["law"][0], x["where"]) for x in s["gained"]} == {("d", "on a longer chain at the same size"),
                                                                ("f", "read for the first time")}
    finished = s["longer_chains_finished"]
    assert (finished["holders_kept"], finished["holders_lost"]) == (["c" * 12], ["a" * 12])
    assert (finished["others_came_to_hold"], finished["others_did_not"]) == (["d" * 12], 0)
    assert s["holders_waiting_on_a_longer_chain"] == 1, "e is still waiting"


def test_the_criterion_is_judged_only_once_enough_have_finished():
    criterion = {"contract": "c", "judged_when": {"finished_at_least": 2},
                 "waiting": [{"law": k, "decision": THEN[k]["decision"],
                              "held": sorted(x for x, f in THEN[k]["fates"].items() if f == "holds")}
                             for k in ("a" * 64, "c" * 64, "e" * 64)],
                 "predictions": [{"id": "L1", "claim": "", "rule": {"lattice": None, "kept_share_below": 0.5}},
                                 {"id": "L2", "claim": "", "rule": {"lattice": "tesseract",
                                                                    "kept_share_at_most": 0.3334}}]}
    judged = H.judge(criterion, NOW, "hand")
    assert (judged["finished"], judged["judged"]) == (2, True)
    assert [(p["finished"], p["kept"], p["share"], p["verdict"]) for p in judged["predictions"]] == [
        (2, 1, 0.5, "missed"), (2, 1, 0.5, "missed")]
    waiting = H.judge(dict(criterion, judged_when={"finished_at_least": 3}), NOW, "hand")
    assert all(p["verdict"].startswith("reported, not judged") for p in waiting["predictions"])
    assert "| `aaaaaaaaaaaa` | tesseract | yes | none |" in H.render_judgement(judged)
