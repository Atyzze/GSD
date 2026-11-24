from __future__ import annotations

from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy, let_through_text
from graph_scale_dynamics.decisions.gates import LET_THROUGH_RULE


def _policy(**more):
    spec = {"engine": {"policy": dict({"let_through_rule": LET_THROUGH_RULE, "let_through_from": 256,
                                       "ab_share": 0.5}, **more)}}
    return Policy.from_spec(spec)


LAWS = [f"{i:064x}" for i in range(400)]


def test_a_gate_with_its_own_share_keeps_it_and_the_rest_stay_at_half():
    policy = _policy(gate_shares=[["starts_alike", 0.0], ["nothing_read", 1.0]])
    for n in (256, 4096, 65536):
        assert not any(policy.let_through(law, "starts_alike", n) for law in LAWS)
        assert all(policy.let_through(law, "nothing_read", n) for law in LAWS)
        through = sum(policy.let_through(law, "too_dense", n) for law in LAWS)
        assert 150 < through < 250
    assert policy.live_share("starts_alike", 64) == 1.0


def test_without_its_own_share_every_gate_is_where_it_was():
    plain, shared = _policy(), _policy(gate_shares=[["starts_alike", 0.0]])
    assert plain.gate_shares == ()
    for gate in ("too_dense", "disconnected", "nothing_read", "empty"):
        for n in (256, 4096):
            assert [plain.let_through(law, gate, n) for law in LAWS] == \
                   [shared.let_through(law, gate, n) for law in LAWS]


def test_the_ledger_and_the_reason_say_what_the_design_set():
    policy = _policy(gate_shares=[["starts_alike", 0.0], ["nothing_read", 1.0]])
    ledger = LT.Ledger()
    assert ledger.share("starts_alike", 4096, policy) == 0.0
    assert ledger.share("nothing_read", 4096, policy) == 1.0
    assert ledger.share("too_dense", 4096, policy) == 0.5
    assert "the study's design records this gate" in let_through_text("nothing_read", 1.0, policy)
    assert "below N=256" in let_through_text("nothing_read", 1.0, _policy())


def test_a_design_draws_laws_free_of_n_from_a_pool_without_the_curvature_term():
    from pathlib import Path

    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from tests.support.proposer_repo import ProposerRepo, top_up_blind
    from tests.support import designs
    design = designs.a_design()
    base = SD.without_terms(design, shipped_spec(), log=lambda line: None)
    spec = SD.campaign_spec(design, base, design["campaigns"][0], 0)
    policy = Policy.from_spec(spec)
    assert design["law_budget"] == 1000
    assert "ollivier_curvature" not in spec["operator_whitelist"] and len(spec["operator_whitelist"]) == 13
    grid = spec["search_policy"]["grid"]
    assert grid["scales"] == ["one"] and (grid["magnitudes"]["min"], grid["magnitudes"]["max"]) == (0.005, 20.0)
    assert [policy.work_budget(n) for n in policy.ladder()] == [units for _, units in design["ladder"]["budgets"]]
    assert policy.own_share("starts_alike") == 0.0 and policy.own_share("nothing_read") is None
    assert policy.live_share("nothing_read", 4096) == 0.1 and policy.own_share("no_steady_chain") == 0.5
    repo = ProposerRepo()
    repo.campaign = lambda cid: {"campaign_id": cid, "spec": spec}
    repo.record_campaign_event = lambda *args: None
    top_up_blind(repo, spec, 60, search_seed=int(design["search_seeds"][0]))
    terms = [term for _cid, law in repo.laws for term in law["terms"]]
    assert len(repo.laws) == 60, "every law drawn runs"
    assert {term["coeff"]["scale"] for term in terms} == {"one"}, "no coefficient knows the size of the graph"
    assert all(0.005 <= abs(term["coeff"]["c0"]) <= 20.0 for term in terms)
