from __future__ import annotations

from pathlib import Path

import pytest

from graph_scale_dynamics.research.probe_atlas import TOLERANCES, _from_n_onward, build_probe_atlas
from graph_scale_dynamics.research.survey_reports import build_fleet_and_host

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def atlas():
    from tests.support.calibration_table import require_table
    return build_probe_atlas(require_table())


def test_every_probe_has_a_trust_by_n_series_and_a_verdict(atlas):
    for probe in ("d_s", "d_V", "d_B", "d_w"):
        a = atlas["probes"][probe]
        assert a["trust_by_n"] and all("worst_error" in r for r in a["trust_by_n"])
        assert a["high_n_trust"] in ("converges", "plateaus_on_some_families", "mixed")
        assert set(a["first_n_with_worst_error_below"]) == {f"{t:g}" for t in TOLERANCES}


def test_from_n_onward_requires_staying_inside():
    series = [(64, 0.5), (256, 0.05), (1024, 0.4), (4096, 0.03), (16384, 0.02)]
    assert _from_n_onward(series, 0.1) == 4096
    assert _from_n_onward(series, 0.01) is None
    assert _from_n_onward(series, 1.0) == 64


def test_the_atlas_says_what_the_table_says(atlas):
    d_s = atlas["probes"]["d_s"]["verdicts"]
    assert sorted(f for f, v in d_s.items() if v == "PLATEAU_BIASED") == [], "d_s is biased on no family it reads"
    assert d_s["uniform_random_tree"] == "IMPROVES_WITH_N" and atlas["probes"]["d_s"]["high_n_trust"] == "converges"
    d_b = atlas["probes"]["d_B"]
    assert d_b["verdicts"]["sierpinski_gasket"] == d_b["verdicts"]["uniform_random_tree"] == "IMPROVES_WITH_N"
    assert d_b["verdicts"]["periodic_hypercubic_lattice_4d"] == "PLATEAU_BIASED", "3.75 of 4 at 1,048,576 nodes"
    assert d_b["high_n_trust"] == "plateaus_on_some_families"
    anchor = atlas["probes"]["d_s"]["refusal_anchor"]["random_4_regular"]
    assert anchor["refused"] == anchor["seeds"] > 0, "refused on every seed at every size"


def test_fleet_report_attributes_live_compute_across_campaigns():
    r = build_fleet_and_host({
        "campaign_id": "2",
        "host_jobs_by_campaign": [{"campaign_id": "1", "n": 4096, "status": "leased", "c": 10},
                                  {"campaign_id": "2", "n": 16384, "status": "leased", "c": 6},
                                  {"campaign_id": "2", "n": 16384, "status": "queued", "c": 40}],
        "attempts": [], "telemetry_trend": [], "jobs": [], "telemetry": {},
    })
    assert r["campaigns_sharing_the_fleet"] == 2
    assert r["home_leased_share"] == pytest.approx(6 / 16)
    assert r["live_compute_by_campaign"][0]["campaign_id"] == "1"


def test_a_family_s_trend_and_its_accuracy_at_the_top_are_said_apart():
    from graph_scale_dynamics.research.probe_atlas import at_the_top, trend_of
    improving_into_noise = {"early_median_drift": 0.048, "late_median_drift": 0.007, "late_median_spread": 0.069}
    assert trend_of(improving_into_noise) == "improves with N", "the cubic lattice's d_s was called flat"
    assert at_the_top(improving_into_noise) == "within its seeds' spread"
    biased = {"early_median_drift": 0.14, "late_median_drift": 0.116, "late_median_spread": 0.004}
    assert trend_of(biased) == "steady" and at_the_top(biased) == "off by 0.116"
    assert trend_of({"early_median_drift": 0.01, "late_median_drift": 0.05}) == "worsens with N"
    assert trend_of({}) is None and at_the_top({}) is None
    assert at_the_top({"late_median_drift": 0.0002, "late_median_spread": 0.0001}) == "on the answer to 0.001", (
        "the square lattice's d_V read 'off by 0.000'")


def test_every_measured_family_of_the_seed_table_has_a_trend_and_an_accuracy():
    import json
    from pathlib import Path
    from graph_scale_dynamics.research.probe_atlas import build_probe_atlas
    table = json.loads((Path(__file__).resolve().parents[2] / "calibration" / "seed_table.json").read_text())
    atlas = build_probe_atlas(table)
    cubic = atlas["probes"]["d_s"]["families"]["periodic_cubic_lattice"]
    assert cubic["trend"] == "improves with N" and cubic["at_the_top"] == "within its seeds' spread"
    for probe, body in atlas["probes"].items():
        for family, entry in body["families"].items():
            if entry.get("late_median_drift") is not None:
                assert entry["trend"] and entry["at_the_top"], (probe, family)
