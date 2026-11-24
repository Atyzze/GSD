from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy, policy_fingerprint

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
ACTING = {"empty", "too_dense", "disconnected", "starts_alike", "starts_apart_by_history", "nothing_read"}
LAWS = [f"{i:064x}" for i in range(4000)]


def _design(study: str) -> dict:
    return json.loads((READINGS / f"study_{study}_design.json").read_text(encoding="utf-8"))


def _policy(study: str = "173") -> Policy:
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, study)
    spec = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                            design["campaigns"][0], 0)
    return Policy.from_spec(spec)


def test_173_is_172_with_a_seed_of_its_own_and_the_841_rules():
    old, new = _design("172"), _design("173")
    same = ("contract", "question", "axes", "ladder", "law_budget", "starts", "limits", "starts_reading", "finds",
            "campaigns", "terms_left_out")
    assert {key: old[key] for key in same} == {key: new[key] for key in same}, "the grid, starts, ladder and budgets"
    assert new["study"] == "173" and len(new["search_seeds"]) == 1 and new["search_seeds"] != old["search_seeds"]
    assert 0 < new["search_seeds"][0] < 2 ** 63
    added = {key: value for key, value in new["engine"].items() if key not in old["engine"]}
    assert added == {"cut_gate": True, "nothing_read_piece_share": 0.9, "longer_chain_budget_scale": 2.0,
                     "ledger_counts_priced": True}
    assert {key: value for key, value in new["engine"].items() if key in old["engine"] and key != "gate_shares"} == {
        key: value for key, value in old["engine"].items() if key != "gate_shares"}
    assert "21:03" in new["decided"]["cut"] and "Record only" in new["decided"]["cut"]
    text = json.dumps(new, ensure_ascii=False)
    assert "—" not in text and "–" not in text


def test_six_gates_stop_a_law_a_tenth_let_through_past_each_at_every_size_and_the_rest_record():
    policy = _policy()
    for n in (256, 1024, 4096, 16384, 65536):
        acting = {gate for gate in G.LET_THROUGH_GATES if policy.live_share(gate, n) < 1.0}
        assert acting == ACTING, n
        for gate in ACTING:
            assert policy.live_share(gate, n) == LT.Ledger().share(gate, n, policy) == 0.1, (gate, n)
    confirmed = LT.Ledger()
    for i in range(150):
        confirmed.feed({"campaign_id": "1", "candidate_id": f"l{i}", "decision_id": f"{2 * i:020d}", "at_n": 4096,
                        "action": "run_next", "rule": "salted", "salted": ["starts_alike"]})
        confirmed.feed({"campaign_id": "1", "candidate_id": f"l{i}", "decision_id": f"{2 * i + 1:020d}",
                        "at_n": 16384, "action": "stop", "rule": "starts_alike", "salted": []})
    assert confirmed.document(policy)["gates"]["starts_alike"]["4096"]["clean_since_last_miss"] >= 100
    assert confirmed.share("starts_alike", 4096, policy) == 0.1, "a tenth stays a tenth after the gate confirms"
    for n in (1024, 4096):
        through = sum(policy.let_through(law, "starts_alike", n) for law in LAWS) / len(LAWS)
        assert 0.085 < through < 0.115, (n, through)
    assert policy.cut_gate and policy.asks_for("cut") and policy.live_share("cut", 4096) == G.RECORD_ONLY
    assert all(policy.let_through(law, "cut", 4096) for law in LAWS[:300]), "cut records and every law goes on"


def test_the_841_settings_are_the_design_s_and_172_s_policy_is_unchanged():
    new, old = _policy("173"), _policy("172")
    assert (new.nothing_read_piece_share, new.longer_chain_budget_scale, new.ledger_counts_priced) == (0.9, 2.0, True)
    assert (old.nothing_read_piece_share, old.longer_chain_budget_scale, old.ledger_counts_priced, old.cut_gate) == (
        0.0, 1.0, False, False)
    assert policy_fingerprint(new) != policy_fingerprint(old)
    assert new.work_budgets == old.work_budgets and new.ladder() == old.ladder()


def test_the_criterion_was_committed_before_any_start_and_names_its_replay():
    criterion = json.loads((READINGS / "study_173_criterion.json").read_text(encoding="utf-8"))
    assert criterion["study"] == "173" and criterion["design"].endswith("study_173_design.json")
    assert "study 173's first start" in criterion["committed_before"]
    assert "tools/design_on_a_bundle.py" in criterion["predicted_from"]
    assert [p.split(":")[0] for p in criterion["predicted"]] == [f"P{i}" for i in range(1, 13)]
    studies = json.loads((READINGS / "studies.json").read_text(encoding="utf-8"))["studies"]
    entry = next(study for study in studies if study["id"] == "173")
    assert entry["criterion"] == criterion["design"].replace("design", "criterion")
