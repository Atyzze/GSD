from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pilot_difference", ROOT / "tools" / "pilot_difference.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

A, B, C, CONTROL = "a" * 64, "b" * 64, "c" * 64, "f" * 64


def _law(law, campaign="1", rule="empty", action="stop", at_n=256, top_n=256):
    return {"campaign_id": campaign, "candidate_id": law, "state": "STOPPED", "top_n": top_n,
            "decision": {"action": action, "rule": rule, "at_n": at_n, "next_n": None, "reason": "words"}}


def _rung(law, n, campaign="1", **values):
    return {"campaign_id": campaign, "candidate_id": law, "n": n, "seeds": 3, "mean_degree": 4.0125,
            "connected_fraction": 1.0, "d_s": None, "d_V": None, "d_B": None, "d_w": None} | values


def _bundle(folder: Path, laws: list, rungs: list, build=769, decisions=()) -> Path:
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({
        "study_id": "169", "build_number": build, "built_utc": "2026-11-14T08:00:00Z",
        "campaigns": [{"campaign_id": "1", "law_budget": 60, "study_design": {"campaign": 0}},
                      {"campaign_id": "6", "law_budget": None}]}))
    for name, rows in (("laws", laws), ("rungs", rungs), ("decisions", decisions)):
        with gzip.open(folder / "tables" / f"{name}.ndjson.gz", "wt", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row) + "\n" for row in rows))
    return folder


def _laws():
    return ([_law(A), _law(B, rule="starts_alike", at_n=4096, top_n=4096), _law(CONTROL, campaign="6")],
            [_rung(A, 64), _rung(A, 256), _rung(B, 4096, d_s=2.0123456789012), _rung(CONTROL, 64, campaign="6")])


def test_a_record_holds_the_blind_laws_and_no_control(tmp_path):
    record = P.record_of(_bundle(tmp_path / "run", *_laws()))
    assert record["contract"] == P.RECORD and (record["study"], record["build_number"]) == ("169", 769)
    assert set(record["laws"]) == {A, B} and record["laws"][B]["rule"] == "starts_alike"
    assert record["laws"][B]["rungs"]["4096"]["d_s"] == 2.01234568 and record["laws"][A]["batch"] == 0


def test_the_same_laws_grown_again_differ_on_nothing(tmp_path):
    laws, rungs = _laws()
    again = [dict(row, d_s=row["d_s"] + 1e-12) if row["d_s"] else row for row in rungs]
    found = P.difference(P.record_of(_bundle(tmp_path / "before", laws, rungs)),
                         P.record_of(_bundle(tmp_path / "after", laws, again, build=770)))
    assert found["checks"] == {"R1": True, "R2": True, "R3": True} and found["moved"] == []
    assert "No law moved." in P.markdown(found) and "build 770" in P.markdown(found)


def test_a_decision_a_depth_and_a_reading_that_moved_are_named_by_law_with_both_values(tmp_path):
    laws, rungs = _laws()
    later = [_law(A, rule="too_dense"), laws[1], laws[2]]
    moved = [rungs[0], rungs[1], dict(rungs[2], d_s=2.0125), rungs[3]]
    found = P.difference(P.record_of(_bundle(tmp_path / "before", laws, rungs)),
                         P.record_of(_bundle(tmp_path / "after", later, moved, build=770)))
    assert found["checks"] == {"R1": True, "R2": False, "R3": False}
    by_law = {row["law"]: row for row in found["moved"]}
    assert by_law[A]["decision"] == [["stop", "empty", 256], ["stop", "too_dense", 256]]
    assert by_law[B]["readings"] == [[4096, "d_s", 2.01234568, 2.0125]]
    text = P.markdown(found)
    assert "decision stop by empty at 256 -> stop by too_dense at 256" in text and "`bbbbbbbbbbbb`" in text


def test_a_law_a_seed_of_which_ended_at_its_budget_is_judged_and_one_named_before_the_run_is_not(tmp_path):
    laws, rungs = _laws()
    later = [_law(A, rule="too_dense"), _law(B, rule="starts_apart_twice", at_n=4096, top_n=4096), laws[2]]
    ended = [{"candidate_id": A, "at_n": 256, "facts_json": json.dumps({"budget_ended": {"seeds": [1], "of": 3,
                                                                                      "at_n": 256}})},
             {"candidate_id": B, "at_n": 4096, "facts_json": json.dumps({"rungs": 3})}]
    before = P.record_of(_bundle(tmp_path / "before", laws, rungs))
    after = P.record_of(_bundle(tmp_path / "after", later, rungs, build=770, decisions=ended))
    declared = P.difference(before, after, declared=["bbbbbbbbbbbb"])
    assert declared["checks"]["R2"] is False, "no clock ends a seed, so a seed at its budget excuses nothing"
    assert declared["counts"] == {"moved": 2, "by_a_lane": 0, "declared": 1, "decision_or_depth": 1,
                                  "readings_only": 0}
    assert "no: named before" in P.markdown(declared) and "no: a window" not in P.markdown(declared)


