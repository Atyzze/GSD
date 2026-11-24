from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import study_twice as T  # noqa: E402


def _table(rows: list[dict]) -> bytes:
    return gzip.compress(b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in rows), mtime=0)


DECISION = {"campaign_id": "1", "candidate_id": "law-a", "decision_id": "d-17", "at_n": 1024, "next_n": 4096,
            "action": "run_next", "rule": "base_block", "created_utc": "2026-11-21T10:00:00Z",
            "facts_json": json.dumps({"chains": {"empty": {"mean_degree": 3.5}}, "measured_utc": "x",
                                      "chain_seconds": 4.0}),
            "inputs_json": json.dumps({"policy": {"dense_cap": 32.0}})}


def _bundle(decisions: list[dict], laws: list[dict], *, extra: dict | None = None) -> dict:
    members = {"tables/decisions.ndjson.gz": _table(decisions), "tables/laws.ndjson.gz": _table(laws),
               "study.json": json.dumps({"study_id": "172", "built_utc": "t", "campaigns": [{"laws": len(laws)}]}
                                        ).encode("utf-8"),
               "index.html": b"<html>"}
    members.update(extra or {})
    return members


def test_the_host_s_own_fields_are_left_out_and_the_order_of_rows_does_not_matter():
    laws = [{"campaign_id": "1", "candidate_id": "law-a", "state": "DONE"},
            {"campaign_id": "1", "candidate_id": "law-b", "state": "STOPPED"}]
    later = dict(DECISION, decision_id="d-99", created_utc="2026-11-22T00:00:00Z",
                 facts_json=json.dumps({"chains": {"empty": {"mean_degree": 3.5}}, "measured_utc": "y",
                                        "chain_seconds": 9.0}))
    found = T.compare_bundles(_bundle([DECISION], laws), _bundle([later], list(reversed(laws))))
    assert found["same"], found
    assert found["pages"] == 1 and found["tables"]["tables/laws.ndjson.gz"]["rows"] == [2, 2]


def test_a_science_field_that_differs_is_named_with_its_row():
    moved = dict(DECISION, facts_json=json.dumps({"chains": {"empty": {"mean_degree": 3.75}}}), at_n=1024)
    found = T.compare_bundles(_bundle([DECISION], []), _bundle([moved], []))
    table = found["tables"]["tables/decisions.ndjson.gz"]
    assert not found["same"] and not table["same"]
    assert table["fields_differ"] == {"facts_json.chains.empty.mean_degree": 1}, table
    assert table["example"]["first"] == "3.5" and table["example"]["second"] == "3.75"


def test_a_size_is_compared_and_never_taken_for_a_time():
    assert not T.host_key("at_n") and not T.host_key("next_n") and not T.host_key("measured_se")
    assert T.host_key("created_utc") and T.host_key("chain_seconds") and T.host_key("seed_peak_memory_bytes")
    assert T.host_key("decided_at") and T.host_key("job_id")
    other = dict(DECISION, at_n=256)
    found = T.compare_bundles(_bundle([DECISION], []), _bundle([other], []))
    assert not found["same"]
    table = found["tables"]["tables/decisions.ndjson.gz"]
    assert table["only_first"] and table["only_second"], table


def test_a_member_in_one_bundle_alone_or_a_document_that_moved_makes_them_differ():
    found = T.compare_bundles(_bundle([], []), _bundle([], [], extra={"finds.json": b"{}"}))
    assert not found["same"] and found["only_second"] == ["finds.json"]
    first = _bundle([], [], extra={"gates_ledger.json": json.dumps({"gates": {"empty": 3}}).encode("utf-8")})
    second = _bundle([], [], extra={"gates_ledger.json": json.dumps({"gates": {"empty": 4}}).encode("utf-8")})
    found = T.compare_bundles(first, second)
    assert not found["same"] and found["documents"]["gates_ledger.json"]["fields_differ"] == ["gates.empty"]


def test_the_short_study_is_172_s_design_cut_to_its_laws_and_sizes():
    from graph_scale_dynamics.operations import study_design
    design = study_design.design_for(ROOT, "172")
    short = T.short_design(design, laws=4, sizes=(64, 256, 1024), seeds=3)
    assert short["law_budget"] == 4 and short["ladder"]["base"] == [64, 256, 1024] and short["ladder"]["deep"] == []
    assert short["ladder"]["budgets"] == [[n, u] for n, u in design["ladder"]["budgets"] if n <= 1024]
    for key in ("search_seeds", "engine", "starts", "limits", "campaigns", "sha256", "path"):
        assert short[key] == design[key], key
    assert design["law_budget"] == 2500 and design["ladder"]["deep"], "the design itself is left as it was"


def test_a_bundle_s_members_are_named_without_its_stem_and_each_part_by_its_campaign(tmp_path):
    from graph_scale_dynamics.reporting.study_bundle import _write_tar_zstd
    target = tmp_path / "study_172_x.tar.zst"
    _write_tar_zstd(target, [("study_172_2026-11-21T14-14-05Z/study.json", b"{}"),
                             ("study_172_2026-11-21T14-14-05Z/campaign_2_reports_2026-11-21T14-14-05Z_d1bf2214/"
                              "28-decision-engine.json", b"{}")])
    assert sorted(T.members(target)) == ["campaign_2/28-decision-engine.json", "study.json"]


def test_a_table_s_host_columns_the_host_s_reports_and_the_order_of_a_list_of_laws_are_left_out():
    seeds = {"columns": ["law", "n", "simulation_seconds", "cpu", "final_mean_degree"],
             "rows": [["law-a", 64, 4.05, 1, 3.5]]}
    ranked = [{"candidate_id": "law-a", "core_seconds": 9.0}, {"candidate_id": "law-b", "core_seconds": 4.0}]
    first = {"campaign_1/28-decision-engine.json": json.dumps({"body": {"seeds": seeds, "ranked": ranked}}).encode(),
             "campaign_1/14-compute.json": b'{"telemetry": 1}'}
    later = {"columns": seeds["columns"], "rows": [["law-a", 64, 3.30, 0, 3.5]]}
    second = {"campaign_1/28-decision-engine.json": json.dumps(
        {"body": {"seeds": later, "ranked": list(reversed(ranked))}}).encode(),
        "campaign_1/14-compute.json": b'{"telemetry": 2}'}
    found = T.compare_bundles(first, second)
    assert found["same"] and found["host_reports"] == 1, found
    moved = {"columns": seeds["columns"], "rows": [["law-a", 64, 4.05, 1, 3.75]]}
    third = {"campaign_1/28-decision-engine.json": json.dumps({"body": {"seeds": moved, "ranked": ranked}}).encode(),
             "campaign_1/14-compute.json": b'{"telemetry": 1}'}
    found = T.compare_bundles(first, third)
    assert found["documents"]["campaign_1/28-decision-engine.json"]["fields_differ"] == ["body.seeds.rows[][]"]
