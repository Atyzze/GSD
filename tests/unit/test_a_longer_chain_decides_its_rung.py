from __future__ import annotations

from graph_scale_dynamics.db.decision_store import best_runs
from graph_scale_dynamics.decisions.evidence import _b143_rung_sampling_state


def _run(seed: int, multiplier: int, reason: str, classification: str, *, audit: bool = False) -> dict:
    health = {"n": 4096, "equilibration": {"sweeps_multiplier": multiplier},
              "rung_terminal": {"reason": reason, "classification": classification, "final_multiplier": multiplier}}
    if audit:
        health["sampler"] = {"sampler_audit": True}
    return {"n": 4096, "seed": seed, "metrics": {"health": health}}


def test_the_longer_chain_supersedes_the_run_it_was_bought_for():
    rows = [_run(0, 1, "ceiling", "CEILING_INSUFFICIENT_ESS"), _run(1, 1, "completed", "EQUILIBRATED"),
            _run(0, 4, "completed", "EQUILIBRATED")]
    best = best_runs(rows)
    assert sorted((m["seed"], m["metrics"]["health"]["equilibration"]["sweeps_multiplier"]) for m in best) == [
        (0, 4), (1, 1)]
    state = _b143_rung_sampling_state({}, 4096, {}, [m["metrics"] for m in best])
    assert state["classification"] == "EQUILIBRATED", "the longer chain completed, so the rung did"
    before = _b143_rung_sampling_state({}, 4096, {}, [m["metrics"] for m in rows])
    assert before["classification"] == "CEILING_INSUFFICIENT_ESS", "648 read the short run's ceiling for good"


def test_a_longer_chain_that_stopped_at_its_window_still_says_so_and_audits_are_not_evidence():
    rows = [_run(0, 1, "ceiling", "CEILING_INSUFFICIENT_ESS"), _run(0, 4, "budget", "TIME_WINDOW"),
            _run(0, 8, "completed", "EQUILIBRATED", audit=True)]
    best = best_runs(rows)
    assert [m["metrics"]["health"]["rung_terminal"]["reason"] for m in best] == ["budget"]
    assert _b143_rung_sampling_state({}, 4096, {}, [m["metrics"] for m in best])["classification"] == "TIME_WINDOW"
