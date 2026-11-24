from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.services.proposer.main import (
    proposal_target_banner, proposal_targets,
)

ROOT = Path(__file__).resolve().parents[2]
ACTIVES = [{"campaign_id": "1", "spec": {}}, {"campaign_id": "2", "spec": {}}]


def test_every_active_campaign_is_a_target():
    assert [c["campaign_id"] for c in proposal_targets(ACTIVES)] == ["1", "2"]


def test_an_extend_only_campaign_is_not_a_target():
    assert [c["campaign_id"] for c in proposal_targets(ACTIVES, frozenset({"1"}))] == ["2"]


def test_the_operators_case_no_longer_silences_the_second_campaign():
    targets = [c["campaign_id"] for c in proposal_targets(ACTIVES, frozenset({"1"}))]
    assert targets == ["2"], (
        "this is exactly the fleet state that produced a campaign with zero laws")


def test_no_active_campaign_means_no_target():
    assert proposal_targets([]) == []
    assert proposal_target_banner([]).startswith("proposer targets: none ")


def test_the_banner_names_the_targets_and_the_campaigns_it_is_not_feeding():
    banner = proposal_target_banner(ACTIVES, frozenset({"1"}))
    assert "proposer targets: 2" in banner
    assert "extend-only" in banner and "1" in banner


def test_the_target_rule_does_not_take_a_home_campaign():
    import inspect
    parameters = list(inspect.signature(proposal_targets).parameters)
    assert parameters == ["actives", "flagged"], (
        "proposal_targets grew a home argument again; the proposer's target set "
        "is the active set and reporting's focus is a different question")
