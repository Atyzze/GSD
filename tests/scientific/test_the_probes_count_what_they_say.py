from __future__ import annotations

import math

import numpy as np
import pytest

from graph_scale_dynamics.measurements import box_covering as B
from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import exact_curves as X
from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements import walk_dimension as W
from graph_scale_dynamics.research import planted_geometries as planted


def _graphs() -> dict:
    return {"ring": C.periodic_ring(60),
            "square": (144, K.edges(K.SQUARE_TORUS, 144)),
            "cubic": (125, K.edges(K.CUBIC_QUOTIENT, 125)),
            "body-centred cubic": (128, K.edges(K.BODY_CENTRED_CUBIC, 128)),
            "Sierpinski gasket": C.sierpinski_gasket(4),
            "random tree": C.uniform_random_tree(200, 1),
            "random graph": planted._largest(*planted.erdos_renyi(300, 3.0, 5))}


GRAPHS = _graphs()
LATTICES = ("ring", "square", "cubic", "body-centred cubic")


def _read(name: str):
    n, edges = GRAPHS[name]
    adjacency = E.build_adjacency(n, edges)
    component = E.largest_component(n, adjacency)
    assert len(component) == n, "each graph here is in one piece"
    return n, edges, adjacency, component


@pytest.mark.parametrize("name", sorted(GRAPHS))
def test_the_return_probability_is_the_trace_of_the_lazy_walk_s_powers(name):
    n, edges, adjacency, component = _read(name)
    exact = X.return_probability(n, edges, 40)
    assert exact[0] == pytest.approx(0.5), "a lazy walk stays with probability one half"
    found = E.return_probability(adjacency, component, np.random.default_rng(11), probes=1536, t_max=40)
    estimate, error = np.asarray(found["p0"]), np.asarray(found["p0_se"])
    assert found["t"] == list(range(1, 41))
    assert (np.abs(estimate - exact) <= 5.0 * error + 1e-12).all(), "within five of its own standard errors at every time"
    assert float(np.max(error / exact)) < 0.05, "and that error is small enough for the test to bite"
    assert estimate[-1] > 1.0 / n - 5.0 * error[-1], "never under the uniform floor 1/N by more than its error"


@pytest.mark.parametrize("name", sorted(GRAPHS))
def test_the_balls_are_every_node_s_balls(name):
    n, edges, adjacency, component = _read(name)
    exact = X.mean_ball(n, edges)
    found = E.volume_growth(adjacency, component, np.random.default_rng(3), sources=n, r_max=len(exact) + 2)
    measured = np.asarray(found["mean_ball"])
    assert measured[:len(exact)] == pytest.approx(exact, abs=1e-9), "with every node a source the mean ball is exact"
    assert (measured[len(exact):] == n).all(), "and past the diameter a ball is the graph"
    assert found["half_volume_radius"] == pytest.approx(X.half_volume_radius(n, edges))
    few = E.volume_growth(adjacency, component, np.random.default_rng(3), r_max=len(exact) + 2)
    if name in LATTICES:
        assert np.asarray(few["mean_ball"])[:len(exact)] == pytest.approx(exact, abs=1e-9), (
            "every node of a lattice sees the same balls, so any sources give the exact curve")
    else:
        off = np.abs(np.asarray(few["mean_ball"])[:len(exact)] - exact)
        assert (off <= 5.0 * np.asarray(few["se"])[:len(exact)] + 0.01 * n).all(), (
            "within its error from fewer sources, and a node in a hundred where the sources drawn all agree")


@pytest.mark.parametrize("name", sorted(GRAPHS))
def test_the_walk_s_mean_square_distance_is_the_walk_matrix_s(name):
    n, edges, adjacency, component = _read(name)
    profile = W.walk_displacement_profile(adjacency, component, np.random.default_rng(5), sources=n,
                                          walks_a_source=48, max_steps=40, keep_sources=True)
    times = profile["times"]
    assert times == W.walk_times(n, 40)[0] and times[0] == 2 and times[-1] == 40
    exact = X.mean_square_distance(n, edges, times)
    measured = np.asarray(profile["mean_square_displacement"])
    rows = np.asarray(profile["source_squares"])
    error = rows.std(axis=0, ddof=1) / math.sqrt(len(rows))
    assert (np.abs(measured - exact) <= 5.0 * error + 0.03 * exact).all(), "the simple walk's own, time for time"
    assert profile["equilibrium_msd"] == pytest.approx(X.equilibrium_mean_square_distance(n, edges))
    ball = X.mean_ball(n, edges)
    assert [volume for _radius, volume in profile["ball_volumes"]] == pytest.approx(ball[1:].tolist(), abs=1e-9)
    assert [radius for radius, _volume in profile["ball_volumes"]] == list(range(1, len(ball)))


