from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from graph_scale_dynamics.reporting import every_chain_report as ECR

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import law_rows as L  # noqa: E402

SIZES = (1024, 4096, 16384)


def _probes(d: float, spread: float = 0.0) -> dict:
    return {"d_s": d, "d_V": d + spread, "d_B": d - spread}


def _seed(law: str, n: int, seed: int, *, from_empty: dict, cubic: dict, reason: str = "completed") -> dict:
    def census(degree):
        return {"edges": degree * n / 2, "cliques": {"triangles": 0}, "squares": 3 * n,
                "largest_component": {"size": n}}

    def given_probes(chain):
        out = {probe: {"valid": True, "value": value, "se": 0.01} for probe, value in chain["probes"].items()}
        out["d_w"] = {"valid": True, "value": 2.0, "se": 0.01}
        out["half_volume_radius"] = chain["reach"](n)
        return out

    metrics = {"health": {"n": n, "rung_terminal": {"reason": reason, "given_chains": [{"name": "random"}, {"name": "cubic"}]}},
               "census": {"empty": census(from_empty["degree"]), "given": census(from_empty["degree"]),
                          "cubic": census(cubic["degree"])},
               "curvature": {"empty": {"measured": True, "mean": -0.4}, "given": {"measured": True, "mean": -0.4},
                             "more_given": {"cubic": {"measured": True, "mean": 0.0}}},
               "half_volume_radius": from_empty["reach"](n),
               "chain_probes": {"given": given_probes(from_empty), "cubic": given_probes(cubic)}}
    from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE
    for probe, value in from_empty["probes"].items():
        metrics[probe] = {"valid": True, PROBE_VALUE[probe]: value, "se": 0.01}
    metrics["d_w"] = {"valid": True, "d_w": 2.6, "se": 0.01}
    return {"candidate_id": law, "n": n, "seed": seed, "metrics": metrics}


EMPTY = {"degree": 7.0, "probes": _probes(1.3, 1.5), "reach": lambda n: math.log(n)}
CUBIC = {"degree": 6.0, "probes": _probes(3.0), "reach": lambda n: 2.0 * n ** (1 / 3)}


def _measurements(law: str, sizes=SIZES, cubic=CUBIC) -> list[dict]:
    return [_seed(law, n, seed, from_empty=EMPTY, cubic=cubic) for n in sizes for seed in range(3)]


def test_report_28_scores_every_chain_and_names_the_cubic_given_chain_a_space():
    scores = ECR.law_scores(_measurements("a" * 64))
    score = scores["a" * 64]
    assert score["top_n"] == 16384 and score["given"] == "random" and score["full"]
    assert score["spaces"] == ["cubic"], score["spaces"]
    assert score["chains"]["cubic"]["d"] == 3 and score["chains"]["cubic"]["space"]
    assert not score["chains"]["empty"]["space"] and not score["chains"]["given"]["space"]
    assert [row[0] for row in score["chains"]["cubic"]["rungs"]] == list(SIZES)
    assert ECR.law_scores(_measurements("b" * 64, sizes=(64, 256))) == {}, "below 1,024 nothing is judged"


def test_report_28_keeps_every_chain_s_values_at_every_size():
    score = ECR.law_scores(_measurements("a" * 64))["a" * 64]
    columns = list(ECR.VALUE_COLUMNS)
    assert set(score["values"]) == {"empty", "given", "cubic"}
    cubic = [dict(zip(columns, row, strict=True)) for row in score["values"]["cubic"]]
    assert [row["n"] for row in cubic] == list(SIZES)
    assert all(row["d_s"] == 3.0 and row["d_w"] == 2.0 and row["mean_degree"] == 6.0 for row in cubic)
    assert cubic[-1]["reach"] == float(f"{2.0 * SIZES[-1] ** (1 / 3):.4g}")
    section = ECR.every_chain_section({"measurements": _measurements("a" * 64)})
    assert section["value_columns"] == columns and section["laws"]["a" * 64]["values"] == score["values"]


def test_what_every_chain_earned_and_where_it_carried_a_law_past_its_chain_from_empty():
    decisions = {"law-1": [{"rule": "d_s_settled", "facts": {"earned_by": "cubic", "chains": {
        "empty": {"action": "stop", "rule": "empty"}, "cubic": {"action": "run_next", "rule": "d_s_settled"}}}}],
                 "law-2": [{"rule": "base_block", "facts": {"chains": {"empty": {"action": "run_next"}}}}],
                 "law-3": [{"rule": "base_block", "facts": {}}]}
    out = ECR.earned(decisions)
    assert out["decisions_chain_by_chain"] == 2 and out["laws_earned"] == ["law-1"]
    assert out["laws_earned_over_the_chain_from_empty"] == ["law-1"]
    assert out["earned_by"] == [{"chain": "cubic", "rule": "d_s_settled", "decisions": 1, "laws": 1}]


