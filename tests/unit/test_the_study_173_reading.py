from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import counters_reading  # noqa: E402
import study_173_reading as SR  # noqa: E402

LAWS = [f"{i:064x}" for i in range(100)]
POLICY = {"let_through_from": 256, "gate_shares": [[gate, 0.1] for gate in SR.SIX] + [["cut", 1.0]], "cut_gate": True}


def _table(folder: Path, name: str, rows: list) -> None:
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / "tables" / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _seeds(cut: int) -> list:
    return [{"termination": "budget" if i < cut else "completed"} for i in range(3)]


def _decision(law, n, action, rule, number, *, next_n=None, rungs=(), facts=None, salted=()):
    inputs = {"policy": POLICY, "rungs": [{"n": m, "seeds": _seeds(k)} for m, k in rungs]}
    return {"campaign_id": "1", "candidate_id": law, "decision_id": f"{number:020d}", "at_n": n, "action": action,
            "rule": rule, "next_n": next_n, "inputs_json": json.dumps(inputs),
            "facts_json": json.dumps(dict(facts or {}, salted=list(salted)))}


def _bundle(tmp_path: Path, *, hours_top: float, record_cut: bool = True) -> Path:
    root = tmp_path / "study_173_x"
    part = root / "campaign_1_reports_x"
    (part / "evidence").mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"study_id": "173", "campaigns": [
        {"campaign_id": "1", "study_design": {"study": "173"}, "state": "done"}, {"campaign_id": "2"}]}))
    rows, number = [], 0
    for i, law in enumerate(LAWS):
        number += 1
        cut_here = i < 10
        facts = {"cut": {"at_n": 1024}} if cut_here and record_cut else {}
        if i < 56:
            rows.append(_decision(law, 1024, "stop", "empty", number, rungs=[(1024, 1 if cut_here else 0)]))
        else:
            rows.append(_decision(law, 1024, "run_next", "base_block", number, next_n=4096,
                                  rungs=[(1024, 1 if cut_here else 0)], facts=facts))
    for i, law in enumerate(LAWS[56:]):
        number += 1
        if i < 34:
            rows.append(_decision(law, 4096, "stop", "starts_alike", number, rungs=[(1024, 0), (4096, 0)]))
        elif i < 36:
            rows.append(_decision(law, 4096, "stop", "over_budget", number, rungs=[(1024, 0), (4096, 0)]))
        else:
            rows.append(_decision(law, 4096, "run_next", "starts_apart", number, next_n=16384,
                                  rungs=[(1024, 0), (4096, 1 if i == 43 else 0)],
                                  facts={"cut": {"at_n": 4096}} if i == 43 and record_cut else {},
                                  salted=["starts_alike"] if i == 40 else ()))
    rows.append(dict(_decision(LAWS[0], 1024, "stop", "empty", 9999), campaign_id="2"))
    _table(root, "decisions.ndjson.gz", rows)
    tops = {law: (4096 if i >= 56 else 1024) for i, law in enumerate(LAWS)}
    tops.update({law: 65536 for law in LAWS[92:]})
    _table(root, "laws.ndjson.gz", [{"campaign_id": "1", "candidate_id": law, "top_n": top} for law, top in tops.items()])
    (root / "gates_ledger.json").write_text(json.dumps({"gates": {
        "empty": {"1024": {"held": 56}}, "starts_alike": {"4096": {"held": 34}}, "cut": {"1024": {"held": 25, "label": "records only"}},
        "kept_shape": {"4096": {"held": 0, "priced": 3, "label": "records only"}}}}))
    (part / "evidence" / "system.json").write_text(json.dumps({"rung_distribution": [
        {"n": 1024, "rung_seconds_total": 90 * 3600}, {"n": 65536, "rung_seconds_total": hours_top * 3600}]}))
    return root


def _patched(monkeypatch, held: dict):
    monkeypatch.setattr(counters_reading, "read", lambda root: {
        "C1_replays": True, "C2_per_batch_reproduced": True, "replay": {"counts": {"replays": 145}},
        "learned_decisions": 0, "per_batch_differ_count": 0})
    monkeypatch.setattr(SR, "held_by", lambda row, gates=SR.SIX: held.get((row["candidate_id"], row["at_n"]))
                        if held.get((row["candidate_id"], row["at_n"])) in gates else None)
    monkeypatch.setattr(SR, "scorers", lambda root: {LAWS[1]: {"score": 7}, LAWS[60]: {"score": 3},
                                                     LAWS[96]: {"score": 12}})


