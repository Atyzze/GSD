from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import dev_mode
from graph_scale_dynamics.research.stability_score import score_rung_rows
from graph_scale_dynamics.scheduling.campaign import validate_campaign

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = (ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json")


@pytest.fixture
def spec() -> dict:
    return json.loads(DEFAULT_SPEC.read_text())


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv(dev_mode.ENV_VAR, "1")
    assert dev_mode.enabled()
    return dev_mode


@pytest.fixture
def certified(monkeypatch):
    monkeypatch.delenv(dev_mode.ENV_VAR, raising=False)
    assert not dev_mode.enabled()


def test_every_relaxation_is_declared_with_its_cost():
    for name, text in dev_mode.RELAXATIONS.items():
        assert "Gives up:" in text, f"{name} does not state what it costs"


def test_provenance_lists_the_relaxations(dev):
    stamp = dev_mode.provenance()
    assert stamp["development_mode"] is True
    assert stamp["certified_run"] is False
    assert stamp["relaxations"] == sorted(dev_mode.RELAXATIONS)


@pytest.mark.parametrize("mutate,fragment", [
    (lambda s: s["base_block"].__setitem__("no_scientific_selection_until_terminal", False),
     "no_scientific_selection_until_terminal"),
])
def test_scientific_invariants_refuse_even_in_dev_mode(dev, spec, mutate, fragment):
    mutate(spec)
    assert any(fragment in problem for problem in validate_campaign(spec)), \
        f"{fragment} must still refuse with every relaxation active"


def test_never_relaxed_names_are_not_also_relaxations():
    overlap = set(dev_mode.NEVER_RELAXED) & set(dev_mode.RELAXATIONS)
    assert not overlap, f"cannot both relax and refuse to relax: {overlap}"


def test_unknown_relaxation_still_raises(dev):
    with pytest.raises(KeyError):
        dev_mode.relaxation_active("no_such_relaxation")


def test_default_spec_is_clean_either_way(certified, spec):
    assert validate_campaign(spec) == []
    os.environ[dev_mode.ENV_VAR] = "1"
    try:
        assert validate_campaign(spec) == []
    finally:
        del os.environ[dev_mode.ENV_VAR]


def test_score_rung_rows_on_no_rungs_returns_zero_not_indexerror():
    scored = score_rung_rows([], floors={"d_s": 0.3, "d_V": 0.03, "d_B": 0.12, "d_w": 0.07})
    assert all(block["score"] == 0.0 for block in scored["blocks"].values())
    assert set(scored["buckets"].values()) == {"NOT_ATTEMPTED"}


def _law(candidate_id: str, family: int, values: list[float], top_n: int,
         stability_score: float = 25.0) -> dict:
    sizes = [64, 256, 1024, 4096, 16384][:len(values)]
    points = [{"n": n, "value": v, "se": 0.1} for n, v in zip(sizes, values, strict=True)]
    return {"candidate_id": candidate_id, "family_id": family,
            "family_label": f"fam-{family}", "family_structure": (),
            "coefficient_vector": [0.1 * len(candidate_id), 0.2], "spec": {},
            "trajectory": points, "top_n": top_n, "latest_value": points[-1]["value"],
            "latest_se": 0.1, "flow_slope_per_log_n": 0.05, "latest_drift": 0.01,
            "stability_score": stability_score}
