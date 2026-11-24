from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.reporting import study_reading as R
from tests.unit.test_a_study_reads_the_same_way_every_time import _study

ROOT = Path(__file__).resolve().parents[2]
LANES = {"entries_by_route": {"1048576": {"its own reading": 2, "salt past the structure gate": 1}},
         "core_hours_by_route": {"salt past the structure gate": 2.0}, "audit_share_of_core_hours": 1.0}
THREE = {"counts": {"finite by the rule": 1, "the bulk agrees": 0, "the local d_s agrees": 0, "all three agree": 0},
         "all_three_agree": []}


def _write(part: Path, code: str, name: str, body: dict) -> None:
    (part / f"{code}-{name}.json").write_text(json.dumps({"body": body}))


def _add_the_night_s_reports(root: Path) -> Path:
    part = root / "campaign_1_part"
    engine = json.loads((part / "28-decision-engine.json").read_text())["body"]
    engine["laws"] += [{"candidate_id": "fresh" + "0" * 59, "action": "run_next", "rule": "base_block",
                        "at_n": 256, "next_n": 1024}]
    engine["the_record"]["structure_by_the_committed_rule"] = {
        "finite": [{"candidate_id": "chain" + "0" * 59, "implied_spectral_dimension": 2.6}], "three_readings": THREE}
    engine["lanes"] = LANES
    _write(part, "28", "decision-engine", engine)
    decisions = json.loads((part / "10-decisions.json").read_text())["body"]["decisions"]
    decisions += [{"candidate_id": f"new{i}", "rule": "start", "action": "run_next", "next_n": 64,
                   "created_utc": f"2026-09-26T{21 + (i % 3):02d}:10:00Z", "decision_id": f"s{i}"} for i in range(9)]
    decisions += [{"candidate_id": "salted" + "0" * 58, "rule": "d_s_settled", "action": "run_next",
                   "next_n": 1048576, "created_utc": "2026-09-27T05:30:00Z", "decision_id": "z1",
                   "reason": "d_s settled; salted past the structure gate, which would refuse: ..."},
                  {"candidate_id": "longer" + "0" * 58, "rule": "longer_chain", "action": "run_next", "at_n": 4096,
                   "next_n": 4096, "created_utc": "2026-09-27T05:40:00Z", "decision_id": "z2"},
                  {"candidate_id": "longer" + "0" * 58, "rule": "no_reading", "action": "stop", "at_n": 4096,
                   "created_utc": "2026-09-27T05:50:00Z", "decision_id": "z3"}]
    _write(part, "10", "decisions", {"decisions": decisions})
    _write(part, "14", "compute", {"work_supply_health": {"candidates_with_live_job_analysis_or_rebuild": 48},
                                   "queued_simulation_claimability": {"by_reason": {"claimable": {
                                       "by_n": {"65536": 85, "4194304": 3}}}}})
    cells = {"64": {"mean_degree": 2.0, "d_s": None, "d_s_bucket": "REFUSED_NO_SCALING_WINDOW"},
             "1024": {"mean_degree": 2.1, "d_s": 1.0, "d_s_bucket": None, "connected_fraction": 1.0},
             "4096": {"mean_degree": 2.1, "d_s": 1.02, "d_s_bucket": None, "connected_fraction": 1.0},
             "16384": {"mean_degree": 5.0, "d_s": 3.9, "d_s_bucket": "REFUSED_CHAINS_DISAGREED",
                       "connected_fraction": 1.0},
             "65536": {"mean_degree": 2.1, "d_s": 1.01, "d_s_bucket": None, "connected_fraction": 1.0},
             "262144": {"mean_degree": 2.1, "d_s": 1.0, "d_s_bucket": None, "connected_fraction": 1.0}}
    phenotype = {"base_sizes": [64, 1024, 4096], "extension_sizes": [16384, 65536, 262144],
                 "per_n": {k: cells[k] for k in ("64", "1024", "4096")},
                 "extension_per_n": {k: cells[k] for k in ("16384", "65536", "262144")},
                 "half_volume_radius_vector": [3.0, 20.0, 21.0],
                 "extension_half_volume_radius_vector": [22.0, 23.0, 24.0]}
    _write(part, "05", "phenotypes", {"specimens": [{"candidate_id": "chain" + "0" * 59, "phenotype": phenotype}]})
    return root


def test_a_reading_carries_pace_the_admission_window_and_the_routes_into_the_deep_rungs(tmp_path):
    reading = R.read_study(_add_the_night_s_reports(_study(tmp_path / "bundle")))
    t0 = reading["campaigns"][0]
    assert reading["contract"] == R.READING_CONTRACT
    assert t0["pace"]["first_hour_laws"] == 3 and t0["pace"]["first_hour"] == "2026-09-26T21"
    assert t0["admission"] == {"laws_in_their_base_block": 1, "laws_with_live_work": 48,
                               "queued_by_n": {"65536": 85, "4194304": 3}}
    assert t0["deep_routes"] == dict(LANES, source="report 28")
    assert t0["longer_chains"] == {"bought": 1, "next": {"parked: still no reading": 1}}


def test_d_s_is_counted_by_the_mean_degree_its_chain_had_and_a_refused_value_is_not_a_reading(tmp_path):
    t0 = R.read_study(_add_the_night_s_reports(_study(tmp_path / "bundle")))["campaigns"][0]
    table = t0["d_s_by_mean_degree"]
    assert table["2-4"]["law_rungs"] == 5 and table["2-4"]["read_share"] == 0.8, "the 64 rung refused"
    assert table["4-8"] == {"law_rungs": 1, "read_share": 0.0, "median": None, "p95": None}, \
        "a value the given chains' disagreement refused is not a reading"


def test_the_three_readings_find_a_chain_the_rule_reads_finite(tmp_path):
    t0 = R.read_study(_add_the_night_s_reports(_study(tmp_path / "bundle")))["campaigns"][0]
    assert t0["three_readings"] == dict(THREE, source="report 28")
    assert R.metrics(t0)["finite_three"] == (1, 0)
    assert R._three_readings({}) == {} and R._deep_routes({}) == {}, "a bundle without them reads none"
