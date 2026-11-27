from __future__ import annotations

import math

import pytest

from graph_scale_dynamics.observability import likeness as L
from graph_scale_dynamics.observability import phenotype as P


def _rows(make):
    return [{"n": n, "seeds": 4, **make(n)} for n in (64, 256, 1024, 4096, 16384)]


def test_curves_are_fitted_from_the_rungs_up_to_the_size_read():
    found = L.curves(_rows(lambda n: {"mean_degree": 4.0, "d_s": 2.0 * (n / 256) ** 0.2,
                                      "half_volume_radius": 3.0 + 2.0 * math.log(n)}), 4096)
    assert found["mean_degree"]["form"] == "constant" and found["mean_degree"]["to_n"] == 4096
    assert found["d_s"]["form"] == "power" and found["d_s"]["b"] == pytest.approx(0.2)
    assert found["reach"]["form"] == "log"
    assert "d_V" not in found
    assert L.curves(_rows(lambda n: {"mean_degree": 4.0}), 1024)["mean_degree"]["form"] is None, (
        "two sizes from 256 lock in no curve")


def test_a_curve_is_the_same_within_the_rule_s_bands():
    rule = P.rule()
    a = {"form": "power", "b": 0.30}
    assert L.same_curve(a, {"form": "power", "b": 0.30 + rule["exponent_within"] * 0.9})[0]
    assert not L.same_curve(a, {"form": "power", "b": 0.30 + rule["exponent_within"] * 1.1})[0]
    c = {"form": "constant", "a": 4.0}
    assert L.same_curve(c, {"form": "constant", "a": 4.0 * (1 + rule["constant_within"] * 0.9)})[0]
    assert not L.same_curve(c, {"form": "constant", "a": 4.0 * (1 + rule["constant_within"] * 1.5)})[0]
    same, why = L.same_curve(c, {"form": "log", "a": 1.0, "b": 0.5})
    assert not same and why == "constant against log"


def test_a_law_is_alike_when_its_kind_agrees_and_no_curve_locked_in_by_both_is_apart():
    made = {"kind": "made", "curves": {"d_s": {"form": "power", "b": 0.3}, "mean_degree": {"form": "constant", "a": 4},
                                       "d_V": {"form": None}}}
    assert L.alike(made, None)["alike"] is None
    assert L.alike(made, {"kind": "moved", "curves": {}})["alike"] is False
    found = L.alike(made, {"kind": "made", "curves": {"d_s": {"form": "power", "b": 0.32}}})
    assert found["alike"] is True and found["curves"] == 1
    found = L.alike(made, {"kind": "made", "curves": {"d_s": {"form": "power", "b": 0.5},
                                                      "mean_degree": {"form": "constant", "a": 4}}})
    assert found["alike"] is False and found["curves"] == 2 and found["why"].startswith("its kind, but d_s")
    found = L.alike(made, {"kind": "made", "curves": {"d_V": {"form": "power", "b": 2}}})
    assert found["alike"] is True and found["curves"] == 0 and "no curve locked in by both" in found["why"], (
        "a curve one law has not locked in is no ground to part them: the kind decides")
