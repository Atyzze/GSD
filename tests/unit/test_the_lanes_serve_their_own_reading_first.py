from __future__ import annotations

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import (
    HOLD, LANE_AUDIT, LANE_FAMILY, LANE_MERIT, RUN_NEXT, Policy, Rung, decide, is_audit_traffic)
from tests.unit.test_decider import FakeStore, entry

POLICY = Policy(promising_bar=False, deep_lane_widths=((1048576, 1),))
MERIT = G.unsalted_law("merit-", POLICY.audit_fraction)
TOP = 1048576
BELOW = 262144


def settled_to(top, d_s=2.2):
    return [Rung(n=n, mean_degree=4.0, connected_fraction=1.0, probes={"d_s": (d_s, 0.01)}, seeds_measured=3)
            for n in POLICY.ladder() if n <= top]


def test_a_law_waiting_for_a_lane_records_where_it_stands_in_its_queue():
    full = {TOP: 1, BELOW: 0}
    merit = decide(MERIT, settled_to(BELOW), POLICY, deep_lane_in_flight=full,
                   standing={"law_score": 61.0, "control_family": None})
    assert (merit.action, merit.rule, merit.next_n) == (HOLD, "deep_lane_full", TOP)
    assert merit.facts["lane"] == {"rank": LANE_MERIT, "queue": "bought on its own reading", "audit": False,
                                   "family": None, "law_score": 61.0}
    family = decide(MERIT, settled_to(BELOW), POLICY, deep_lane_in_flight=full,
                    standing={"law_score": 80.0, "control_family": "random_regular_3"})
    assert family.facts["lane"]["rank"] == LANE_FAMILY, "a known answer waits behind every other law (C1)"
    bought = decide(MERIT, settled_to(BELOW), POLICY, deep_lane_in_flight={TOP: 0, BELOW: 0})
    assert (bought.action, bought.next_n) == (RUN_NEXT, TOP) and bought.facts["lane"]["rank"] == LANE_MERIT
    below_the_lanes = decide(MERIT, settled_to(16384), POLICY)
    assert "lane" not in below_the_lanes.facts, "only a lane's rung is queued"


def test_audit_traffic_is_named_by_its_route():
    assert is_audit_traffic("salted", {}) and is_audit_traffic("plateau_follow", {})
    assert is_audit_traffic("d_s_settled", {"salted": ["too_dense"]})
    assert is_audit_traffic("d_s_settled", {"gate": {"salted": True}})
    assert not is_audit_traffic("d_s_settled", {"salted": [], "gate": {"result": "finite dimension"}})
    assert LANE_MERIT < LANE_AUDIT < LANE_FAMILY


class LaneStore(FakeStore):
    def __init__(self, *, in_lane, waiting, entries):
        super().__init__([], entries=entries)
        self.latest = {law: {"action": "run_next", "rule": rule, "next_n": TOP, "at_n": BELOW, "priority": 1,
                             "facts": facts} for law, rule, facts in in_lane}
        for law, rank, score in waiting:
            self.latest[law] = {"action": "hold", "rule": "deep_lane_full", "next_n": TOP, "at_n": BELOW,
                                "priority": None, "facts": {"lane": {"rank": rank, "law_score": score}}}
        self.parked, self.woken = {}, []

    def record_decision(self, campaign_id, row):
        super().record_decision(campaign_id, row)
        self.latest[row["law"]] = {k: row.get(k) for k in ("action", "rule", "next_n", "at_n", "priority", "facts")}

    def laws_in_flight_at(self, campaign_id, n):
        return sum(1 for d in self.latest.values() if d["action"] == "run_next" and d["next_n"] == n)

    def laws_waiting_for_the_lane(self, campaign_id, n, limit, *, merit_only=False):
        rows = [(law, d) for law, d in self.latest.items() if d["action"] == "hold"
                and d["rule"] == "deep_lane_full" and d["next_n"] == n]
        rank = lambda d: (d["facts"].get("lane") or {}).get("rank", 0)  # noqa: E731
        rows = [r for r in rows if not merit_only or rank(r[1]) == LANE_MERIT]
        rows.sort(key=lambda r: (rank(r[1]), -((r[1]["facts"].get("lane") or {}).get("law_score") or 0)))
        return [law for law, _ in rows[:limit]]

    def audit_laws_in_flight_at(self, campaign_id, n):
        return [{"law": law, "at_n": d["at_n"], "priority": d["priority"], "facts": d["facts"]}
                for law, d in self.latest.items() if d["action"] == "run_next" and d["next_n"] == n
                and is_audit_traffic(d["rule"], d["facts"]) and law not in self.parked]

    def park_lane_seeds(self, campaign_id, law, n):
        self.parked[law] = n
        return {"parked": 2, "stopping": 1}

    def parked_rung(self, campaign_id, law):
        return self.parked.get(law)

    def wake_lane_seeds(self, campaign_id, law, n):
        self.woken.append(law)
        self.parked.pop(law, None)
        return 3

    def latest_decision(self, campaign_id, law):
        return self.latest.get(law)


