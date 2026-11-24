from __future__ import annotations

import json
from dataclasses import replace

from graph_scale_dynamics.decisions import starts_rule as FS
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import (
    DONE, GATED_RULES, HOLD, PARKING_RULES, RULES_REVISION, RUN_NEXT, STOP, Decision, Policy, Rung, rules_revision,
    policy_fingerprint)
from graph_scale_dynamics.decisions.replay import replay_matches

EVERY = Policy(every_chain=True)
LAW = G.unsalted_law("law-", EVERY.audit_fraction)
NAMES = ["empty", "random", "honeycomb", "cubic", "tesseract"]
RUNGS = [Rung(n=n, mean_degree=3.0, seeds_measured=3) for n in (64, 256, 1024, 4096)]


def salted_law(gate: str, n: int = 4096) -> str:
    i = 0
    while not G.salted(f"law-{i}", gate, EVERY.salt_share(gate, n)):
        i += 1
    return f"law-{i}"


def reading(classes: dict, *, fates=None, references=True) -> dict:
    sizes = sorted(classes)
    read = [n for n in sizes if classes[n] != "not_read"]
    at = read[-1] if read else None
    return {"class": classes[at] if at else "not_read", "at_n": at, "top_n": sizes[-1],
            "top_dense": bool(at and at != sizes[-1]),
            "by_n": {str(n): [classes[n], [NAMES]] for n in sizes}, "fates": fates or {}, "references": references}


def chosen(rule="d_s_settled", action=RUN_NEXT, at_n=4096, next_n=16384, priority=1, facts=None, law=LAW):
    return Decision(law=law, action=action, rule=rule, reason=f"d_s: {rule}", at_n=at_n, next_n=next_n,
                    priority=priority,
                    facts=facts if facts is not None else {"mean_degree": 3.0, "chains": {
                        "empty": {"action": action, "rule": rule, "next_n": next_n}}})


def decide(reading_, chosen_=None, law=LAW, policy=EVERY, **context):
    return FS.decide(law, chosen_ or chosen(law=law), reading_, policy, RUNGS, **context)


CUBIC_HOLDS = {"honeycomb": ["melted", 0.1], "cubic": ["holds", 0.95], "tesseract": ["melted", 0.0]}


def test_a_shape_buys_the_next_size_whatever_d_s_did():
    for d_s in (chosen(), chosen("unsettled_twice", STOP, next_n=None, priority=None)):
        decision = decide(reading({1024: "selects", 4096: "selects"}, fates=CUBIC_HOLDS), d_s)
        assert (decision.action, decision.rule, decision.next_n, decision.priority) == (RUN_NEXT, FS.SHAPE, 16384, 1)
        assert "cubic holding" in decision.reason
        assert decision.facts["d_s"]["rule"] == d_s.rule, "what d_s's rule would have decided is recorded"
        seen = decision.facts["starts_reading"]
        assert seen["decided"] and seen["class"] == "selects" and seen["at_n"] == 4096
        assert decision.facts["chains"] == d_s.facts["chains"], "every chain's own decision is kept"
    assert FS.SHAPE in GATED_RULES and FS.APART in GATED_RULES, "a size they buy meets the structure gate"


def test_every_start_alike_parks_the_law_even_where_d_s_settled():
    decision = decide(reading({1024: "forgets", 4096: "forgets"}))
    assert (decision.action, decision.rule, decision.next_n) == (STOP, FS.ALIKE, None)
    assert decision.rule in PARKING_RULES, "a park, with everything it measured kept"
    assert "(d_s's rule: d_s_settled)" in decision.reason and decision.facts["d_s"]["action"] == RUN_NEXT


def test_starts_apart_buy_one_look_and_park_the_second_time():
    once = decide(reading({1024: "remembers", 4096: "remembers"}))
    assert (once.action, once.rule, once.next_n, once.priority) == (RUN_NEXT, FS.APART, 16384, 2)
    at_16384 = chosen(at_n=16384, next_n=65536)
    twice = decide(reading({1024: "remembers", 4096: "remembers", 16384: "remembers"}), at_16384)
    assert (twice.action, twice.rule) == (STOP, FS.APART_TWICE) and twice.rule in PARKING_RULES
    alike_after = decide(reading({1024: "remembers", 4096: "remembers", 16384: "forgets"}), at_16384)
    assert alike_after.rule == FS.ALIKE
    shaped_between = decide(reading({4096: "remembers", 16384: "selects", 65536: "remembers"}, fates=CUBIC_HOLDS),
                            chosen(at_n=65536, next_n=262144))
    assert (shaped_between.rule, shaped_between.next_n) == (FS.APART, 262144), (
        "a shape between two looks starts the count again")


