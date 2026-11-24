from __future__ import annotations

from graph_scale_dynamics.decisions.engine import Policy, in_audit_sample
from graph_scale_dynamics.research.report_catalog import REPORT_BY_CODE
from graph_scale_dynamics.research.report_pipeline import BUILDERS

POLICY = Policy()
AUDITED = next(f"law-{i}" for i in range(5000) if in_audit_sample(f"law-{i}", POLICY.audit_fraction))


def _rung(n, md, cf=1.0, d_s=None, se=0.05):
    q = {"mean_degree": md, "connected_fraction": cf, "measurement_seed_count": 3,
         "d_s": d_s, "d_s_bucket": None, "probes": {"d_s": {"se": se}}}
    return str(n), q


def _decision(i, at_n, action, rule, *, next_n=None, priority=None, jobs=0, audit=False):
    return {"decision_id": f"{i:019d}-x", "created_utc": f"2026-09-16T00:00:{i:02d}Z", "at_n": at_n, "next_n": next_n,
            "action": action, "rule": rule, "reason": rule, "priority": priority, "jobs_created": jobs,
            "released_hold": False, "engine": "decision-engine-1", "facts": {"audit_sample": audit}}


def test_report_28_is_registered_and_counts_what_each_rule_decided_and_bought():
    assert REPORT_BY_CODE["28"].slug == "decision-engine"
    snapshot = {
        "engine_decisions": {
            "dense-law": [_decision(1, None, "run_next", "start", next_n=64, jobs=3),
                          _decision(2, 64, "run_next", "base_block", next_n=256, jobs=3),
                          _decision(3, 256, "stop", "too_dense")],
            "settled-law": [_decision(4, 4096, "run_next", "settled", next_n=16384, priority=1, jobs=3),
                            _decision(5, 16384, "run_next", "d_s_settled", next_n=65536, priority=2, jobs=3)],
        },
        "rung_spend": [{"candidate_id": "settled-law", "n": 16384, "core_seconds": 900.0}],
    }
    body = BUILDERS["28"](snapshot)
    rules = {(row["action"], row["rule"]): row for row in body["rules"]}
    assert rules[("stop", "too_dense")]["decisions"] == 1
    assert rules[("run_next", "settled")]["core_seconds_bought"] == 900.0
    assert body["decisions"] == 5 and body["laws_decided"] == 2
    laws = {row["candidate_id"]: row for row in body["laws"]}
    assert (laws["dense-law"]["action"], laws["dense-law"]["rule"]) == ("stop", "too_dense")
    assert body["bought_by_priority_and_what_the_next_rung_showed"] == {"1": {"d_s_settled": 1},
                                                                        "2": {"not_decided_yet": 1}}


def test_a_final_verdict_stop_is_priced_on_the_audit_sample():
    rows = [_rung(64, 2.5), _rung(256, 2.5, cf=0.01), _rung(1024, 2.5, cf=0.003),
            _rung(4096, 2.5, cf=0.95, d_s=1.4)]
    snapshot = {
        "phenotypes": [{"candidate_id": AUDITED, "phenotype": {"per_n": dict(rows), "extension_per_n": {}}}],
        "engine_decisions": {AUDITED: [_decision(1, 1024, "run_next", "base_block", next_n=4096, audit=True)]},
    }
    snapshot["engine_decisions"]["unfinished-audit-law"] = [_decision(2, 256, "run_next", "base_block", next_n=1024,
                                                                    audit=True)]
    losses = BUILDERS["28"](snapshot)["stop_losses_on_the_audit_sample"]
    assert (losses["audit_sample_laws"], losses["examined"], losses["not_examined_base_block_unfinished"]) == (2, 1, 1)
    assert losses["by_rule"]["disconnected"] == {"audit_laws_it_would_have_stopped": 1, "measured_past_the_stop": 1,
                                                 "later_real_d_s": 1}


def _work(units, budget=1000, reason="completed"):
    return {"health": {"rung_terminal": {"reason": reason, "work": {"units": units, "budget": budget}}}}


def test_report_28_bands_every_seed_by_where_the_engine_landed_its_law():
    snapshot = {
        "engine_decisions": {"slow-law": [_decision(1, 256, "stop", "over_budget")]},
        "measurements": [{"candidate_id": "slow-law", "n": 64, "seed": s, "created_utc": "x", "metrics": _work(u)}
                         for s, u in ((0, 5), (1, 50), (2, 200))]
                        + [{"candidate_id": "slow-law", "n": 256, "seed": s, "created_utc": "x",
                            "metrics": _work(u, reason=r)}
                           for s, u, r in ((0, 1, "completed"), (1, 980, "budget"), (2, 2, "completed"))],
    }
    bands = BUILDERS["28"](snapshot)["budget_use"]["over_budget"]
    assert bands["64"] == {"<1%": 1, "1-10%": 1, "10-50%": 1}
    assert bands["256"]["reached"] == 1, "a seed that ended at its budget is counted as having reached it"


def test_report_28_carries_every_seed_with_its_simulation_and_probe_times():
    attempt = {"candidate_id": "law-a", "n": 64, "kind": "simulate", "finished_utc": "2026-09-16T00:00:01Z"}
    snapshot = {
        "engine_decisions": {"law-a": [_decision(1, 64, "run_next", "base_block", next_n=256)]},
        "attempts": [attempt | {"seed": 0, "attempt_id": "a0", "wall_seconds": 6.0, "user_cpu_seconds": 5.0,
                                "system_cpu_seconds": 0.5, "peak_pss_bytes": 1000, "final_edge_count": 80,
                                "final_mean_degree": 2.5, "error_class": None},
                     attempt | {"seed": 1, "attempt_id": "a1", "wall_seconds": 60.0, "error_class": "budget",
                                "finished_utc": "2026-09-16T00:00:00Z"},
                     attempt | {"seed": 1, "attempt_id": "a2", "wall_seconds": 3.0, "error_class": None}],
        "measurements": [{"candidate_id": "law-a", "n": 64, "seed": 0, "created_utc": "x", "probe_seconds_d_s": 0.2,
                          "probe_seconds_d_v": 0.01, "probe_seconds_d_b": 0.02, "probe_seconds_d_w": 0.1,
                          "metrics": _work(100)}],
    }
    seeds = BUILDERS["28"](snapshot)["seeds"]
    table = [dict(zip(seeds["columns"], row, strict=True)) for row in seeds["rows"]]
    assert seeds["laws"] == ["law-a"] and len(table) == 2
    first, second = table
    assert (first["simulation_seconds"], first["cpu_seconds"], first["peak_memory_bytes"]) == (6.0, 5.5, 1000)
    assert (first["budget_fraction"], first["d_s_seconds"], first["d_w_seconds"]) == (0.1, 0.2, 0.1)
    assert (second["attempts"], second["simulation_seconds"], second["d_s_seconds"]) == (2, 3.0, None)


def test_budget_use_lands_a_law_by_the_rule_that_bought_it():
    from graph_scale_dynamics.research.decision_engine_report import _landing
    assert _landing(_decision(1, 4096, "run_next", "d_s_settled", next_n=16384, priority=1)) == "settled"
    assert _landing(_decision(2, 4096, "run_next", "base_block", next_n=4096)) == "run_next"
    assert _landing(_decision(5, 4096, "hold", "unsettled", next_n=16384)) == "hold"
    assert _landing(_decision(6, 1024, "stop", "disconnected")) == "disconnected"
