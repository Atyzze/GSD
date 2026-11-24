from __future__ import annotations

import hashlib
import json
from pathlib import Path

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import initial_sweeps_multiplier, one_shot_policy

ROOT = Path(__file__).resolve().parents[2]
DESIGN = "tests/fixtures/a_design.json"
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "cap_pass_criterion.json"
RESTS_AT_THE_CAP = {
    "dsl_version": 1, "init": "empty",
    "terms": [{"op": "degree_anchor", "params": {"k": 3}, "coeff": {"c0": 0.0124579, "scale": "one"}},
              {"op": "degree_fourth_sum", "params": {}, "coeff": {"c0": 0.986358, "scale": "one"}},
              {"op": "degree_square_sum", "params": {}, "coeff": {"c0": -0.590444, "scale": "one"}}],
    "dynamics": {"kind": "equilibrium", "beta": 3.53257, "sweeps": 30, "locality": 0.32626, "zero_temperature": True,
                 "move_mix": {"add": 0.0548905, "delete": 0.0548905, "swap": 0.890219}}}
EQUILIBRATES_AT_ITS_FIRST_CHUNK = {
    "dsl_version": 1, "init": "empty",
    "terms": [{"op": "degree_fourth_sum", "params": {}, "coeff": {"c0": 2.18354, "scale": "one"}},
              {"op": "wedge_count", "params": {}, "coeff": {"c0": -0.70558, "scale": "one"}}],
    "dynamics": {"kind": "equilibrium", "beta": 1.82468, "sweeps": 48, "locality": 0.398375,
                 "move_mix": {"add": 0.1844285, "delete": 0.1844285, "swap": 0.631143}}}


def _spec() -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    raw = (ROOT / DESIGN).read_bytes()
    design = dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=DESIGN)
    spec = SD.without_terms(design, control.shipped_spec(), log=lambda *a, **k: None)
    return SD.campaign_spec(design, spec, design["campaigns"][0], 0)


def _run(law: dict, n: int, seed: int, **settings) -> dict:
    spec = _spec()
    policy = dict(one_shot_policy(spec, n, dsl.fingerprint(law), law), work_budget=10 ** 15, **settings)
    return run_one_shot(law, n, seed, one_shot=policy,
                        initial_multiplier=settings.get("max_sweeps_multiplier") or initial_sweeps_multiplier(spec, n))


def test_the_criterion_came_before_the_code():
    assert json.loads(CRITERION.read_text(encoding="utf-8"))["committed_utc"] == "2026-11-19T16:48:52Z"


def test_a_zero_temperature_chain_at_rest_at_the_cap_is_at_rest():
    envelope = _run(RESTS_AT_THE_CAP, 256, 1)
    terminal = envelope["rung_terminal"]
    assert (terminal["reason"], terminal["classification"], terminal["passes_in_a_row"]) == \
        ("completed", eq.AT_REST, 1), "806 ran a chunk of no moves here, read no rest and classed it OPERATIONAL_UNRESOLVED"
    assert [row["multiplier"] for row in envelope["sampling_checkpoints"]] == [4, 64]


def test_a_finite_temperature_pass_at_the_cap_keeps_the_class_its_re_read_gave():
    envelope = _run(EQUILIBRATES_AT_ITS_FIRST_CHUNK, 256, 0, max_sweeps_multiplier=4)
    terminal = envelope["rung_terminal"]
    assert (terminal["reason"], terminal["classification"], terminal["passes_in_a_row"]) == \
        ("completed", eq.EQUILIBRATED_ACTIVE, 1), "806 read the same chain twice and gave it this class"
    assert [row["multiplier"] for row in envelope["sampling_checkpoints"]] == [4]
