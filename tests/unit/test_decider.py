from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions.decider import QUEUE_ORDER, decide_pass
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.engine import Policy

POLICY = Policy()
LAW = G.unsalted_law("law-", POLICY.audit_fraction)


def entry(md, cf=1.0, d_s=None, se=0.05):
    return {"mean_degree": md, "connected_fraction": cf, "measurement_seed_count": 3, "d_s": d_s,
            "d_s_bucket": None, "probes": {"d_s": {"se": se}}}


class FakeStore:
    def __init__(self, laws, entries=None, seeds=None, depth=0, held=()):
        self.laws, self.entries, self.seeds = list(laws), entries or {}, seeds or {}
        self.depth, self.held = depth, list(held)
        self.jobs, self.states, self.decisions = [], {}, []

    def laws_awaiting_decision(self, campaign_id):
        return self.laws

    def law_evidence(self, campaign_id, law):
        return {"entries": self.entries.get(law, {}), "phenotype": ({"per_n": self.entries[law]} if law in self.entries else None)}

    def record_phenotype(self, campaign_id, law, phenotype):
        self.phenotypes = getattr(self, "phenotypes", {}) | {law: phenotype}

    def seed_rows(self, campaign_id, law):
        return self.seeds.get(law, {})

    def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, **_scale):
        self.jobs.append((law, n, seeds, work_budget, queue_order))
        return seeds

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        self.states[law] = (state, rule, next_n)
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return self.depth

    def held_laws(self, campaign_id):
        return self.held


def test_a_new_law_starts_at_the_first_rung_with_three_seeds_and_its_budget():
    store = FakeStore([LAW])
    tally = decide_pass(store, "1")
    assert store.jobs == [(LAW, 64, 3, POLICY.work_budget(64), QUEUE_ORDER["base"])]
    assert tally[("run_next", "start")] == 1
    recorded = store.decisions[0]
    assert (recorded["rule"], recorded["jobs_created"], recorded["rows_changed"]) == ("start", 3, 1)


def test_a_stop_changes_the_law_and_creates_no_work():
    store = FakeStore([LAW], entries={LAW: {64: entry(17.0), 256: entry(17.0)}})
    decide_pass(store, "1")
    assert store.jobs == [] and store.states[LAW][0:2] == ("STOPPED", "too_dense")
    assert store.decisions[0]["jobs_created"] == 0


def test_a_seed_that_reached_its_budget_is_read_and_marked_and_the_law_goes_on():
    budget = POLICY.work_budget(64)
    seeds = {LAW: {64: [{"work_units": 1, "work_budget": budget, "ended": None},
                        {"work_units": budget, "work_budget": budget, "ended": "budget"},
                        {"work_units": 2, "work_budget": budget, "ended": None}]}}
    store = FakeStore([LAW], entries={LAW: {64: entry(2.5)}}, seeds=seeds)
    decide_pass(store, "1")
    assert store.states[LAW][0:2] == ("BASE_BLOCK_RUNNING", "base_block") and store.jobs[0][1] == 256
    assert store.decisions[0]["facts"]["budget_ended"] == {"seeds": [1], "of": 3, "at_n": 64}


