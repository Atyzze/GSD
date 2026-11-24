from __future__ import annotations

from pathlib import Path
from graph_scale_dynamics.measurements import analysis


ROOT = Path(__file__).resolve().parents[2]


def test_rung_payload_publishes_every_dimension_channel():
    from graph_scale_dynamics.scaleflow.flow import SUMMARY_OBSERVABLES, summary_dimensions
    from graph_scale_dynamics.services.api.overview import _published_channels, _published_dims

    assert SUMMARY_OBSERVABLES == ("d_s", "d_V", "d_B", "d_w")
    stored = {name: {"mean": 1.5} for name in SUMMARY_OBSERVABLES}
    stored |= {f"{name}_valid_fraction": 1.0 for name in SUMMARY_OBSERVABLES}

    published = _published_dims(stored)
    for name in SUMMARY_OBSERVABLES:
        assert published[name] == 1.5, f"{name} is missing from the rung payload"
        assert published[f"{name}_valid"] == 1.0

    assert published["d_V"] == 1.5
    assert [c["channel"] for c in _published_channels(stored)] == list(SUMMARY_OBSERVABLES)
    assert summary_dimensions(stored)["d_V"] == 1.5


def test_a_stored_channel_the_estimator_could_not_emit_is_withheld_with_a_reason():
    from graph_scale_dynamics.scaleflow.flow import summary_dimensions
    from graph_scale_dynamics.scaleflow.observables import IMPLAUSIBLE_ABOVE

    channel, ceiling = next(iter(IMPLAUSIBLE_ABOVE.items()))
    values = summary_dimensions({channel: {"mean": ceiling * 10}})
    assert values[channel] is None
    assert channel in values["withheld_implausible"]


FOUR_CHANNELS = ("d_s", "d_V", "d_B", "d_w")


def _torus(side: int = 32):
    from graph_scale_dynamics.measurements import calibration as cal
    n, edges = cal.periodic_square_lattice(side)
    return n, edges


def _envelope(n, edges, late: bool = False):
    from tests.support import chains as SC
    return SC.envelope(n, SC.chain(
        "empty", final={"edge_count": len(edges), "mean_degree": 2 * len(edges) / n, "max_degree": 4, "energy": 0.0},
        block={"edge_list": [list(e) for e in edges], "trajectory": [],
               "late_change": {"contract": "late-change-1", "from_move": 1000, "added": [list(edges[0])],
                               "removed": []} if late else None}))


def test_measurement_pass_computes_all_four_channels():
    from graph_scale_dynamics.measurements.analysis import analyze_envelope
    metrics, curves = analyze_envelope(_envelope(*_torus()), seed=1)
    for channel in FOUR_CHANNELS:
        assert metrics[channel]["valid"] is True, (channel, metrics[channel])
    assert metrics["geometry_snapshot_mode"] == "final_state_only", "a chain is read at its end, all four channels"
    assert {"box_covering", "walk_displacement"} <= set(curves), "the geometry curves are kept with d_s's and d_V's"


def test_box_exponent_is_withheld_when_the_power_law_precondition_fails(monkeypatch):
    import numpy as np

    from graph_scale_dynamics.measurements import box_covering, estimators
    monkeypatch.setattr(box_covering, "fit_box_dimension",
                        lambda profile: {"valid": True, "box_covering_exponent": 2.3, "power_law_preferred": False,
                                         "se": 0.1})
    n, edges = _torus()
    adj = estimators.build_adjacency(n, edges)
    component = estimators.largest_component(n, adj)
    ball = estimators.volume_growth(adj, component, np.random.default_rng(1))["mean_ball"]
    out = estimators._measure_geometry(adj, component, np.random.default_rng(1), ball)
    assert out["d_B"]["valid"] is False and out["d_B"]["refusal"] == "NOT_POWER_LAW"
    assert out["d_B"]["would_have_reported"] == 2.3 and "power-law" in out["d_B"]["reason"]
    monkeypatch.setattr(box_covering, "fit_box_dimension",
                        lambda profile: {"valid": True, "box_covering_exponent": 2.0, "power_law_preferred": True,
                                         "se": 0.1})
    kept = estimators._measure_geometry(adj, component, np.random.default_rng(1), ball)
    assert kept["d_B"] == {"valid": True, "d_B": 2.0, "se": 0.1, "power_law_preferred": True}


def test_the_geometry_is_measured_once_on_the_last_state_and_recorded(monkeypatch):
    from graph_scale_dynamics.measurements import estimators
    calls = []
    real = estimators._measure_graph

    def counted(*args, measure_geometry=False, **kwargs):
        calls.append(measure_geometry)
        return real(*args, measure_geometry=measure_geometry, **kwargs)

    monkeypatch.setattr(analysis, "_measure_graph", counted)
    metrics, _ = analysis.analyze_envelope(_envelope(*_torus(), late=True), seed=1)
    assert calls == [True] and metrics["geometry_snapshot_mode"] == "final_state_only", "a chain is read at its end"
    assert metrics["snapshot_selection"]["configurations"] == 1 and metrics["d_s"]["snapshots"]["k"] == 1
    assert metrics["snapshot_selection"] == {"contract": "final-chunk-2", "configurations": 1}
    assert metrics["d_B"]["valid"] is True, "the final state carries the channel"


def test_unmeasured_geometry_is_reported_rather_than_omitted(monkeypatch):
    from graph_scale_dynamics.measurements import estimators
    real = estimators._measure_graph
    monkeypatch.setattr(analysis, "_measure_graph",
                        lambda *a, measure_geometry=False, **k: real(*a, measure_geometry=False, **k))
    metrics, _ = analysis.analyze_envelope(_envelope(*_torus()), seed=1)
    for channel in ("d_B", "d_w"):
        assert metrics[channel] == {"valid": False, "refusal": "NOT_MEASURED", "reason": "geometry channels not measured",
                                    "small_world": metrics[channel].get("small_world")}, metrics[channel]
    assert metrics["geometry_snapshot_mode"] == "not_measured"


