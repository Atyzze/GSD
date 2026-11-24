from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from tools import benchmark_campaign as B  # noqa: E402
from graph_scale_dynamics.decisions.engine import Policy  # noqa: E402
from graph_scale_dynamics.dsl import dsl  # noqa: E402
from graph_scale_dynamics.scheduling.campaign import validate_campaign  # noqa: E402
from graph_scale_dynamics.scheduling.limits import work_budget  # noqa: E402

KINDS = {"engine": B.benchmark_spec, "lattice": B.lattice_spec, "deep": B.deep_spec}


@pytest.fixture(scope="module")
def base():
    return json.loads(B.DEFAULT_SPEC.read_text())


def test_the_tool_derives_from_the_engine_survey():
    assert B.DEFAULT_SPEC.name == "campaign_engine_survey.json" and B.DEFAULT_SPEC.is_file()


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_campaign_start_accepts_every_benchmark(base, kind):
    spec = KINDS[kind](base)
    assert validate_campaign(spec) + main._engine_required(spec) == [], kind


@pytest.mark.parametrize("kind,ladder,seeds", [
    ("engine", (64, 256, 1024, 4096), 3),
    ("lattice", (64, 256, 1024, 4096, 16384, 65536, 262144), 5),
    ("deep", (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576), 5),
])
def test_every_reader_of_the_ladder_reads_the_engines(base, kind, ladder, seeds):
    spec = KINDS[kind](base)
    policy = Policy.from_spec(spec)
    assert policy.ladder() == ladder and tuple(spec["ladder"]) == ladder
    assert list(policy.base_sizes) == spec["base_block"]["sizes"]
    assert list(policy.deep_sizes) == spec.get("extension_ladder", [])
    assert policy.seeds == seeds == spec["base_block"]["measurement_seeds_per_size"] == spec["default_seeds"]
    assert set(spec["stage_seeds"].values()) == {seeds} and len(spec["stage_seeds"]) == len(ladder)
    assert spec["budgets"]["max_n"] == ladder[-1]
    assert all(work_budget(spec, n) == policy.work_budget(n) for n in ladder)
    assert policy.audit_fraction == 1.0
    assert spec["search_policy"]["kind"] == "hand" and spec["proposer"] == {"pool_min": 1}


def test_the_lattice_and_deep_budgets(base):
    from graph_scale_dynamics.scheduling.limits import units_for_seconds
    lattice = Policy.from_spec(B.lattice_spec(base))
    assert all(lattice.work_budget(n) >= units_for_seconds(base, 4 * 3600) for n in lattice.ladder())
    deep = Policy.from_spec(B.deep_spec(base))
    assert deep.work_budget(262144) == units_for_seconds(base, 4 * 3600)
    assert deep.work_budget(1048576) == units_for_seconds(base, 24 * 3600)


def test_the_lattice_laws_are_valid_laws():
    laws = B.lattice_laws()
    assert len(laws) == 46
    assert not [law["label"] for law in laws if dsl.validate(law["spec"], complexity_budget=12)]
