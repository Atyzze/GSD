from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research.hamiltonian_preflight import ZERO_TEMPERATURE_FOLDED, equilibrium_identity
from graph_scale_dynamics.services.proposer import blind
from tests.support.proposer_repo import ProposerRepo, top_up_blind
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
LEFT_OUT = "triangle_count"


def test_a_campaign_draws_its_seed_s_stream():
    repo = ProposerRepo()
    top_up_blind(repo, SURVEY, 5, search_seed=77)
    grid = SURVEY["search_policy"]["grid"]
    expected = blind.blind_batch(random.Random(0), 5, SURVEY["operator_whitelist"], grid, set(), set(),
                                 fingerprint=dsl.fingerprint,
                                 physical_identity=lambda law: equilibrium_identity(
                                     law, version=ZERO_TEMPERATURE_FOLDED)[0],
                                 complexity_budget=SURVEY["complexity_budget"],
                                 streams=lambda i: blind.law_stream(77, i))
    assert [cid for cid, _ in repo.laws] == [dsl.fingerprint(law) for law in expected]


def test_a_term_left_out_of_the_pool_is_never_drawn_and_every_law_drawn_runs():
    from graph_scale_dynamics.operations import study
    from graph_scale_dynamics.operations import study_design as SD
    design = {"study": "test", "terms_left_out": [LEFT_OUT]}
    lines = []
    spec = SD.without_terms(design, deepcopy(SURVEY), log=lines.append)
    assert LEFT_OUT not in spec["operator_whitelist"] and LEFT_OUT in SURVEY["operator_whitelist"]
    assert set(spec["operator_whitelist"]) == set(SURVEY["operator_whitelist"]) - {LEFT_OUT}
    assert "every law drawn runs" in lines[0]
    repo = ProposerRepo()
    repo.set_flag(f"{study.LAW_BUDGET_PREFIX}1", "12")
    repo.campaign = lambda cid: {"campaign_id": cid, "spec": spec}
    repo.record_campaign_event = lambda *args: None
    top_up_blind(repo, spec, 12, search_seed=156)
    assert len(repo.laws) == 12, "twelve laws drawn, the budget's, and all twelve run"
    assert all(term["op"] != LEFT_OUT for _, law in repo.laws for term in law["terms"])
    assert study.budget_room(repo, "1", len(repo.laws)) == 0
    assert SD.without_terms({"study": "test"}, SURVEY) is SURVEY
    with pytest.raises(ValueError, match="does not have"):
        SD.without_terms({"study": "test", "terms_left_out": ["no_such_term"]}, SURVEY)
