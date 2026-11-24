from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import design_on_a_bundle as D  # noqa: E402

from graph_scale_dynamics.decisions.decider import decision_inputs  # noqa: E402
from graph_scale_dynamics.decisions.engine import Rung, Seed, decide  # noqa: E402
from graph_scale_dynamics.decisions.replay import policy_from_inputs  # noqa: E402

LAWS = {"a" * 64: (3.0, None), "b" * 64: (3.0, 256), "c" * 64: (0.01, None)}
SECONDS = {64: 2.0, 256: 4.0, 1024: 9.0}


def _seed(termination):
    return Seed(termination=termination, work_units=10 ** 9, moves=1000, first_chunk_units=10 ** 8,
                first_chunk_moves=1000, first_multiplier=1, final_multiplier=1, work_budget=4 * 10 ** 11)


def _rungs(sizes, degree, cut_at):
    return [Rung(n=n, mean_degree=degree, connected_fraction=1.0, probes={}, seeds_measured=3,
                 seeds=tuple(_seed("budget" if n == cut_at and i == 0 else "completed") for i in range(3)))
            for n in sizes]


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("bundle") / "study_x"
    (root / "tables").mkdir(parents=True)
    _, recorded = D.design_policy("172")
    policy = policy_from_inputs(recorded)
    rows, seeds, number = [], [], 0
    for law, (degree, cut_at) in LAWS.items():
        for sizes in ((64,), (64, 256), (64, 256, 1024)):
            number += 1
            rungs = _rungs(sizes, degree, cut_at)
            made = decide(law, rungs, policy)
            rows.append({"campaign_id": "1", "candidate_id": law, "decision_id": f"{number:020d}-d",
                         "at_n": sizes[-1], "action": made.action, "rule": made.rule, "next_n": made.next_n,
                         "inputs_json": json.dumps(decision_inputs(law, rungs, policy))})
            seeds += [[list(LAWS).index(law), sizes[-1], i, SECONDS[sizes[-1]], 0.5, 0.25] for i in range(3)]
    with gzip.open(root / "tables" / "decisions.ndjson.gz", "wt", encoding="utf-8") as out:
        out.write("\n".join(json.dumps(row) for row in rows) + "\n")
    report = root / "campaign_1_reports_2026-11-21T00-00-00Z_x"
    report.mkdir()
    body = {"seeds": {"columns": ["law", "n", "seed", "simulation_seconds", "d_s_seconds", "d_V_seconds"],
                      "laws": list(LAWS), "rows": seeds}, "every_chain": {"laws": {}}}
    (report / "28-decision-engine.json").write_text(json.dumps({"body": body}), encoding="utf-8")
    return root


def test_a_design_on_its_own_bundle_ends_each_law_where_the_record_does(bundle):
    found = D.read(bundle, "172")
    assert found["laws"] == 3 and found["decisions"] == 9
    assert found["ends"] == {"in flight when the bundle was made": 2, "stops": 1}
    assert found["stops_by_rule"] == {"empty": 1} and found["acting"] == ["disconnected", "empty", "too_dense"]
    at = found["by_size"]
    assert at["256"]["recorded_only"] == {} and at["256"]["cut_seed"] == 1, "172 has no cut gate: nothing recorded"
    assert at["1024"]["stops"] == {"empty": 1} and at["1024"]["goes_on"] == 2
    assert at["64"]["seconds_a_law"] == pytest.approx(3 * (2.0 + 0.75))


def test_173_s_design_records_the_cut_and_holds_no_law_by_it(bundle):
    found = D.read(bundle, "173")
    assert "cut" not in found["acting"] and {"nothing_read", "starts_alike", "starts_apart_by_history"} <= set(
        found["acting"])
    assert found["by_size"]["256"]["recorded_only"] == {"cut": 1}, "the verdict is recorded and the law goes on"
    assert found["ends"] == {"in flight when the bundle was made": 2, "stops": 1}
    assert found["design_sha256"] == D.design_policy("173")[0]["sha256"]


def test_a_design_whose_cut_gate_is_closed_stops_the_cut_law_where_it_was_cut(bundle, tmp_path):
    design = json.loads((ROOT / "graph_scale_dynamics/resources/readings/study_173_design.json").read_text())
    design["engine"]["gate_shares"] = [[name, 0.0 if name == "cut" else share]
                                       for name, share in design["engine"]["gate_shares"]]
    path = tmp_path / "closed.json"
    path.write_text(json.dumps(design), encoding="utf-8")
    found = D.read(bundle, str(path))
    assert found["stops_by_rule"] == {"cut": 1, "empty": 1} and "cut" in found["acting"]
    assert found["by_size"]["256"]["stops"] == {"cut": 1} and found["by_size"]["256"]["held"] == 1
    assert found["by_size"]["1024"]["decided"] == 2, "a law the design stops is not followed past it"


def test_the_projection_carries_each_size_s_shares_to_the_design_s_laws(bundle):
    found = D.read(bundle, "172", laws=300)
    sizes = found["projected"]["sizes"]
    assert sizes["64"]["laws"] == 300 and sizes["1024"]["laws"] == 300
    assert sizes["1024"]["stopped"] == 100.0 and sizes["1024"]["stops"] == {"empty": 100.0}
    assert sizes["64"]["core_hours"] == pytest.approx(round(300 * 3 * 2.75 / 3600, 1))
    text = D.render(found)
    assert "projected on 300 laws" in text and "the gates that act: disconnected, empty, too_dense" in text
