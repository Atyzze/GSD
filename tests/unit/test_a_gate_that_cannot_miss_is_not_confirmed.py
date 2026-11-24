from __future__ import annotations

from graph_scale_dynamics.research import gate_tree as T


def _row(at_n, action, rule, *, salted=(), gate=None):
    facts = {"salted": list(salted)} if salted else {}
    if gate is not None:
        facts["gate"] = gate
    return {"decision_id": f"{at_n}-{rule}", "at_n": at_n, "action": action, "rule": rule, "facts": facts}


def test_a_law_the_full_rule_never_read_ended_untested():
    final = {4096: _row(4096, "run_next", "starts_alike", salted=["starts_alike"]),
             16384: _row(16384, "stop", "starts_alike")}
    assert T._ledger_outcome(final, 4096, final[16384]) == T.UNTESTED
    final[16384]["facts"]["gate"] = {"stage": "early", "result": "no finite dimension"}
    assert T._ledger_outcome(final, 4096, final[16384]) == T.UNTESTED
    read = {4096: final[4096], 65536: _row(65536, "stop", "no_finite_dimension",
                                           gate={"stage": "full", "result": "no finite dimension"})}
    assert T._ledger_outcome(read, 4096, read[65536]) == T.CLEAN


def test_untested_laws_never_confirm_a_gate():
    entries = [(f"k{i:04d}", T.UNTESTED) for i in range(5000)]
    assert T.ledger(entries, T.CHEAP)["label"] == "testing"
