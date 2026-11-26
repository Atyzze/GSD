from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gates_map  # noqa: E402


def test_the_committed_map_is_what_the_code_draws():
    model = gates_map.model()
    assert json.loads(gates_map.OUT_JSON.read_text(encoding="utf-8")) == json.loads(json.dumps(model)), (
        "the map is stale: python3 tools/gates_map.py draws it again")
    assert gates_map.OUT_SVG.read_text(encoding="utf-8") == gates_map.svg(model), (
        "the drawing is stale: python3 tools/gates_map.py draws it again")


def test_every_stop_and_hold_is_a_named_gate():
    model = gates_map.model()
    assert model["stops_that_are_not_gates"] == [], (
        "the engine stops or holds a law under a rule that is not in decisions/gates.GATES: "
        f"{model['stops_that_are_not_gates']}")
    stops = {s["rule"] for s in model["streams"] if s["action"] in ("stop", "hold")}
    named = {g["name"] for g in model["gates"]}
    assert named - stops == {"early_stage"}, "every gate but the early stage's label is a stop or a hold the engine writes"


def test_the_streams_are_declared_once_and_the_engine_writes_exactly_them():
    from graph_scale_dynamics.decisions import engine as E
    from graph_scale_dynamics.decisions import gates as G
    model = gates_map.model()
    assert model["written_but_not_declared"] == [] and model["declared_but_not_written"] == [], model
    assert len({(s.action, s.rule) for s in G.STREAMS}) == len(G.STREAMS) == 40
    for gate in G.GATES:
        stream = [s for s in G.STREAMS if s.rule == gate.name]
        assert (stream == [] if gate.action is None else stream == [G.Stream(gate.action, gate.name, gate.reads)])
    assert E.AUDIT_RULES == {"salted", "gate_audit", "plateau_follow"}


def test_the_map_reads_each_part_from_where_the_code_keeps_it():
    model = gates_map.model()
    assert [d["code"] for d in model["draw"]][:5] == ["no_terms", "over_budget", "duplicate_term", "no_sparse_phase",
                                                     "unbounded_below"], "validity_problem's order"
    assert {"salted", "gate_audit", "plateau_follow"} == {s["rule"] for s in model["streams"] if s["audit"]}
    keys = {(e["table"], e["refers_to"]) for e in model["evidence"]}
    assert {("measurements", "artifacts"), ("artifacts", "jobs"), ("jobs", "campaign_candidates")} <= keys
    assert model["salt"]["share"] == 0.10