def test_a_law_whose_first_chunk_would_not_fit_the_next_size_is_parked_and_starts_nothing():
    budget = POLICY.work_budget(256)
    dear = {"first_chunk_units": 2 * budget, "first_chunk_moves": 100, "first_multiplier": 4, "work_budget": budget}
    cheap = dict(dear, first_chunk_units=budget // 1000)
    for seeds, parked in ((dear, True), (cheap, False)):
        store = FakeStore([LAW], entries={LAW: {64: entry(2.5)}}, seeds={LAW: {64: [dict(seeds)] * 3}})
        decide_pass(store, "1")
        decision = store.decisions[0]
        assert decision["facts"]["first_chunk"]["fits"] is (not parked)
        if parked:
            assert (decision["action"], decision["rule"], store.jobs) == ("stop", "over_budget", [])
            assert store.states[LAW][0] == "PARKED"
        else:
            assert decision["rule"] == "base_block" and store.jobs[0][1] == 256


def test_a_settled_law_is_bought_at_its_priority():
    rungs = {64: entry(2.5), 256: entry(2.5), 1024: entry(2.50, d_s=1.50), 4096: entry(2.51, d_s=1.52)}
    store = FakeStore([LAW], entries={LAW: rungs})
    decide_pass(store, "1")
    assert store.jobs == [(LAW, 16384, 3, int(POLICY.work_budget(16384) * POLICY.merit_budget_scale), QUEUE_ORDER[1])]


def test_held_laws_are_released_only_when_nothing_waits():
    held = [{"law": "held-b", "next_n": 16384, "at_n": 4096, "priority": None, "since": "2026-09-16T01:00:00Z"},
            {"law": "held-a", "next_n": 16384, "at_n": 4096, "priority": None, "since": "2026-09-16T00:00:00Z"}]
    busy = FakeStore([], depth=5, held=held)
    decide_pass(busy, "1")
    assert busy.jobs == []
    idle = FakeStore([], depth=0, held=held)
    tally = decide_pass(idle, "1")
    assert [j[0] for j in idle.jobs] == ["held-a", "held-b"]
    assert tally[("run_next", "hold_released")] == 2
    assert all(d["released_hold"] and d["queue_order"] == QUEUE_ORDER["held"] for d in idle.decisions)


def test_every_decision_is_recorded_with_what_it_changed():
    store = FakeStore([LAW, "law-new"], entries={LAW: {64: entry(17.0), 256: entry(17.0)}})
    decide_pass(store, "1")
    assert len(store.decisions) == 2
    assert all({"jobs_created", "rows_changed", "rule", "facts", "engine"} <= set(d) for d in store.decisions)


def test_the_phenotype_the_decision_read_is_written_back():
    store = FakeStore([LAW], entries={LAW: {64: entry(2.5)}})
    decide_pass(store, "1")
    assert store.phenotypes[LAW] == {"per_n": {64: entry(2.5)}}


def test_one_law_that_fails_does_not_stop_the_others():
    class Broken(FakeStore):
        def law_evidence(self, campaign_id, law):
            if law == "broken":
                raise KeyError(256)
            return super().law_evidence(campaign_id, law)

        def record_failure(self, campaign_id, law, error):
            self.failures = getattr(self, "failures", []) + [(law, error)]

    store = Broken(["broken", LAW])
    tally = decide_pass(store, "1")
    assert [law for law, _ in store.failures] == ["broken"]
    assert store.failures[0][1].startswith("KeyError: 256 at decisions/decider.py:")
    assert tally[("failed", "KeyError")] == 1 and tally[("run_next", "start")] == 1
    assert [j[0] for j in store.jobs] == [LAW]


def test_a_failure_names_the_line_it_failed_at():
    from graph_scale_dynamics.decisions.decider import failure_text
    from graph_scale_dynamics.decisions.known_result import chain_word
    try:
        chain_word(None, None)
    except AttributeError as error:
        said = failure_text(error)
    assert said.startswith("AttributeError: ") and " at decisions/known_result.py:" in said and said.endswith(
        " in chain_word")
    assert failure_text(ValueError("x")) == "ValueError: x"


def test_a_hold_released_into_an_idle_queue_never_buys_a_deep_rung():
    held = [{"law": "cheap", "at_n": 4096, "next_n": 16384, "priority": None, "since": "1"},
            {"law": "deep", "at_n": 65536, "next_n": 262144, "priority": None, "since": "0"},
            {"law": "last", "at_n": 262144, "next_n": 1048576, "priority": None, "since": "0"}]
    store = FakeStore([], depth=0, held=held)
    decide_pass(store, "1")
    assert [job[:2] for job in store.jobs] == [("cheap", 16384)]


class LaneStore(FakeStore):
    def __init__(self, *args, in_flight=0, waiting=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.in_flight, self.waiting, self.asked = in_flight, list(waiting), []

    def laws_in_flight_at(self, campaign_id, n):
        return self.in_flight

    def laws_waiting_for_the_lane(self, campaign_id, n, limit):
        self.asked.append(limit)
        return self.waiting[:limit]

    def law_evidence(self, campaign_id, law):
        return dict(super().law_evidence(campaign_id, law), standing={"law_score": 42.0})


def _deep_entries():
    rows = {64: entry(2.5), 256: entry(2.5), 1024: entry(2.5, d_s=1.5), 4096: entry(2.5, d_s=1.50),
            16384: entry(2.51, d_s=1.52), 65536: entry(2.52, d_s=1.53), 262144: entry(2.52, d_s=1.54)}
    return {n: dict(cell, measurement_seed_count=3) for n, cell in rows.items()}


def test_waiting_laws_take_the_lane_as_it_opens_and_the_pass_counts_what_it_buys():
    laws = [f"law-{i}" for i in range(3000)
            if not any(G.salted(f"law-{i}", gate, POLICY.audit_fraction) for gate in G.SALTED_GATES)][:3]
    entries = {law: _deep_entries() for law in laws}
    store = LaneStore(laws[2:], entries=entries, in_flight=2, waiting=laws[:2])
    tally = decide_pass(store, "1", replace(POLICY, promising_bar=False))
    assert store.asked == [2], "room is the lane less what is in flight"
    bought = [job[0] for job in store.jobs if job[1] == 1048576]
    assert bought == laws[:2], bought
    assert tally[("hold", "deep_lane_full")] == 1, "the lane was full by the time the new law was decided"