def test_the_looks_are_counted_from_the_last_base_rung():
    assert FS._park_at(reading({1024: "remembers", 4096: "remembers"}), EVERY, 4096) is None
    assert FS._park_at(reading({4096: "remembers", 16384: "remembers"}), EVERY, 16384) == FS.APART_TWICE
    assert FS._park_at(reading({4096: "remembers", 16384: "not_read", 65536: "remembers"}), EVERY, 65536) == (
        FS.APART_TWICE), "a size no two chains read is not a look"


def test_a_park_lets_its_share_through_for_one_size():
    whole = replace(EVERY, deep_salt_at_most=EVERY.audit_fraction)
    law = salted_law(FS.ALIKE)
    let = decide(reading({1024: "forgets", 4096: "forgets"}), chosen(law=law), law=law)
    assert (let.action, let.rule, let.next_n) == (RUN_NEXT, "salted", 16384)
    assert let.facts["salted"] == [FS.ALIKE] and let.facts["salted_from"]["rule"] == FS.ALIKE
    spent = decide(reading({1024: "forgets", 4096: "forgets", 16384: "forgets"}),
                   chosen(at_n=16384, next_n=65536, law=law), law=law, policy=whole)
    assert (spent.action, spent.rule) == (STOP, FS.ALIKE)
    assert spent.facts["salt_spent"] == {"gate": FS.ALIKE, "salted_at": 4096, "held_at": 16384}
    changed = decide(reading({4096: "forgets", 16384: "selects"}, fates=CUBIC_HOLDS),
                     chosen(at_n=16384, next_n=65536, law=law), law=law, policy=whole)
    assert changed.rule == FS.SHAPE, "one whose reading changed there goes on as any law would"
    assert G.BY_NAME[FS.ALIKE].salted and G.BY_NAME[FS.APART_TWICE].salted
    assert EVERY.salt_share(FS.ALIKE, 4096) == EVERY.audit_fraction == 0.1


def test_without_a_reading_the_law_is_decided_as_before_and_says_why():
    d_s = chosen()
    for given, why in ((None, "no reading of the starts"),
                       (reading({1024: "not_read", 4096: "not_read"}), "no size from 1,024 read by two chains or more"),
                       (reading({4096: "forgets"}, references=False), "the lattices' references are not this tree's")):
        decision = decide(given, d_s)
        assert (decision.action, decision.rule, decision.next_n) == (d_s.action, d_s.rule, d_s.next_n)
        assert decision.facts["starts_reading"] == {"decided": False, "why": why}


def test_only_d_s_s_rules_of_depth_are_the_starts_to_decide():
    alike = reading({1024: "forgets", 4096: "forgets"})
    for rule, action in (("failed", STOP), ("complete_rung", RUN_NEXT), ("empty", STOP),
                         ("disconnected", STOP), ("too_dense", STOP),
                         ("ladder_complete", DONE), ("gate_audit", RUN_NEXT), ("no_finite_dimension", STOP)):
        kept = chosen(rule, action, next_n=4096 if action == RUN_NEXT else None)
        assert decide(alike, kept) is kept, rule
    longer = decide(alike, chosen("longer_chain", RUN_NEXT, next_n=4096))
    assert longer.rule == FS.ALIKE, "a longer chain for a law the starts park is not run (629, improvement 3)"
    past_a_park = chosen("salted", facts={"salted": ["no_reading"], "salted_from": {"rule": "no_reading"}})
    decided = decide(alike, past_a_park)
    assert decided.rule == FS.ALIKE and "salted" not in decided.facts, "a let-through past d_s's park is d_s's"
    below = chosen(at_n=1024, next_n=4096)
    assert decide(alike, below) is below, "below the last base rung the base block runs"
    assert FS.decide(LAW, chosen(), alike, Policy(), RUNGS).rule == "d_s_settled", "a campaign of one chain"
    assert FS.D_S_DEPTH >= {"d_s_settled", "second_rung", "no_reading", "unsettled_twice", "reading_lost",
                            "no_second_rung", "no_plateau", "deep_lane_full"}


