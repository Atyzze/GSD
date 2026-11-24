from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.limits import declares_default_limits
from graph_scale_dynamics.scheduling.provenance import (
    freeze_campaign_spec,
    policy_hashes,
    provenance_mismatches,
    search_policy_payload,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json"

BUILD_806_SEARCH_POLICY_HASH = "cd3b8c12ee510272db757210ef8856fb0ef3ed83e1e992e002e2743d288a9a27"


def _template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _pre_304(spec: dict | None = None) -> dict:
    out = deepcopy(spec or _template())
    out.pop("extension_ladder", None)
    return out


def _hashes(spec: dict) -> dict[str, str]:
    return policy_hashes(freeze_campaign_spec(spec))


BUILD_305_SCALES = ["one", "log_N", "inv_log_N", "inv_N", "inv_sqrt_N", "power"]


def test_a_default_window_campaign_keeps_its_search_policy_hash():
    spec = _pre_304()
    spec["search_policy"]["grid"]["scales"] = list(BUILD_305_SCALES)
    assert _hashes(spec)["search_policy_hash"] == BUILD_806_SEARCH_POLICY_HASH


def test_narrowing_the_scale_grid_forks_the_search_policy_hash():
    narrowed = _pre_304()
    assert narrowed["search_policy"]["grid"]["scales"] == ["one"], "the shipped grid"
    assert _hashes(narrowed)["search_policy_hash"] != BUILD_806_SEARCH_POLICY_HASH


def test_omitting_the_limits_block_hashes_the_same_as_spelling_the_defaults_out():
    from graph_scale_dynamics.scheduling.limits import DEFAULT_LIMITS
    explicit = _pre_304()
    explicit["limits"] = {"contract": explicit["limits"].get("contract"),
                          "mean_degree_window": dict(DEFAULT_LIMITS["mean_degree_window"]),
                          "connectivity_floor": DEFAULT_LIMITS["connectivity_floor"]}
    implicit = _pre_304()
    implicit.pop("limits", None)
    assert declares_default_limits(explicit) and declares_default_limits(implicit)
    assert _hashes(explicit)["search_policy_hash"] == _hashes(implicit)["search_policy_hash"]
    assert "limits" not in search_policy_payload(freeze_campaign_spec(explicit))


@pytest.mark.parametrize("field,value", [
    ("mean_degree_window", {"min": 0.0, "max": 32.0}),
    ("connectivity_floor", 0.75),
    ("mean_degree_cap_armed_from_n", 1024),
])
def test_every_declared_boundary_moves_the_search_policy_hash(field, value):
    varied = _pre_304()
    varied.setdefault("limits", {})[field] = value
    assert not declares_default_limits(varied)
    assert _hashes(varied)["search_policy_hash"] != BUILD_806_SEARCH_POLICY_HASH


def test_the_extension_ladder_moves_the_search_policy_hash():
    with_ladder = _pre_304()
    with_ladder["extension_ladder"] = [65536, 262144, 1048576]
    assert _hashes(with_ladder)["search_policy_hash"] != BUILD_806_SEARCH_POLICY_HASH


def test_the_window_moves_only_the_search_policy_hash():
    base, wide = _pre_304(), _pre_304()
    wide["limits"]["mean_degree_window"]["max"] = 32.0
    before, after = _hashes(base), _hashes(wide)
    assert after["search_policy_hash"] != before["search_policy_hash"]
    assert after["science_contract_hash"] == before["science_contract_hash"]
    assert after["resource_policy_hash"] == before["resource_policy_hash"]


def _campaign_row(campaign_id: str, spec: dict, seed: int) -> dict:
    row = {"campaign_id": campaign_id, "name": f"c{campaign_id}",
           "spec": freeze_campaign_spec(spec), "search_seed": seed,
           "created_build": 306, "created_runtime_fingerprint": "fp",
           "provenance_contract": "immutable-campaign-1"}
    row.update(_hashes(spec))
    return row


def test_a_wrong_science_hash_is_a_mismatch():
    spec = freeze_campaign_spec(_template())
    stored = _campaign_row("2", _template(), 7)
    stored["science_contract_hash"] = "0" * 64
    problems = provenance_mismatches(
        {**stored, "spec": spec, "provenance_contract": "immutable-campaign-1"})
    assert any(p.startswith("science_contract_hash") for p in problems)
