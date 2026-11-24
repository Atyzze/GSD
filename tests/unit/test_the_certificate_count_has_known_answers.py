from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from graph_scale_dynamics.research import certificate_known_answers as K
from graph_scale_dynamics.resources import committed
from graph_scale_dynamics.measurements import certificate

ROOT = Path(__file__).resolve().parents[2]


def _criterion() -> dict:
    return json.loads(committed.path("certificate_known_answers_criterion_3.json").read_text(encoding="utf-8"))


def _judged() -> dict:
    return json.loads(committed.path("certificate_known_answers_3_judged.json").read_text(encoding="utf-8"))


def test_the_known_answer_is_the_series_own_correlation_time():
    assert abs(K.tau_of(K.phi_for(18.0)) - 18.0) < 1e-9 and K.phi_for(1.0) == 0.0
    drawn = K.ar1(0.9, 4000, 200, np.random.default_rng(3))
    assert abs(float(drawn.var()) - 1.0 / (1.0 - 0.81)) < 0.5
    lag_one = float(np.mean(drawn[:, 1:] * drawn[:, :-1]) / np.mean(drawn * drawn))
    assert abs(lag_one - 0.9) < 0.02


def test_the_count_read_is_the_certificate_s_own():
    series = K.ar1(0.5, 240, 1, np.random.default_rng(5))[0]
    own = certificate.equilibration_certificate(K.envelope_of(series))["effective_samples_counted"]["windowed"]
    assert K.window_count(series) == own and len(K.late_of(series)) == 144
    assert K.window_count(np.ones(240)) is None


def test_a_batch_means_count_cannot_read_below_about_its_number_of_batches():
    slow = K.ar1(K.phi_for(2000.0), 240, 300, np.random.default_rng(7))
    read = [K.batch_means_count(row, 8) for row in slow]
    assert min(read) > 5.0, "eight batches cannot say fewer than a handful of samples: the reason no count is fit at 8"
    assert float(np.median([K.batch_means_count(row, 4) for row in slow])) < 8.0
    fast = K.ar1(0.0, 240, 300, np.random.default_rng(9))
    assert float(np.median([K.batch_means_count(row, 8) for row in fast])) > 60.0
    assert K.batch_means_count(np.ones(240), 8) is None and K.batch_means_count(slow[0], 1) is None


def test_a_rung_is_measured_again_as_it_was_committed():
    criterion = _criterion()
    small = dict(criterion, rungs=[dict(criterion["rungs"][0], replicates=200)], true_samples=[1, 32, 64])
    again = {row["true_samples"]: row for row in K.measure_rungs(small)}
    kept = {row["true_samples"]: row for row in _judged()["rows"] if row["chains"] == criterion["rungs"][0]["chains"]}
    for true in (1, 64):
        for threshold in ("8", "16"):
            then = kept[true]["per_chain"][threshold]
            assert abs(again[true]["per_chain"][threshold] - then) < 0.08, (true, threshold, then)
    assert again[1]["unread_chains"] == 0


def test_the_rung_judgement_in_the_tree_is_the_one_the_rule_gives():
    criterion, kept = _criterion(), _judged()
    again = K.judge_rungs(criterion, kept["rows"])
    for key in ("by_threshold", "fit_at", "rule", "thresholds"):
        assert json.loads(json.dumps(again[key])) == kept[key], key
    assert kept["measured_utc"] > criterion["committed_utc"] and kept["criterion"] == criterion["contract"]
    page = (ROOT / "docs" / "readings" / "certificate_known_answers_3_judged.md").read_text(encoding="utf-8")
    assert page == K.render_rungs(kept)


def test_every_chain_s_own_count_is_fit_at_16_and_the_chain_from_empty_alone_is_not():
    kept = _judged()
    assert kept["fit_at"] == [16]
    for chains, read in kept["by_threshold"]["16"]["rungs"].items():
        assert read["k1"] and read["k2"] and read["k3"] and read["passes"], chains
        assert not read["k3_by_the_chain_from_empty_alone"], "one chain's count cannot see a starved chain"
    assert not any(read["passes"] for read in kept["by_threshold"]["8"]["rungs"].values())
    assert "fit at 16" in K.render_rungs(kept)
