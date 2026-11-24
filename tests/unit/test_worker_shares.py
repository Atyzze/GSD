from __future__ import annotations

import pytest

from graph_scale_dynamics.services.worker.main import allowed_campaigns


def row(campaign_id, target, leased=0, queued=10):
    return {"campaign_id": campaign_id, "workers_target": target,
            "leased": leased, "queued": queued}


def test_no_declared_share_means_claim_freely():
    assert allowed_campaigns([row("1", None), row("2", None)]) is None


def test_an_empty_fleet_offers_nothing():
    assert allowed_campaigns([]) == ()


def test_a_campaign_at_its_share_is_not_offered():
    assert allowed_campaigns([row("A", 8, leased=8), row("B", 24, leased=0)]) == ("B",)


def test_the_campaign_furthest_below_its_share_is_offered_first():
    assert allowed_campaigns([row("A", 8, leased=0), row("B", 24, leased=0)]) == ("B",)


def test_equal_deficits_are_offered_together():
    assert set(allowed_campaigns([row("A", 8, leased=0), row("B", 8, leased=0)])) == {"A", "B"}


def test_a_share_with_no_work_does_not_hold_the_allow_list():
    assert allowed_campaigns([row("A", 8, leased=0, queued=500),
                              row("B", 24, leased=0, queued=0)]) == ("A",)


def test_every_campaign_at_its_share_offers_nothing_under_a_share():
    assert allowed_campaigns([row("A", 8, leased=8), row("B", 24, leased=24)]) == ()


def test_a_paused_campaign_is_never_offered():
    assert allowed_campaigns([row("A", 0, leased=0, queued=500), row("B", 24)]) == ("B",)


def test_an_undeclared_share_yields_to_a_declared_one_that_is_behind():
    assert allowed_campaigns([row("A", None), row("B", 24, leased=0)]) == ("B",)


@pytest.mark.parametrize("leased,expected", [(0, ("B",)), (16, ("A", "B")), (24, ("A",))])
def test_the_fleet_converges_on_the_declared_division(leased, expected):
    assert set(allowed_campaigns([row("A", 8, leased=0), row("B", 24, leased=leased)])) \
        == set(expected)
