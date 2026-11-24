from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.reporting import study_reading as R
from graph_scale_dynamics.scaleflow.probes import Bucket
from graph_scale_dynamics.research.every_law import every_law_table

ROOT = Path(__file__).resolve().parents[2]
T0_16 = {"zero_temperature": True, "dense_cap": 16.0, "label": "zero temperature, mean degree to 16"}
FINITE_32 = {"zero_temperature": False, "dense_cap": 32.0, "label": "finite temperature, mean degree to 32"}
POLICY = {"base_sizes": [64, 256, 1024, 4096], "deep_sizes": [16384, 65536, 262144, 1048576, 4194304],
          "deep_lane_widths": [[1048576, 4], [4194304, 1]], "plateau_from_n": 262144}


def _decision(law, at, rule, action="stop", next_n=None, when="2026-09-27T01:00:00Z", did=None):
    return {"candidate_id": law, "at_n": at, "rule": rule, "action": action, "next_n": next_n,
            "created_utc": when, "decision_id": did or f"{when}-{law}-{rule}"}


def _gate(name, withheld, through, *, salted=True, rung=256, later=None, settled=None, unsalted=None):
    return {"gate": name, "stage": "final verdict", "salted": salted, "withheld": withheld, "let_through": through,
            "by_rung": {str(rung): {"withheld": withheld, "let_through": through}},
            "let_through_later": later or {}, "settled_later_share": settled,
            "unsalted_settled_later_share_at_the_same_rungs": unsalted}


def _trajectory(law, top_bucket):
    return {"candidate_id": law, "sizes": [64, 256, 1024, 4096],
            "probe_buckets": {"d_s": [None, None, None, top_bucket]}}


def _part(root: Path, name: str, *, tree, laws, decisions, ranked, matched, trajectories, seeds=(), regime=None):
    part = root / name
    part.mkdir(parents=True)
    (part / "manifest.json").write_text(json.dumps({"cycle_state": "COMPLETE"}))
    engine = {"gate_tree": tree, "laws": laws, "laws_decided": tree["laws"], "decisions": len(decisions),
              "policy": POLICY,
              "the_record": {"decision_record": {"decisions": len(decisions), "sampled": len(decisions), "mismatches": []},
                             "draw_ledger": {"draws": 30, "admitted_share": 0.3,
                                             "refused_by_reason": {"invalid:no_sparse_phase": {"share": 0.4}}},
                             "compute_by_regime": {"by_rung": regime or {}},
                             "structure_gate": {"laws_read": 0, "why": "nothing read yet"}},
              "seeds": {"columns": ["law", "n", "seed", "simulation_seconds"], "laws": [],
                        "rows": [list(row) for row in seeds]}}
    for code, name_, body in (("28", "decision-engine", engine), ("10", "decisions", {"decisions": decisions}),
                              ("22", "stability-score", {"every_law": every_law_table(ranked), "laws_scored": len(ranked),
                                                          "control_families": {"matched": matched}}),
                              ("04", "flow", {"trajectories": trajectories})):
        (part / f"{code}-{name_}.json").write_text(json.dumps({"body": body}))
    return part


