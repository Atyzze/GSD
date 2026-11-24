from __future__ import annotations

import json

from graph_scale_dynamics.decisions import every_chain as EC
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import structure_gate as SG
from graph_scale_dynamics.decisions.decider import QUEUE_ORDER, decide_pass
from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT, STOP, Decision, Policy, Rung, policy_fingerprint
from graph_scale_dynamics.decisions.replay import replay_matches

EVERY = Policy(every_chain=True)
LAW = G.unsalted_law("law-", EVERY.audit_fraction)


def entry(md, cf=1.0, d_s=None, se=0.05):
    return {"mean_degree": md, "connected_fraction": cf, "measurement_seed_count": 3, "d_s": d_s,
            "d_s_bucket": None, "probes": {"d_s": {"se": se}}}


EMPTY = {64: entry(0.0), 256: entry(0.0), 1024: entry(0.0), 4096: entry(0.0)}
SETTLED = {64: entry(3.0), 256: entry(3.0), 1024: entry(3.0, d_s=1.98), 4096: entry(3.0, d_s=2.01)}


class FakeStore:
    def __init__(self, entries, chains=None):
        self.entries, self.chains = entries, chains
        self.jobs, self.states, self.decisions = [], {}, []

    def laws_awaiting_decision(self, campaign_id):
        return [LAW]

    def law_evidence(self, campaign_id, law):
        out = {"entries": self.entries, "phenotype": None}
        if self.chains is not None:
            out["chains"] = self.chains
        return out

    def record_phenotype(self, campaign_id, law, phenotype):
        pass

    def seed_rows(self, campaign_id, law):
        return {}

    def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, **_scale):
        self.jobs.append((law, n, queue_order))
        return seeds

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        self.states[law] = (state, rule, next_n)
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return 1

    def held_laws(self, campaign_id, limit=None):
        return []


def test_a_given_chain_that_settles_earns_the_law_its_next_size_where_the_chain_from_empty_stays_empty():
    store = FakeStore(EMPTY, chains={"random": EMPTY, "honeycomb": SETTLED})
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert (decision["action"], decision["rule"], decision["next_n"]) == (RUN_NEXT, "d_s_settled", 16384)
    assert store.jobs == [(LAW, 16384, QUEUE_ORDER[1])]
    facts = decision["facts"]
    assert facts["earned_by"] == "honeycomb" and decision["reason"].startswith("the chain from honeycomb: ")
    assert facts["chains"]["empty"]["rule"] == "empty" and facts["chains"]["random"]["rule"] == "empty"
    assert set(decision["inputs"]["chains"]) == {"random", "honeycomb"}
    assert replay_matches(json.loads(json.dumps(decision, default=str)))["matches"], "it replays from every chain"


def test_without_the_rule_the_chain_from_empty_decides_as_before():
    store = FakeStore(EMPTY, chains={"random": EMPTY, "honeycomb": SETTLED})
    decide_pass(store, "1", Policy())
    decision = store.decisions[0]
    assert (decision["action"], decision["rule"]) == (STOP, "empty") and "chains" not in decision["facts"]
    assert "chains" not in decision["inputs"], "a campaign that does not declare it records what it always did"
    assert policy_fingerprint(Policy()) != policy_fingerprint(EVERY)


def test_when_no_chain_earns_a_rung_the_chain_from_empty_s_stop_stands_with_every_chain_s_beside_it():
    dense = {64: entry(17.0), 256: entry(17.0)}
    store = FakeStore({64: entry(0.0), 256: entry(0.0)}, chains={"random": dense, "honeycomb": dense})
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert (decision["action"], decision["rule"]) == (STOP, "empty") and "earned_by" not in decision["facts"]
    assert {name: row["rule"] for name, row in decision["facts"]["chains"].items()} == {
        "empty": "empty", "random": "too_dense", "honeycomb": "too_dense"}


def test_a_chain_whose_readings_stop_below_the_top_rung_takes_no_part():
    short = {64: entry(3.0), 256: entry(3.0), 1024: entry(3.0, d_s=1.98)}
    store = FakeStore(EMPTY, chains={"honeycomb": short})
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert decision["rule"] == "empty" and set(decision["facts"]["chains"]) == {"empty"}


def _decision(action, rule, next_n, facts=None):
    return Decision(law=LAW, action=action, rule=rule, reason=rule, at_n=4096, next_n=next_n, facts=facts or {})


def test_a_rung_on_a_chain_s_own_reading_goes_before_one_for_audit_s_sake_and_the_furthest_first():
    own, salted = _decision(RUN_NEXT, "d_s_settled", 16384), _decision(RUN_NEXT, "salted", 16384, {"salted": ["x"]})
    longer, hold = _decision(RUN_NEXT, "longer_chain", 4096), _decision(HOLD, "deep_lane_full", 16384)
    stop = _decision(STOP, "empty", None)
    ranked = sorted([(stop, 0), (hold, 1), (salted, 2), (longer, 3), (own, 4)], key=lambda pair: EC._rank(*pair))
    assert [d.rule for d, _ in ranked] == ["d_s_settled", "longer_chain", "salted", "deep_lane_full", "empty"]
    settled = Decision(law=LAW, action=RUN_NEXT, rule="d_s_settled", reason="", at_n=4096, next_n=16384, priority=1)
    looked = Decision(law=LAW, action=RUN_NEXT, rule="second_rung", reason="", at_n=4096, next_n=16384, priority=2)
    assert min([(looked, 0), (settled, 1)], key=lambda pair: EC._rank(*pair))[0] is settled


