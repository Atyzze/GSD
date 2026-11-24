from __future__ import annotations

import json

import numpy as np
import pytest

from graph_scale_dynamics.measurements import box_covering as B
from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements import walk_dimension as W
from graph_scale_dynamics.research import known_structures as S
from graph_scale_dynamics.research import planted_geometries as planted
from graph_scale_dynamics.scaleflow.probes import Bucket, RefusalCode, bucket_for_rung

READ: dict = {}


def _balls(name: str, built, seed: int = 1):
    if name not in READ:
        n, edges = built()
        adjacency = E.build_adjacency(n, edges)
        component = E.largest_component(n, adjacency)
        volume = E.volume_growth(adjacency, component, np.random.default_rng(seed), keep_sources=True)
        READ[name] = (volume, E.fit_dh(volume, len(component)), len(component))
    return READ[name]


def _ball_of(width: float, exponent: float, radii: int) -> list[float]:
    return [1.0] + [width * (r + 0.5) ** exponent for r in range(1, radii + 1)]


def test_a_power_all_the_way_is_read_to_its_last_radius():
    assert E.last_radius_of_the_window(_ball_of(3.0, 2.0, 40), 10 ** 9) == 40
    assert E.last_radius_of_the_window([1.0, 5.0], 10 ** 9) is None, "one radius is no window"


def test_on_a_torus_the_window_ends_where_the_balls_first_meet_themselves():
    for name, built, half_side in (("square", lambda: (1024, K.edges(K.SQUARE_TORUS, 1024)), 16),
                                   ("cube", lambda: S.box_torus((16, 16, 16)), 8),
                                   ("4D", lambda: S.box_torus((8, 8, 8, 8)), 4)):
        volume, fit, _n = _balls(name, built)
        assert half_side <= fit["window_cut_at"] <= half_side + 1, (name, fit["window_cut_at"])
        assert fit["valid"] and fit["window"]["r_hi"] == fit["window_cut_at"]
        slopes = fit["local_slopes"]
        assert slopes[-1] >= (1.0 - E.WITHIN_OF_THE_STEEPEST) * max(slopes), "its last radius is within reach of the steepest"


def test_a_strip_is_read_at_its_largest_radii_where_its_exponent_has_come_down_to_a_line_s():
    volume, fit, _n = _balls("strip", lambda: S.box_torus((2048, 4)))
    ball = np.asarray(volume["mean_ball"])
    assert ball[2:12].tolist() == [8.0 * r - 4.0 for r in range(2, 12)], "four around: eight more nodes a step"
    assert fit["valid"] and fit["window_cut_at"] == volume["r_max"], "the balls are nowhere near the whole strip"
    assert fit["d_V_window"] == pytest.approx(1.0, abs=0.05)
    assert fit["local_slopes"][0] == max(fit["local_slopes"]) > 1.7, "steepest at its second radius, where the window used to end"
    assert 8 <= fit["window"]["settled_from"] <= 16, "and its exponent is within a tenth of its value from about there"


def test_a_slab_is_read_as_the_plane_it_is_beyond_its_thickness():
    _volume, fit, _n = _balls("slab", lambda: S.box_torus((64, 64, 4)))
    assert fit["valid"] and fit["d_V_window"] == pytest.approx(2.0, abs=0.15) and fit["window_cut_at"] >= 30
    _volume, thin, _n = _balls("thin slab", lambda: S.box_torus((32, 32, 4)))
    assert thin["window"]["points"] <= 5 and thin["d_V_window"] > 2.3, (
        "32 by 32 by 4 has no plane's stretch between its thickness and its sides: it is read at its short scale")


def test_the_slowing_fall_is_what_tells_a_second_stretch_from_the_end_of_the_first():
    settling = [1.0] + [8.0 * (r + 0.5) - 8.0 for r in range(1, 61)]
    assert E.last_radius_of_the_window(settling, 10 ** 9) == 60, "1 + 1/(x - 1): each octave falls half as far as the last"
    steady = [1.0] + [2.0 * (r + 0.5) ** 2 * (1.0 - r / 90.0) for r in range(1, 61)]
    ends = E.last_radius_of_the_window(steady, 10 ** 9)
    assert ends <= 12, "a fall that does not slow is the end of the stretch, not a second one"
    exponent = np.diff(np.log(steady[1:])) / np.diff(np.log(np.arange(1, 61) + 0.5))
    assert exponent[ends - 2] >= (1.0 - E.WITHIN_OF_THE_STEEPEST) * exponent.max() > exponent[ends - 1]


