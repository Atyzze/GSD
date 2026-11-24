from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import study_172_reading as SR  # noqa: E402
from graph_scale_dynamics.decisions import gates as G  # noqa: E402

LAWS = [f"{i:064x}" for i in range(400)]


def _table(folder: Path, name: str, rows: list) -> None:
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / "tables" / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _decision(law, action, rule, n=1024, number=0):
    return {"campaign_id": "1", "candidate_id": law, "decision_id": f"{number:020d}", "at_n": n, "action": action,
            "rule": rule, "inputs_json": json.dumps({"policy": {"one_die": True}})}


def test_with_one_die_a_law_goes_on_at_one_pick_whichever_gates_hold_it(monkeypatch):
    held = {law: (["empty", "disconnected"] if i % 2 else ["too_dense"]) for i, law in enumerate(LAWS)}
    monkeypatch.setattr(SR, "held_by", lambda row: held[row["candidate_id"]])
    monkeypatch.setattr(SR, "shares_met", lambda row: {gate: 0.1 for gate in SR.FACTS})
    latest = {}
    for i, law in enumerate(LAWS):
        on = G.die(law, None, 1024) < 0.1
        latest[("1", law, 1024)] = _decision(law, "run_next" if on else "stop", "base_block" if on else held[law][0])
    found = SR.one_die(Path("."), latest)
    assert found["one_die"] and found["against_the_pick"] == 0
    assert sum(found["held"].values()) == 400 and 0.05 < found["share_one_or_more"] < 0.16
    wrong = next(law for law in LAWS if G.die(law, None, 1024) >= 0.1)
    latest[("1", wrong, 1024)] = _decision(wrong, "run_next", "base_block")
    assert SR.one_die(Path("."), latest)["against_the_pick_laws"] == [wrong], "a law past its pick is named"


def _bundle(tmp_path: Path, *, stopped: int, over: int, hours: float) -> Path:
    root = tmp_path / "study_172_x"
    part = root / "campaign_1_reports_x"
    (part / "evidence").mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"study_id": "172", "campaigns": [
        {"campaign_id": "1", "study_design": {"study": "172"}}, {"campaign_id": "2", "name": "controls"}]}))
    decisions = [_decision(law, "stop", "empty", number=i) if i < stopped else _decision(law, "run_next", "base_block",
                                                                                          number=i)
                 for i, law in enumerate(LAWS[:100])]
    decisions += [_decision(law, "stop", "over_budget", n=4096, number=1000 + i) for i, law in enumerate(LAWS[:over])]
    decisions.append(dict(_decision(LAWS[0], "stop", "empty", number=5000), campaign_id="2"))
    _table(root, "decisions.ndjson.gz", decisions)
    _table(root, "laws.ndjson.gz", [{"campaign_id": "1", "candidate_id": law, "regime": "zero_temperature",
                                     "decision": {"action": "done", "rule": "ladder_complete"}} for law in LAWS[:100]])
    (root / "gates_ledger.json").write_text(json.dumps({"gates": {
        "empty": {"1024": {"held": stopped}}, "starts_alike": {"4096": {"held": 0}}}}))
    (part / "evidence" / "system.json").write_text(json.dumps({"rung_distribution": [
        {"n": 1024, "rung_seconds_total": hours * 3600 / 2}, {"n": 65536, "rung_seconds_total": hours * 3600 / 2}]}))
    (part / "23-hang-autopsy.json").write_text(json.dumps({"body": {"ranked": [
        {"candidate_id": LAWS[1], "rungs": [{"classification": "OPERATIONAL_UNRESOLVED", "worst_reason": "budget"}]}]}}))
    return root


def test_each_item_is_judged_on_the_criterion_s_own_range(tmp_path, monkeypatch):
    from tools import counters_reading
    monkeypatch.setattr(counters_reading, "read", lambda root: {
        "C1_replays": True, "C2_per_batch_reproduced": True, "replay": {"counts": {"replays": 101}},
        "learned_decisions": 60, "per_batch_differ_count": 0})
    monkeypatch.setattr(SR, "held_by", lambda row: [])
    found = SR.read(_bundle(tmp_path, stopped=60, over=3, hours=900.0))
    items = found["items"]
    assert found["its_own"] and found["campaigns"] == ["1"], "the controls are not the study's laws"
    assert items["R5"]["holds"] and items["R5"]["read"] == {"stopped_by_the_three": 60, "decided_at_1024": 100}
    assert items["R6"]["holds"] and items["R6"]["read"]["over_budget_before_65536"] == 3
    assert items["R7"]["holds"] and items["R7"]["read"]["total"] == 900.0
    assert items["R1"]["holds"] and items["R2"]["holds"] and items["R3"]["holds"]
    assert items["R4"]["holds"] is None, "no law held back, nothing to read"
    worse = SR.read(_bundle(tmp_path / "b", stopped=80, over=5, hours=400.0))["items"]
    assert (worse["R5"]["holds"], worse["R6"]["holds"], worse["R7"]["holds"]) == (False, False, False)
    assert "R5 fails: the three stopped 80 of 100 (80.0%)" in SR.render(SR.read(_bundle(tmp_path / "c", stopped=80,
                                                                                         over=5, hours=400.0)))
