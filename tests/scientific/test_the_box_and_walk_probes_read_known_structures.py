from __future__ import annotations

import math

import numpy as np
import pytest

from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements.box_covering import (
    BOX_COVERING_CONTRACT, CONCORDANCE_UNRESOLVED, CONCORDANT, DISCORDANT, dimension_concordance)
from graph_scale_dynamics.measurements.walk_dimension import (
    EINSTEIN_CONSISTENT, EINSTEIN_UNRESOLVED, EINSTEIN_VIOLATED, WALK_DIMENSION_CONTRACT, einstein_relation_check,
    walk_dimension)
from graph_scale_dynamics.research import planted_geometries as planted
from graph_scale_dynamics.scaleflow.observables import (
    BOX_COVERING_EXPONENT, DIMENSION_LIKE_OBSERVABLES, NO_CHANNEL_MEASURES_HAUSDORFF_DIMENSION, OBSERVABLE_ALIASES)

GASKET = math.log(3) / math.log(2)
BY_ITS_BALLS = E.NO_DIMENSION[E.EXPONENTIAL][1] + ", by the ball probe's verdict"
GASKET_WALK = math.log(5) / math.log(2)
STRUCTURES = {
    "ring": lambda: C.periodic_ring(1024),
    "square": lambda: (4096, K.edges(K.SQUARE_TORUS, 4096)),
    "cubic at 1,024": lambda: (1024, K.edges(K.CUBIC_QUOTIENT, 1024)),
    "cubic at 4,096": lambda: (4096, K.edges(K.CUBIC_QUOTIENT, 4096)),
    "cubic at 16,384": lambda: (16384, K.edges(K.CUBIC_QUOTIENT, 16384)),
    "Sierpinski gasket": lambda: C.sierpinski_gasket(7),
    "random 4-regular": lambda: planted.random_regular(16384, 4, 1),
    "random graph": lambda: planted._largest(*planted.erdos_renyi(16384, 4.0, 1)),
    "dense random graph": lambda: planted._largest(*planted.erdos_renyi(4096, 60.0, 3)),
    "binary tree": lambda: C.balanced_tree(2, 9),
    "random graph of mean degree 2": lambda: C.erdos_renyi_graph(2048, 2.0, 1),
}
READ = {}


def _read(name: str) -> dict:
    if name not in READ:
        n, edges = STRUCTURES[name]()
        READ[name] = E._measure_graph(n, edges, np.random.default_rng(1), measure_geometry=True)[0]
    return READ[name]


@pytest.mark.parametrize("name,dimension,within", [("ring", 1.0, 0.10), ("square", 2.0, 0.12),
                                                   ("cubic at 4,096", 3.0, 0.35), ("cubic at 16,384", 3.0, 0.35),
                                                   ("Sierpinski gasket", GASKET, 0.25)])
def test_the_boxes_read_a_structure_within_the_band_of_its_known_answer(name, dimension, within):
    box = _read(name)["d_B"]
    assert box["valid"] and box["power_law_preferred"], box
    assert abs(box["d_B"] - dimension) <= within, (name, box["d_B"])
    assert 0.0 < box["se"] < 0.15, "and say how far to trust it"


@pytest.mark.parametrize("name,walk,within", [("ring", 2.0, 0.15), ("square", 2.0, 0.15), ("cubic at 16,384", 2.0, 0.15),
                                              ("Sierpinski gasket", GASKET_WALK, 0.30)])
def test_the_walk_reads_a_structure_within_the_band_of_its_known_answer(name, walk, within):
    read = _read(name)["d_w"]
    assert read["valid"], read
    assert abs(read["d_w"] - walk) <= within, (name, read["d_w"])
    assert 0.0 < read["se"] < 0.15
    assert read["subdiffusive"] is (name == "Sierpinski gasket"), "only the fractal's walk is slower than a lattice's"


