from __future__ import annotations

from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.services.api import landscape_worker as W

FOUR = ["d_s", "d_V", "d_B", "d_w"]


def _point(d_s, d_V, d_B, d_w, settled=FOUR):
    return {"d_s_estimate": d_s, "d_v_estimate": d_V, "d_b_estimate": d_B, "d_w_estimate": d_w,
            "stability_contracting_probes": list(settled)}


def test_the_fifth_band_is_four_settled_probes_agreeing_by_the_einstein_relation():
    assert W.LANDSCAPE_BANDS[0] == W.BAND_EINSTEIN and W.BAND_EINSTEIN in W.SETTLED_BANDS
    lattice = _point(3.0, 3.0, 2.95, 2.0)
    assert W.landscape_band(lattice) == W.BAND_EINSTEIN and lattice["einstein"]["tau"] == L.tau()
    gasket = _point(1.365, 1.585, 1.585, 2.322)
    assert W.landscape_band(gasket) == W.BAND_EINSTEIN, "a fractal agrees by the relation as a space does"
    apart = _point(3.0, 3.0, 3.0, 2.6)
    assert W.landscape_band(apart) == W.BAND_TIER4 and apart["einstein"]["agree"] is False
    assert W.landscape_band(_point(3.0, 3.0, 3.0, 2.0, FOUR[:3])) == W.BAND_TIER3, "three settled is no fifth band"
    assert W.landscape_band(_point(3.0, None, 3.0, 2.0)) == W.BAND_TIER4, "a probe not read is no agreement"
