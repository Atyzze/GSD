from __future__ import annotations

from graph_scale_dynamics.decisions import starts_rule as FS
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT, STOP, Decision, Policy, Rung
from graph_scale_dynamics.reporting import every_chain_report as ECR
from graph_scale_dynamics.reporting import starts_decided as FD

EVERY = Policy(every_chain=True)
NAMES = ["empty", "random", "honeycomb", "cubic", "tesseract"]
RUNGS = [Rung(n=n, mean_degree=3.0, seeds_measured=3) for n in (64, 256, 1024, 4096)]
CUBIC_HOLDS = {"honeycomb": ["melted", 0.1], "cubic": ["holds", 0.95], "tesseract": ["melted", 0.0]}


def _law(prefix: str, *, salted: bool) -> str:
    i = 0
    while G.salted(f"{prefix}{i}", FS.ALIKE, EVERY.salt_share(FS.ALIKE, 4096)) != salted:
        i += 1
    return f"{prefix}{i}"


def reading(classes: dict, fates=None) -> dict:
    sizes = sorted(classes)
    return {"class": classes[sizes[-1]], "at_n": sizes[-1], "top_n": sizes[-1], "top_dense": False,
            "by_n": {str(n): [classes[n], [NAMES]] for n in sizes}, "fates": fates or {}, "references": True}


def chosen(law, rule="d_s_settled", action=RUN_NEXT, at_n=4096, next_n=16384) -> Decision:
    return Decision(law=law, action=action, rule=rule, reason=f"d_s: {rule}", at_n=at_n, next_n=next_n,
                    priority=1 if action == RUN_NEXT else None,
                    facts={"chains": {"empty": {"action": action, "rule": rule, "next_n": next_n}}})


class Record:
    def __init__(self):
        self.laws: dict = {}
        self.tick = 0

    def add(self, decision: Decision) -> Decision:
        self.tick += 1
        self.laws.setdefault(decision.law, []).append({
            "decision_id": f"{self.tick:020d}-00000000", "created_utc": f"2026-10-08T13:{self.tick:02d}:00Z",
            "at_n": decision.at_n, "next_n": decision.next_n, "action": decision.action, "rule": decision.rule,
            "reason": decision.reason, "facts": decision.facts})
        return decision

    def starts_reading(self, classes: dict, d_s: Decision, fates=None) -> Decision:
        return self.add(FS.decide(d_s.law, d_s, reading(classes, fates), EVERY, RUNGS))


def campaign():
    a, b, c, g = (_law(name, salted=False) for name in ("a-", "b-", "c-", "g-"))
    d, e, f, i = (_law(name, salted=True) for name in ("d-", "e-", "f-", "i-"))
    record = Record()
    for law in (a, d, g):
        record.add(chosen(law, "no_reading", STOP, next_n=None))
    record.add(chosen(c, "deep_lane_full", HOLD))
    record.add(chosen(b))
    record.add(chosen(e, "base_block", at_n=1024, next_n=4096))
    forgets = {1024: "forgets", 4096: "forgets"}
    record.starts_reading({1024: "remembers", 4096: "remembers"}, chosen(a, "no_reading", STOP, next_n=None))
    record.starts_reading(forgets, chosen(c, "deep_lane_full", HOLD))
    record.starts_reading(forgets, chosen(d, "no_reading", STOP, next_n=None))
    record.add(FS.decide(g, chosen(g, "no_reading", STOP, next_n=None), None, EVERY, RUNGS))
    record.starts_reading({**forgets, 16384: "forgets"}, chosen(b, at_n=16384, next_n=65536))
    record.starts_reading(forgets, chosen(e))
    record.starts_reading(forgets, chosen(f))
    let = FS.decide(i, chosen(i), reading(forgets), EVERY, RUNGS)
    record.add(Decision(law=i, action=STOP, rule="no_finite_dimension", reason="structure gate at N=4,096: refused",
                        at_n=4096, next_n=None, facts=let.facts))
    record.starts_reading({**forgets, 16384: "selects"}, chosen(d, at_n=16384, next_n=65536), CUBIC_HOLDS)
    record.starts_reading({**forgets, 16384: "forgets"}, chosen(e, at_n=16384, next_n=65536))
    return record.laws, dict(a=a, b=b, c=c, d=d, e=e, f=f, g=g, i=i)


def test_every_decision_the_starts_took_is_set_against_what_d_s_would_have_decided():
    record, law = campaign()
    out = FD.decided(record)
    assert out["contract"] == FD.CONTRACT and out["from"] == "the decisions' facts"
    assert (out["decisions"], out["laws"]) == (9, 7)
    assert out["not_taken"] == {"no reading of the starts": 1}, "where they had the word and did not take it"
    assert out["parked_where_d_s_climbed"] == sorted([law["b"], law["c"], law["e"]]), (
        "B and E parked where d_s settled, C where d_s waited for its lane")
    assert out["climbed_where_d_s_parked"] == [law["a"]]
    pairs = {(row["starts_reading"], row["d_s"]): row["decisions"] for row in out["against_d_s"]}
    assert pairs == {("climbs", "parks"): 1, ("climbs", "climbs"): 1, ("let_through", "parks"): 1,
                     ("let_through", "climbs"): 2, ("parks", "climbs"): 3, ("stops", "climbs"): 1}
    rules = {(row["rule"], row["d_s"]): row["decisions"] for row in out["by_rules"]}
    assert rules[(FS.ALIKE, "deep_lane_full")] == 1 and rules[("salted", "d_s_settled")] == 2
    assert out["first_utc"] == "2026-10-08T13:07:00Z" and out["last_utc"] == "2026-10-08T13:16:00Z"


