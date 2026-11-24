from __future__ import annotations

import math

from graph_scale_dynamics.scheduling import memory as M

MIB = 1024 ** 2
N = 4096


def price(monkeypatch, local: dict, measured: int | None):
    monkeypatch.setattr(M, "_observed_peak_profile", lambda conn, kind: {})
    monkeypatch.setattr(M, "_observed_candidate_peak_profile", lambda conn, kind, c, law: local)
    monkeypatch.setattr(M, "projected_candidate_edges", lambda *a: None)
    monkeypatch.setattr(M, "_measured_quantile", lambda conn, kind, target, q: measured)
    return M.predicted_claim_peak_bytes(None, kind="simulation", campaign_id="6", candidate_id="law", n=N, spec={})


def own(peak: int, metric: str = "pss") -> dict:
    return {N: {"edge_count": 9000, "reservation_peak_bytes": peak, "peak_rss_bytes": peak, "memory_metric": metric}}


def test_a_law_s_second_seed_at_a_size_is_priced_from_its_first_not_from_the_fallback(monkeypatch):
    fallback = M.fallback_reservation_bytes({}, N, "simulation")
    assert fallback > 1100 * MIB, "781: the fallback at 4,096 is 1,229 MiB, 17 times a median run's peak"
    alone = price(monkeypatch, own(70 * MIB), None)
    _per_node, _base, safety = M._model_settings({}, "simulation")
    assert alone == math.ceil(70 * MIB * safety), "its own peak there, with the model's safety"
    with_fleet = price(monkeypatch, own(70 * MIB), 134 * MIB)
    assert with_fleet == math.ceil(134 * MIB * M.EXPECTED_PEAK_SLACK), "never under the rung's p95 with its slack"
    assert with_fleet < fallback / 7


def test_a_law_s_own_peak_above_the_rung_s_p95_prices_it():
    assert M.own_earlier_seed_bytes({}, "simulation", own(900 * MIB), N) > 900 * MIB


def test_a_legacy_rss_reading_or_no_reading_at_the_size_keeps_the_old_path(monkeypatch):
    assert M.own_earlier_seed_bytes({}, "simulation", own(70 * MIB, "rss_only"), N) is None
    assert M.own_earlier_seed_bytes({}, "simulation", {1024: own(70 * MIB)[N]}, N) is None
    assert M.own_earlier_seed_bytes({}, "simulation", {N: {"memory_metric": "pss"}}, N) is None
