from __future__ import annotations

from graph_scale_dynamics.decisions import starts_rule as FS
from graph_scale_dynamics.decisions.engine import RUN_NEXT, Decision, Policy, Rung
from graph_scale_dynamics.observability import starts_reading as F
from graph_scale_dynamics.operations.study_design import design_for, designed_studies


def test_every_design_decided_chain_by_chain_has_a_reference_at_every_size_of_its_ladder():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    refs = F.table_references()
    assert refs, "the table's references are this tree's"
    checked = 0
    from tests.support import designs
    every = [designs.a_design(), *(design_for(None, study) or {} for study in designed_studies())]
    for design in every:
        study = design.get("study")
        if not (design.get("engine") or {}).get("every_chain"):
            continue
        ladder = design.get("ladder") or {}
        sizes = [int(n) for n in [*(ladder.get("base") or []), *(ladder.get("deep") or [])] if int(n) >= F.FROM_N]
        for start in design.get("starts") or []:
            family = start.get("family")
            if family not in F.LATTICES:
                continue
            missing = [n for n in sizes if n not in (refs.get(family) or {})]
            assert not missing, f"study {study}: {family} has no reference at {missing}"
            checked += 1
    assert checked >= 6, "the six lattice starts of every design in the tree, and of the tests' own"


def _law(refs: dict, sizes: list[int]) -> dict:
    cubic = next(iter(refs["periodic_cubic_quotient"].values()))["start"]
    rungs = []
    for n in sizes:
        own = {family: ((refs.get(family) or {}).get(n) or next(iter(refs[family].values())))["start"]
               for family in F.LATTICES}
        rungs.append({"n": n, "empty": cubic, "given": cubic,
                      "more_given": {name: own[family] for family, (name, _d) in F.LATTICES.items()}})
    starts = [{"name": "random", "family": "random_at_drawn_degree"},
              *({"name": name, "family": family} for family, (name, _d) in F.LATTICES.items())]
    return {"chains": {"given_name": "random", "rungs": rungs}, "starts": starts}


def test_a_size_without_references_is_said_and_is_not_decided_by_the_starts():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    every = F.table_references()
    refs = {family: {n: ref for n, ref in by_n.items() if n <= 65536} for family, by_n in every.items()}
    law = _law(refs, [16384, 65536, 262144])
    reading = F.law_reading(law["chains"], law["starts"], references=refs)
    assert reading["at_n"] == 262144
    assert reading["references"] is False, "the flag says the size read had no reference, not that some file exists"
    lattices = sorted(name for name, _d in F.LATTICES.values())
    assert len(lattices) == 7 and reading["unreferenced"] == {"n": 262144, "lattices": lattices}
    top = reading["rungs"][-1]
    assert all(top["fates"][name]["fate"] is None for name in lattices)
    compact = F.compact(reading)
    assert compact["unreferenced"]["n"] == 262144
    policy = Policy(every_chain=True)
    chosen = Decision(law="law-x", action=RUN_NEXT, rule="d_s_settled", reason="d_s settled", at_n=262144,
                      next_n=1048576, priority=1, facts={"chains": {}})
    rungs = [Rung(n=n, mean_degree=6.0, seeds_measured=3) for n in (64, 256, 1024, 4096, 16384, 65536, 262144)]
    decision = FS.decide("law-x", chosen, compact, policy, rungs)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "d_s_settled", 1048576)
    seen = decision.facts["starts_reading"]
    assert seen["decided"] is False and f"no reference for {', '.join(lattices)} at N=262,144" in seen["why"]


def test_a_size_with_its_references_is_read_as_before():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    every = F.table_references()
    law = _law(every, [16384, 65536])
    reading = F.law_reading(law["chains"], law["starts"], references=every)
    assert reading["references"] is True and "unreferenced" not in reading
    fates = reading["rungs"][-1]["fates"]
    assert len(fates) == 7 and {fate["fate"] for fate in fates.values()} == {"unmoved"}, (
        "a lattice on its own start is the start itself")


def test_the_space_score_calls_the_plane_lattices_a_space_and_refuses_the_others_for_their_reach():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.observability import space_score as S
    references = F.table_references()
    assert len(references) == 7, "the six lattice starts and the honeycomb"
    found = {}
    for family, sizes in references.items():
        rungs = [{"n": n, "given": sizes[n]["start"]} for n in sorted(sizes)]
        assert [rung["n"] for rung in rungs] == [1024, 4096, 16384, 65536, 262144, 1048576], family
        assert all(rung["given"][probe]["of"] == 10 for rung in rungs for probe in S.DIMENSION_PROBES), family
        found[family] = S.chain_reading(rungs, "given")
    assert {family: (reading["d"], reading["space"]) for family, reading in found.items()} == {
        "periodic_square_lattice": (2, True), "periodic_triangular_lattice": (2, True),
        "periodic_honeycomb_lattice": (2, True), "periodic_cubic_quotient": (3, False),
        "periodic_body_centred_cubic_lattice": (3, False), "periodic_face_centred_cubic_lattice": (3, False),
        "periodic_tesseract_quotient": (4, False)}
    for family in ("periodic_cubic_quotient", "periodic_body_centred_cubic_lattice",
                   "periodic_face_centred_cubic_lattice"):
        rungs = found[family]["rungs"]
        assert all(rung["properties"]["dimension"]["distance"] <= 1.0 for rung in rungs), (
            family, "its probes' median is within the score's margin of 3 at every size")
        assert all(rung["properties"]["agree"]["distance"] <= 1.0 for rung in rungs), family
        refused = [rung for rung in rungs if rung["distance"] > 1.0]
        assert refused and all(rung["worst"] == "reach" for rung in refused), (
            family, "what refuses it is the reach from one size to the next, a whole number of steps")
    cubic = references["periodic_cubic_quotient"]
    assert (cubic[1024]["start"]["reach"]["mean"], cubic[1048576]["start"]["reach"]["mean"]) == (7.0, 73.0)
    tesseract = found["periodic_tesseract_quotient"]["rungs"]
    assert tesseract[0]["worst"] == "agree" and tesseract[0]["properties"]["agree"]["reading"] == 0.832
    assert all(rung["worst"] == "reach" for rung in tesseract[1:])
