from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.operations import focus
from graph_scale_dynamics.operations import study_map

ROOT = Path(__file__).resolve().parents[2]


def _world(monkeypatch, own: dict, more: dict):
    kinds = {"11": own, "13": more}
    monkeypatch.setattr(study_map, "decided", lambda repo, campaign, law: True)
    monkeypatch.setattr(focus, "seed_kinds", lambda repo, campaign, law: kinds[str(campaign)])
    state = {"plan": focus.plan(ROOT), "campaigns": {focus.NEIGHBOURS: "12", focus.SEEDS: "13", focus.DEPTH: "14"}}
    current = {"law": "holder", "of": "11", "kind": "frozen"}
    return state, current


def test_the_seeds_campaign_s_new_seeds_join_the_law_s_own_three_by_number(monkeypatch):
    own = {seed: {4096: "frozen", 16384: "frozen"} for seed in (0, 1, 2)}
    more = {seed: {4096: "frozen", 16384: "frozen" if seed != 4 else "moved"} for seed in range(6)}
    state, current = _world(monkeypatch, own, more)
    found = focus.seeds_of(None, state, current)
    assert found["of"] == 6, "seeds 3 to 5 exist only in the seeds' campaign, and are counted"
    assert found["other"] == [4] and found["reproduced"] is True
    assert set(found["more"]) == {"0", "1", "2", "3", "4", "5"} and set(found["own"]) == {"0", "1", "2"}


def test_a_seed_its_run_again_reads_differently_is_not_reproduced(monkeypatch):
    own = {seed: {16384: "frozen"} for seed in (0, 1, 2)}
    more = {seed: {16384: "moved" if seed == 1 else "frozen"} for seed in range(6)}
    state, current = _world(monkeypatch, own, more)
    found = focus.seeds_of(None, state, current)
    assert found["reproduced"] is False and found["compared_at"]["1"] == 16384
    assert found["other"] == [1], "each seed read at 16,384 in the seeds' campaign"


def test_a_seed_is_compared_at_the_size_both_campaigns_read_and_not_across_sizes(monkeypatch):
    own = {seed: {1024: "made", 4096: "made"} for seed in (0, 1, 2)}
    more = {seed: {1024: "made", 4096: "made", 16384: "moved"} for seed in range(6)}
    state, current = _world(monkeypatch, own, more)
    current["kind"] = "moved"
    found = focus.seeds_of(None, state, current)
    assert found["reproduced"] is True and found["compared_at"] == {"0": 4096, "1": 4096, "2": 4096}, (
        "its own campaign at 4,096 against the seeds' campaign at 4,096, not at 16,384")
    assert found["other"] == [] and found["of"] == 6


def test_nothing_about_its_seeds_is_said_before_its_own_kind_is_read(monkeypatch):
    state, current = _world(monkeypatch, {0: {16384: "ring"}}, {0: {16384: "ring"}})
    current["kind"] = None
    assert focus.seeds_of(None, state, current) is None
