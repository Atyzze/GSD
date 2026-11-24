from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.research import score_known_answers as K

ROOT = Path(__file__).resolve().parents[2]


def _committed() -> dict:
    return json.loads(K.JUDGED.read_text(encoding="utf-8"))


def test_the_judged_reading_is_what_its_criterion_and_rows_give():
    margins, document = K.run()
    assert json.loads(json.dumps(document)) == _committed(), "run python3 tools/score_known_answers.py --write"
    assert margins == L.margins(), "the score reads the criterion's margins"


def test_the_criterion_passes_on_seeds_it_had_not_seen_read_by_the_final_probes():
    document = _committed()
    assert document["passes"] is True and not document["judged"]["misses"]
    counts = document["judged"]["counts"]
    assert all(counts[k]["of"] > 0 and counts[k]["held"] == counts[k]["of"] for k in ("K1", "K2", "K3", "K4")), counts
    measured = json.loads(K.MEASURED.read_text(encoding="utf-8"))
    criterion = K.criterion()
    assert sorted({r["seed"] for r in measured["rows"]}) == [51, 52, 53] == criterion["seeds"]
    assert measured["criterion"] == criterion["contract"] and document["committed_utc"] == criterion["committed_utc"]
    from graph_scale_dynamics.calibration import fingerprint as F
    assert F.estimator_fingerprint() in criterion["measured_by"], "read by the probes this tree runs"


def test_every_exact_lattice_settles_every_probe_it_is_held_to_and_five_points_where_its_ladder_holds_all_four():
    training = _committed()["training"]
    assert not training["does_not_settle"] and not training["beyond_tau"]
    first = training["first_five_points"]
    for family, at in first.items():
        assert at <= 1_048_576, family
    holds = json.loads(K.HOLDS.read_text())["with_a_dimension"]
    cases = K.table_cases()
    for family in (name for name in holds if name.startswith("periodic_")):
        by_n = cases[family][0]
        pairs = list(L.pairs(by_n))
        whole = [(a, b) for a, b in pairs if all(band["from_nodes"] <= a for band in holds[family].values())]
        if whole:
            assert first.get(family, 2**40) <= whole[0][1], "a score an exact lattice cannot pass at its sizes is not kept"
            continue
        a, b = pairs[-1]
        found = L.points_at(by_n[a]["side"], by_n[b]["side"], b, L.margins())
        held = {probe for probe, band in holds[family].items() if band["from_nodes"] <= a}
        assert held <= set(found["settled"]), (family, "every probe held at both sizes of its top pair settles there")


def test_the_margins_are_twice_the_widest_training_step_on_the_grid():
    margins = L.margins()
    grid = K.criterion()["training"]["margin_grid"]
    for probe in L.PROBES:
        for level, widest in margins["widest_training_step"][probe].items():
            if widest is None:
                continue
            allowed = margins["relative"][probe][level]
            assert allowed in grid and allowed >= 2 * widest
            assert all(g < 2 * widest - 1e-12 for g in grid if g < allowed), (probe, level)
    assert margins["tau"] >= margins["widest_training_residual"]["residual"]


def test_a_random_graph_and_a_small_world_score_nothing_and_a_lattice_settles_twice():
    cases = K.judged_cases_4(K._json(K.MEASURED_5)["rows"], K.criterion_5())["structures"]
    for name in ("random 3-regular graph", "square lattice with 0.008 shortcuts a node",
                 "preferential attachment, two links a node"):
        assert L.score(K._as_chain(cases[name]), references={})["score"] == 0, name
    cubic = L.score(K._as_chain(cases["cubic"]), references={})
    assert cubic["to_n"] == 65536 and cubic["items"] == {"d_s": 3, "d_V": 3, "d_B": 3, "d_w": 2, "einstein": 2}


def test_criterion_4_is_kept_as_it_was_judged_and_names_its_misses():
    _margins, document = K.run_4()
    assert json.loads(json.dumps(document)) == json.loads(K.JUDGED_4.read_text(encoding="utf-8")), (
        "run python3 tools/score_known_answers.py --write")
    assert document["passes"] is False and document["score"] == "gsd-law-score-7"
    missed = sorted({(m["prediction"], m["structure"]) for m in document["judged"]["misses"]})
    assert missed == [("S1", "periodic strip 16 nodes wide"), ("S1", "periodic tube 16 by 16 nodes across"),
                      ("S1", "periodic tube 8 by 8 nodes across"),
                      ("S2", "uniform random tree, every edge a path of 8")]
    measured = json.loads(K.MEASURED_4.read_text(encoding="utf-8"))
    assert sorted({r["seed"] for r in measured["rows"]}) == [51, 52, 53] == K.criterion_4()["seeds"]


def test_criterion_5_was_written_fresh_on_seeds_and_shapes_criterion_4_had_not_read_and_its_reading_is_kept():
    four, five = K.criterion_4(), K.criterion_5()
    assert five["committed_utc"] > four["committed_utc"] and not set(five["seeds"]) & set(four["seeds"])
    assert not {c["name"] for c in five["crossovers"]} & {c["name"] for c in four["crossovers"]} - {
        "uniform random tree, every edge a path of 8", "soup of cycles, the largest 6,144 nodes"}
    _margins, document = K.run_5()
    assert json.loads(json.dumps(document)) == json.loads(K.JUDGED_5.read_text(encoding="utf-8")), (
        "run python3 tools/score_known_answers.py --write")
    measured = json.loads(K.MEASURED_5.read_text(encoding="utf-8"))
    assert sorted({r["seed"] for r in measured["rows"]}) == [61, 62, 63] and measured["criterion"] == five["contract"]
    assert document["passes"] is False and document["score"] == K.SCORE_5 == "gsd-law-score-8"
    assert L.CONTRACT == "gsd-law-score-9", (
        "the score in force adds the still lattice to 8; no known answer carries accepted moves, so it reads them as 8 did")
    missed = sorted({(m["prediction"], m["structure"]) for m in document["judged"]["misses"]})
    assert missed == [("S2", "uniform random tree, every edge a path of 16"),
                      ("S2", "uniform random tree, every edge a path of 8")]
    assert K.IN_FORCE_AT_846 == "gsd-law-score-6", (
        "the score in force when criterion 5 was judged; the operator put the candidate in force at 848")
    counts = document["judged"]["counts"]
    assert all(counts[k]["of"] > 0 for k in counts), counts