@pytest.mark.parametrize("name", sorted(GRAPHS))
def test_a_cover_is_a_cover_and_no_box_holds_another_s_centre(name):
    n, edges, adjacency, component = _read(name)
    every = X.balls(n, edges)
    apart = X.distances(n, edges)
    diameter = every.shape[1] - 1
    for radius in (1, 2, 3, 5):
        centres = B.greedy_box_centres(adjacency, component, radius, np.random.default_rng(radius))
        assert B.greedy_box_cover(adjacency, component, radius, np.random.default_rng(radius)) == len(centres)
        assert X.is_a_cover(n, edges, centres, radius), "every node is within the radius of a centre"
        between = apart[np.ix_(centres, centres)] + np.eye(len(centres)) * 1e9
        assert between.min() > radius, "a centre is a node no earlier box had covered"
        assert len(centres) >= n / every[:, min(radius, diameter)].max(), "never fewer boxes than the largest ball allows"
    assert len(B.greedy_box_centres(adjacency, component, diameter, np.random.default_rng(0))) == 1


def test_a_ring_is_covered_by_between_one_and_two_times_the_fewest_boxes():
    n, _edges, adjacency, component = _read("ring")
    for radius in (1, 2, 4, 7):
        boxes = B.greedy_box_cover(adjacency, component, radius, np.random.default_rng(radius))
        fewest = math.ceil(n / (2 * radius + 1))
        assert fewest <= boxes <= 2 * fewest, (radius, boxes)


def test_the_box_window_is_whole_radii_from_three_to_a_ball_of_an_eighth_of_the_nodes():
    square = [2 * r * r + 2 * r + 1 for r in range(80)]
    assert B.window_radii(square, 4096) == list(range(3, 16)), "2r^2+2r+1 is at most 512 up to radius 15"
    assert B.window_radii(square, 1024) == [3, 4, 5, 6, 7]
    assert B.window_radii(square, 65536) == sorted({int(round(v)) for v in np.geomspace(3, 63, 16)})
    assert len(B.window_radii(square, 65536)) <= B.MAX_BOX_RADII and B.window_radii(square, 65536)[-1] == 63
    assert B.window_radii(square, 200) == [3] and B.window_radii(square, 150) == []
    assert B.window_radii([1, 5, 13], 10 ** 6) == [], "no ball was counted from radius 3"
    cubic = [(4 * r ** 3 + 6 * r * r + 8 * r + 3) // 3 for r in range(40)]
    refused = B.box_covering_profile(None, np.arange(1024), np.random.default_rng(0), cubic)
    assert not refused["valid"] and refused["refusal"] == "WINDOW_TOO_SHORT" and refused["radii"] == [3], (
        "a ball of radius 4 holds 129 of 1,024 nodes, one more than an eighth")
    assert B.fit_box_dimension(refused)["refusal"] == "WINDOW_TOO_SHORT"


def test_the_box_fit_is_the_straight_line_of_the_boxes_against_a_box_s_width():
    radii = [3, 4, 5, 6, 8, 11]
    exact = {"valid": True, "radii": radii, "box_counts": [5e5 * (2 * r + 1) ** -2.5 for r in radii],
             "box_count_sd": [0.0] * len(radii), "covers": 3, "n_component": 10 ** 6}
    fit = B.fit_box_dimension(exact)
    assert fit["valid"] and fit["power_law_preferred"] and fit["box_covering_exponent"] == pytest.approx(2.5)
    assert fit["se"] == pytest.approx(0.0, abs=1e-9) and fit["radii_used"] == radii
    falling = dict(exact, box_counts=[1e5 * math.exp(-0.9 * r) for r in radii])
    refused = B.fit_box_dimension(falling)
    assert refused["valid"] and not refused["power_law_preferred"] and refused["delta_aicc"] >= 4.0


def test_the_walk_window_runs_from_eight_steps_to_a_quarter_of_equilibrium():
    times = [2, 3, 5, 8, 11, 16, 23, 32, 45, 64]
    msd = [1.5 * t for t in times]
    assert W.walk_window(times, msd, 400.0).tolist() == [3, 4, 5, 6, 7, 8, 9]
    assert W.walk_window(times, msd, 100.0).tolist() == [3, 4, 5], "1.5 t is at most 25 up to t = 16"
    profile = {"valid": True, "component_size": 10 ** 6, "times": times, "equilibrium_msd": 400.0,
               "mean_square_displacement": [3.0 * t ** (2.0 / 2.5) for t in times],
               "ball_volumes": [[r, 3.0 * r ** 2] for r in range(1, 60)]}
    fit = W.fit_walk_dimension(profile)
    assert fit["valid"] and fit["walk_dimension"] == pytest.approx(2.5) and fit["times_used"] == times[3:]
    short = W.fit_walk_dimension(dict(profile, equilibrium_msd=100.0))
    assert not short["valid"] and short["refusal"] == "WALK_SATURATED"
    tree_like = dict(profile, ball_volumes=[[r, 3.0 ** r] for r in range(1, 12)])
    assert W.fit_walk_dimension(tree_like)["walk_dimension"] == pytest.approx(2.5), (
        "the walk fits its own curve: whether the balls grow as a power is the ball probe's verdict, in one place")