def test_a_settled_d_s_goes_before_a_second_look_whichever_chain_comes_first():
    looked = {64: entry(3.0), 256: entry(3.0), 1024: entry(3.0, d_s=1.5), 4096: entry(3.0, d_s=2.5)}
    store = FakeStore(EMPTY, chains={"random": looked, "honeycomb": SETTLED})
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert (decision["rule"], decision["priority"], decision["facts"]["earned_by"]) == ("d_s_settled", 1, "honeycomb")
    assert decision["facts"]["chains"]["random"]["rule"] == "second_rung"
    from graph_scale_dynamics.decisions.replay import replay
    row = json.loads(json.dumps(decision, default=str))
    assert replay_matches(row)["matches"] is True
    row["inputs"]["rules_revision"] = 537
    taken = replay(row["inputs"])
    assert (taken.rule, taken.priority, taken.facts["earned_by"]) == ("second_rung", 2, "random")


def test_a_decision_replays_with_its_chains_in_the_order_it_took_them():
    alike = {64: entry(3.0), 256: entry(3.0), 1024: entry(3.0)}
    store = FakeStore({64: entry(0.0), 256: entry(0.0), 1024: entry(0.0)}, chains={"random": alike, "cubic": alike})
    decide_pass(store, "1", EVERY)
    row = json.loads(json.dumps(store.decisions[0], sort_keys=True, default=str))
    assert row["facts"]["earned_by"] == "random" and row["inputs"]["chain_order"] == ["random", "cubic"]
    assert list(row["inputs"]["chains"]) == ["cubic", "random"], "stored by name"
    assert replay_matches(row)["matches"] is True
    before = json.loads(json.dumps(row))
    before["inputs"].pop("chain_order")
    assert replay_matches(before)["matches"] is False, "by name, the cubic chain's"
    assert replay_matches(before, ["random", "cubic"])["matches"] is True, "in the campaign's order"


def _metrics(n, *, given_d_s=None, edges=96, giant=64):
    census = {"n": n, "edges": edges, "largest_component": {"size": giant}}
    probe = {"valid": given_d_s is not None, "value": given_d_s, "se": 0.05,
             **({} if given_d_s is not None else {"refusal": "TOO_FEW_USABLE_POINTS"})}
    return {"health": {"n": n}, "census": {"empty": census, "given": census, "honeycomb": census},
            "chain_probes": {"given": {"d_s": probe, "d_V": {"valid": False, "value": None, "se": None,
                                                             "refusal": None}},
                             "honeycomb": {"d_s": probe}}}


def test_a_given_chain_s_cells_are_built_as_the_chain_from_empty_s_from_its_probes_and_census():
    spec = {"sampling_contract": {"given_starts": [{"name": "random"}, {"name": "honeycomb"}]}}
    state = {"terminal": True, "classification": "AT_REST", "history": [], "failures": []}
    rows = {64: [_metrics(64, given_d_s=1.9) for _ in range(3)]}
    cells = EC.chain_cells(spec, rows, {64: state})
    assert set(cells) == {"random", "honeycomb"}
    for name in ("random", "honeycomb"):
        cell = cells[name][64]
        assert cell["mean_degree"] == 3.0 and cell["connected_fraction"] == 1.0
        assert cell["measurement_seed_count"] == 3 and abs(cell["d_s"] - 1.9) < 1e-12 and cell["d_s_bucket"] is None
    assert EC.chain_names(spec) == ["empty", "random", "honeycomb"]


def test_a_given_chain_not_read_keeps_the_rung_s_seeds_and_reads_nothing():
    spec = {"sampling_contract": {"given_starts": [{"name": "random"}]}}
    state = {"terminal": True, "classification": "AT_REST", "history": [], "failures": []}
    metrics = _metrics(64, given_d_s=None)
    cell = EC.chain_cells(spec, {64: [metrics, metrics, metrics]}, {64: state})["random"][64]
    assert cell["measurement_seed_count"] == 3 and cell["d_s"] is None and cell["d_s_bucket"]


def test_each_chain_s_structure_is_read_as_a_pair_of_itself():
    structure = {65536: {"empty": {"seeds": 3, "gap": 0.1}, "given": {"seeds": 3, "gap": 0.2},
                         "more_given": {"honeycomb": {"seeds": 3, "gap": 0.3}},
                         "log_diameter": {"raised": 0, "false": 3, "unknown": 0, "not_measured": 0}}}
    from_empty = EC.chain_structure(structure, -1, "empty")[65536]
    assert from_empty["empty"] is from_empty["given"] and from_empty["log_diameter"]["false"] == 3
    first = EC.chain_structure(structure, 0, "random")[65536]
    assert first["empty"]["gap"] == 0.2 and "log_diameter" not in first
    assert EC.chain_structure(structure, 1, "honeycomb")[65536]["given"]["gap"] == 0.3
    assert EC.chain_structure(structure, 2, "cubic") == {}


def test_the_gate_reads_every_given_chain_s_structure_where_a_run_has_them():
    rows = [{"n": 64, "seed": s, "metrics": _metrics(64)} for s in range(3)]
    rung = SG.rung_structure(rows)[64]
    assert set(rung) == {"empty", "given", "more_given", "log_diameter"}
    assert rung["more_given"]["honeycomb"]["seeds"] == 3 and rung["more_given"]["honeycomb"]["giant"] == 1.0
    for row in rows:
        del row["metrics"]["census"]["honeycomb"]
    assert "more_given" not in SG.rung_structure(rows)[64], "a run without them reads as it always did"


def test_the_chosen_decision_keeps_the_seed_s_rules_alike_for_every_chain():
    rung = Rung(n=64, mean_degree=3.0, seeds_measured=2)
    decision = EC.decide_every_chain(LAW, {"empty": [rung], "honeycomb": [rung]}, EVERY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "complete_rung", 64)
