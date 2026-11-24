from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.base_block import (
    BASE_BLOCK_CONTRACT, DEFAULT_BASE_SIZES, base_sizes, validate_base_block,
)
from graph_scale_dynamics.scheduling.campaign import validate_campaign
from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json"


def _spec():
    return json.loads(CONFIG.read_text())


def test_five_rungs_is_the_default_and_validates():
    spec = _spec()
    assert base_sizes(spec) == (64, 256, 1024, 4096, 16384) == DEFAULT_BASE_SIZES
    assert validate_base_block(spec) == []


def _strip_depth(spec):
    spec.pop("extension_ladder", None)
    return spec


def test_four_and_six_rungs_are_equally_legal():
    for sizes in ([64, 256, 1024, 4096], [64, 256, 1024, 4096, 16384, 65536]):
        spec = _strip_depth(_spec())
        spec["ladder"] = sizes
        spec["stage_seeds"] = {str(i): 3 for i in range(len(sizes))}
        spec["base_block"]["sizes"] = sizes
        spec["budgets"]["max_n"] = sizes[-1]
        spec["policy"]["initial_sweeps_multiplier"] = {str(n): 4 for n in sizes}
        spec["policy"]["convergence"]["min_rungs_for_fits"] = len(sizes)
        spec["policy"]["equilibration_rejection_min_rungs"] = len(sizes)
        assert validate_campaign(freeze_campaign_spec(spec)) == [], sizes
        assert base_sizes(spec) == tuple(sizes)


def test_the_ladder_is_the_base_block_and_nothing_deeper():
    spec = _strip_depth(_spec())
    spec["ladder"] = [64, 256, 1024, 4096, 16384, 65536]
    problems = validate_base_block(spec)
    assert any("exactly the base block" in p for p in problems)


def test_fewer_than_three_rungs_is_refused():
    spec = _spec()
    spec["ladder"] = [64, 256]
    spec["base_block"]["sizes"] = [64, 256]
    assert any("at least 3" in p for p in validate_base_block(spec))
    with pytest.raises(ValueError):
        base_sizes(spec)


def test_contract_name_is_not_a_rung_count():
    assert "four" not in BASE_BLOCK_CONTRACT
