from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy

ROOT = Path(__file__).resolve().parents[2]
FACTS = {"empty", "too_dense", "disconnected"}
LAWS = [f"{i:064x}" for i in range(300)]


def _policy(study: str = "171"):
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, study)
    assert design is not None and len(design["campaigns"]) == 1
    assert design["law_budget"] == {"171": 1000, "172": 2500}[study]
    spec = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                            design["campaigns"][0], 0)
    return Policy.from_spec(spec)


def test_only_the_three_fact_gates_hold_a_law_back_in_study_171():
    policy = _policy()
    acting = {gate for gate in G.LET_THROUGH_GATES
              for n in policy.ladder() if policy.live_share(gate, n) < 1.0}
    assert acting == FACTS, "only empty, dense, disconnected and the budget"
    for gate in sorted(G.LET_THROUGH_GATES - FACTS):
        for n in (256, 4096, 65536):
            assert all(policy.let_through(law, gate, n) for law in LAWS), (gate, n)
            assert LT.Ledger().share(gate, n, policy) == 1.0
    for gate in sorted(FACTS):
        assert policy.live_share(gate, 64) == 1.0, "below 256 every verdict records and the law goes on"
        assert policy.live_share(gate, 256) == G.TESTING_SHARE


def test_study_171_s_fact_gates_read_three_sizes_in_a_row():
    assert _policy().fact_sizes_in_a_row == 3, "three sizes in a row (828)"


def test_study_171_s_budgets_are_four_times_170_s_at_4096_and_16384():
    budgets = dict(_policy().work_budgets)
    assert budgets == {64: 4e11, 256: 4e11, 1024: 4e11, 4096: 1.6e12, 16384: 8e12, 65536: 2.4e13}
    assert _policy().ladder()[-1] == 65536


def test_study_172_is_171_at_2500_laws_with_one_die_a_law_a_size():
    from dataclasses import replace
    from graph_scale_dynamics.decisions.engine import policy_fingerprint
    bigger, baseline = _policy("172"), _policy("171")
    assert bigger.one_die and not baseline.one_die, "one die a law a size in 172, asked as a choice"
    shares = tuple((G.today(gate), share) for gate, share in baseline.gate_shares)
    assert replace(bigger, one_die=False) == replace(baseline, gate_shares=tuple(sorted(shares))), (
        "every other field is 171's, the gate named as it is today")
    assert policy_fingerprint(bigger) != policy_fingerprint(baseline)
    assert bigger.own_share("repeats_a_known_result") == 1.0
    picks = {gate: [bigger.let_through(law, gate, 1024) for law in LAWS] for gate in sorted(FACTS)}
    assert picks["empty"] == picks["too_dense"] == picks["disconnected"], "one pick a law a size, read by every gate"
