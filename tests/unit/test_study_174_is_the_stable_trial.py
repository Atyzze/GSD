from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy, policy_fingerprint

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
FACTS = {"empty", "too_dense", "disconnected"}
LAWS = [f"{i:064x}" for i in range(4000)]


def _design(study: str) -> dict:
    return json.loads((READINGS / f"study_{study}_design.json").read_text(encoding="utf-8"))


def _policy(study: str = "174", batch: int = 0) -> Policy:
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, study)
    spec = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                            design["campaigns"][batch], batch)
    return Policy.from_spec(spec)


def test_174_is_173_in_ten_batches_of_1000_on_seeds_of_its_own_with_the_gates_chosen():
    old, new = _design("173"), _design("174")
    same = ("contract", "question", "axes", "ladder", "starts", "limits", "starts_reading", "finds", "terms_left_out")
    assert {key: old[key] for key in same} == {key: new[key] for key in same}, "the grid, starts, ladder and budgets"
    assert new["study"] == "174" and new["law_budget"] == 1000 and len(new["campaigns"]) == 10
    assert len(set(new["search_seeds"])) == 10 and not set(new["search_seeds"]) & set(old["search_seeds"])
    assert all(0 < seed < 2 ** 63 for seed in new["search_seeds"])
    assert [entry["label"] for entry in new["campaigns"]] == [
        f"laws free of N, drawn blind, batch {k} of 10" for k in range(1, 11)]
    assert all({k: v for k, v in entry.items() if k != "label"} == {k: v for k, v in old["campaigns"][0].items()
                                                                    if k != "label"} for entry in new["campaigns"])
    changed = {key for key in set(old["engine"]) | set(new["engine"]) if old["engine"].get(key) != new["engine"].get(key)}
    assert changed == {"gate_shares", "gate_from"} and new["engine"]["gate_from"] == [["nothing_read", 16384]]
    moved = {gate for (gate, share), (_, was) in zip(new["engine"]["gate_shares"], old["engine"]["gate_shares"],
                                                      strict=True) if share != was}
    assert moved == {"starts_apart_by_history"}
    assert "15:38" in new["decided"]["gates"] and "Agree with the recommendation" in new["decided"]["gates"]
    text = json.dumps(new, ensure_ascii=False)
    assert "—" not in text and "–" not in text


def test_nothing_read_records_below_16384_and_acts_from_it_a_tenth_let_through():
    policy = _policy()
    assert policy.acts_from("nothing_read") == 16384 and policy.acts_from("empty") == 0
    for n in (256, 1024, 4096):
        assert policy.live_share("nothing_read", n) == LT.Ledger().share("nothing_read", n, policy) == G.RECORD_ONLY
        assert all(policy.let_through(law, "nothing_read", n) for law in LAWS[:300]), n
    for n in (16384, 65536):
        assert policy.live_share("nothing_read", n) == LT.Ledger().share("nothing_read", n, policy) == 0.1
        through = sum(policy.let_through(law, "nothing_read", n) for law in LAWS) / len(LAWS)
        assert 0.085 < through < 0.115, (n, through)
    for n in (1024, 4096, 16384):
        acting = {gate for gate in G.LET_THROUGH_GATES if policy.live_share(gate, n) < 1.0}
        assert acting == FACTS | {"starts_alike"} | ({"nothing_read"} if n >= 16384 else set()), n
    assert policy.live_share("starts_apart_by_history", 4096) == G.RECORD_ONLY


def test_every_batch_draws_its_own_laws_on_the_same_rules_and_173_s_policy_is_unchanged():
    from graph_scale_dynamics.operations import study_design as SD
    design = SD.design_for(ROOT, "174")
    seeds = [SD.seed_of(design, index) for index in range(10)]
    assert seeds == design["search_seeds"]
    prints = {policy_fingerprint(_policy("174", batch)) for batch in range(10)}
    assert len(prints) == 1, "ten batches, one rule"
    assert _policy("173").gate_from == () and policy_fingerprint(_policy("173")) != prints.pop()


def test_the_criterion_was_committed_before_any_start_and_names_its_replay():
    criterion = json.loads((READINGS / "study_174_criterion.json").read_text(encoding="utf-8"))
    assert criterion["study"] == "174" and criterion["design"].endswith("study_174_design.json")
    assert "study 174's first start" in criterion["committed_before"]
    assert "tools/design_on_a_bundle.py" in criterion["predicted_from"]
    assert [p.split(":")[0] for p in criterion["predicted"]] == [f"P{i}" for i in range(1, 10)]
    studies = json.loads((READINGS / "studies.json").read_text(encoding="utf-8"))["studies"]
    entry = next(study for study in studies if study["id"] == "174")
    assert entry["laws"] == 10000
    assert entry["criterion"] == criterion["design"].replace("design", "criterion")