def test_a_lattice_too_small_for_a_window_is_refused_and_not_read_wrongly():
    small = _read("cubic at 1,024")
    assert small["d_B"] == {**small["d_B"], "valid": False, "refusal": "WINDOW_TOO_SHORT"}
    assert small["d_w"] == {**small["d_w"], "valid": False, "refusal": "WALK_SATURATED"}
    assert _read("cubic at 4,096")["d_w"]["refusal"] == "WALK_SATURATED", "boxes read from 4,096, the walk from 16,384"
    assert small["d_s"]["valid"] and small["d_V"]["valid"], "the two other probes read it"


@pytest.mark.parametrize("name", ["random 4-regular", "random graph", "binary tree", "random graph of mean degree 2"])
def test_where_the_balls_grow_exponentially_every_probe_refuses_for_that_reason(name):
    read = _read(name)
    assert read["d_V"]["refusal"] == "EXPONENTIAL_GROWTH" and read["d_V"]["volume_growth"]["verdict"] == "exponential"
    for probe in ("d_s", "d_B", "d_w"):
        assert read[probe] == {**read[probe], "valid": False, "refusal": "EXPONENTIAL_GROWTH",
                               "reason": BY_ITS_BALLS}, read[probe]


def test_the_boxes_alone_would_have_read_a_tree_and_a_sparse_random_graph_and_the_number_is_kept_beside_the_refusal():
    for name, near in (("binary tree", 2.15), ("random graph of mean degree 2", 1.6)):
        assert abs(_read(name)["d_B"]["would_have_reported"] - near) < 0.3, name


def test_a_dense_random_graph_too_small_for_a_verdict_on_its_balls_is_read_by_no_probe():
    read = _read("dense random graph")
    assert read["d_V"]["volume_growth"]["verdict"] == "too small"
    assert {read[probe]["refusal"] for probe in ("d_s", "d_V", "d_B", "d_w")} == {"NO_SCALING_WINDOW"}
    assert all("too small to tell how they grow" in read[probe]["reason"] for probe in ("d_s", "d_V", "d_B", "d_w"))


def test_the_verdict_on_the_balls_alone_turns_a_reading_into_a_refusal_and_changes_nothing_else():
    n, edges = STRUCTURES["square"]()
    adj = E.build_adjacency(n, edges)
    component = E.largest_component(n, adj)
    mean_ball = E.volume_growth(adj, component, np.random.default_rng(1))["mean_ball"]
    read = E._measure_geometry(adj, component, np.random.default_rng(2), mean_ball)
    refused = E._measure_geometry(adj, component, np.random.default_rng(2), mean_ball, growth=E.EXPONENTIAL)
    undecided = E._measure_geometry(adj, component, np.random.default_rng(2), mean_ball, growth=E.UNDECIDED)
    for probe in ("d_B", "d_w"):
        assert read[probe]["valid"]
        assert refused[probe] == {"valid": False, "refusal": "EXPONENTIAL_GROWTH", "reason": BY_ITS_BALLS,
                                  "would_have_reported": read[probe][probe]}
        assert (undecided[probe]["refusal"], undecided[probe]["would_have_reported"]) == (
            "GROWTH_UNDECIDED", read[probe][probe])
    assert refused["_geometry_curves"]["box_covering"]["box_counts"] == read["_geometry_curves"]["box_covering"][
        "box_counts"], "the curves are measured and kept all the same"


def test_the_dimensions_are_ordered_and_the_gasket_keeps_the_einstein_relation():
    assert _read("ring")["d_B"]["d_B"] < _read("Sierpinski gasket")["d_B"]["d_B"] < _read("square")["d_B"]["d_B"] < (
        _read("cubic at 16,384")["d_B"]["d_B"])
    gasket = _read("Sierpinski gasket")
    check = einstein_relation_check(spectral=gasket["d_s"]["d_s"], mass=gasket["d_B"]["d_B"], walk=gasket["d_w"]["d_w"])
    assert check["verdict"] == EINSTEIN_CONSISTENT and check["anomalous_diffusion"], check


