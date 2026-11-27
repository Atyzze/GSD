from __future__ import annotations

import pytest

H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}


def _law(beta: float, *, terms=None) -> dict:
    from graph_scale_dynamics.dsl import dsl
    spec = dict(H12, dynamics=dict(H12["dynamics"], beta=beta), terms=terms if terms is not None else H12["terms"])
    return dsl.normalize(spec)


def _laws(rows) -> dict[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    out = {}
    for code, spec, verdict, score, control in rows:
        out[dsl.fingerprint(spec)] = {"spec": spec, "verdict": verdict, "code": code, "score": score,
                                      "control": control}
    return out


def test_the_most_verified_laws_of_one_term_set_nearest_one_centre_are_the_first_zone():
    from graph_scale_dynamics.operations import zone_choice as Z
    two = H12["terms"][:2]
    laws = _laws([("A1", _law(0.188203), Z.CONFIRMED, 1, False), ("A2", _law(0.19), Z.CONFIRMED, 1, False),
                  ("A3", _law(0.192), Z.CONFIRMED, 1, False), ("A4", _law(0.2), Z.DENIED, 1, False),
                  ("A5", _law(0.9), Z.CONFIRMED, 1, False),
                  ("B1", _law(0.3, terms=two), Z.CONFIRMED, 38, False), ("B2", _law(0.302, terms=two), Z.CONFIRMED, 27, False),
                  ("B3", _law(0.304, terms=two), Z.UNMATCHED, 19, False),
                  ("C1", _law(0.5, terms=H12["terms"][1:]), Z.CONFIRMED, 17, True),
                  ("C2", _law(0.501, terms=H12["terms"][1:]), Z.CONFIRMED, 1, False)])
    found = Z.first(laws, radius=0.1)
    zone = found["chosen"]
    assert zone["code"] == "A2" and zone["near"] == 3 and zone["laws"] == 4, (
        "four confirmed laws share the term set, three of them within 0.1 of A2, the denied A4 left out")
    assert set(zone["near_laws"]) == {laws_id for laws_id, e in laws.items() if e["code"] in ("A1", "A2", "A3")}
    assert zone["terms"] == ["degree_cube_sum", "degree_neighbor_gradient", "square_edge_overlap"]
    assert [g["code"] for g in found["groups"]][:2] == ["A2", "B1"], "B's best score does not outrank A's count"
    assert "3 verified laws within 0.1 of A2" in found["why"] and "the next, 2 verified laws within 0.1 of B1" in found["why"]
    assert "1 standing control never chosen" in found["why"]
    assert found["counts"] == {"confirmed": 8, "denied": 1, "unmatched": 1, "controls": 1, "laws": 10}
    assert all(g["code"] != "C1" for g in found["groups"]), "a control is never a centre or a member"


def test_ties_go_to_the_larger_group_then_the_closer_centre_and_nothing_is_chosen_from_laws_alone():
    from graph_scale_dynamics.operations import zone_choice as Z
    two = H12["terms"][:2]
    laws = _laws([("A1", _law(0.188203), Z.CONFIRMED, 1, False), ("A2", _law(0.19), Z.CONFIRMED, 1, False),
                  ("A3", _law(0.9), Z.CONFIRMED, 1, False),
                  ("B1", _law(0.3, terms=two), Z.CONFIRMED, 38, False), ("B2", _law(0.302, terms=two), Z.CONFIRMED, 27, False)])
    found = Z.first(laws, radius=0.1)
    assert found["chosen"]["laws"] == 3 and found["chosen"]["near"] == 2, "two each within 0.1: the larger group"
    alone = _laws([("A1", _law(0.188203), Z.CONFIRMED, 1, False), ("A3", _law(0.9), Z.CONFIRMED, 1, False),
                   ("B1", _law(0.3, terms=two), Z.CONFIRMED, 38, False), ("B2", _law(0.302, terms=two), Z.DENIED, 1, False)])
    none = Z.first(alone, radius=0.1)
    assert none["chosen"] is None and none["why"].startswith("no two verified laws of one term set lie within 0.1")


def test_a_run_again_is_confirmed_denied_or_unmatched_chain_by_chain():
    from graph_scale_dynamics.operations import dex_check
    from graph_scale_dynamics.operations import zone_choice as Z

    def chain(law, n, seed, init, **changed):
        row = {"law": law, "n": n, "seed": seed, "replicate": 0, "chain": 0, "init": init, "moves": 1000, "ran": True,
               "accepted_moves": 400, "final_edges": 90, "peak_edges": 95, "max_degree": 6, "work_units": 5000,
               "termination": "certified", "science": "s", "source": "dex_177"}
        return dict(row, **changed)

    recorded = [chain(law, n, 0, init) for law in ("same", "other", "longer") for n in (64, 256)
                for init in ("empty", "random")]
    own = [dict(chain("same", n, 0, init), source="study 178's folder") for n in (64, 256) for init in ("empty", "random")]
    own += [chain("other", 64, 0, "empty"), chain("other", 256, 0, "random", accepted_moves=401)]
    own += [chain("longer", 64, 0, "empty", moves=2000)]
    found = dex_check.judged(recorded, own, ["same", "other", "longer", "never"], by="study 178's folder", science="s")
    assert {law: e["verdict"] for law, e in found.items()} == {
        "same": Z.CONFIRMED, "other": Z.DENIED, "longer": Z.UNMATCHED, "never": Z.UNMATCHED}
    assert found["same"]["agree"] == 4 and found["same"]["sizes"] == [64, 256]
    assert found["other"]["first_differ"]["accepted_moves"] == [400, 401] and found["other"]["agree"] == 1
    assert found["longer"]["other_length"] == 1 and found["never"]["chains"] == 0


@pytest.mark.parametrize("check, said", [({"agree": 3}, "confirmed"), ({"agree": 3, "differ": 1}, "denied"),
                                         ({}, "unmatched"), (None, "unmatched")])
def test_a_verdict_reads_its_counts(check, said):
    from graph_scale_dynamics.operations import dex_check
    assert dex_check.verdict_of(check) == said
