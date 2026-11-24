from __future__ import annotations

import pytest

from graph_scale_dynamics.scaleflow.probes import PROBES
from graph_scale_dynamics.services.api.landscape_worker import (
    BAND_EINSTEIN, BAND_FLOWING, BAND_TIER2, BAND_TIER3, BAND_TIER4, LANDSCAPE_BANDS, contracting_tier, landscape_band)


def _row(probes=(), **extra) -> dict:
    return {"stability_contracting_probes": list(probes), **extra}


def test_a_four_probe_law_is_never_dropped():
    all_four = _row(PROBES)
    assert contracting_tier(all_four) == 4
    band = landscape_band(all_four)
    assert band in LANDSCAPE_BANDS, f"a four-probe law was assigned {band!r}, which is not a band"
    assert band == BAND_TIER4, (
        "a law that settled on all four probes was not drawn in the all-four band. "
        "This is the single result the "
        "survey exists to find and it must not be the one row the chart drops."
    )
    assert landscape_band(_row(PROBES[:3])) == BAND_TIER3


def test_every_tier_lands_in_a_real_band():
    for count in range(len(PROBES) + 1):
        band = landscape_band(_row(PROBES[:count]))
        assert band in LANDSCAPE_BANDS, f"tier {count} resolved to {band!r}"


def test_the_ladder_never_demotes_a_law_for_settling_one_more_probe():
    rank = {band: i for i, band in enumerate(LANDSCAPE_BANDS)}
    seen = [rank[landscape_band(_row(PROBES[:count]))] for count in range(len(PROBES) + 1)]
    assert seen == sorted(seen, reverse=True), (
        f"band index by tier is {seen}; a law moved down the chart by settling "
        "one more probe"
    )


def test_the_tier_is_not_the_score_divided_by_twenty_five():
    proportional = _row([], stability_score=72.0,
                        stability_buckets={p: "STILL_DRIFTING" for p in PROBES})
    assert contracting_tier(proportional) == 0
    assert landscape_band(proportional) == BAND_FLOWING, (
        "a law scoring 72 from four partial blocks was placed in a tier band. "
        "The tier comes from the buckets, never from score/25."
    )


def test_a_law_with_nothing_settled_is_flowing():
    assert landscape_band(_row([])) == BAND_FLOWING
    assert landscape_band({}) == BAND_FLOWING


@pytest.mark.parametrize("pair,tier", [
    (("d_s", "d_B"), 2),
    (("d_s", "d_w"), 2),
    (("d_V", "d_B"), 2),
])
def test_the_pair_is_carried_even_though_the_band_counts(pair, tier):
    row = _row(pair)
    assert contracting_tier(row) == tier
    assert landscape_band(row) == BAND_TIER2
    assert tuple(row["stability_contracting_probes"]) == pair


def test_the_projection_carries_the_tier_and_it_agrees_with_the_probe_list():
    from graph_scale_dynamics.services.api.landscape_worker import stability_fields

    buckets = {"d_s": "CONVERGED", "d_V": "STILL_DRIFTING",
               "d_B": "CONVERGED", "d_w": "NOT_ATTEMPTED"}
    fields = stability_fields({
        "score": 50.0, "display_score": 50, "approach": 0.5, "approach_score": 50.0,
        "approach_is_provisional": False, "score_status": "base", "buckets": buckets,
        "valid_rungs": {}, "evidence": {"measured_base_rungs": 5},
    })
    assert fields["stability_contracting_probes"] == ["d_s", "d_B"]
    assert fields["stability_contracting_tier"] == 2
    assert landscape_band(fields) == BAND_TIER2


def test_the_band_names_are_distinct_and_ordered_deepest_first():
    assert len(set(LANDSCAPE_BANDS)) == len(LANDSCAPE_BANDS)
    assert LANDSCAPE_BANDS[:3] == (BAND_EINSTEIN, BAND_TIER4, BAND_TIER3), "the 5th band is the deepest (783)"
    assert LANDSCAPE_BANDS[-1] == BAND_FLOWING
