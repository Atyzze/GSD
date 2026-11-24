from __future__ import annotations

import json
import re

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.reporting import gate_trees_page as P
from graph_scale_dynamics.research import gate_tree as T

_ids = iter(range(10_000))


def row(at_n, action, rule, *, salted=(), settled=None, next_n=None):
    facts = {}
    if salted:
        facts["salted"] = list(salted)
    if settled is not None:
        facts["d_s_settled"] = settled
    return {"decision_id": f"d{next(_ids):05d}", "at_n": at_n, "next_n": next_n, "action": action, "rule": rule,
            "facts": facts}


def the_record():
    return {
        "A": [row(None, "run_next", "start"), row(256, "run_next", "base_block"), row(1024, "run_next", "base_block"),
              row(4096, "run_next", "d_s_settled", settled=True), row(16384, "run_next", "complete_rung")],
        "B": [row(256, "stop", "empty")],
        "C": [row(256, "run_next", "base_block", salted=["empty"]),
              row(1024, "run_next", "base_block", salted=["empty"]),
              row(4096, "run_next", "d_s_settled", salted=["empty"], settled=True)],
        "D": [row(256, "run_next", "base_block"), row(1024, "stop", "disconnected")],
        "F": [row(4096, "hold", "unsettled"), row(4096, "run_next", "salted", salted=["no_reading"]),
              row(16384, "stop", "reading_lost")],
        "G": [row(256, "run_next", "base_block", salted=["too_dense"]), row(1024, "stop", "disconnected")],
        "H": [row(16384, "hold", "unsettled", salted=["no_finite_dimension"])],
    }


def gate(tree, name):
    return next(g for g in tree["gates"] if g["gate"] == name)


def test_each_rung_counts_the_laws_that_finished_it_by_where_they_went():
    tree = T.build_gate_tree(the_record())
    assert tree["laws"] == 7
    rungs = {r["n"]: r for r in tree["rungs"]}
    assert rungs[256]["finished"] == 5 and rungs[256]["went_on_by"] == {"base_block": 4}
    assert rungs[256]["stopped"] == {"empty": 1}
    assert rungs[256]["salted_past"] == {"empty": 1, "too_dense": 1}
    assert rungs[1024]["stopped"] == {"disconnected": 2}
    assert rungs[4096]["went_on_by"] == {"d_s_settled": 2, "salted": 1}, "a released hold's last word counts"
    assert rungs[16384]["finished"] == 2, "a rung short of seeds is not finished (A), a stop and a hold are"
    assert rungs[16384]["held"] == {"unsettled": 1} and rungs[16384]["stopped"] == {"reading_lost": 1}


def test_a_gate_counts_each_law_once_and_compares_its_salted_laws_with_the_unsalted():
    tree = T.build_gate_tree(the_record())
    empty = gate(tree, "empty")
    assert (empty["withheld"], empty["let_through"], empty["share_let_through"]) == (1, 1, 0.5)
    assert empty["by_rung"] == {"256": {"withheld": 1, "let_through": 1}}, "once, at the first rung it happened"
    assert empty["let_through_later"] == {T.SETTLED_LATER: 1} and empty["settled_later_share"] == 1.0
    assert tree["unsalted_later_by_rung"]["256"] == {T.SETTLED_LATER: 1, T.STOPPED_LATER: 1}
    assert empty["unsalted_settled_later_share_at_the_same_rungs"] == 0.5
    assert gate(tree, "too_dense")["let_through_later"] == {T.STOPPED_LATER: 1}
    assert gate(tree, "disconnected")["withheld"] == 2
    no_reading = gate(tree, "no_reading")
    assert no_reading["let_through"] == 1 and no_reading["let_through_later"] == {T.STOPPED_LATER: 1}
    structure = gate(tree, "no_finite_dimension")
    assert structure["let_through_later"] == {T.HELD_SAME_RUNG: 1} and structure["went_on"] == 0
    assert structure["settled_later_share"] is None, "a salt that bought nothing has nothing to compare"
    assert gate(tree, "unsettled")["withheld"] == 1


def test_the_tree_keeps_every_gate_in_the_order_a_law_meets_them():
    tree = T.build_gate_tree({})
    assert [g["gate"] for g in tree["gates"]] == [g.name for g in G.GATES]
    assert all(g["why_not_salted"] for g in tree["gates"] if not g["salted"])
    assert tree["laws"] == 0 and tree["rungs"] == []


def test_the_page_carries_every_campaign_s_tree_side_by_side_on_aligned_rungs():
    tree = T.build_gate_tree(the_record())
    other = T.build_gate_tree({"Z": [row(256, "stop", "too_dense")]})
    page = P.render(P.document([{"campaign_id": "1", "label": "zero temperature, mean degree to 16", "tree": tree},
                                {"campaign_id": "2", "label": "zero temperature, mean degree to 32", "tree": other}],
                               title="Study gsd533: the gate trees", study={}), links={"explorer": None, "front": None})
    data = json.loads(re.search(r'id="gate-trees-data">(.*?)</script>', page, re.S).group(1))
    assert [c["label"] for c in data["campaigns"]] == ["zero temperature, mean degree to 16",
                                                      "zero temperature, mean degree to 32"]
    assert data["campaigns"][0]["tree"] == json.loads(json.dumps(tree)), "the record as report 28 carries it"
    assert {r["n"] for r in data["campaigns"][1]["tree"]["rungs"]} == {256}
    ledger = next(g for g in data["campaigns"][0]["tree"]["gates"] if g["gate"] == "too_dense")
    entry = ledger["salt_ledger"]["up to 4,096"]
    assert entry["ended_untested"] == 1 and entry["clean"] == 0, (
        "the salt's ledger rides along; a law the committed rule never read ended untested")
    assert "<script src" not in page