def test_a_law_a_final_verdict_let_through_keeps_its_mark_and_d_s_s_readings_are_kept():
    from graph_scale_dynamics.decisions.engine import is_audit_traffic
    let = chosen(facts={"salted": ["too_dense"], "d_s_settled": True, "d_s_step": 0.01, "mean_degree": 16.5,
                        "chains": {"empty": {"action": RUN_NEXT, "rule": "d_s_settled", "next_n": 16384}}})
    shaped = decide(reading({1024: "selects", 4096: "selects"}, fates=CUBIC_HOLDS), let)
    assert shaped.rule == FS.SHAPE and shaped.facts["salted"] == ["too_dense"]
    assert is_audit_traffic(shaped.rule, shaped.facts), "a verdict's let-through, wherever it waits"
    assert shaped.facts["d_s_settled"] is True and shaped.facts["d_s_step"] == 0.01
    parked = decide(reading({1024: "forgets", 4096: "forgets"}), let)
    assert (parked.rule, parked.facts["salted"]) == (FS.ALIKE, ["too_dense"])
    assert not set(FS.REPLACED_FACTS) & set(parked.facts) - {"starts_reading", "d_s"}


def test_a_class_the_rule_does_not_read_is_decided_as_before():
    d_s = chosen()
    odd = dict(reading({4096: "forgets"}), **{"class": "something_else"})
    decision = decide(odd, d_s)
    assert (decision.action, decision.rule) == (d_s.action, d_s.rule)
    assert decision.facts["starts_reading"] == {"decided": False, "why": "a class the rule does not read: something_else"}


def test_the_structure_gate_reads_each_chain_alone_on_what_the_starts_buy():
    import math
    from graph_scale_dynamics.decisions.engine import GATE_RULES
    policy = Policy(every_chain=True, plateau_follow_in_flight=0)

    def two_d(n):
        return {"gap": 4.0 / n, "diameter": n ** 0.5}

    def expander(n):
        return {"gap": 0.2, "diameter": 3.0 * math.log(n)}

    def law_rungs(geometry):
        out = []
        for n in [n for n in policy.ladder() if n <= 65536]:
            one = {"seeds": 3, "giant": 1.0, "gap_reason": None} | geometry(n)
            structure = {"empty": one, "given": one,
                         "log_diameter": {"raised": 0, "false": 3, "unknown": 0, "not_measured": 0}}
            out.append(Rung(n=n, mean_degree=2.5, connected_fraction=1.0, probes={"d_s": (1.5, 0.01)},
                            seeds_measured=3, structure=structure))
        return out

    shaped = reading({16384: "selects", 65536: "selects"}, fates=CUBIC_HOLDS)
    at_65536 = chosen(at_n=65536, next_n=262144)
    passed = FS.decide(LAW, at_65536, shaped, policy, {"empty": law_rungs(expander), "cubic": law_rungs(two_d)})
    assert (passed.action, passed.rule, passed.next_n) == (RUN_NEXT, FS.SHAPE, 262144)
    from graph_scale_dynamics.decisions import structure_gate as SG
    assert passed.facts["gate"]["chain"] == "cubic" and passed.facts["gate"]["result"] == SG.FINITE
    refused = FS.decide(LAW, at_65536, shaped, policy, {"empty": law_rungs(expander), "cubic": law_rungs(expander)})
    assert refused.action == STOP and refused.rule in GATE_RULES and refused.facts["gate"]["chain"] == "cubic"
    from_empty_only = FS.decide(LAW, at_65536, shaped, policy, law_rungs(expander))
    assert from_empty_only.action == STOP and "chain" not in from_empty_only.facts["gate"], "one chain: nothing to name"


def test_a_shape_from_the_plateau_rung_waits_for_room_in_its_lane():
    deep = Policy(every_chain=True, deep_lane_widths=((262144, 2), (1048576, 4)))
    width = deep.deep_lane_width(262144)
    assert width == 2 and 262144 in deep.lane_rungs()
    shaped = reading({16384: "selects", 65536: "selects"}, fates=CUBIC_HOLDS)
    full = FS.decide(LAW, chosen(at_n=65536, next_n=262144), shaped, deep, RUNGS, deep_lane_in_flight={262144: width})
    assert (full.action, full.rule, full.next_n) == (HOLD, "deep_lane_full", 262144)
    assert full.facts["starts_bought"] == FS.SHAPE
    room = FS.decide(LAW, chosen(at_n=65536, next_n=262144), shaped, deep, RUNGS,
                     deep_lane_in_flight={262144: width - 1})
    assert (room.action, room.rule) == (RUN_NEXT, FS.SHAPE) and room.facts["lane"]["rank"] is not None
    below_plateau = decide(reading({1024: "selects", 4096: "selects"}, fates=CUBIC_HOLDS),
                           deep_lane_in_flight={16384: 99})
    assert below_plateau.rule == FS.SHAPE, "below the plateau rung no lane holds a law, as for d_s (rule 6)"


