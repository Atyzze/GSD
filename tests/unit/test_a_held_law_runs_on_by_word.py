from __future__ import annotations

import json

from graph_scale_dynamics.decisions import by_word
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.decisions.let_through import Ledger
from graph_scale_dynamics.decisions.replay import replay_matches

POLICY = Policy()
LAW = G.unsalted_law("law-", POLICY.audit_fraction)
OTHER = G.unsalted_law("other-", POLICY.audit_fraction)


def entry(md, cf=1.0):
    return {"mean_degree": md, "connected_fraction": cf, "measurement_seed_count": 3, "d_s": None,
            "d_s_bucket": None, "probes": {"d_s": {"se": 0.05}}}


DENSE = {64: entry(17.0), 256: entry(17.0)}


class Store:
    def __init__(self, awaiting, named):
        self.awaiting, self.named = list(awaiting), dict(named)
        self.jobs, self.states, self.decisions = [], {}, []

    def laws_awaiting_decision(self, campaign_id):
        return self.awaiting

    def run_on_laws(self, campaign_id):
        return self.named

    def law_evidence(self, campaign_id, law):
        return {"entries": DENSE, "phenotype": {"per_n": DENSE}}

    def record_phenotype(self, campaign_id, law, phenotype):
        return None

    def seed_rows(self, campaign_id, law):
        return {}

    def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, **_scale):
        self.jobs.append((law, n))
        return seeds

    def set_law_state(self, campaign_id, law, state, *, rule, next_n, parked_ok=False):
        self.states[law] = (state, rule, next_n, parked_ok)
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return 1

    def held_laws(self, campaign_id):
        return []


def named(gate="too_dense", at_n=256):
    return {"gate": gate, "at_n": at_n, "list": "graph_scale_dynamics/resources/readings/study_1_run_on.json",
            "class": "a line or a ring"}


def test_the_gate_alone_stops_the_law_and_the_word_runs_it_on_to_the_next_size():
    alone = Store([LAW], {})
    decide_pass(alone, "1")
    assert (alone.decisions[0]["action"], alone.decisions[0]["rule"], alone.decisions[0]["at_n"]) == (
        "stop", "too_dense", 256)
    store = Store([], {LAW: named()})
    decide_pass(store, "1")
    row = store.decisions[0]
    assert (row["action"], row["rule"], row["at_n"], row["next_n"]) == ("run_next", by_word.RULE, 256, 1024)
    assert store.jobs == [(LAW, 1024)]
    assert store.states[LAW][0] == "BASE_BLOCK_RUNNING" and store.states[LAW][3] is True, (
        "a parked law is revived only by a decision that names it")
    assert row["facts"]["run_on"]["gate"] == "too_dense" and row["facts"]["run_on"]["held"]["action"] == "stop"
    assert "the operator's word past too_dense at N=256" in row["reason"]
    assert row["inputs"]["run_on"] == named()


def test_a_word_for_another_gate_or_size_changes_nothing():
    for word in (named(gate="empty"), named(at_n=1024)):
        store = Store([], {LAW: word})
        decide_pass(store, "1")
        assert (store.decisions[0]["action"], store.decisions[0]["rule"]) == ("stop", "too_dense")
        assert store.jobs == []


def test_every_decision_replays_with_the_word_and_without_it():
    store = Store([OTHER], {LAW: named()})
    decide_pass(store, "1")
    assert {row["rule"] for row in store.decisions} == {"too_dense", by_word.RULE}
    for row in store.decisions:
        found = replay_matches(json.loads(json.dumps(row, default=str)))
        assert found["matches"], found["differences"]


def test_the_gate_s_counts_do_not_move_when_a_law_runs_on():
    def rows(with_word):
        out = [{"campaign_id": "1", "candidate_id": LAW, "decision_id": "001", "at_n": 256, "action": "stop",
                "rule": "too_dense", "salted": None, "signature": None}]
        if with_word:
            out += [{"campaign_id": "1", "candidate_id": LAW, "decision_id": "002", "at_n": 256,
                     "action": "run_next", "rule": by_word.RULE, "salted": None, "signature": None},
                    {"campaign_id": "1", "candidate_id": LAW, "decision_id": "003", "at_n": 1024,
                     "action": "stop", "rule": "too_dense", "salted": None, "signature": None}]
        return out

    def counts(ledger):
        return {key: (c.held, c.let_through, c.clean) for key, c in ledger.counters.items()}

    plain, worded = Ledger(), Ledger()
    for row in rows(False):
        plain.feed(row)
    for row in rows(True):
        worded.feed(row)
    assert counts(worded) == counts(plain) == {("too_dense", 256): (1, 0, 0)}
    assert worded.by_word == {("1", LAW)}


def test_the_flag_names_laws_by_campaign_and_refuses_what_it_does_not_know():
    raw = json.dumps(by_word.flag({"path": "x.json", "sha256": "ab"}, {"7": {LAW: named()}}))
    assert by_word.entries_of(raw, "7") == {LAW: named()}
    assert by_word.entries_of(raw, "8") == {}
    assert by_word.entries_of("not json", "7") == {} and by_word.entries_of(json.dumps({"laws": {}}), "7") == {}