def test_report_28_reads_the_decisions_the_snapshot_keeps():
    decisions = {"law-1": [{"rule": "base_block", "facts": {"earned_by": "honeycomb", "chains": {
        "empty": {"action": "stop", "rule": "empty"}, "honeycomb": {"action": "run_next", "rule": "base_block"}}}}]}
    section = ECR.every_chain_section({"measurements": [], "engine_decisions": decisions})
    assert section["decisions_chain_by_chain"] == 1 and section["laws_earned_over_the_chain_from_empty"] == ["law-1"]
    assert ECR.every_chain_section({"measurements": [], "decisions": decisions})["decisions_chain_by_chain"] == 0


def _ledger_row(law: str, rule: str, at_n: int, *, zero: bool, drawn: str, ops=("degree_anchor",)) -> dict:
    return {"candidate_id": law, "fate": [rule, at_n], "admitted_utc": drawn,
            "spec": {"zero_temperature": zero, "terms": [[op, None, 1.0, "one", None] for op in ops]}}


def _bundle(root: Path, *, running: bool = False) -> Path:
    campaigns = []
    for index in (1, 2):
        folder = root / f"campaign_{index}"
        folder.mkdir(parents=True)
        laws = [f"{index}{k}".ljust(64, "0") for k in range(6)]
        rows = [_ledger_row(laws[0], "empty", 256, zero=True, drawn=f"2026-10-08T0{index}:00:00Z"),
                _ledger_row(laws[1], "too_dense", 64, zero=False, drawn=f"2026-10-08T0{index}:01:00Z"),
                _ledger_row(laws[2], "empty", 64, zero=False, drawn=f"2026-10-08T0{index}:02:00Z"),
                _ledger_row(laws[3], "over_budget", 4096, zero=True, drawn=f"2026-10-08T0{index}:03:00Z"),
                _ledger_row(laws[4], "done", 16384, zero=True, drawn=f"2026-10-08T0{index}:04:00Z"),
                _ledger_row(laws[5], "empty", 256, zero=False, drawn=f"2026-10-08T0{index}:05:00Z", ops=("edge",))]
        scores = ECR.law_scores(_measurements(laws[4]) + _measurements(laws[3], sizes=(1024, 4096)))
        engine = {"law_ledger": {"rows": rows},
                  "laws": [{"candidate_id": law, "action": "run_next" if running and k == 0 else "stop"}
                           for k, law in enumerate(laws)],
                  "seeds": {"columns": ["law", "n", "seed", "ended"], "laws": laws,
                            "rows": [[k, 64, s, "ceiling" if k in (1, 2) else "completed"]
                                     for k in range(6) for s in range(3)]},
                  "every_chain": {"laws": scores, "laws_earned_over_the_chain_from_empty": [laws[4]] if index == 1 else []},
                  "the_record": {"compute_by_regime": {"by_rung": {"zero": {"zero:64": {"core_seconds": 3600.0}}}}}}
        (folder / "28-decision-engine.json").write_text(json.dumps({"body": engine}))
        campaigns.append({"campaign_id": str(index), "name": f"the sparse region, drawn blind ({index} of 2)",
                          "bundle": folder.name, "law_budget": 6, "laws_held": 6})
    control = root / "campaign_3"
    control.mkdir()
    (control / "28-decision-engine.json").write_text(json.dumps({"body": {"law_ledger": {"rows": []}}}))
    campaigns.append({"campaign_id": "3", "name": "campaign-standing-controls", "bundle": control.name})
    (root / "study.json").write_text(json.dumps({"study": "169", "built_utc": "2026-10-09T00:00:00Z",
                                                 "campaigns": campaigns}))
    return root


def test_a_study_s_bundle_is_read_campaign_by_campaign(tmp_path):
    data = L.study(_bundle(tmp_path))
    assert [part["drawn"] for part in data["parts"]] == [True, True, False], "the controls' campaign draws no law"
    assert data["missing"] == [] and not any(part["failed_sections"] for part in data["parts"] if part["drawn"])
    laws = L.drawn_laws(data["parts"])
    assert len(laws) == 12 and {law["campaign_id"] for law in laws} == {"1", "2"}
    assert {law["rule"] for law in laws} == {"empty", "too_dense", "over_budget", "done"}
    assert sum(law["zero_temperature"] for law in laws) == 6
    assert {law["regime"] for law in laws} == {"zero_temperature", "equilibrium"}
    assert sum(bool(law["score"]) for law in laws) == 4, "two laws of each campaign reached a size from 1,024"
    assert all(law["decided"] for law in laws)


def test_a_law_still_running_is_not_decided(tmp_path):
    laws = L.drawn_laws(L.study(_bundle(tmp_path, running=True))["parts"])
    assert sum(not law["decided"] for law in laws) == 2, "the first law of each campaign still runs"