def entry(md, d_s=None):
    return {"mean_degree": md, "connected_fraction": 1.0, "measurement_seed_count": 3, "d_s": d_s,
            "d_s_bucket": None, "probes": {"d_s": {"se": 0.05}}}


EMPTY = {64: entry(0.0), 256: entry(0.0), 1024: entry(0.0), 4096: entry(0.0)}
SETTLED = {64: entry(3.0), 256: entry(3.0), 1024: entry(3.0, d_s=1.98), 4096: entry(3.0, d_s=2.01)}


class Store:
    def __init__(self, entries, chains, starts_reading, *, parked=(), fingerprint=None):
        self.entries, self.chains, self.starts_reading = entries, chains, starts_reading
        self.parked, self.fingerprint = list(parked), fingerprint
        self.jobs, self.states, self.decisions = [], {}, []

    def laws_awaiting_decision(self, campaign_id):
        return [] if self.parked else [LAW]

    def law_evidence(self, campaign_id, law):
        return {"entries": self.entries, "phenotype": None, "chains": self.chains, "starts_reading": self.starts_reading}

    def record_phenotype(self, campaign_id, law, phenotype):
        pass

    def seed_rows(self, campaign_id, law):
        return {}

    def enqueue_seeds(self, campaign_id, law, n, *, seeds, work_budget, queue_order, **_scale):
        self.jobs.append((law, n))
        return seeds

    def set_law_state(self, campaign_id, law, state, *, rule, next_n, parked_ok=False):
        self.states[law] = (state, rule, next_n)
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return 1

    def held_laws(self, campaign_id, limit=None):
        return []

    def parked_laws(self, campaign_id, limit=None):
        return list(self.parked)

    def decision_rules_fingerprint(self, campaign_id):
        return self.fingerprint

    def record_decision_rules_fingerprint(self, campaign_id, fingerprint):
        self.fingerprint = fingerprint


def test_a_d_s_that_settled_on_a_given_chain_no_longer_buys_a_law_whose_starts_end_alike():
    store = Store(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, reading({1024: "forgets", 4096: "forgets"}))
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert (decision["action"], decision["rule"]) == (STOP, FS.ALIKE) and store.jobs == []
    assert decision["facts"]["d_s"]["rule"] == "d_s_settled" and "earned_by" not in decision["facts"]
    assert decision["inputs"]["starts_reading"]["class"] == "forgets", "the decision records what it read"
    assert replay_matches(json.loads(json.dumps(decision, default=str)))["matches"], "and replays from it"


def test_a_shape_a_lattice_holds_is_earned_by_it_where_the_chain_from_empty_would_stop():
    store = Store(EMPTY, {"random": EMPTY, "cubic": SETTLED},
                  reading({1024: "selects", 4096: "selects"}, fates=CUBIC_HOLDS))
    decide_pass(store, "1", EVERY)
    decision = store.decisions[0]
    assert (decision["action"], decision["rule"], decision["next_n"]) == (RUN_NEXT, FS.SHAPE, 16384)
    assert decision["facts"]["earned_by"] == "cubic" and store.jobs == [(LAW, 16384)]
    assert decision["facts"]["chains"]["empty"]["rule"] == "empty"
    assert replay_matches(json.loads(json.dumps(decision, default=str)))["matches"]


def test_a_decision_replays_from_the_starts_it_recorded_and_one_made_without_them():
    store = Store(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, reading({1024: "forgets", 4096: "forgets"}))
    decide_pass(store, "1", EVERY)
    row = json.loads(json.dumps(store.decisions[0], default=str))
    assert replay_matches(row)["matches"] is True
    row["inputs"].pop("starts_reading")
    assert replay_matches(row)["matches"] is False, "without them d_s's rule decides, and it settled"
    before = Store(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, None)
    decide_pass(before, "1", EVERY)
    made_before = json.loads(json.dumps(before.decisions[0], default=str))
    assert made_before["rule"] == "d_s_settled" and "starts_reading" not in made_before["inputs"]
    assert replay_matches(made_before)["matches"] is True, "a decision with no starts' reading read none"


