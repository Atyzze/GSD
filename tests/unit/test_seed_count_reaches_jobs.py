from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.base_block import (
    MAX_MEASUREMENT_SEEDS, MIN_MEASUREMENT_SEEDS, measurement_seeds,
)

ROOT = Path(__file__).resolve().parents[2]


def test_the_shipped_default_declares_three_seeds():
    spec = json.loads(
        (ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    assert measurement_seeds(spec) == 3


@pytest.mark.parametrize("declared,expected", [
    (3, 3), (4, 4), (MAX_MEASUREMENT_SEEDS, MAX_MEASUREMENT_SEEDS),
    (MAX_MEASUREMENT_SEEDS + 50, MAX_MEASUREMENT_SEEDS),
    (1, MIN_MEASUREMENT_SEEDS), (2, MIN_MEASUREMENT_SEEDS),
    (0, MIN_MEASUREMENT_SEEDS), (-3, MIN_MEASUREMENT_SEEDS),
    ("three", MIN_MEASUREMENT_SEEDS), (None, MIN_MEASUREMENT_SEEDS),
])
def test_the_accessor_is_total(declared, expected):
    assert measurement_seeds({"base_block": {"measurement_seeds_per_size": declared}}) == expected


def test_a_spec_that_says_nothing_gets_the_floor_and_not_the_useless_count():
    assert measurement_seeds({}) == MIN_MEASUREMENT_SEEDS
    assert measurement_seeds({"base_block": {}}) == MIN_MEASUREMENT_SEEDS