def test_an_open_patch_and_a_carpet_are_read_before_their_edges_tell():
    _volume, patch, _n = _balls("patch", lambda: S.open_square(128))
    assert patch["valid"] and patch["d_V_window"] == pytest.approx(2.0, abs=0.15) and patch["window_cut_at"] < 40
    _volume, carpet, _n = _balls("carpet", lambda: C.sierpinski_carpet(4))
    assert carpet["valid"] and carpet["d_V_window"] == pytest.approx(np.log(8) / np.log(3), abs=0.2)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_a_tree_with_hubs_is_refused_because_its_nodes_do_not_agree(seed):
    volume, fit, _n = _balls(f"hubs {seed}", lambda: planted.preferential_attachment(16384, 1, seed), seed=seed)
    growth = fit["volume_growth"]
    assert not fit["valid"] and growth["verdict"] in (E.UNEVEN, E.UNTESTED, E.EXPONENTIAL, E.UNDECIDED)
    apart = np.asarray(volume["sources_apart"])[1:fit["window_cut_at"] + 1]
    assert apart.max() > 1.1 > E.SOURCES_APART_AT_MOST, "its sources' balls lie more than a factor of e apart"
    if growth["verdict"] == E.UNEVEN:
        assert fit["refusal"] == "GROWTH_UNEVEN" and "differ most" in fit["reason"] and "would_have_reported" in fit


def test_the_hubs_are_what_refuses_it_where_its_balls_alone_read_as_a_power():
    verdicts = [_balls(f"hubs {seed}", lambda: planted.preferential_attachment(16384, 1, seed), seed=seed)[1][
        "volume_growth"]["verdict"] for seed in (0, 1, 2, 3)]
    assert E.UNEVEN in verdicts, verdicts


@pytest.mark.parametrize("name,built", [
    ("uniform tree", lambda: C.uniform_random_tree(16384, 3)),
    ("percolation", lambda: planted.critical_percolation_cluster(128, 3)),
    ("plane", lambda: planted.random_geometric(4096, 2, 8.0, 3)),
])
def test_a_random_geometry_s_nodes_agree_well_enough(name, built):
    volume, fit, _n = _balls(name, built, seed=3)
    assert fit["valid"], fit
    assert fit["volume_growth"]["sources_apart"] < E.SOURCES_APART_AT_MOST - 0.05, "and by a margin"
    assert fit["volume_growth"]["sources_apart"] == pytest.approx(
        max(volume["sources_apart"][fit["window"]["r_lo"]:fit["window"]["r_hi"] + 1])), "the largest over the window"


def test_a_lattice_s_nodes_agree_exactly():
    volume, fit, _n = _balls("square", lambda: (1024, K.edges(K.SQUARE_TORUS, 1024)))
    assert max(volume["sources_apart"]) == pytest.approx(0.0, abs=1e-12)
    assert fit["volume_growth"]["sources_apart"] == pytest.approx(0.0, abs=1e-12)


def test_the_curve_that_is_kept_gives_the_same_verdict_again():
    for name in ("hubs 0", "hubs 1", "uniform tree", "strip", "square"):
        volume, fit, n = READ[name]
        kept = json.loads(json.dumps({key: value for key, value in volume.items() if key != "balls_per_source"}))
        again = E.fit_dh(kept, n)
        assert again["volume_growth"]["verdict"] == fit["volume_growth"]["verdict"], name
        assert again.get("refusal") == fit.get("refusal") and again.get("d_V_window") == fit.get("d_V_window"), name
    bare = {key: value for key, value in READ["hubs 0"][0].items() if key not in ("balls_per_source", "sources_apart")}
    assert "sources_apart" not in E.fit_dh(bare, READ["hubs 0"][2])["volume_growth"], (
        "a curve kept before 763 holds no spread, and is judged on its mean alone")