def _study(root: Path, study_id="252", built="2026-09-27T07:00:00Z", *, order=("1", "2")) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    ring, unknown, parked = "ring" + "0" * 60, "unknown" + "0" * 57, "parked" + "0" * 58
    t0 = _part(root, "campaign_1_part", tree={
        "laws": 10,
        "gates": [_gate("empty", 5, 1, later={"stopped_later": 1}, settled=0.0, unsalted=0.25),
                  _gate("too_dense", 1, 0), _gate("over_budget", 1, 0, salted=False, rung=1024)],
        "rungs": [{"n": 4096, "finished": 3, "went_on": 2, "went_on_by": {"d_s_settled": 2}},
                  {"n": 1048576, "finished": 1}]},
        laws=[{"candidate_id": ring, "action": "run_next", "rule": "d_s_settled", "at_n": 262144, "next_n": 1048576},
              {"candidate_id": unknown, "action": "hold", "rule": "deep_lane_full", "at_n": 262144,
               "next_n": 4194304}],
        decisions=[
            _decision(ring, 4096, "d_s_settled", "run_next", 16384, "2026-09-27T01:00:00Z"),
            _decision(unknown, 4096, "d_s_settled", "run_next", 16384, "2026-09-27T01:00:01Z"),
            _decision("tw" + "0" * 62, 1024, "over_budget", when="2026-09-27T01:00:02Z"),
            _decision(parked, 262144, "deep_lane_full", "hold", 1048576, "2026-09-27T02:00:00Z"),
            _decision(unknown, 262144, "deep_lane_full", "hold", 1048576, "2026-09-27T02:00:01Z"),
            _decision(ring, 262144, "deep_lane_full", "hold", 1048576, "2026-09-27T02:00:02Z"),
            _decision(parked, 262144, "reading_lost", "stop", None, "2026-09-27T02:00:03Z"),
            _decision(ring, 262144, "d_s_settled", "run_next", 1048576, "2026-09-27T03:00:00Z"),
            _decision(unknown, 262144, "d_s_settled", "run_next", 1048576, "2026-09-27T04:00:00Z"),
            _decision(unknown, 1048576, "deep_lane_full", "hold", 4194304, "2026-09-27T05:00:00Z")],
        ranked=[{"candidate_id": ring, "display_score": 100, "top_measured_rung": 262144,
                 "control_family": {"family": "periodic_ring"}},
                {"candidate_id": unknown, "display_score": 60, "top_measured_rung": 1048576,
                 "control_family": {"family": None, "ambiguous_with": []}}],
        matched={"periodic_ring": 1},
        trajectories=[_trajectory("a", None), _trajectory("b", Bucket.REFUSED_NO_SCALING_WINDOW.value),
                      _trajectory("c", Bucket.REFUSED_MEAN_DEGREE_ABOVE_WINDOW.value)],
        seeds=[("a", 64, 0, 0.5), ("a", 64, 1, 1.5), ("a", 4096, 0, 8.0)],
        regime={"zero_temperature": {"simulation:64": {"core_seconds": 3600.0},
                                     "analysis:64": {"core_seconds": 1800.0},
                                     "simulation:4096": {"core_seconds": 7200.0}}})
    finite = _part(root, "campaign_2_part", tree={
        "laws": 4, "gates": [_gate("empty", 1, 0), _gate("no_reading", 1, 1, rung=4096)],
        "rungs": [{"n": 4096, "finished": 2, "went_on": 1, "went_on_by": {"salted": 1}}]},
        laws=[], decisions=[_decision("x", 4096, "no_reading")], ranked=[], matched={},
        trajectories=[_trajectory("d", Bucket.REFUSED_CHAINS_DISAGREED.value),
                      _trajectory("e", Bucket.REFUSED_NEVER_EQUILIBRATED.value)])
    records = {"1": {"campaign_id": "1", "quadrant": T0_16, "bundle": t0.name},
               "2": {"campaign_id": "2", "quadrant": FINITE_32, "bundle": finite.name}}
    campaigns = []
    for new_id, old_id in zip(("1", "2"), order, strict=True):
        record = dict(records[old_id], campaign_id=new_id, law_budget=10000, laws_held=20 if old_id == "1" else 8,
                      state="active", created_utc="2026-09-26T21:00:00Z", report={"finished_utc": built})
        campaigns.append(record)
    (root / "study.json").write_text(json.dumps({"study_id": study_id, "built_utc": built, "build_number": 536,
                                                 "folder": f"/data/projects/GSD/{study_id}/main",
                                                 "campaigns": campaigns, "missing": []}))
    return root


def test_every_refusal_bucket_is_about_one_thing():
    refusals = {b.value for b in Bucket if b.value.startswith("REFUSED_")}
    groups = (R.GEOMETRY, R.LIMITS, R.SAMPLING)
    assert set().union(*groups) == refusals, "a refusal bucket no group names reads as 'other refusal'"
    assert sum(len(g) for g in groups) == len(refusals), "and none is in two groups"
    assert R.kind_of(None) == "read" and R.kind_of("CONVERGED") == "read"


