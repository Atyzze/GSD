from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from graph_scale_dynamics.measurements import analysis
from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import version as V

ROOT = Path(__file__).resolve().parents[2]
def _read(n, edges, seed=3):
    return E._measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)[0]


def test_the_shipped_spec_names_the_one_analysis():
    assert V.ANALYSIS_VERSION == "analysis-5.3.0"
    shipped = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                         .read_text(encoding="utf-8"))
    assert shipped["analysis_version"] == V.ANALYSIS_VERSION, "a campaign made from the shipped spec runs it"


def test_d_v_s_error_is_its_spread_over_the_sources():
    n, edges = C.uniform_random_tree(1024, seed=1)
    assert _read(n, edges)["d_V"]["se_method"]["method"] == "bootstrap over sources, the window found again in each"


def test_d_w_s_error_is_its_spread_over_the_walkers():
    n, edges = C.sierpinski_gasket(6)
    new = _read(n, edges)
    assert new["d_w"]["valid"], new["d_w"]
    adjacency = E.build_adjacency(n, edges)
    component = E.largest_component(n, adjacency)
    ball = E.volume_growth(adjacency, component, np.random.default_rng(1))["mean_ball"]
    walk = E._measure_geometry(adjacency, component, np.random.default_rng(1), ball)
    assert "source_squares" not in walk["_geometry_curves"]["walk_displacement"], "working state, not kept"
    assert new["d_w"]["se"] > 0.0


def test_a_box_exponent_carries_an_error_or_is_refused():
    n, edges = C.periodic_square_lattice(64)
    box = _read(n, edges)["d_B"]
    assert box["valid"] and math.isfinite(box["se"]) and box["se"] > 0.0
    assert not _read(*C.periodic_square_lattice(16))["d_B"]["valid"], "256 nodes hold no four radii"


def test_the_measured_error_is_kept_beside_the_wide_one_at_the_last_state():
    read = analysis._of_the_last_state({"valid": True, "d_s": 2.0, "se": 0.3, "measured_se": 0.02}, "d_s")
    assert (read["d_s"], read["se"], read["measured_se"]) == (2.0, 0.3, 0.02)
    assert "measured_se" not in analysis._of_the_last_state({"valid": True, "d_s": 2.0, "se": 0.3}, "d_s")