def _cells(top):
    return {n: entry(4.0, d_s=2.2, se=0.01) for n in POLICY.ladder() if n <= top}


def test_an_audit_law_gives_its_lane_to_a_law_bought_on_its_own_reading_and_resumes_after():
    salted = {"salted": ["no_finite_dimension"], "gate": {"salted": True}, "lane": {"rank": LANE_AUDIT}}
    store = LaneStore(in_lane=[("audit-6214", "d_s_settled", salted)], waiting=[(MERIT, LANE_MERIT, 61.0)],
                      entries={MERIT: _cells(BELOW)})
    tally = decide_pass(store, "1", POLICY)
    gave = store.latest["audit-6214"]
    assert (gave["action"], gave["rule"], gave["next_n"]) == ("hold", "deep_lane_full", TOP)
    assert gave["facts"]["yielded"] == {"to": MERIT, "at_n": TOP, "parked": 2, "stopping": 1}
    assert gave["facts"]["lane"]["rank"] == LANE_AUDIT and gave["facts"]["salted"] == ["no_finite_dimension"]
    assert store.parked == {"audit-6214": TOP} and store.states["audit-6214"][0] == "HELD"
    took = store.latest[MERIT]
    assert (took["action"], took["rule"], took["next_n"]) == ("run_next", "d_s_settled", TOP)
    assert tally[("hold", "lane_yielded")] == 1
    decide_pass(store, "1", POLICY)
    assert store.latest["audit-6214"]["action"] == "hold" and store.woken == []
    store.latest[MERIT] = {"action": "done", "rule": "ladder_complete", "next_n": None, "at_n": TOP, "priority": None,
                           "facts": {}}
    tally = decide_pass(store, "1", POLICY)
    back = store.latest["audit-6214"]
    assert (back["action"], back["rule"], back["next_n"]) == ("run_next", "lane_resumed", TOP)
    assert back["facts"]["resumed"] == {"at_n": TOP, "seeds": 3} and back["facts"]["lane"]["rank"] == LANE_AUDIT
    assert store.woken == ["audit-6214"] and store.states["audit-6214"][0] == "EXTENDING"
    assert tally[("run_next", "lane_resumed")] == 1
    assert not [j for j in store.jobs if j[0] == "audit-6214"], "its seeds exist; nothing is enqueued again"


def test_nobody_gives_a_lane_to_audit_traffic_or_to_a_known_answer():
    merit_in_lane = {"lane": {"rank": LANE_MERIT}}
    store = LaneStore(in_lane=[("merit-in", "d_s_settled", merit_in_lane)],
                      waiting=[("salted-w", LANE_AUDIT, 90.0), ("family-w", LANE_FAMILY, 95.0)], entries={})
    decide_pass(store, "1", POLICY)
    assert store.parked == {} and store.latest["merit-in"]["action"] == "run_next"
    audit_in_lane = {"salted": ["too_dense"], "lane": {"rank": LANE_AUDIT}}
    store = LaneStore(in_lane=[("audit-in", "d_s_settled", audit_in_lane)],
                      waiting=[("family-w", LANE_FAMILY, 95.0)], entries={})
    decide_pass(store, "1", POLICY)
    assert store.parked == {}, "C1 orders the families last; only a law bought on its own reading takes a lane"