def test_when_the_rules_change_every_law_a_rule_parked_is_decided_once_more():
    store = Store(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, reading({1024: "remembers", 4096: "remembers"}),
                  parked=[LAW], fingerprint="before")
    decide_pass(store, "1", EVERY)
    assert [(d["law"], d["rule"]) for d in store.decisions] == [(LAW, FS.APART)]
    assert store.fingerprint == policy_fingerprint(EVERY) and rules_revision(EVERY) == RULES_REVISION == 782
    again = Store(EMPTY, {"random": EMPTY}, reading({4096: "remembers"}), parked=[LAW],
                  fingerprint=policy_fingerprint(EVERY))
    decide_pass(again, "1", EVERY)
    assert again.decisions == [], "once: a fingerprint already seen decides nothing again"
    one_chain = Store(EMPTY, {"random": EMPTY}, None, parked=[LAW], fingerprint="before")
    decide_pass(one_chain, "1", Policy())
    assert one_chain.decisions == [], "a campaign decided by its chain from empty keeps its parks"


def test_new_rules_are_recorded_as_seen_only_once_every_law_they_name_was_decided_again():
    class Pending(Store):
        def law_evidence(self, campaign_id, law):
            return {"pending": True, "pending_reasons": ["rung_writing"]} if self.writing else super().law_evidence(
                campaign_id, law)

    store = Pending(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, reading({1024: "remembers", 4096: "remembers"}),
                    parked=[LAW], fingerprint="before")
    store.writing = True
    decide_pass(store, "1", EVERY)
    assert store.decisions == [] and store.fingerprint == "before", "not yet decided, so not yet seen"
    store.writing = False
    decide_pass(store, "1", EVERY)
    assert [(d["law"], d["rule"]) for d in store.decisions] == [(LAW, FS.APART)]
    assert store.fingerprint == policy_fingerprint(EVERY)


def test_a_law_left_pending_under_new_rules_does_not_make_every_pass_decide_every_parked_law_again():
    stuck = "law-stuck"

    class Remembering(Store):
        left = None

        def law_evidence(self, campaign_id, law):
            return {"pending": True, "pending_reasons": ["rung_writing"]} if law == stuck else super().law_evidence(
                campaign_id, law)

        def rules_redo_left(self, campaign_id, fingerprint):
            return None if self.left is None or self.left[0] != fingerprint else set(self.left[1])

        def record_rules_redo_left(self, campaign_id, fingerprint, laws):
            self.left = (fingerprint, list(laws))

    store = Remembering(EMPTY, {"random": EMPTY, "honeycomb": SETTLED},
                        reading({1024: "remembers", 4096: "remembers"}), parked=[LAW, stuck], fingerprint="before")
    decide_pass(store, "1", EVERY)
    assert [d["law"] for d in store.decisions] == [LAW] and store.fingerprint == "before"
    assert store.left == (policy_fingerprint(EVERY), [stuck]), "the pass says which law is still to decide"
    for _ in range(3):
        decide_pass(store, "1", EVERY)
    assert [d["law"] for d in store.decisions] == [LAW], "decided once, not once a pass"
    store.law_evidence = lambda campaign_id, law: Store.law_evidence(store, campaign_id, law)
    decide_pass(store, "1", EVERY)
    assert [d["law"] for d in store.decisions] == [LAW, stuck] and store.fingerprint == policy_fingerprint(EVERY)


def test_a_pass_deciding_laws_again_records_those_left_as_it_goes(monkeypatch):
    from graph_scale_dynamics.decisions import decider
    monkeypatch.setattr(decider, "REDO_KEPT_EVERY", 2)
    laws = [f"law-{i}" for i in range(5)]
    kept = []

    class Counting(Store):
        def rules_redo_left(self, campaign_id, fingerprint):
            return None

        def record_rules_redo_left(self, campaign_id, fingerprint, left):
            kept.append(list(left))

        def record_decision(self, campaign_id, row):
            super().record_decision(campaign_id, row)
            if len(self.decisions) == 3:
                raise KeyboardInterrupt

    store = Counting(EMPTY, {"random": EMPTY, "honeycomb": SETTLED}, reading({1024: "remembers", 4096: "remembers"}),
                     parked=laws, fingerprint="before")
    try:
        decide_pass(store, "1", EVERY)
    except KeyboardInterrupt:
        pass
    assert kept == [laws[2:]], "after two laws the three left were recorded"
    assert store.fingerprint == "before"