def test_the_laws_decided_again_at_the_switch_are_counted_from_what_they_were_to_what_they_are():
    record, law = campaign()
    switch = FD.decided(record)["at_the_switch"]
    assert switch["laws"] == 4, "A, C, D and G; B and E met the starts at a new size"
    assert switch["unparked"] == sorted([law["a"], law["d"]]) and switch["parked"] == [law["c"]]
    kinds = {(row["was"], row["now"]): row["laws"] for row in switch["kinds"]}
    assert kinds == {("climbs", "parks"): 1, ("parks", "climbs"): 1, ("parks", "let_through"): 1,
                     ("parks", "parks"): 1}
    assert {(row["was"], row["now"]) for row in switch["rules"]} == {
        ("no_reading", FS.APART), ("deep_lane_full", FS.ALIKE), ("no_reading", "salted"), ("no_reading", "no_reading")}


def test_what_a_park_s_let_through_read_a_size_later_is_what_the_park_cost():
    record, law = campaign()
    let = FD.decided(record)["let_through"]
    alike = let[FS.ALIKE]
    assert alike["laws"] == 4
    assert alike["a_size_later"] == {"a shape": 1, "parked again": 1, "not yet": 1,
                                     "refused by the structure gate": 1}
    assert alike["a_shape"] == [law["d"]], "the law the park would have lost"
    assert let[FS.APART_TWICE] == {"laws": 0, "a_size_later": {}, "decided_otherwise": {}, "a_shape": []}


def test_a_bundle_without_report_28_s_counts_is_read_from_report_10_s_rules_and_reasons():
    record, law = campaign()
    rows = {name: [{key: value for key, value in row.items() if key != "facts"} for row in rows]
            for name, rows in record.items()}
    out = FD.decided(rows, from_rules=True)
    assert out["from"] == "report 10's rules and reasons"
    assert out["decisions"] == 8 and out["not_taken"] == {}
    assert out["parked_where_d_s_climbed"] == sorted([law["b"], law["c"], law["e"]]), (
        "a park's reason names d_s's rule")
    assert out["climbed_where_d_s_parked"] == [], "a size bought does not say what d_s would have done"
    switch = out["at_the_switch"]
    assert (switch["laws"], switch["unparked"], switch["parked"]) == (3, sorted([law["a"], law["d"]]), [law["c"]])
    alike = out["let_through"][FS.ALIKE]
    assert alike["a_size_later"] == {"a shape": 1, "parked again": 1, "not yet": 1} and alike["a_shape"] == [law["d"]]


def test_report_28_carries_the_count_beside_every_chain_s_scores():
    record, _law_names = campaign()
    section = ECR.every_chain_section({"measurements": [], "engine_decisions": record})
    assert "error" not in section, section.get("error")
    assert section["starts_decided"]["decisions"] == 9
    assert ECR.every_chain_section({"measurements": []})["starts_decided"]["decisions"] == 0
    assert "starts_decided" in section["reading"]


def test_a_decision_s_kind_is_what_it_does_to_the_law_s_depth():
    assert FD.kind(RUN_NEXT, FS.SHAPE) == "climbs" and FD.kind(HOLD, "deep_lane_full") == "climbs"
    assert FD.kind(RUN_NEXT, "salted") == "let_through" and FD.kind(RUN_NEXT, "gate_audit") == "let_through"
    assert FD.kind(HOLD, "deep_lane_full", {"salted_from": {"rule": FS.ALIKE}}) == "let_through"
    assert FD.kind(HOLD, "unsettled") == "holds" and FD.kind(STOP, "no_reading") == "parks"
    assert FD.kind(STOP, FS.APART_TWICE) == "parks" and FD.kind(STOP, "no_finite_dimension") == "stops"
    assert FD.kind("done", "ladder_complete") == "ends" and FD.kind(None, None) == "not_recorded"


def test_a_study_s_campaigns_are_counted_as_one():
    record, law = campaign()
    one = FD.decided(record)
    assert FD.combined([one]) == dict(one, campaigns=1), "one campaign's count is its own"
    two = FD.combined([one, FD.decided({}), {"contract": "another reading"}])
    assert two["campaigns"] == 2 and two["decisions"] == 9 and two["at_the_switch"]["laws"] == 4
    both = FD.combined([one, one])
    assert (both["decisions"], both["laws"], both["at_the_switch"]["laws"]) == (18, 14, 8)
    assert both["let_through"][FS.ALIKE]["a_size_later"]["a shape"] == 2
    assert both["parked_where_d_s_climbed"] == sorted([law["b"], law["c"], law["e"]] * 2)
