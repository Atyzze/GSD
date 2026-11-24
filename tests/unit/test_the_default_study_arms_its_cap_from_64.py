from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.scheduling.limits import mean_degree_cap_armed

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def test_the_shipped_survey_arms_the_cap_at_its_first_rung():
    assert SHIPPED["limits"]["mean_degree_cap_armed_from_n"] == 64 == SHIPPED["ladder"][0]
    assert all(mean_degree_cap_armed(SHIPPED, n) for n in SHIPPED["ladder"])
    from graph_scale_dynamics.operations import study_design
    for study in study_design.designed_studies():
        limits = study_design.design_for(None, study)["limits"]
        assert limits["mean_degree_cap_armed_from_n"] == SHIPPED["limits"]["mean_degree_cap_armed_from_n"], study


def test_every_quadrant_of_the_default_study_arms_it_from_64():
    for _label, quadrant in S.quadrant_specs(SHIPPED):
        assert quadrant["limits"]["mean_degree_cap_armed_from_n"] == 64
        assert mean_degree_cap_armed(quadrant, 64)


def test_a_campaign_frozen_with_256_keeps_it():
    before = dict(SHIPPED, limits=dict(SHIPPED["limits"], mean_degree_cap_armed_from_n=256))
    assert not mean_degree_cap_armed(before, 64) and mean_degree_cap_armed(before, 256)