def test_a_reading_counts_the_gates_the_base_block_and_the_cost_as_the_reports_say(tmp_path):
    reading = R.read_study(_study(tmp_path / "study"))
    assert reading["contract"] == R.READING_CONTRACT and reading["study_id"] == "252"
    t0, finite = reading["campaigns"]
    assert (t0["short"], finite["short"]) == ("T0/16", "finite/32")
    assert t0["hours"] == 10.0 and t0["laws_per_hour"] == 2
    empty = t0["gates"]["empty"]
    assert (empty["judged"], empty["share_of_decided"], empty["let_through_share"]) == (6, 0.6, round(1 / 6, 4))
    assert (empty["settled_later_share"], empty["unsalted_settled_later_share"]) == (0.0, 0.25), "Q's evidence"
    base = t0["base_block"]
    assert (base["finished"], base["d_s_settled"], base["laws_with_a_complete_block"]) == (3, 2, 3)
    assert base["d_s_at_the_top_rung"]["kinds"] == {"read": 1, "geometry": 1, "limits": 1}
    assert finite["base_block"]["d_s_at_the_top_rung"]["kinds"] == {"sampling": 2}
    assert finite["base_block"]["no_d_s_reading"] == 2, "withheld and let through at the top rung"
    assert t0["seconds_per_seed"]["64"] == {"seeds": 2, "median_seconds": 1.0, "max_seconds": 1.5}
    assert t0["core_hours_by_rung"] == {"64": 1.5, "4096": 2.0}
    assert t0["deep"]["bought"] == {"16384": 2, "1048576": 2} and t0["deep"]["deepest_finished"] == 1048576
    assert t0["families"]["d_s_settled_laws"] == {"laws": 2, "named": 1, "none": 1}
    study = reading["study"]
    assert study["salted_gates"] == {"judged": 10, "let_through": 2, "let_through_share": 0.2}, (
        "the budget in work stops no law on a judgement, so it is not salted and not counted")
    row = R.metrics(t0)
    assert (row["empty"], row["families"], row["core_hours"]) == (0.6, 1, 3.5)
    text = R.render(reading)
    assert "T0/16" in text and "finite/32" in text and "what the let-through found (Q)" in text


def test_a_lane_entry_while_others_waited_is_counted_and_a_family_ahead_is_named(tmp_path):
    lanes = R.read_study(_study(tmp_path / "study"))["campaigns"][0]["lanes"]
    one = lanes["1048576"]
    assert one["entered"] == {"laws": 2, "named": 1, "none": 1}
    assert one["waited"]["laws"] == 3, "the parked law waited too"
    assert one["entries_while_others_waited"] == 1, "the unknown law went in with no one waiting"
    assert one["family_ahead_of_a_non_family"] == 1, "the ring went in while the unknown law waited"
    assert one["in_lane_now"] == {"laws": 1, "named": 1} and one["families_through"] == ["periodic_ring"]
    four = lanes["4194304"]
    assert four["waiting_now"] == {"laws": 1, "none": 1} and four["entered"]["laws"] == 0
    assert R.metrics(R.read_study(tmp_path / "study")["campaigns"][0])["lane_1048576"] == (1, 0)


def test_two_readings_compare_by_quadrant_even_when_a_new_study_numbers_them_otherwise(tmp_path):
    before = R.read_study(_study(tmp_path / "first", built="2026-09-26T21:19:00Z"))
    after = R.read_study(_study(tmp_path / "night", study_id="253", order=("2", "1")))
    comparison = R.compare(before, after)
    assert comparison["contract"] == R.COMPARISON_CONTRACT
    assert comparison["hours_between"] == pytest.approx(9.683, abs=1e-3)
    first, second = comparison["campaigns"]
    assert (first["short"], first["before_campaign_id"]) == ("finite/32", "2"), "matched by the quadrant"
    assert (second["short"], second["before_campaign_id"]) == ("T0/16", "1")
    assert second["rows"]["laws_held"] == [20, 20] and second["rows"]["empty"] == [0.6, 0.6]
    text = R.render_comparison(comparison)
    assert "T0/16" in text and "20 -> 20" in text and "hours later" in text


def _tool():
    spec = importlib.util.spec_from_file_location("tool_read_bundle", ROOT / "tools" / "read_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_saves_a_reading_and_sets_a_later_bundle_beside_it(tmp_path, capsys):
    tool = _tool()
    first = _study(tmp_path / "first", built="2026-09-26T21:19:00Z")
    saved = tmp_path / "first.reading.json"
    assert tool.main([str(first), "--json", str(saved)]) == 0
    assert json.loads(saved.read_text())["contract"] == R.READING_CONTRACT
    capsys.readouterr()
    night = _study(tmp_path / "night")
    assert tool.main([str(night), "--against", str(saved)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("study 252 at 2026-09-27T07:00:00Z") and "->" in out
    assert "bundle campaign_" not in out, "with --against, the comparison alone"
    with pytest.raises(ValueError):
        R.load_reading(tmp_path / "first" / "study.json")