def test_a_law_missing_from_the_run_fails_and_a_larger_budget_is_said_for_what_it_is(tmp_path):
    laws, rungs = _laws()
    before = P.record_of(_bundle(tmp_path / "before", laws, rungs))
    fewer = P.difference(before, P.record_of(_bundle(tmp_path / "fewer", laws[1:], rungs[2:], build=770)))
    assert fewer["checks"]["R1"] is False and fewer["only_in_the_record"] == [A]
    more = P.difference(before, P.record_of(_bundle(tmp_path / "more", laws + [_law(C)], rungs + [_rung(C, 64)])))
    assert more["only_in_the_run"] == 1 and more["laws_in_both"] == 2 and more["only_in_the_run_laws"] == [C]
    assert more["checks"] == {"R1": True, "R2": True, "R3": True}, (
        "R1 judges the record's laws alone: a law a larger budget drew is no failure")
    assert "not judged: a larger budget draws laws the record never held" in P.markdown(more)


def test_a_law_a_busier_deep_lane_held_is_listed_and_not_judged(tmp_path):
    laws, rungs = _laws()
    before = P.record_of(_bundle(tmp_path / "before", laws, rungs))
    held = [laws[0], _law(B, rule="deep_lane_full", action="hold", at_n=4096, top_n=4096), laws[2]]
    resumed = [laws[0], _law(B, rule="lane_resumed", action="run_next", at_n=4096, top_n=16384), laws[2]]
    for name, later in (("held", held), ("resumed", resumed)):
        found = P.difference(before, P.record_of(_bundle(tmp_path / name, later, rungs, build=771)))
        assert found["checks"] == {"R1": True, "R2": True, "R3": True}, name
        assert found["counts"]["by_a_lane"] == 1 and found["moved"][0]["lane"], name
        assert "no: a lane" in P.markdown(found), name
    moved = [laws[0], _law(B, rule="starts_apart_twice", at_n=4096, top_n=4096), laws[2]]
    assert P.difference(before, P.record_of(_bundle(tmp_path / "moved", moved, rungs, build=771)))["checks"]["R2"] is False


def test_the_command_writes_a_record_and_reads_a_run_against_it(tmp_path, capsys):
    laws, rungs = _laws()
    run = _bundle(tmp_path / "run", laws, rungs)
    kept = tmp_path / "record.json"
    assert P.main([str(run), "--record", str(kept)]) == 0 and P.load(kept)["laws"].keys() == {A, B}
    out = tmp_path / "difference.md"
    assert P.main([str(run), "--against", str(kept), "--md", str(out), "--json", str(tmp_path / "d.json")]) == 0
    assert "R1, every law of the record is in the run: passes" in out.read_text() and "No law moved." in capsys.readouterr().out
    assert json.loads((tmp_path / "d.json").read_text())["contract"] == P.CONTRACT
    with pytest.raises(ValueError):
        P.load(ROOT / "tests" / "fixtures" / "a_design.json")


def test_a_design_that_fixes_its_seeds_grows_the_same_laws_in_every_folder():
    from graph_scale_dynamics.operations import study_design as SD
    one = designs.a_design()
    seeds = [one["search_seeds"][0] + index for index in range(5)]
    fixed = dict(one, search_seeds=seeds, campaigns=[one["campaigns"][0]] * 5)
    assert [SD.seed_of(fixed, index) for index in range(5)] == seeds
    assert SD.seed_of(fixed, 2, search_seed=seeds[0]) == seeds[2]
    with pytest.raises(ValueError):
        SD.seed_of(fixed, 0, search_seed=7)
    with pytest.raises(ValueError):
        SD.seed_of(dict(fixed, search_seeds=seeds[:2]), 0)
    drawn = dict(fixed, search_seeds=None)
    assert SD.seed_of(drawn, 0) is None and SD.seed_of(drawn, 3, search_seed=10) == 13
    assert not (ROOT / "graph_scale_dynamics" / "resources" / "readings" / "pilot_reference_record.json").exists(), (
        "no pilot record from another study is in the tree since 785: a run is read against another bundle")