def test_geometry_channels_cannot_perturb_the_existing_estimators():
    import numpy as np

    from graph_scale_dynamics.measurements import estimators
    n, edges = _torus()
    without_rng, with_rng = np.random.default_rng(5), np.random.default_rng(5)
    without, _ = estimators._measure_graph(n, edges, without_rng, measure_geometry=False)
    with_geometry, _ = estimators._measure_graph(n, edges, with_rng, measure_geometry=True)
    assert with_geometry["d_B"]["valid"] and with_geometry["d_w"]["valid"], "the channels were measured"
    assert with_geometry["d_s"] == without["d_s"] and with_geometry["d_V"] == without["d_V"]
    assert with_rng.random() == without_rng.random(), "the caller's generator is left where it was"


def test_dev_mode_is_off_by_default_and_always_stamped():
    from graph_scale_dynamics.operations import dev_mode
    import os

    assert dev_mode.enabled() is False
    assert dev_mode.provenance()["certified_run"] is True
    previous = os.environ.get("GSD_DEV_MODE")
    os.environ["GSD_DEV_MODE"] = "1"
    try:
        stamp = dev_mode.provenance()
        assert stamp["certified_run"] is False
        assert stamp["warning"] and "not a certified run" in stamp["warning"].lower()
        assert dev_mode.stamp({"body": 1})["run_mode"]["development_mode"] is True
    finally:
        if previous is None:
            del os.environ["GSD_DEV_MODE"]
        else:
            os.environ["GSD_DEV_MODE"] = previous


def test_stored_implausible_exponent_is_filtered_on_read():
    from graph_scale_dynamics.scaleflow.flow import summary_dimensions

    legacy = summary_dimensions({
        "d_w": {"mean": 280.4}, "d_s": {"mean": 2.05},
        "d_w_valid_fraction": 1.0,
    })
    assert legacy["d_w"] is None
    assert legacy["d_s"] == 2.05, "an unrelated channel must not be collateral"
    assert "d_w" in legacy["withheld_implausible"]


def test_the_filter_bound_is_derived_from_the_estimator_not_chosen():
    from graph_scale_dynamics.measurements.walk_dimension import SLOWEST_SPREAD
    from graph_scale_dynamics.scaleflow.observables import IMPLAUSIBLE_ABOVE

    largest_emittable = 2.0 / SLOWEST_SPREAD

    assert largest_emittable < IMPLAUSIBLE_ABOVE["d_w"], (
        "the ceiling must sit above what the estimator can legitimately emit"
    )
    assert IMPLAUSIBLE_ABOVE["d_w"] < 2 * largest_emittable, (
        "the ceiling is far looser than the estimator requires; it would let "
        "pre-fix records through"
    )


def test_plausible_values_are_untouched_by_the_filter():
    from graph_scale_dynamics.scaleflow.flow import summary_dimensions

    for value in (1.97, 2.31, 4.51, 6.20, 13.9):
        row = summary_dimensions({"d_w": {"mean": value}})
        assert row["d_w"] == round(value, 3), value
        assert "withheld_implausible" not in row


def test_every_channel_has_a_declared_ceiling():
    from graph_scale_dynamics.scaleflow.flow import SUMMARY_OBSERVABLES
    from graph_scale_dynamics.scaleflow.observables import IMPLAUSIBLE_ABOVE

    assert set(SUMMARY_OBSERVABLES) == set(IMPLAUSIBLE_ABOVE)


def test_the_base_block_is_one_number_and_depth_adds_segments():
    from graph_scale_dynamics.domain.model import ensemble_code

    base = {64: 917, 256: 918, 1_024: 919, 4_096: 920}
    assert ensemble_code(base) == "G-917"
    assert ensemble_code(base | {16_384: 1_043}) == "G-917"
    assert ensemble_code(base | {16_384: 1_043, 65_536: 1_108}) == "G-917"


def test_a_scrambled_base_block_still_resolves_to_one_stable_code():
    from graph_scale_dynamics.domain.model import ensemble_code

    assert ensemble_code({64: 922, 256: 917, 1_024: 920, 4_096: 921}) == "G-917"


def test_a_partially_started_block_already_has_its_final_code():
    from graph_scale_dynamics.domain.model import ensemble_code

    assert ensemble_code({64: 917, 256: 918}) == "G-917"
    assert ensemble_code({64: 917, 256: 918, 1_024: 919, 4_096: 920}) == "G-917"
    assert ensemble_code({}) is None


def test_the_hash_remains_the_exact_identity():
    from graph_scale_dynamics.domain.model import candidate_id

    left = candidate_id({"terms": [{"op": "edge", "c": 0.5}]})
    right = candidate_id({"terms": [{"op": "edge", "c": 0.5}]})
    other = candidate_id({"terms": [{"op": "edge", "c": 0.6}]})
    assert left == right and left != other
    assert len(left) == 64


_NOT_THE_TREE = {".git", ".venv", "venv", "node_modules", "build", "dist",
                 "instance", "var", "htmlcov", "__pycache__"}


def test_no_orphan_html_ships():
    served = {"index.html", "candidate.html"}
    found = {p.name for p in ROOT.rglob("*.html")
             if not _NOT_THE_TREE.intersection(p.relative_to(ROOT).parts)}
    assert found == served, f"unreachable HTML in the tree: {sorted(found - served)}"