def test_each_prediction_is_read_from_the_bundle_and_judged_on_its_range(tmp_path, monkeypatch):
    held = {(law, 1024): "empty" for law in LAWS[:62]}
    held.update({(law, 4096): "starts_alike" for law in LAWS[56:90] + LAWS[92:96] + LAWS[97:99]})
    _patched(monkeypatch, held)
    found = SR.read(_bundle(tmp_path, hours_top=60.0))
    items = found["items"]
    assert found["its_own"] and not found["progress"] and found["campaigns"] == ["1"]
    assert items["P1"]["holds"] and items["P2"]["holds"]
    assert items["P3"]["holds"] and items["P3"]["read"]["cut"] == {
        "buying_with_a_cut_seed": 1, "cut_recorded": 1, "missing": {}, "missing_count": 0}
    assert items["P3"]["read"]["recording_gates_priced"] == {"cut": 25, "kept_shape": 3}, (
        "841's ledger counted a budget stop against a gate that only records; 843's says priced")
    assert items["P4"]["read"]["by_size"]["1024"] == {"held": 62, "went_on": 6, "share": 6 / 62,
                                                      "by_gate": {"empty": 62}}
    assert items["P4"]["read"]["by_size"]["4096"]["went_on"] == 6, "34 stopped by the gate, 6 let on"
    assert items["P4"]["read"]["shares_at_the_last_decision"]["4096"]["nothing_read"] == 0.1
    assert items["P5"]["holds"] and items["P5"]["read"]["share"] == 0.56
    assert items["P6"]["read"] == {"decided": 44, "stopped": 34, "share": 34 / 44, "by_rule": {"starts_alike": 34}}
    assert items["P6"]["holds"]
    assert items["P7"]["read"]["reached"]["4096"] == 44 and items["P7"]["read"]["reached"]["65536"] == 8
    assert items["P8"]["read"]["over_budget_at_4096"] == 2 and items["P8"]["read"]["over_budget_before_65536"] == 2
    assert items["P9"]["read"]["followed_one_size_up"] == 0, "no cut law was decided a size up"
    assert items["P10"]["read"] == {"cut_laws": 11, "scoring_cut": 1, "scoring_rest": 2, "rest": 89,
                                    "ratio": (1 / 11) / (2 / 89)}
    assert items["P11"]["read"]["let_through_and_scoring"] == {}
    assert items["P12"]["holds"] and items["P12"]["read"]["total"] == 150.0
    assert "P5 holds: the fact gates stopped 56 of 100 (56.0%) at 1,024" in SR.render(found)


def test_a_missing_cut_verdict_a_lucky_scorer_and_a_top_heavy_cost_are_misses(tmp_path, monkeypatch):
    held = {(LAWS[96], 4096): "starts_alike"}
    _patched(monkeypatch, held)
    found = SR.read(_bundle(tmp_path, hours_top=200.0, record_cut=False))
    items = found["items"]
    assert items["P3"]["holds"] is False and items["P3"]["read"]["cut"]["missing_count"] == 1
    assert items["P12"]["holds"] is False, "290 core-hours, 69% at 65,536"
    monkeypatch.setattr(SR, "held_by", lambda row, gates=SR.SIX: "starts_alike"
                        if row["candidate_id"] in (LAWS[96], LAWS[60]) and "starts_alike" in gates else None)
    lucky = SR.read(_bundle(tmp_path / "b", hours_top=60.0))["items"]["P11"]
    assert lucky["read"]["let_through_and_scoring"] == {LAWS[96][:12]: {"score": 12, "gate": "starts_alike",
                                                                         "at_n": 4096}}
    assert lucky["holds"], "one let-through scorer is inside the range of at most one"
    other = SR.read(_bundle(tmp_path / "c", hours_top=60.0))
    assert "not 173's bundle" not in SR.render(other)
