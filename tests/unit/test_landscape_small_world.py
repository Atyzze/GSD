from __future__ import annotations

import math

from graph_scale_dynamics.services.api.landscape_worker import (
    BAND_FLOWING, SMALL_WORLD_FROM, apply_small_world, in_contracting_band, landscape_band, small_world,
)

SIZES = (64, 256, 1024, 4096, 16384, 65536)


def _entry(radius) -> dict:
    return {"rungs": [{"n": n, "summary": {"half_volume_radius": {"mean": radius(n)},
                                           "connected_fraction": {"mean": 1.0}}} for n in SIZES]}


def _point(probes) -> dict:
    return {"stability_contracting_probes": list(probes), "stability_contracting_tier": len(probes)}


A96_N1 = {64: 3.17, 256: 4.13, 1024: 5.01, 4096: 6.02, 16384: 7.02, 65536: 8.02}


def test_a_small_world_a_study_read_is_one():
    found = small_world(_entry(lambda n: A96_N1[n]))
    assert found is not None
    assert found["sizes"][0] == SMALL_WORLD_FROM


def test_a_four_dimensional_lattice_is_not_a_small_world():
    assert small_world(_entry(lambda n: 0.6 * n ** 0.25)) is None


def test_a_two_dimensional_lattice_is_not_a_small_world():
    assert small_world(_entry(lambda n: 0.4 * math.sqrt(n))) is None


def test_a_ring_below_1024_that_wires_randomly_above_is_judged_on_its_deep_rungs():
    radius = {64: 9.5, 256: 47.3, 1024: 8.5, 4096: 9.7, 16384: 10.7, 65536: 11.5}
    assert small_world(_entry(lambda n: radius[n])) is not None


def test_a_small_world_leaves_every_settled_band_and_keeps_its_readings():
    point = _point(["d_B", "d_V"])
    apply_small_world(point, _entry(lambda n: A96_N1[n]))
    assert point["small_world"]
    assert point["stability_contracting_probes"] == [] and point["stability_contracting_tier"] == 0
    assert not in_contracting_band(point)
    assert landscape_band(point) == BAND_FLOWING


def test_a_geometry_keeps_its_band():
    point = _point(["d_s", "d_B"])
    apply_small_world(point, _entry(lambda n: 0.6 * n ** 0.25))
    assert "small_world" not in point
    assert point["stability_contracting_probes"] == ["d_s", "d_B"]


def test_too_few_deep_rungs_decide_nothing():
    entry = {"rungs": [r for r in _entry(lambda n: A96_N1[n])["rungs"] if r["n"] <= 4096]}
    assert small_world(entry) is None
