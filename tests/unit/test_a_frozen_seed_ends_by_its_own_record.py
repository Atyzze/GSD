from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy

ROOT = Path(__file__).resolve().parents[2]
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "frozen_early_end_criterion.json"
FROZEN_LAW = {"dsl_version": 1, "init": "empty",
              "terms": [{"op": "degree_square_sum", "params": {}, "coeff": {"c0": 0.0195231, "scale": "one"}},
                        {"op": "degree_anchor_abs", "params": {"k": 30}, "coeff": {"c0": 0.310632, "scale": "one"}},
                        {"op": "edge_count", "params": {}, "coeff": {"c0": 11.0352, "scale": "one"}}],
              "dynamics": {"kind": "equilibrium", "beta": 90.9435, "sweeps": 120, "locality": 0.579577,
                           "move_mix": {"add": 0.09005, "delete": 0.09005, "swap": 0.8199}}}


def _row(*frozen, rest=False):
    chains = {f"c{i}": {"activity": {"frozen": flag}} for i, flag in enumerate(frozen)}
    return {"certificate": {"decide": list(chains), "chains": chains,
                            "at_rest": {"chains": {"c0": {"at_rest": True}}} if rest else None}}


def test_the_criterion_came_before_the_code():
    assert json.loads(CRITERION.read_text(encoding="utf-8"))["committed_utc"] == "2026-11-19T04:40:07Z"


def test_every_chain_frozen_on_two_chunks_in_a_row_and_nothing_less():
    assert eq.frozen_twice([_row(True, True), _row(True, True)])
    assert not eq.frozen_twice([_row(True, True)]), "one frozen chunk is not enough"
    assert not eq.frozen_twice([_row(True, False), _row(True, True)])
    assert not eq.frozen_twice([_row(True, True), _row(True, None)]), "a chain not read is not frozen"
    assert not eq.frozen_twice([_row(True, rest=True), _row(True, rest=True)]), "zero temperature is read by its rest"


def test_a_frozen_law_ends_on_its_second_chunk_as_it_would_have_at_the_cap():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    policy = dict(one_shot_policy(campaign), work_budget=10 ** 15, max_sweeps_multiplier=64, mean_degree_cap=16.0)
    envelope = run_one_shot(FROZEN_LAW, 64, 1, one_shot=policy, initial_multiplier=1, record_points=60)
    terminal = envelope["rung_terminal"]
    assert (terminal["reason"], terminal["classification"]) == ("frozen", eq.FROZEN_OR_ABSORBING)
    assert [row["multiplier"] for row in envelope["sampling_checkpoints"]] == [1, 2]
