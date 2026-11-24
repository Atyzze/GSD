from __future__ import annotations

from graph_scale_dynamics.research import landscape_audit, report_pipeline
from graph_scale_dynamics.research.decision_explanation import candidate_decision_trails

BASE = [64, 256, 1024, 4096]


def _phenotype(connected: float, d: float = 2.0, drift: float = 0.0) -> dict:
    values = {probe: [d + drift * i for i in range(len(BASE))] for probe in ("d_s", "d_V", "d_B", "d_w")}
    return {"base_sizes": list(BASE), "probe_vectors": values,
            "probe_se_vectors": {probe: [0.05] * len(BASE) for probe in values},
            "per_n": {str(n): {"mean_degree": 4.0, "connected_fraction": connected} for n in BASE},
            "connected_fraction_vector": [connected] * len(BASE)}


def _snapshot(floor: float | None) -> dict:
    spec = {"limits": {"connectivity_floor": floor}} if floor is not None else {}
    phenotypes = [{"candidate_id": "law-a", "phenotype": _phenotype(0.8)},
                  {"candidate_id": "law-b", "phenotype": _phenotype(1.0, drift=0.4)}]
    return {"campaign_id": "1", "campaign": {"spec": spec}, "phenotypes": phenotypes,
            "candidates": [{"candidate_id": p["candidate_id"], "spec": {}} for p in phenotypes],
            "engine_decisions": {}}


def test_a_report_reads_the_campaign_s_floor():
    snapshot = _snapshot(0.5)
    assert landscape_audit.snapshot_connectivity_floor(snapshot) == 0.5
    assert landscape_audit.snapshot_connectivity_floor({}) == landscape_audit.CONNECTIVITY_FLOOR
    rows = {r["candidate_id"]: r for r in landscape_audit.snapshot_landscape_rows(snapshot)}
    assert rows["law-a"]["connectivity"]["floor"] == 0.5
    assert rows["law-a"]["connectivity"]["classification"] != "FAILED_FLOOR", "0.8 is above the campaign's floor"
    assert rows["law-a"]["dimensional_class"] != "REFUSED_BELOW_CONNECTIVITY_FLOOR"
    default = {r["candidate_id"]: r for r in landscape_audit.snapshot_landscape_rows(_snapshot(None))}
    assert default["law-a"]["connectivity"]["classification"] == "FAILED_FLOOR"


def test_reports_05_and_10_class_each_law_alike():
    snapshot = _snapshot(0.5)
    one = {r["candidate_id"]: r["dimensional_class"] for r in landscape_audit.snapshot_landscape_rows(snapshot)}
    e = report_pipeline._report_e(snapshot)
    assert {sp["candidate_id"]: sp["dimensional_class"] for sp in e["specimens"]} == one
    snapshot["engine_decisions"] = {"law-a": [{"decision_id": "1", "rule": "ladder_complete", "at_n": 4096}]}
    trails = candidate_decision_trails(snapshot)
    assert all(t["dimensional_class"] == one[t["candidate_id"]] for t in trails["trails"])
    audit = landscape_audit.build_landscape_audit(snapshot)
    assert audit["scope_and_completeness"]["connectivity_floor"] == 0.5
    assert audit["connectivity_viability"]["contract"]["floor"] == 0.5
