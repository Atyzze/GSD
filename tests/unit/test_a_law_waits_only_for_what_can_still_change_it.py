from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy

ROOT = Path(__file__).resolve().parents[2]
RULE = Policy(let_through_rule=G.LET_THROUGH_RULE, let_through_from=256, known_result_after=100)


def _design(study: str) -> Policy:
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, study)
    spec = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                            design["campaigns"][0], 0)
    return Policy.from_spec(spec)


def _laws(count: int, verdict_past: int) -> list:
    return [{"campaign_id": "1", "candidate_id": f"l{i}", "number": i + 1, "campaign_order": 0, "ended": False,
             "verdict_past": verdict_past} for i in range(count)]


def test_a_design_whose_every_share_is_its_own_learns_nothing_so_no_law_waits():
    pilot = _design("173")
    assert LT.learned_gates(pilot) == [] and not LT.known_results_learned(pilot)
    assert not any(LT.learns(pilot, n) for n in (64, 256, 1024, 4096, 16384, 65536))
    points = LT.FixedPoints().refresh(_laws(400, 1024), pilot, own="1")
    assert points.determined(3, 4096, pilot, lambda keys: []) is not None, (
        "300 earlier laws undecided at 4,096 change nothing a fixed share decides: 841 made this law wait")


def test_a_design_with_a_learned_share_still_waits_as_834_made_it():
    baseline = _design("172")
    assert LT.learned_gates(baseline) == ["disconnected", "empty", "too_dense"]
    assert not LT.learns(baseline, 64) and LT.learns(baseline, 256) and LT.learns(baseline, 65536)
    points = LT.FixedPoints().refresh(_laws(400, 1024), baseline, own="1")
    assert points.determined(3, 4096, baseline, lambda keys: []) is None
    settled = _laws(400, 1024)
    for law in settled[:250]:
        law["verdict_past"] = 16384
    assert LT.FixedPoints().refresh(settled, baseline, own="1").determined(3, 4096, baseline, lambda keys: []) == {
        "undecided": 50, "let_through_most": 0}


def test_the_known_result_learns_its_list_unless_it_only_records():
    assert LT.known_results_learned(RULE) and LT.learns(RULE, 256)
    fixed = replace(RULE, gate_shares=tuple((gate, 1.0) for gate in sorted(G.LET_THROUGH_GATES)))
    assert LT.learned_gates(fixed) == [] and not LT.known_results_learned(fixed) and not LT.learns(fixed, 4096)
    acting = replace(fixed, gate_shares=tuple((gate, 0.1 if gate == LT.KNOWN_RESULT else 1.0)
                                              for gate in sorted(G.LET_THROUGH_GATES)))
    assert LT.learned_gates(acting) == [] and LT.known_results_learned(acting), (
        "a known result acting at a fixed share still learns which results are known")
    size = int(acting.known_result_size())
    assert not LT.learns(acting, size // 4) and LT.learns(acting, size)
    assert not LT.known_results_learned(replace(RULE, known_result_after=0))
    assert LT.learned_gates(replace(RULE, ab_share=0.5)) == [], "an A/B arm's share is fixed"
