from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from graph_scale_dynamics.decisions import every_chain as EC
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import Policy, Rung, Seed, decide
from graph_scale_dynamics.decisions.replay import replay_matches

ROOT = Path(__file__).resolve().parents[2]
DESIGN = json.loads((ROOT / "tests/fixtures/a_design.json").read_text())
A_POLICY = replace(Policy(), **{key: value for key, value in DESIGN["engine"].items() if hasattr(Policy(), key)})
A_LAW = "5228e5bd1f2eb488a20e8c59e818a4db7e10e2f7d1221e6cdedca263ab94cd2e"
LATTICES = ("square", "triangular", "cubic", "bcc", "fcc", "tesseract")


def entry(md, cf=1.0):
    return {"mean_degree": md, "connected_fraction": cf, "measurement_seed_count": 3, "d_s": None,
            "d_s_bucket": None, "probes": {"d_s": {"se": None}}}


BASE = {64: entry(16.03, 0.94), 256: entry(16.01, 0.95), 1024: entry(16.0, 0.95), 4096: entry(16.0, 0.96)}
ONLY_4096 = {4096: entry(16.0)}


class FakeStore:
    def __init__(self, chains):
        self.chains, self.decisions, self.failures = chains, [], []

    def laws_awaiting_decision(self, campaign_id):
        return [A_LAW]

    def law_evidence(self, campaign_id, law):
        return {"entries": BASE, "phenotype": None, "chains": self.chains}

    def record_phenotype(self, campaign_id, law, phenotype):
        pass

    def seed_rows(self, campaign_id, law):
        return {}

    def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, **_scale):
        return seeds

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def record_failure(self, campaign_id, law, error):
        self.failures.append(error)

    def queue_depth(self, campaign_id):
        return 1

    def held_laws(self, campaign_id, limit=None):
        return []


def test_a_lattice_chain_read_only_at_the_law_s_top_is_decided_without_it_and_nothing_fails():
    store = FakeStore({"random": BASE, **{name: ONLY_4096 for name in LATTICES}})
    tally = decide_pass(store, "3", A_POLICY)
    assert store.failures == [] and not [key for key in tally if key[0] == "failed"], (tally, store.failures)
    decision = store.decisions[0]
    assert decision["rule"] != "failed"
    assert set(decision["facts"]["chains"]) == {"empty", "random"}
    assert replay_matches(json.loads(json.dumps(decision, default=str)))["matches"]


def test_it_decides_as_the_law_would_without_those_chains():
    with_lattices = FakeStore({"random": BASE, **{name: ONLY_4096 for name in LATTICES}})
    without = FakeStore({"random": BASE})
    decide_pass(with_lattices, "3", A_POLICY)
    decide_pass(without, "3", A_POLICY)
    a, b = with_lattices.decisions[0], without.decisions[0]
    assert (a["action"], a["rule"], a["next_n"], a["reason"]) == (b["action"], b["rule"], b["next_n"], b["reason"])


def test_a_lattice_chain_with_a_rung_below_still_takes_part():
    store = FakeStore({"random": BASE, "square": {1024: entry(16.0), 4096: entry(16.0)}})
    decide_pass(store, "3", A_POLICY)
    assert set(store.decisions[0]["facts"]["chains"]) == {"empty", "random", "square"}


@pytest.mark.parametrize("n", [4096, 16384, 65536])
def test_the_engine_alone_still_needs_a_rung_below_so_the_chain_is_kept_out_before_it(n):
    seeds = tuple(Seed(termination="converged", work_units=10, work_budget=3600) for _ in range(3))
    lone = [Rung(n=n, mean_degree=3.0, connected_fraction=1.0, seeds=seeds)]
    with pytest.raises(IndexError):
        decide(A_LAW, lone, A_POLICY)
    base = [Rung(n=size, mean_degree=3.0, connected_fraction=1.0, seeds=seeds) for size in (64, 256, 1024, 4096)]
    deeper = base + [Rung(n=size, mean_degree=3.0, connected_fraction=1.0, seeds=seeds)
                     for size in (16384, 65536) if size <= n]
    chosen = EC.decide_every_chain(A_LAW, {"empty": deeper, "square": lone}, A_POLICY)
    assert "square" not in chosen.facts["chains"]


def test_a_lone_rung_in_the_base_block_still_takes_part():
    seeds = tuple(Seed(termination="converged", work_units=1, work_budget=60) for _ in range(3))
    first = [Rung(n=64, mean_degree=3.0, connected_fraction=1.0, seeds=seeds)]
    chosen = EC.decide_every_chain(A_LAW, {"empty": first, "square": first}, A_POLICY)
    assert set(chosen.facts["chains"]) == {"empty", "square"}