def test_a_salt_s_next_rung_is_its_measure_and_a_spent_salt_is_not_a_second_withholding():
    def spent_row(at_n, rule, *, reading=None):
        r = row(at_n, "stop", rule)
        r["facts"]["salt_spent"] = {"gate": rule, "salted_at": at_n // 4, "held_at": at_n}
        if reading:
            r["facts"]["gate"] = {"result": reading, "salted": True, "salt_spent": r["facts"]["salt_spent"]}
        return r

    def gate_row(at_n, rule, reading, **kw):
        r = row(at_n, "run_next", rule, **kw)
        r["facts"]["gate"] = {"result": reading}
        return r

    record = {
        "held": [gate_row(65536, "d_s_settled", "no finite dimension", salted=["no_finite_dimension"]),
                 spent_row(262144, "no_finite_dimension", reading="no finite dimension")],
        "turned": [gate_row(65536, "d_s_settled", "no finite dimension", salted=["no_finite_dimension"]),
                   gate_row(262144, "d_s_settled", "finite dimension")],
        "waiting": [gate_row(65536, "d_s_settled", "undecidable", salted=["no_finite_dimension"])],
        "refused": [row(65536, "stop", "no_finite_dimension")],
        "empty-spent": [row(256, "run_next", "base_block", salted=["empty"]), spent_row(1024, "empty")],
    }
    tree = T.build_gate_tree(record)
    structure = gate(tree, "no_finite_dimension")
    assert (structure["withheld"], structure["let_through"], structure["salt_spent"]) == (1, 3, 1)
    assert structure["salt_next_rung"] == {T.HELD: 1, T.CHANGED: 1, T.NOT_YET: 1}
    assert structure["salt_next_rung_reading"] == {"no finite dimension": 1, "finite dimension": 1}
    empty = gate(tree, "empty")
    assert (empty["withheld"], empty["let_through"], empty["salt_spent"]) == (0, 1, 1)
    assert empty["salt_next_rung"] == {T.HELD: 1} and "salt_next_rung_reading" not in empty
    rungs = {r["n"]: r for r in tree["rungs"]}
    assert rungs[1024]["stopped"] == {"empty": 1} and rungs[1024]["salt_spent"] == {"empty": 1}
    assert tree["contract"] == "gsd-gate-tree-3"


def test_the_salt_s_ledger_follows_every_salted_law_to_its_end_and_reads_its_label():
    record = {}
    for i in range(1000):
        record[f"e{i:04d}"] = [row(256, "run_next", "base_block", salted=["empty"]), row(1024, "stop", "too_dense")]
    record["e-going"] = [row(256, "run_next", "base_block", salted=["empty"]), row(1024, "run_next", "base_block")]
    record["e-same-rung"] = [row(256, "stop", "too_dense", salted=["empty"])]

    def structure(name, *, finite_later=False, ends=True):
        rows = [row(65536, "run_next", "d_s_settled", salted=["no_finite_dimension"])]
        later = row(262144, "run_next" if finite_later or not ends else "stop",
                    "d_s_settled" if finite_later or not ends else "no_finite_dimension")
        later["facts"]["gate"] = {"result": "finite dimension" if finite_later else "no finite dimension",
                                  "stage": "full"}
        rows.append(later)
        if finite_later:
            rows.append(row(1048576, "done", "ladder_complete"))
        record[name] = rows
    for i in range(5):
        structure(f"s-before-{i}")
    structure("s-turned", finite_later=True)
    for i in range(7):
        structure(f"s-after-{i}")
    tree = T.build_gate_tree(record)
    empty = gate(tree, "empty")["salt_ledger"]
    assert list(empty) == [T.CHEAP]
    assert empty[T.CHEAP] == {"salted": 1002, "clean": 0, "missed": 0, "open": 1, "bought_nothing": 1,
                              "ended_untested": 1000, "clean_since_last_miss": 0, "needed": 1000,
                              "label": "testing", "salt_under_554": 0.5}, (
        "a law stopped by another rule at the salted rung is not clean, and a law no rule could miss confirms nothing")
    deep = gate(tree, "no_finite_dimension")["salt_ledger"][T.DEEP]
    assert (deep["salted"], deep["clean"], deep["missed"], deep["open"]) == (13, 12, 1, 0), (
        "the law that read a finite dimension after its salt is the gate's miss, whatever it did next")
    assert deep["clean_since_last_miss"] == 7, "a miss sends the count back to zero"
    assert deep["label"] == "testing" and deep["salt_under_554"] == 0.1 and deep["needed"] == 300
    assert "salt_ledger" not in gate(tree, "disconnected"), "a gate that salted nothing has no ledger"
    assert T.ledger([("a", T.CLEAN)] * 299, T.DEEP)["label"] == "testing"
    assert T.ledger([(f"k{i:03d}", T.CLEAN) for i in range(300)], T.DEEP)["label"] == "confirmed"
