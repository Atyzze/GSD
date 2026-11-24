from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.measurements import random_starts
from graph_scale_dynamics.measurements.calibration import control_family_reaches
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import study_design as SD
from graph_scale_dynamics.operations.study import QUADRANT_PREFIX, quadrant_of
from graph_scale_dynamics.scheduling.campaign import validate_campaign
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy, resolve_given_start
from graph_scale_dynamics.scheduling.limits import limits, mean_degree_cap_armed, work_budget
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]
LAW = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
LAW_ID = "5" * 64
LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]


def _design() -> dict:
    return designs.of_four_starts()


def _spec(index: int = 0) -> dict:
    design = _design()
    return SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][index], index)


@pytest.mark.parametrize("index", range(len(designs.of_four_starts()["campaigns"])))
def test_each_campaign_is_a_survey_on_the_design(index):
    spec = _spec(index)
    assert validate_campaign(spec) == []
    assert spec["description"].startswith(QUADRANT_PREFIX), "a survey's folder: the standing and cooled controls"
    policy = Policy.from_spec(spec)
    assert policy.every_chain and policy.dense_cap == 16.0 and list(policy.ladder()) == LADDER
    assert limits(spec)["mean_degree_window"]["max"] == 16.0 and mean_degree_cap_armed(spec, 64)
    assert [work_budget(spec, n) for n in LADDER] == [units for _, units in _design()["ladder"]["budgets"]]
    assert quadrant_of(spec)["zero_temperature"] == "drawn"
    assert spec["sampling_contract"]["given_starts"] == _design()["starts"]
    assert not {"given_start", "given_start_rule", "given_start_by_law"} & set(spec["sampling_contract"])
    assert spec["study_design"]["design_sha256"] == _design()["sha256"]


def test_every_law_has_its_starts_at_every_rung_and_one_drawn_degree():
    spec = _spec()
    families = set()
    for n in LADDER[:6]:
        policy = one_shot_policy(spec, n, LAW_ID, LAW)
        first = policy["given_start"]
        assert first["name"] == "random" and first["n"] == n and control_family_reaches(first["family"], n)
        families.add(first["family"])
        assert [t["family"] for t in policy["more_given"]] == [
            "periodic_square_lattice", "periodic_cubic_quotient", "periodic_tesseract_quotient"]
        assert all(control_family_reaches(t["family"], n) for t in policy["more_given"])
        assert "given_capped_alone" not in policy and policy["mean_degree_cap"] == 16.0
        assert resolve_given_start(spec, n, LAW_ID, LAW) == first
    assert len(families) == 1, "the same degree at every N"
    assert 0.0 < random_starts.parse(families.pop()) <= 16.0


def test_a_law_s_five_chains_run_and_are_read_and_decided_chain_by_chain():
    from graph_scale_dynamics.artifact_store.chain_record import build_record
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.observability.chains_course import seed_chains_course
    from graph_scale_dynamics.decisions.decider import _rungs
    from graph_scale_dynamics.decisions.every_chain import EMPTY, decide_every_chain
    from graph_scale_dynamics.decisions.evidence import _b143_rung_sampling_state, _rung_cell
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    spec = _spec()
    law_id = fingerprint(LAW)
    policy = dict(one_shot_policy(spec, 64, law_id, LAW), max_sweeps_multiplier=2)
    rows = []
    for seed in range(3):
        envelope = run_one_shot(LAW, 64, seed, one_shot=policy, record_points=40)
        metrics, _ = analyze_one_shot_envelope(envelope, seed=seed)
        given_chains = {"square", "cubic", "tesseract"}
        assert set(metrics["census"]) == {"empty", "given", *given_chains}
        assert given_chains <= set(seed_chains_course(envelope))
        assert given_chains <= set(envelope["descent"]["chains"]), "each chain by its name"
        assert set(chain["start"] for chain in build_record(envelope)["chains"][2:]) == given_chains
        rows.append({"n": 64, "seed": seed, "metrics": metrics})

    class Repo:
        def measurements(self, law, version, campaign_id):
            return rows

    store = DecisionStore(Repo(), None, {"campaign_id": "1", "spec": spec})
    summary = rung_summary([r["metrics"] for r in rows])
    states = {64: _b143_rung_sampling_state(spec, 64, summary, [r["metrics"] for r in rows])}
    chains = store.law_chains("1", law_id, states, [64])["chains"]
    assert list(chains) == ["random", "square", "cubic", "tesseract"]
    for name, cells in chains.items():
        assert cells[64]["measurement_seed_count"] == 3, name
    entries = {64: _rung_cell(spec, 64, summary, states[64])}

    class Seeds:
        def seed_rows(self, campaign_id, law):
            return {}

    rungs = {EMPTY: _rungs(Seeds(), "1", law_id, entries)}
    rungs.update({name: _rungs(Seeds(), "1", law_id, cells) for name, cells in chains.items()})
    decision = decide_every_chain(law_id, rungs, Policy.from_spec(spec))
    assert set(decision.facts["chains"]) == {"empty", "random", "square", "cubic", "tesseract"}
    assert decision.action == "run_next" and decision.next_n == 256, "the base block goes on for every law"


def test_a_design_whose_ladder_stops_at_the_base_block_makes_a_campaign_that_validates():
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    design = _design()
    design["ladder"] = dict(design["ladder"], deep=[], budgets=[[n, u] for n, u in design["ladder"]["budgets"]
                                                               if n <= 4096])
    spec = SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][0], 0)
    assert validate_campaign(freeze_campaign_spec(spec)) == []
    assert set(spec["policy"]["initial_sweeps_multiplier"]) <= {"64", "256", "1024", "4096"}
    assert Policy.from_spec(spec).first_multiplier(1024) == int(spec["policy"]["initial_sweeps_multiplier"]["1024"])
