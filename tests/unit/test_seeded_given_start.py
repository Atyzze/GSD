from __future__ import annotations

import pytest

from graph_scale_dynamics.scaleflow.engine_door import given_start_edges, given_start_name
from graph_scale_dynamics.measurements.calibration import control_family_edges
from graph_scale_dynamics.scheduling.job_creation import resolve_given_start


def test_a_square_lattice_is_built_at_the_rung_size_with_the_right_degree():
    for n in (256, 1024, 4096, 16384):
        edges = control_family_edges("periodic_square_lattice", n)
        assert edges is not None and len(edges) == 2 * n, n
        assert max(max(u, v) for u, v in edges) == n - 1


def test_a_size_the_family_cannot_reach_is_refused_not_approximated():
    assert control_family_edges("periodic_square_lattice", 1000) is None
    assert control_family_edges("periodic_square_lattice", 100000) is None
    assert control_family_edges("no_such_family", 1024) is None
    with pytest.raises(ValueError, match="near-miss"):
        resolve_given_start({"sampling_contract": {"given_start": {
            "family": "periodic_square_lattice"}}}, 1000)


def test_an_undeclared_given_start_is_the_historical_draw():
    assert resolve_given_start({}, 1024) is None
    assert resolve_given_start({"sampling_contract": {}}, 1024) is None
    assert given_start_edges(None, 1024) is None
    assert given_start_name(None) == "erdos_renyi_mean_degree_8"


def test_a_declared_family_reaches_the_engine_as_edges():
    spec = {"sampling_contract": {"given_start": {"family": "periodic_square_lattice"}}}
    resolved = resolve_given_start(spec, 1024)
    assert resolved == {"family": "periodic_square_lattice", "n": 1024}
    built = {"family": resolved["family"], "edges": control_family_edges(resolved["family"], resolved["n"])}
    applied = given_start_edges(built, 1024)
    assert len(applied) == 2048
    assert given_start_name(built) == "family_periodic_square_lattice"


def test_a_family_named_without_edges_raises_rather_than_falling_back():
    with pytest.raises(ValueError, match="carries no edges"):
        given_start_edges({"family": "periodic_square_lattice"}, 1024)


def test_edges_outside_the_declared_size_are_refused():
    with pytest.raises(ValueError, match="the size of the chain from empty"):
        given_start_edges({"family": "x", "edges": [(0, 5000)]}, 1024)


def test_the_resolution_consumes_no_randomness():
    a = resolve_given_start({"sampling_contract": {"given_start": {
        "family": "periodic_square_lattice"}}}, 256)
    b = resolve_given_start({"sampling_contract": {"given_start": {
        "family": "periodic_square_lattice"}}}, 256)
    assert a == b
    assert control_family_edges(a["family"], a["n"]) == control_family_edges(b["family"], b["n"])
