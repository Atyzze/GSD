from __future__ import annotations

import numpy as np

from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements.calibration import random_regular_graph


def _diffusive_curve(n=1 << 20, t_max=400):
    times = list(range(1, t_max + 1))
    return {"t": times, "p0": [1.0 / n + 0.5 * t ** -1.0 for t in times], "p0_se": [1e-9] * t_max}, n


def _refused_with(monkeypatch, delta):
    monkeypatch.setattr(E, "diffusive_window_evidence", lambda t, q: {
        "comparable": True, "delta_aicc": delta, "power_law_exponent": -1.0, "gap_decay_rate": 0.1,
        "is_power_law": delta > E.DIFFUSIVE_WINDOW_MIN_DELTA_AICC})
    curve, n = _diffusive_curve()
    return E.fit_ds(curve, n)


def test_a_refusal_the_power_law_led_says_so(monkeypatch):
    ahead = _refused_with(monkeypatch, 0.7)
    assert ahead["refusal"] == "NO_DIFFUSIVE_WINDOW" and ahead["would_have_reported"] is not None
    assert "fits a power law better" in ahead["reason"] and "by only 0.7" in ahead["reason"]
    assert "better described by spectral-gap decay" not in ahead["reason"]
    behind = _refused_with(monkeypatch, -4.2)
    assert "better described by spectral-gap decay" in behind["reason"] and "-4.2" in behind["reason"]


def test_the_other_probes_keep_what_they_computed_on_an_expander():
    n, edges = random_regular_graph(4096, 4, seed=3)
    result, _ = E._measure_graph(n, edges, np.random.default_rng(3), measure_geometry=True)
    for probe in ("d_V", "d_B", "d_w"):
        assert (result[probe]["valid"], result[probe]["refusal"]) == (False, "EXPONENTIAL_GROWTH"), (
            "an expander at 4,096 is refused by the three probes that read along the radius, for its balls")
    assert np.isfinite(result["d_V"]["would_have_reported"]), "the ball probe keeps the slope it would have read"
    for probe in ("d_B", "d_w"):
        value = result[probe].get("would_have_reported")
        assert value is None or (isinstance(value, float) and np.isfinite(value)), (
            "a number where the probe's own curve gave one, none where its window was too short", probe, result[probe])
