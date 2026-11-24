from __future__ import annotations

import json

from tools import base_block_reading as B

NOTHING = [None] * 4


def _row(n, probes=NOTHING):
    return [n, *probes, None, 1.0, 0.5, 0.0, 0.0, 0.0]


def _law(rows_by_chain, cls="remembers"):
    return {"values": rows_by_chain, "starts_reading": {"class": cls}}


def _report(laws, seeds, decided):
    return {"body": {"every_chain": {"laws": laws}, "laws": decided,
                     "seeds": {"columns": ["law", "n", "simulation_seconds", "d_s_seconds", "d_V_seconds"],
                               "laws": sorted({row[0] for row in seeds}), "rows": seeds}}}


def _bundle(tmp_path, reports: dict, controls=()):
    root = tmp_path / "study"
    campaigns = []
    for name, report in reports.items():
        folder = root / f"{name}_reports_x"
        folder.mkdir(parents=True)
        (folder / "28-decision-engine.json").write_text(json.dumps(report), encoding="utf-8")
        campaigns.append({"bundle": folder.name, **({"controls": {}} if name in controls else {})})
    (root / "study.json").write_text(json.dumps({"campaigns": campaigns}), encoding="utf-8")
    return root


def test_a_law_read_nowhere_on_the_base_block_is_counted_and_its_deep_cost_and_reads_said(tmp_path):
    silent = _law({"empty": [_row(n) for n in (64, 256, 1024, 4096, 16384)],
                   "cubic": [_row(n) for n in (1024, 4096)] + [_row(16384, [3.0, None, None, None])]})
    small = _law({"empty": [_row(64, [1.0, None, None, None])] + [_row(n) for n in (256, 1024, 4096)]})
    read = _law({"given": [_row(4096, [2.0, 2.1, None, None])]})
    shallow = _law({"empty": [_row(64), _row(256), _row(1024)]})
    seeds = [["a", 16384, 100.0, 5.0, 5.0], ["a", 4096, 999.0, 1.0, 1.0], ["c", 16384, 40.0, 0.0, 0.0]]
    decided = [{"candidate_id": "a", "rule": "starts_apart_twice", "action": "stop", "at_n": 16384}]
    pilot = _report({"a": silent, "b": small, "c": read, "d": shallow}, seeds, decided)
    controls = _report({"z": silent}, [["z", 16384, 1e6, 0.0, 0.0]], [])
    found = B.read_bundle(_bundle(tmp_path, {"campaign_1": pilot, "campaign_6": controls}, controls={"campaign_6"}))
    total = found["total"]
    assert (total["laws_read_from_1024"], total["laws_with_4096"]) == (4, 3), "the controls are left out"
    assert total["nothing_on_the_base_block"] == 1 and total["nothing_at_1024_and_4096"] == 2
    assert total["only_at_64_or_256"] == 1, "a reading at 64 or 256 is said apart: none is relied on there"
    assert total["reached_16384"] == 1 and total["deep_seconds"] == 150.0
    [case] = found["cases"]
    assert case["law"] == "a" and case["deep_seconds"] == 110.0 and case["rule"] == "starts_apart_twice"
    assert case["deep_reads"] == {"cubic": [[16384, "d_s"]]} or case["deep_reads"] == {"cubic": [(16384, "d_s")]}
    assert found["deep_reads_after_nothing"] == 1 and case["class"] == "remembers"


def test_the_gate_s_parks_and_let_throughs_and_the_laws_a_budget_ended_are_counted(tmp_path):
    silent = _law({"empty": [_row(n) for n in (64, 256, 1024, 4096)]})
    decided = [{"candidate_id": "a", "rule": "nothing_read", "action": "stop", "at_n": 4096},
               {"candidate_id": "b", "rule": "starts_apart", "action": "run_next", "at_n": 4096,
                "budget_ended_at": [1024]}]
    report = _report({"a": silent, "b": silent}, [], decided)
    report["body"]["gate_tree"] = {"gates": [{"gate": "nothing_read", "withheld": 1, "salted_past": 1,
                                              "salt_spent": 0}]}
    found = B.read_bundle(_bundle(tmp_path, {"campaign_1": report}))
    gate = found["campaigns"]["campaign_1"]["the_gate"]
    assert gate["parked"] == 1 and gate["parked_laws"] == ["a"]
    assert gate["tree"] == {"withheld": 1, "salted_past": 1, "salt_spent": 0}
    assert found["total"]["parked_by_the_gate"] == 1 and found["total"]["laws_ended_at_a_budget"] == 1
