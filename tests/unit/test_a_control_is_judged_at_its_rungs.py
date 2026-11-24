from __future__ import annotations

from graph_scale_dynamics.research import control_verdict as V

CRITERION = V.load_criterion(V.CRITERIA["campaign-standing-controls"])
LAW = {law["label"]: law["candidate_id"] for law in V.control_laws(CRITERION)}


def _c1(top_n):
    return {LAW["C1"]: {"top_n": top_n, "empty": "no finite dimension", "given": "no finite dimension",
                        "given_implied_d_s": None}}


def test_a_law_below_the_rules_window_is_running_not_failed():
    result = V.judge(CRITERION, _c1(16384))
    row = next(r for r in result["laws"] if r["label"] == "C1")
    assert row["verdict"] == "running" and result["overall"] == "running"
    assert "measured to N=16,384; judged from N=65,536" in row["why"] and "given expected" in row["why"]


def test_the_same_reading_at_the_rules_window_fails():
    result = V.judge(CRITERION, _c1(65536))
    assert next(r for r in result["laws"] if r["label"] == "C1")["verdict"] == "fail"
    assert result["overall"] == "fail"


def test_an_older_bundle_without_the_top_rung_reads_it_from_the_given_chains_probes():
    chains = {LAW["C1"]: {"empty": "no finite dimension", "given": "no finite dimension"}}
    probes = {LAW["C1"]: {"4096": {}, "16384": {}}}
    assert V.judge(CRITERION, chains, probes)["overall"] == "running"
    assert V.judge(CRITERION, chains)["overall"] == "fail", "with nothing to say how far it ran, judged as before"
