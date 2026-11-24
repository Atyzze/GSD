import json
from copy import deepcopy
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.base_block import (
    anchor_n, base_sizes, extension_sizes, is_extension_rung,
    validate_base_block,
)
from graph_scale_dynamics.scheduling.campaign import validate_campaign

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
BASE = [64, 256, 1024, 4096, 16384]


def _with_depth(rungs=(65536, 262144)):
    spec = deepcopy(SURVEY)
    spec.pop("extension_ladder", None)
    spec["extension_ladder"] = list(rungs)
    spec["ladder"] = BASE + list(rungs)
    return spec


def test_the_anchor_is_derived_not_declared():
    spec = _with_depth()
    assert anchor_n(spec) == max(base_sizes(spec)) == 16384
    assert "anchor_n" not in spec


@pytest.mark.parametrize("n,expected", [(64, False), (16384, False), (65536, True), (262144, True)])
def test_extension_rungs_are_identified_by_n(n, expected):
    assert is_extension_rung(_with_depth(), n) is expected


def test_an_extension_rung_at_or_below_the_anchor_is_refused():
    spec = _with_depth()
    spec["extension_ladder"] = [16384, 65536]
    spec["ladder"] = BASE + [16384, 65536]
    problems = validate_base_block(spec)
    assert any("strictly above the base block" in p for p in problems), problems


def test_the_ladder_must_match_the_two_declarations():
    spec = _with_depth()
    spec["ladder"] = BASE + [65536]
    problems = validate_base_block(spec)
    assert any("base_block.sizes followed by extension_ladder" in p for p in problems), problems


def test_a_ladder_past_the_block_without_a_declaration_is_still_refused():
    spec = deepcopy(SURVEY)
    spec.pop("extension_ladder", None)
    spec["ladder"] = BASE + [65536]
    problems = validate_base_block(spec)
    assert any("unless extension_ladder declares" in p for p in problems), problems


@pytest.mark.parametrize("bad", [[], [65536, 65536], [262144, 65536], [-1], ["65536"]])
def test_a_malformed_extension_ladder_is_refused(bad):
    spec = _with_depth()
    spec["extension_ladder"] = bad
    spec["ladder"] = BASE + [v for v in bad if isinstance(v, int)]
    assert validate_base_block(spec), f"{bad} should not validate"


def test_extension_sizes_raises_rather_than_guessing_on_a_bad_spec():
    spec = _with_depth()
    spec["extension_ladder"] = [262144, 65536]
    with pytest.raises(ValueError, match="strictly increasing"):
        extension_sizes(spec)


def _rung_rows(ns):
    return [{"n": n, "summary": {"n": n, "connected_fraction": {"mean": 0.99},
                                 "d_s": {"mean": 1.24 + 0.001 * i, "se": 0.01}},
             "terminal_classification": "EQUILIBRATED_ACTIVE", "chains_verdict": None}
            for i, n in enumerate(ns)]


def test_the_shipped_depth_config_validates_and_is_shaped_as_declared():
    spec = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    problems = validate_campaign(spec)
    assert not problems, problems
    assert base_sizes(spec) == tuple(BASE), "the neutral population is unchanged"
    assert extension_sizes(spec) == (65536, 262144, 1048576)
    assert anchor_n(spec) == 16384
    assert spec["limits"]["mean_degree_window"] == {"min": 0.0, "max": 16.0}, (
        "build 415: the open window. Campaign 1 of build 414 measured what [1.5, 8] "
        "cost: 142 of 461 laws (30.8%) ended pinned at the cap reading 8.03/8.01/8.00 "
        "and only 8 of them ever produced a d_s value, while 199 more sat below the "
        "floor producing none. 74% of the population was unreadable by construction")
    assert spec["limits"]["mean_degree_cap_armed_from_n"] == 256, (
        "build 425: armed from 256, not 1024. Measured on the 424 bundle: at N=256 the mean degree quantiles are 1.5 / 8.0 / 41.0 / 255.0 and the MAX IS 255.0, the complete graph. 18.2% of laws exceed 16 there and 6.6% reach 128+, and N=256 was 46.9% of all simulation wall. At N=64 the same laws top out at 63.0, also complete, for 3.7%. One unclamped rung shows the divergence; the second shows it again at sixteen times the edges")


def test_the_child_is_handed_the_budget_in_work_for_its_own_rung():
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    policy = Policy.from_spec(SURVEY)
    for n in (16384, 65536):
        made = one_shot_policy(SURVEY, n)
        assert made["work_budget"] == policy.work_budget(n)
        assert made["work_unit"]["weights"] == policy.work_weights()
    assert one_shot_policy(SURVEY)["work_budget"] == policy.work_budget(policy.base_sizes[-1])
