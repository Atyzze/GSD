from __future__ import annotations

from graph_scale_dynamics.calibration.rekey import (
    CHANNEL_FIELDS, EVIDENCE_FIELDS, IGNORED_FIELDS, choose_sample, compare_cell,
    predicted_wall_seconds, rekey_document, sample_coverage)
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION


def _cell(family="periodic_ring", n=1024, seed=0, d_s=1.02, elapsed=0.4,
          fingerprint="old0000000000000", reason=None):
    return {
        "family": family, "parameter": n, "seed": seed, "n": n, "analysis": ANALYSIS_VERSION,
        "component": n, "status": "ok", "graph_varies_per_seed": False,
        "cell_fingerprint": fingerprint, "science_fingerprint": "sci-old",
        "computed_utc": "2026-09-09T07:43:00Z", "host": "box",
        "elapsed_seconds": elapsed,
        "channels": {
            "d_s": {"valid": True, "value": d_s, "se": 0.01, "reason": None},
            "d_V": {"valid": True, "value": 1.0, "se": 0.02, "reason": None},
            "d_B": {"valid": False, "value": None, "se": None,
                    "reason": reason or "not a power law"},
            "d_w": {"valid": True, "value": 2.0, "se": 0.03, "reason": None},
        },
    }


def test_an_identical_recompute_compares_clean():
    assert compare_cell(_cell(), _cell()) == []


def test_provenance_and_timing_are_not_evidence():
    fresh = _cell(elapsed=9.9, fingerprint="new0000000000000")
    fresh["computed_utc"] = "2026-09-12T03:41:25Z"
    fresh["host"] = "other-host"
    fresh["science_fingerprint"] = "sci-new"
    assert compare_cell(_cell(), fresh) == []
    for field in IGNORED_FIELDS:
        assert field not in EVIDENCE_FIELDS


def test_a_moved_probe_value_is_caught():
    diffs = compare_cell(_cell(d_s=1.02), _cell(d_s=1.07))
    assert any(d.startswith("d_s.value") for d in diffs)


def test_a_refusal_that_changes_its_reason_is_caught():
    diffs = compare_cell(_cell(reason="not a power law"),
                         _cell(reason="model selection (AICc)"))
    assert diffs and any(d.startswith("d_B.reason") for d in diffs)
    assert "reason" in CHANNEL_FIELDS


def test_a_channel_that_starts_answering_is_caught():
    before = _cell()
    after = _cell()
    after["channels"]["d_B"] = {"valid": True, "value": 1.9, "se": 0.2, "reason": None}
    diffs = compare_cell(before, after)
    assert any(d.startswith("d_B.valid") for d in diffs)


def test_a_changed_component_or_n_is_caught():
    after = _cell()
    after["component"] = 900
    assert any(d.startswith("component") for d in compare_cell(_cell(), after))


def _stale(family, n, seed, elapsed):
    return {"task": {"key": f"{family}:{n}:{seed}", "family": family,
                     "parameter": n, "seed": seed},
            "cell": _cell(family=family, n=n, seed=seed, elapsed=elapsed)}


def test_every_family_is_represented_before_any_family_is_sampled_twice():
    stale = ([_stale("ring", 64, s, 0.1) for s in range(5)]
             + [_stale("gasket", 64, s, 0.1) for s in range(5)]
             + [_stale("tree", 64, s, 0.1) for s in range(5)])
    chosen = choose_sample(stale, sample=3, workers=4)
    assert {c["task"]["family"] for c in chosen} == {"ring", "gasket", "tree"}, (
        "cell_fingerprint mixes in a per-family digest, so a sample that skips a "
        "family has not checked that family's key at all")


def test_the_default_sample_takes_the_cheapest_of_each_family_not_the_deepest():
    stale = [_stale("ring", 64, 0, 0.1), _stale("ring", 262144, 0, 400.0)]
    chosen = choose_sample(stale, sample=1, workers=8)
    assert chosen[0]["cell"]["n"] == 64
    assert choose_sample(stale, sample=1, workers=8, deep=True)[0]["cell"]["n"] == 262144


def test_the_budget_is_wall_time_at_the_worker_count_not_serial_time():
    items = [_stale("f", 1024, i, 100.0) for i in range(10)]
    assert predicted_wall_seconds(items, workers=1) == 1000.0
    assert predicted_wall_seconds(items, workers=10) == 100.0, (
        "ten 100s cells on ten workers is 100s, not 1000s")
    assert predicted_wall_seconds(items, workers=100) == 100.0, (
        "a pool cannot finish faster than its longest single cell")


def test_depth_is_bought_only_with_budget_that_remains():
    stale = ([_stale(f"f{i}", 64, 0, 0.1) for i in range(5)]
             + [_stale("f0", 262144, 1, 400.0)])
    lean = choose_sample(stale, sample=40, budget_seconds=10.0, workers=4)
    assert all(c["cell"]["n"] == 64 for c in lean), "400s does not fit a 10s budget"
    rich = choose_sample(stale, sample=40, budget_seconds=1000.0, workers=4)
    assert any(c["cell"]["n"] == 262144 for c in rich), (
        "with budget the deep cell must be bought; the size-dependent case is "
        "still the one worth paying for")