def test_the_curves_and_contracts_are_kept_with_a_reading():
    n, edges = STRUCTURES["square"]()
    result, curves = E._measure_graph(n, edges, np.random.default_rng(1), measure_geometry=True)
    box, walk = curves["box_covering"], curves["walk_displacement"]
    assert box["valid"] and box["radii"][0] == 3 and box["covers"] == 3 and len(box["box_counts"]) == len(box["radii"])
    assert walk["valid"] and walk["sources"] == 48 and walk["walks_a_source"] == 16 and "source_squares" not in walk
    assert result["d_B"] == READ.setdefault("square", result)["d_B"], "the same seed reads the same"
    adjacency = E.build_adjacency(n, edges)
    alone = walk_dimension(adjacency, E.largest_component(n, adjacency), np.random.default_rng(2))
    assert alone["contract"] == WALK_DIMENSION_CONTRACT and alone["times_used"][0] >= 8
    assert BOX_COVERING_CONTRACT == "gsd-box-covering-2" and WALK_DIMENSION_CONTRACT == "gsd-walk-dimension-2"


def test_a_component_under_the_measurable_size_is_refused():
    n, edges = C.periodic_ring(12)
    read = E._measure_graph(n, edges, np.random.default_rng(0), measure_geometry=True)[0]
    assert read["d_B"]["refusal"] == read["d_w"]["refusal"] == "COMPONENT_BELOW_MEASURABLE_SIZE"


def test_agreeing_channels_are_concordant():
    result = dimension_concordance(spectral=1.95, distance_volume=2.05, box_covering=1.90)
    assert result["verdict"] == CONCORDANT and result["channels_measured"] == 3


def test_channels_far_apart_are_discordant():
    result = dimension_concordance(spectral=1.1031775, distance_volume=8.006937782517415, box_covering=2.0)
    assert result["verdict"] == DISCORDANT and result["spread"] > 6.0


def test_a_single_channel_cannot_establish_concordance():
    assert dimension_concordance(spectral=2.0)["verdict"] == CONCORDANCE_UNRESOLVED
    assert len(dimension_concordance(spectral=1.0, distance_volume=3.0, box_covering=2.0)["pairwise_gaps"]) == 3


def test_box_covering_is_registered_as_a_third_dimension_channel():
    assert BOX_COVERING_EXPONENT in DIMENSION_LIKE_OBSERVABLES
    assert OBSERVABLE_ALIASES[BOX_COVERING_EXPONENT] == "d_B" and len(DIMENSION_LIKE_OBSERVABLES) == 3
    assert "finite graph" in NO_CHANNEL_MEASURES_HAUSDORFF_DIMENSION and "Hausdorff" in NO_CHANNEL_MEASURES_HAUSDORFF_DIMENSION


def test_the_einstein_relation_reads_three_channels_or_says_it_cannot():
    check = einstein_relation_check(spectral=2.0, mass=2.0, walk=2.0)
    assert check["verdict"] == EINSTEIN_CONSISTENT and check["spectral_predicted"] == pytest.approx(2.0)
    assert check["anomalous_diffusion"] is False
    off = einstein_relation_check(spectral=3.0, mass=1.5, walk=2.0)
    assert off["verdict"] == EINSTEIN_VIOLATED and "not measuring what the relation assumes" in off["reason"]
    assert einstein_relation_check(spectral=2.0, mass=2.0)["verdict"] == EINSTEIN_UNRESOLVED
    assert einstein_relation_check(spectral=2.0, mass=2.0, walk=float("nan"))["verdict"] == EINSTEIN_UNRESOLVED
    assert einstein_relation_check(spectral=2.0, mass=2.0, walk=0.0)["verdict"] == EINSTEIN_UNRESOLVED
