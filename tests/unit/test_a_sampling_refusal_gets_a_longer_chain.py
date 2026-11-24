from __future__ import annotations

import json

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import QUEUE_ORDER, decide_pass, decision_inputs
from graph_scale_dynamics.decisions.engine import RUN_NEXT, STOP, Policy, Rung, decide
from graph_scale_dynamics.decisions.replay import replay_matches
from graph_scale_dynamics.decisions.rungs import rung_from_entry
from graph_scale_dynamics.reporting import study_reading
from tests.unit.test_decider import FakeStore, entry

POLICY = Policy()
LAW = G.unsalted_law("law-", POLICY.audit_fraction)
NEVER = "REFUSED_NEVER_EQUILIBRATED"


def unread(top_refusal, *, longer=False):
    base = [Rung(n=n, mean_degree=2.5, connected_fraction=1.0, probes={}, seeds_measured=3,
                 d_s_refusal=("REFUSED_NO_SCALING_WINDOW" if n < 4096 else top_refusal),
                 longer_chain=(longer and n == 4096)) for n in (64, 256, 1024, 4096)]
    return base


def replays(law, rungs, decision):
    row = json.loads(json.dumps(decision.as_dict() | {"inputs": decision_inputs(law, rungs, POLICY)}, default=str))
    verdict = replay_matches(dict(row, facts_json=json.dumps(decision.facts, default=str)))
    assert verdict["matches"] and verdict["same_rules"], verdict
    return True


def test_a_sampling_refusal_at_the_top_buys_the_rung_once_more_with_a_longer_chain():
    for bucket in sorted(G.REFUSAL_SAMPLING):
        d = decide(LAW, unread(bucket), POLICY)
        assert (d.action, d.rule, d.next_n, d.priority) == (RUN_NEXT, "longer_chain", 4096, 2), bucket
        assert d.facts["d_s_refusal"] == {"kind": "sampling", "bucket": bucket, "longer_chain": False}
        assert replays(LAW, unread(bucket), d)


def test_after_its_longer_chain_the_law_parks_as_before():
    d = decide(LAW, unread(NEVER, longer=True), POLICY)
    assert (d.action, d.rule) == (STOP, "no_reading") and "its longer chain did not read it either" in d.reason
    assert d.facts["d_s_refusal"]["longer_chain"] is True
    assert replays(LAW, unread(NEVER, longer=True), d)


def test_a_refusal_for_the_graph_or_the_limits_parks_at_once():
    for bucket in sorted(G.REFUSAL_GEOMETRY | G.REFUSAL_LIMITS):
        d = decide(LAW, unread(bucket), POLICY)
        assert (d.action, d.rule) == (STOP, "no_reading"), bucket
        assert d.facts["d_s_refusal"]["kind"] in ("geometry", "limits")
    unknown = decide(LAW, unread(None), POLICY)
    assert (unknown.rule, unknown.facts["d_s_refusal"]["kind"]) == ("no_reading", "not known")


def test_the_rung_carries_its_refusal_only_when_d_s_did_not_read():
    refused = rung_from_entry(4096, dict(entry(2.5), d_s=1.9, d_s_bucket=NEVER))
    assert refused.d_s_refusal == NEVER and "d_s" not in refused.probes
    read = rung_from_entry(4096, entry(2.5, d_s=1.9))
    assert read.d_s_refusal is None and "d_s" in read.probes
    assert rung_from_entry(4096, entry(2.5), longer_chain=True).longer_chain


def test_the_decider_asks_the_store_for_the_longer_chain():
    class Store(FakeStore):
        def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, longer=False, **_scale):
            self.jobs.append((law, n, seeds, work_budget, queue_order, longer))
            return seeds

    cells = {n: dict(entry(2.5), d_s_bucket=(NEVER if n >= 1024 else None)) for n in (64, 256, 1024, 4096)}
    store = Store([LAW], entries={LAW: cells})
    tally = decide_pass(store, "1")
    assert tally[("run_next", "longer_chain")] == 1
    assert store.jobs == [(LAW, 4096, 3, Policy().work_budget(4096), QUEUE_ORDER["base"], True)], (
        "the rung's own budget and rank")
    assert store.states[LAW][:2] == ("BASE_BLOCK_RUNNING", "longer_chain")
    assert [(d["priority"], d["queue_order"]) for d in store.decisions] == [(2, QUEUE_ORDER["base"])], \
        "the decision itself is unchanged; only where its rung waits"


def test_the_study_reading_counts_refusals_by_the_gates_own_groups():
    assert study_reading.SAMPLING == G.REFUSAL_SAMPLING and study_reading.GEOMETRY == G.REFUSAL_GEOMETRY
    assert study_reading.LIMITS == G.REFUSAL_LIMITS
    assert all(study_reading.kind_of(b) == G.refusal_kind(b) for b in sorted(G.REFUSAL_SAMPLING | G.REFUSAL_LIMITS))