@pytest.mark.parametrize("name,built,verdicts", [
    ("triangles", lambda: S.hyperbolic_triangles(7), (E.EXPONENTIAL, E.UNDECIDED)),
    ("squares", lambda: S.hyperbolic_squares(7), (E.EXPONENTIAL, E.UNDECIDED)),
    ("hyperbolic geometric", lambda: S.hyperbolic_geometric_graph(4096, 12.0, 1.0, 3), (E.EXPONENTIAL, E.UNDECIDED)),
    ("hyperbolic random", lambda: S.hyperbolic_random_graph(4096, 8.0, 0.75, 3), (E.TOO_SMALL,)),
])
def test_a_hyperbolic_structure_has_no_dimension_to_read(name, built, verdicts):
    _volume, fit, _n = _balls(name, built)
    assert not fit["valid"] and fit["volume_growth"]["verdict"] in verdicts, fit["volume_growth"]


def test_no_probe_reads_where_the_window_is_too_short_to_test_or_the_nodes_do_not_agree():
    n, edges = 4096, K.edges(K.SQUARE_TORUS, 4096)
    adjacency = E.build_adjacency(n, edges)
    component = E.largest_component(n, adjacency)
    mean_ball = E.volume_growth(adjacency, component, np.random.default_rng(1))["mean_ball"]
    read = E._measure_geometry(adjacency, component, np.random.default_rng(2), mean_ball)
    for growth, refusal, says in ((E.UNTESTED, "NO_SCALING_WINDOW", "too few to tell how they grow"),
                                  (E.UNEVEN, "GROWTH_UNEVEN", "the same from every node"),
                                  (E.TOO_SMALL, "NO_SCALING_WINDOW", "too small to tell how they grow")):
        refused = E._measure_geometry(adjacency, component, np.random.default_rng(2), mean_ball, growth=growth)
        for probe in ("d_B", "d_w"):
            assert read[probe]["valid"]
            assert (refused[probe]["refusal"], refused[probe]["would_have_reported"]) == (refusal, read[probe][probe])
            assert says in refused[probe]["reason"] and "by the ball probe's verdict" in refused[probe]["reason"]
        spectral = E._refused_for_its_balls({"valid": True, "d_s": 2.0}, "d_s", growth)
        assert spectral == {"valid": False, "refusal": refusal, "reason": spectral["reason"], "would_have_reported": 2.0}
    assert set(E.NOT_CLEARLY_A_POWER) == {E.EXPONENTIAL, E.UNDECIDED, E.UNEVEN, E.UNTESTED, E.TOO_SMALL}
    assert bucket_for_rung({"valid": False, "refusal": "GROWTH_UNEVEN"}, terminal_classification=None) == (
        Bucket.REFUSED_NO_SCALING_WINDOW) and RefusalCode("GROWTH_UNEVEN")


def test_a_graph_read_whole_refuses_every_probe_for_its_hubs():
    n, edges = planted.preferential_attachment(4096, 1, 0)
    read = E._measure_graph(n, edges, np.random.default_rng(5), measure_geometry=True)[0]
    verdict = read["d_V"]["volume_growth"]["verdict"]
    assert verdict in E.NOT_CLEARLY_A_POWER, verdict
    assert not any(read[probe]["valid"] for probe in ("d_s", "d_V", "d_B", "d_w"))
    assert {read[probe]["refusal"] for probe in ("d_s", "d_B", "d_w")} == {E.NOT_CLEARLY_A_POWER[verdict][0]}


def test_the_boxes_and_the_walk_start_where_the_balls_exponent_has_settled():
    square = [2 * r * r + 2 * r + 1 for r in range(80)]
    assert B.window_radii(square, 4096, settled_from=1) == B.window_radii(square, 4096) == list(range(3, 16))
    assert B.window_radii(square, 4096, settled_from=9) == list(range(9, 16))
    assert B.window_radii(square, 4096, settled_from=13) == [13, 14, 15]
    assert B.window_radii(square, 4096, settled_from=20) == []
    short = B.box_covering_profile(None, np.arange(4096), np.random.default_rng(0), square, settled_from=13)
    assert short["refusal"] == "WINDOW_TOO_SHORT" and "a box 27 nodes across, where the balls' exponent has settled" in (
        short["reason"])
    times = [2, 3, 5, 8, 11, 16, 23, 32, 45, 64, 91, 128]
    msd = [1.5 * t for t in times]
    assert W.walk_window(times, msd, 4000.0).tolist() == list(range(3, 12))
    assert W.walk_window(times, msd, 4000.0, settled_from=6).tolist() == list(range(7, 12)), "1.5 t passes 36 after 24"
    profile = {"valid": True, "component_size": 10 ** 6, "times": times, "equilibrium_msd": 4000.0,
               "mean_square_displacement": msd, "ball_volumes": []}
    assert W.fit_walk_dimension(profile, settled_from=6)["times_used"] == times[7:]
    late = W.fit_walk_dimension(profile, settled_from=11)
    assert late["refusal"] == "WINDOW_TOO_SHORT" and "the walk ends before a scaling regime can form" in late["reason"]
    explored = W.fit_walk_dimension(dict(profile, equilibrium_msd=100.0))
    assert explored["refusal"] == "WALK_SATURATED" and explored["saturated"] is True


