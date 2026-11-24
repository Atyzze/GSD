from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions import starts_rule as R
from graph_scale_dynamics.decisions import replay as P

GIVEN = {"d": 5.83, "kind": "grown", "beyond_checked": True, "line": False}
HONEYCOMB = {"d": 5.88, "kind": "grown", "beyond_checked": True, "line": False}


def _parked() -> E.Decision:
    return E.Decision(law="a" * 64, action=E.STOP, rule=R.APART_TWICE, reason="parked", at_n=16384, next_n=None,
                      facts={}, observations=())


def _shown(chains: dict) -> E.Decision:
    reading = {"dimension": {"tier": 2, "chains": chains}}
    return R.shown(_parked(), reading, E.Policy(dimension_extends=True), 65536)


def test_the_reason_names_its_chains_in_the_starts_order_whatever_order_they_came_in():
    as_evidence = _shown({"given": GIVEN, "honeycomb": HONEYCOMB})
    as_stored = _shown({"honeycomb": HONEYCOMB, "given": GIVEN})
    assert as_evidence.rule == R.DIMENSION and as_evidence.next_n == 65536
    assert as_evidence.reason == as_stored.reason
    assert as_evidence.reason.index("given d 5.83") < as_evidence.reason.index("honeycomb d 5.88")


def test_the_starts_order_puts_an_unknown_chain_last_by_name():
    chains = {"zeta": 0, "tesseract": 0, "cubic": 0, "alpha": 0, "honeycomb": 0, "given": 0, "empty": 0}
    assert [name for name, _c in R.in_start_order(chains)] == [
        "empty", "given", "honeycomb", "cubic", "tesseract", "alpha", "zeta"]


def test_a_replay_names_the_facts_that_differ_and_both_values(monkeypatch):
    recorded = _shown({"given": GIVEN, "honeycomb": HONEYCOMB})
    replayed = E.Decision(law=recorded.law, action=recorded.action, rule=recorded.rule, reason=recorded.reason,
                          at_n=recorded.at_n, next_n=recorded.next_n, priority=recorded.priority,
                          facts=dict(recorded.facts, overrode=dict(recorded.facts["overrode"], reason="other")),
                          observations=())
    monkeypatch.setattr(P, "replay", lambda inputs, order=None: replayed)
    row = {"inputs": {"law": recorded.law, "policy": {"dimension_extends": True}}, "facts": recorded.facts,
           "action": recorded.action, "rule": recorded.rule, "reason": recorded.reason, "next_n": recorded.next_n, "at_n": recorded.at_n,
           "priority": recorded.priority}
    result = P.replay_matches(row)
    differs = [d for d in result["differences"] if d.startswith("facts differ")]
    assert differs == ['facts differ: overrode.reason recorded "parked", replayed "other"']


def test_the_facts_shown_are_bounded():
    recorded = {f"k{i}": i for i in range(9)}
    replayed = {f"k{i}": i + 1 for i in range(9)}
    text = P.facts_differ(recorded, replayed)
    assert text.count("recorded") == P.FACTS_SHOWN and text.endswith("; and 5 more")
    assert len(P.facts_differ({"x": "a" * 1000}, {"x": "b"})) < 400


def _shaped(fates: dict) -> E.Decision:
    policy = E.Policy(every_chain=True)
    rungs = [E.Rung(n=n, mean_degree=3.0, seeds_measured=3) for n in (64, 256, 1024, 4096)]
    names = ["empty", "random", "square", "triangular", "cubic", "bcc", "fcc", "tesseract"]
    reading = {"class": "holds", "at_n": 4096, "top_n": 4096, "top_dense": False, "references": True,
               "by_n": {"1024": ["holds", [names]], "4096": ["holds", [names]]}, "fates": fates}
    chosen = E.Decision(law="a" * 64, action=E.RUN_NEXT, rule="d_s_settled", reason="d_s: d_s_settled", at_n=4096,
                        next_n=16384, priority=1, facts={"mean_degree": 3.0}, observations=())
    return R.decide("a" * 64, chosen, reading, policy, {name: rungs for name in names})


def test_a_shape_two_lattices_hold_is_decided_alike_whatever_order_its_fates_were_stored_in():
    as_measured = _shaped({"square": ["holds", 0.99], "triangular": ["dense", 0.0], "bcc": ["holds", 0.94]})
    as_stored = _shaped({"bcc": ["holds", 0.94], "square": ["holds", 0.99], "triangular": ["dense", 0.0]})
    assert as_measured.rule == R.SHAPE and as_measured.next_n == 16384
    assert "(square, bcc holding)" in as_measured.reason
    assert as_measured.reason == as_stored.reason
    assert as_measured.facts.get("gate") == as_stored.facts.get("gate")
    assert (as_measured.facts.get("gate") or {}).get("chain", "square") == "square"
