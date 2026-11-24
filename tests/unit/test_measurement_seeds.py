from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scaleflow.flow import rung_summary
from graph_scale_dynamics.scheduling.base_block import (
    MAX_MEASUREMENT_SEEDS, MIN_MEASUREMENT_SEEDS, validate_base_block,
)

ROOT = Path(__file__).resolve().parents[2]


def _spec(seeds):
    spec = json.loads(
        (ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    spec["base_block"]["measurement_seeds_per_size"] = seeds
    return spec


@pytest.mark.parametrize("seeds", [MIN_MEASUREMENT_SEEDS, 4, MAX_MEASUREMENT_SEEDS])
def test_a_workable_seed_count_is_accepted(seeds):
    assert validate_base_block(_spec(seeds)) == []


@pytest.mark.parametrize("seeds", [0, -1, 1, 2, 1.5, True, MAX_MEASUREMENT_SEEDS + 1])
def test_an_unworkable_seed_count_is_refused(seeds):
    problems = validate_base_block(_spec(seeds))
    assert any("measurement_seeds_per_size" in p for p in problems), problems


def test_a_count_below_the_floor_is_refused_at_creation():
    for seeds in (1, 2):
        problems = validate_base_block(_spec(seeds))
        assert any("at least" in p for p in problems), (seeds, problems)


def _metrics(d_s_value, se):
    return {"d_s": {"valid": True, "d_s": d_s_value, "se": se},
            "d_V": {"valid": False}, "d_B": {"valid": False}, "d_w": {"valid": False}}


def test_a_single_seed_cannot_report_reproducibility():
    out = rung_summary([_metrics(1.5, 0.4)])["d_s"]
    assert out["n_seeds"] == 1
    assert out["between_seed_sd"] is None


def test_seeds_that_agree_narrow_the_error_bar():
    one = rung_summary([_metrics(1.5, 0.4)])["d_s"]
    three = rung_summary([_metrics(1.5, 0.4)] * 3)["d_s"]
    assert three["n_seeds"] == 3
    assert three["between_seed_sd"] == 0.0
    assert three["se"] < one["se"]
    assert three["se"] == pytest.approx(one["se"] / (3 ** 0.5), rel=1e-9)


def test_seeds_that_disagree_widen_it():
    agree = rung_summary([_metrics(1.5, 0.4)] * 3)["d_s"]
    differ = rung_summary([_metrics(1.2, 0.4), _metrics(1.5, 0.4), _metrics(1.8, 0.4)])["d_s"]
    assert differ["between_seed_sd"] > 0.0
    assert differ["se"] > agree["se"]
    assert differ["mean"] == pytest.approx(1.5)


def test_the_freeze_tool_hashes_this_tree_not_an_installed_copy():
    source = (ROOT / "tools" / "science_freeze.py").read_text(encoding="utf-8")
    inserted = source.index("sys.path.insert(0, str(ROOT))")
    imported = source.index("from graph_scale_dynamics.domain.science_identity import")
    assert inserted < imported, (
        "science_freeze.py imports science_identity before putting this tree first "
        "on sys.path, so it can hash an installed copy instead of the checkout"
    )