def test_a_strip_s_boxes_and_walk_are_not_read_at_its_short_scale():
    n, edges = S.box_torus((4096, 4))
    read, curves = E._measure_graph(n, edges, np.random.default_rng(1), measure_geometry=True)
    settled = read["d_V"]["window"]["settled_from"]
    assert curves["box_covering"]["radii"][0] == settled > B.SMALLEST_RADIUS
    assert read["d_B"]["valid"] and read["d_B"]["d_B"] == pytest.approx(1.0, abs=0.1), "1.13 from radius three"
    assert read["d_s"]["valid"] and read["d_s"]["d_s"] == pytest.approx(1.0, abs=0.1)
    walk = read["d_w"]
    assert (walk["valid"] and walk["d_w"] == pytest.approx(2.0, abs=0.15)) or walk["refusal"] == "WINDOW_TOO_SHORT", (
        "read as a line's, or refused where 512 steps end before five times past the short scale: never 2.3")


def test_d_v_s_error_is_the_spread_of_the_whole_reading_its_window_found_again_for_each_resampling():
    n, edges = S.sierpinski_tetrahedron(5)
    adjacency = E.build_adjacency(n, edges)
    component = E.largest_component(n, adjacency)
    values, errors = [], []
    for seed in range(12):
        fit = E.fit_dh(E.volume_growth(adjacency, component, np.random.default_rng(seed), keep_sources=True),
                       len(component))
        values.append(fit["d_V_window"])
        errors.append(fit["se"])
    spread = float(np.std(values, ddof=1))
    assert spread > 0.05, "on a fractal the window's end moves with the sources"
    assert 0.5 * spread <= float(np.median(errors)) <= 2.0 * spread, "and the error says so"
    assert fit["se_method"]["method"] == "bootstrap over sources, the window found again in each"


def test_d_v_on_a_lattice_whose_nodes_are_alike_is_exact_and_its_error_nothing():
    _, fit, _ = _balls("a cubic lattice of 4,096", lambda: C.periodic_cubic_lattice(16))
    assert fit["valid"] and fit["se"] < 1e-9


def test_the_fleet_counts_a_small_graph_s_balls_from_more_sources():
    assert [E.sources_for_the_verdict(n) for n in (64, 1024, 4096, 8192, 16384, 65536, 1048576)] == [
        128, 128, 128, 64, 32, 32, 40]
    result, curves = E._measure_graph(*C.periodic_square_lattice(32), np.random.default_rng(0))
    assert curves["volume_growth"]["sources"] == 128 and result["d_V"]["valid"]
    small, _ = E._measure_graph(*C.periodic_ring(64), np.random.default_rng(0))
    assert small["d_V"]["valid"], "and from every node where there are fewer"
    n, edges = C.periodic_square_lattice(32)
    adjacency = E.build_adjacency(n, edges)
    alone = E.volume_growth(adjacency, E.largest_component(n, adjacency), np.random.default_rng(0))
    assert alone["sources"] == 24, "a call that names no count keeps the count the reaches were measured with"


def test_from_128_sources_a_hyperbolic_graph_of_4096_nodes_is_refused_where_24_read_it_on_some_draws():
    read = {24: 0, 128: 0}
    for draw in range(6):
        n, edges = S.hyperbolic_geometric_graph(4096, 12.0, 1.0, 1000 + draw)
        adjacency = E.build_adjacency(n, edges)
        component = E.largest_component(n, adjacency)
        for sources in read:
            volume = E.volume_growth(adjacency, component, np.random.default_rng(draw), sources=sources, keep_sources=True)
            read[sources] += bool(E.fit_dh(volume, len(component))["valid"])
    assert read[128] == 0, read