def test_the_sample_reports_the_coverage_it_actually_has():
    stale = [_stale("ring", 64, 0, 0.1), _stale("gasket", 4096, 0, 0.2)]
    cov = sample_coverage(choose_sample(stale, sample=40, workers=4))
    assert cov["families"] == ["gasket", "ring"]
    assert cov["n_min"] == 64 and cov["n_max"] == 4096, (
        "coverage must be stated, never implied: cells above n_max were not "
        "verified and the report has to say so")


def test_a_sample_always_contains_at_least_one_cell_per_family():
    stale = [_stale("ring", 262144, 0, 5000.0)]
    assert len(choose_sample(stale, sample=40, budget_seconds=1.0, workers=1)) == 1, (
        "family coverage is taken before the budget is consulted; a budget that "
        "admitted nothing would verify nothing and then re-stamp everything")


def test_restamping_records_what_was_verified_and_why(monkeypatch):
    import graph_scale_dynamics.calibration.rekey as R
    monkeypatch.setattr(R.FP, "cell_fingerprint", lambda family, root=None: "new-cell-fp")
    monkeypatch.setattr(R.FP, "science_fingerprint", lambda: "new-sci")
    monkeypatch.setattr(R.FP, "estimator_fingerprint", lambda root=None: "new-est")

    document = {"estimator_fingerprint": "old-est", "science_fingerprint": "old-sci",
                "cells": {"a": _cell(), "b": _cell(seed=1),
                          "broken": dict(_cell(seed=2), status="failed")}}
    plan = [{"key": "a", "family": "periodic_ring"},
            {"key": "b", "family": "periodic_ring"},
            {"key": "broken", "family": "periodic_ring"}]
    record = rekey_document(document, plan,
                            verification={"checked": ["a"], "mismatches": [], "failed": []},
                            justification="the change only touches a health observable "
                                          "that no cell records")
    assert record["cells_restamped"] == 2, "a failed cell is not evidence and is not re-stamped"
    assert document["cells"]["a"]["cell_fingerprint"] == "new-cell-fp"
    assert document["cells"]["broken"]["cell_fingerprint"] == "old0000000000000"
    assert record["from_estimator_fingerprint"] == "old-est"
    assert record["to_estimator_fingerprint"] == "new-est"
    assert record["cells_verified"] == ["a"]
    assert "health observable" in record["justification"]
    assert document["rekeys"][-1] is record, "the record stays on the table, permanently"


def test_a_second_rekey_appends_rather_than_replacing(monkeypatch):
    import graph_scale_dynamics.calibration.rekey as R
    monkeypatch.setattr(R.FP, "cell_fingerprint", lambda family, root=None: "fp")
    monkeypatch.setattr(R.FP, "science_fingerprint", lambda: "sci")
    monkeypatch.setattr(R.FP, "estimator_fingerprint", lambda root=None: "est")
    document = {"cells": {"a": _cell()}}
    plan = [{"key": "a", "family": "periodic_ring"}]
    for i in range(2):
        rekey_document(document, plan,
                       verification={"checked": ["a"], "mismatches": [], "failed": []},
                       justification=f"pass {i}")
    assert len(document["rekeys"]) == 2, (
        "the history of what was migrated without recomputation is the audit "
        "trail; overwriting it would hide a chain of re-keys")


def test_the_cli_exposes_it_without_running_anything():
    import main as gsd_main
    parser = gsd_main.build_parser()
    args = parser.parse_args(["calibration-rekey", "--sample", "12"])
    assert args.sample == 12 and args.apply is False
    assert parser.parse_args(
        ["calibration-rekey", "--apply", "--justification", "x"]).justification == "x"


def test_the_sample_runs_in_the_suites_runner_and_is_priced_from_the_table(monkeypatch):
    from graph_scale_dynamics.calibration import rekey as R
    from graph_scale_dynamics.calibration.cells import cell_key

    ring, grid = _cell(n=1024), _cell(family="periodic_square_lattice", n=4096)
    chosen = [{"task": {"key": cell_key(c["family"], c["parameter"], c["seed"]), "family": c["family"],
                        "parameter": c["parameter"], "seed": c["seed"], "n": c["n"]}, "cell": c}
              for c in (ring, grid)]
    seen = {}

    def runner(todo, *, workers, admission, document, log, task_args, finish, blocked, root, science):
        seen.update(workers=workers, document=document, keys=[t["key"] for t in todo])
        finish(dict(ring, elapsed_seconds=0.1))
        blocked.append({"key": chosen[1]["task"]["key"], "n": 4096, "reason": "the host could not hold it"})

    monkeypatch.setattr(R, "_run_in_workers", runner)
    table = {"cells": {"elsewhere": _cell(n=65536)}}
    result = R.verify_sample(chosen, workers=2, log=lambda *_: None, document=table)
    assert seen["workers"] == 2 and seen["document"] is table
    assert seen["keys"] == [item["task"]["key"] for item in chosen]
    assert result["checked"] == [chosen[0]["task"]["key"]] and result["identical"] == 1
    assert result["failed"] == [{"key": chosen[1]["task"]["key"],
                                 "error": "cannot be admitted: the host could not hold it"}]
