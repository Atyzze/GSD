from __future__ import annotations

import pytest

from graph_scale_dynamics.research import claim_ledger as ledger

KNOWN_FALSE = {"calibration_table_gates_a_release"}


@pytest.fixture(scope="module")
def tree():
    return ledger.evaluate_tree()


def test_the_tree_lane_checks_something(tree):
    assert len(tree["claims"]) >= 12
    assert {claim["claim_id"] for claim in tree["claims"]} >= {
        "ds_noise_floor", "aicc_threshold", "depth_is_bought_on_ds_alone",
        "degree_anchor_identity", "deep_lane_widths"}


def test_every_tree_claim_holds_except_the_one_that_is_known_to_be_false(tree):
    refuted = {claim["claim_id"] for claim in tree["claims"] if claim["verdict"] == ledger.REFUTED}
    assert refuted == KNOWN_FALSE, (
        "the tree lane's verdicts moved. A constant this ledger reads has "
        "changed, and every document quoting it is now wrong: fix the documents "
        f"rather than the claim. Refuted now: {sorted(refuted)}")


def test_nothing_in_the_tree_lane_is_uncheckable(tree):
    from tests.support.calibration_table import table_available
    host_state = set() if table_available() else {"ds_noise_floor"}
    stuck = [claim["claim_id"] for claim in tree["claims"]
             if claim["verdict"] == ledger.UNCHECKABLE and claim["claim_id"] not in host_state]
    assert not stuck, f"these tree claims could not be evaluated at all: {stuck}"


def test_every_verdict_is_published_beside_the_number_it_came_from(tree):
    for claim in tree["claims"]:
        assert claim.get("reading"), f"{claim['claim_id']} has a verdict and no reading"
        assert "measured" in claim, f"{claim['claim_id']} states a verdict with no measurement"
        assert claim.get("asserted_in"), f"{claim['claim_id']} does not say where it was claimed"


def test_the_readings_lead_with_the_summary(tree):
    assert tree["readings"] and str(tree["readings"][0])
    assert tree["counts"][ledger.VERIFIED] + tree["counts"][ledger.REFUTED] \
        + tree["counts"][ledger.UNCHECKABLE] == len(tree["claims"])


def test_every_claim_is_the_tree_s():
    assert {claim.lane for claim in ledger.tree_claims()} == {ledger.LANE_TREE}
