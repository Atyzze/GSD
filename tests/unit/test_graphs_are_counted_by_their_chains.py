from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.observability.rung_distribution import chains_per_seed
from graph_scale_dynamics.operations import study_design as SD
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]


def test_a_seed_grows_its_chain_from_empty_and_every_given_chain():
    assert chains_per_seed({"sampling_contract": {"given_starts": [{"name": "a"}, {"name": "b"}]}}) == 3
    assert chains_per_seed({"sampling_contract": {"given_start_rule": {"by": "atlas"}}}) == 2
    assert chains_per_seed({"sampling_contract": {"given_start": {"family": "x"}}}) == 2
    assert chains_per_seed({}) == 1 and chains_per_seed(None) == 1


def test_a_study_on_eight_starts_grows_eight_graphs_a_seed():
    design = designs.a_design()
    base = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                      .read_text(encoding="utf-8"))
    for index, entry in enumerate(design["campaigns"]):
        assert chains_per_seed(SD.campaign_spec(design, base, entry, index)) == 8
