from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.observability import starts_reading as F
from graph_scale_dynamics.observability import law_score as L

HONEYCOMB, CUBIC, TESSERACT = "periodic_honeycomb_lattice", "periodic_cubic_quotient", "periodic_tesseract_quotient"
SIZES = (1024, 4096, 16384, 65536)


def side(**values) -> dict:
    return {key: {"mean": value, "se": 0.0, "seeds": 3} for key, value in values.items()}


def plane(n: int, **more) -> dict:
    return dict(mean_degree=4.0, triangles_per_node=0.0, squares_per_node=1.0, kappa=0.0, giant_fraction=1.0,
                reach=0.5 * math.sqrt(n), d_s=2.0, d_V=2.0, d_B=2.0, d_w=2.0, **more)


def wired(n: int) -> float:
    return 0.6 * math.log(n)


def random_graph(n: int, **more) -> dict:
    return dict(dict(mean_degree=6.0, triangles_per_node=0.01, squares_per_node=0.05, kappa=-0.5, giant_fraction=1.0,
                     reach=wired(n), d_s=4.0, d_V=5.0 + math.log(n) / 10, d_B=4.5, d_w=2.4), **more)


def ring(n: int) -> dict:
    return dict(mean_degree=2.0, triangles_per_node=0.0, squares_per_node=0.0, kappa=0.0, giant_fraction=1.0,
                reach=n / 4.0, d_s=1.0, d_V=1.0, d_B=1.0, d_w=2.0)


def shape(family: str, n: int) -> dict:
    if family == HONEYCOMB:
        return dict(mean_degree=3.0, triangles_per_node=0.0, squares_per_node=0.0, kappa=0.0, giant_fraction=1.0,
                    reach=0.6 * math.sqrt(n), d_s=1.9, d_V=2.0, d_B=2.0, d_w=2.0)
    if family == CUBIC:
        return dict(mean_degree=6.0, triangles_per_node=0.0, squares_per_node=3.0, kappa=0.0, giant_fraction=1.0,
                    reach=0.8 * n ** (1 / 3), d_s=2.6, d_V=2.8, d_B=2.7, d_w=2.1)
    return dict(mean_degree=8.0, triangles_per_node=0.0, squares_per_node=6.0, kappa=0.0, giant_fraction=1.0,
                reach=0.9 * n ** 0.25, d_s=3.0, d_V=3.2, d_B=3.1, d_w=2.2)


REFS = {family: {n: {"start": side(**shape(family, n)), "random_reach": wired(n)} for n in SIZES}
        for family in (HONEYCOMB, CUBIC, TESSERACT)}


def held(family: str, n: int, **more) -> dict:
    values = shape(family, n)
    return dict(values, triangles_per_node=0.01, squares_per_node=values["squares_per_node"] * 0.98, **more)


def melted(family: str, n: int) -> dict:
    return random_graph(n, mean_degree=shape(family, n)["mean_degree"])


def law(per_size) -> dict:
    rungs = []
    for n in SIZES:
        from_empty, random, honeycomb, cubic, tesseract = per_size(n)
        rungs.append({"n": n, "seeds": 3, "empty": side(**from_empty), "given": side(**random),
                      "more_given": {"honeycomb": side(**honeycomb), "cubic": side(**cubic),
                                     "tesseract": side(**tesseract)}})
    return {"rungs": rungs,
            "every_chain": [{"name": "empty", "key": "empty", "start": "the empty graph"},
                            {"name": "random", "key": "given", "start": "random_at_drawn_degree"},
                            {"name": "honeycomb", "key": "honeycomb", "start": HONEYCOMB},
                            {"name": "cubic", "key": "cubic", "start": CUBIC},
                            {"name": "tesseract", "key": "tesseract", "start": TESSERACT}]}


def scored(per_size) -> dict:
    return L.score(law(per_size), references=REFS)


def lattices_melted(n):
    return melted(HONEYCOMB, n), melted(CUBIC, n), melted(TESSERACT, n)


def refused(n: int) -> dict:
    return dict(mean_degree=6.0, giant_fraction=1.0, reach=wired(n), d_s=None, d_V=None, d_B=None, d_w=None)


def side_of(values: dict) -> dict:
    return {key: {"mean": value, "se": 0.0, "seeds": 3 if value is not None else 0, "of": 3}
            for key, value in values.items()}


def chains_of(per_size, sizes=SIZES, given=None) -> dict:
    rungs = [{"n": n, "seeds": 3, "empty": side_of(per_size(n)), "given": side_of((given or refused)(n))}
             for n in sizes]
    return {"rungs": rungs}


def test_the_ladder_is_a_seventh_a_size_to_4194304_and_the_twin_starts_count_alike():
    assert [round(L.depth(n) * 7, 6) for n in L.LADDER] == [1, 2, 3, 4, 5, 6, 7]
    assert L.depth(512) == 0.0 and L.depth(8_388_608) == 1.0
    assert dict(L.WEIGHTS) == {"empty": 1.0, "random": 1.0, "lattice": 0.6, "kept": 0.3, "frozen": 0.0, "still": 0.0}
    assert L.POINTS == 15 and L.ITEMS == ("d_s", "d_V", "d_B", "d_w", "einstein")


def test_the_pairs_are_relied_on_from_4096_and_step_as_the_ladder_does():
    assert L.pairs([64, 256, 1024, 4096, 16384, 65536]) == [(4096, 16384), (16384, 65536)]
    assert L.pairs([4096, 8000, 15625, 64000]) == [(4096, 15625), (15625, 64000)]
    assert L.pairs([1024, 4096]) == [] and L.pairs([4096]) == []
    assert [L.level(n) for n in (16384, 15625, 20736, 64000, 331776, 1030301)] == [
        16384, 16384, 16384, 65536, 262144, 1048576]


def test_a_plane_grown_from_empty_settles_all_four_twice_and_agrees_by_einstein():
    found = scored(lambda n: (plane(n), random_graph(n), *lattices_melted(n)))
    assert (found["score"], found["by"], found["chain"], found["to_n"]) == (57, "empty", "empty", 65536)
    assert found["points"] == L.POINTS and found["einstein"] is True
    top = found["sizes"][-1]["chains"]["empty"]
    assert top["settled"] == list(L.PROBES) and top["residual"] == 0.0 and top["from_n"] == 16384
    assert top["items"] == {item: 3 for item in L.ITEMS}
    first = found["sizes"][0]["chains"]["empty"]
    assert first["items"] == {item: 2 for item in L.ITEMS} and first["points"] == 10
    assert round(100 * L.depth(4_194_304) * dict(L.WEIGHTS)["empty"]) == 100
    assert [size["n"] for size in found["sizes"]] == [16384, 65536], "nothing is relied on under 4,096"


def test_the_random_start_counts_as_the_chain_from_empty_does():
    found = L.score(chains_of(refused, given=plane), references=REFS)
    assert (found["score"], found["by"], found["chain"]) == (57, "random", "given")


def test_a_lattice_that_keeps_its_shape_counts_three_tenths():
    flat = {n: dict(held(HONEYCOMB, n), d_s=2.0) for n in SIZES}
    five = {"rungs": [{"n": n, "fates": {"honeycomb": {"fate": "holds"}}} for n in SIZES]}
    chains = law(lambda n: (refused(n), refused(n), flat[n], melted(CUBIC, n), melted(TESSERACT, n)))
    found = L.score(chains, five, references=REFS)
    assert (found["score"], found["by"], found["chain"], found["to_n"]) == (17, "kept", "honeycomb", 65536)
    assert found["sizes"][-1]["chains"]["honeycomb"]["fate"] == "holds"


def test_a_lattice_start_that_became_another_geometry_counts_six_tenths():
    thinned = {n: dict(held(TESSERACT, n), d_s=2.0, d_V=2.0, d_B=2.0, d_w=2.0, reach=0.5 * math.sqrt(n)) for n in SIZES}
    five = {"rungs": [{"n": n, "fates": {"tesseract": {"fate": "loses"}}} for n in SIZES]}
    chains = law(lambda n: (refused(n), refused(n), melted(HONEYCOMB, n), melted(CUBIC, n), thinned[n]))
    found = L.score(chains, five, references=REFS)
    assert (found["score"], found["by"], found["chain"]) == (34, "lattice", "tesseract")


def test_a_probe_that_moves_past_its_margin_has_not_settled():
    def climbing(n):
        return dict(plane(n), d_s=2.0 * (1.0 + 0.2) ** math.log(n / 4096, 4))
    found = L.score(chains_of(climbing), references=REFS)
    top = found["sizes"][-1]["chains"]["empty"]
    assert "d_s" not in top["settled"] and top["einstein"] is False
    assert top["items"] == {"d_s": 1, "d_V": 3, "d_B": 3, "d_w": 3, "einstein": 1} and top["points"] == 11
    assert found["score"] == round(100 * L.depth(65536) * 11 / L.POINTS)
    assert "11 of 15" in top["how"] and "d_s reads at two sizes" in top["how"]


def test_four_settled_probes_that_break_the_einstein_relation_earn_it_one_point():
    found = L.score(chains_of(lambda n: dict(plane(n), d_w=2.6)), references=REFS)
    top = found["sizes"][-1]["chains"]["empty"]
    assert top["settled"] == list(L.PROBES) and top["residual"] > L.tau() and top["points"] == 13
    assert top["items"]["einstein"] == 1 and found["einstein"] is False


def test_a_fractal_agrees_by_the_einstein_relation():
    gasket = dict(d_s=2 * math.log(3) / math.log(5), d_V=math.log(3) / math.log(2), d_B=math.log(3) / math.log(2),
                  d_w=math.log(5) / math.log(2))
    found = L.score(chains_of(lambda n: dict(plane(n), **gasket)), references=REFS)
    assert found["points"] == L.POINTS and found["sizes"][-1]["chains"]["empty"]["residual"] < 1e-9


def test_nothing_scores_before_two_sizes_from_4096_and_refusals_score_nothing():
    only = L.score(chains_of(plane, sizes=(1024, 4096)), references=REFS)
    assert only["score"] == 0 and only["sizes"] == [] and only["by"] is None
    assert L.score(chains_of(refused), references=REFS)["score"] == 0
    once = L.score(chains_of(lambda n: plane(n) if n <= 16384 else refused(n)), references=REFS)
    assert (once["score"], once["to_n"], once["points"]) == (round(100 * L.depth(16384) * 10 / 15), 16384, 10), (
        "it holds to the largest size it earned points at")
    small = L.score(chains_of(lambda n: dict(plane(n), giant_fraction=0.2)), references=REFS)
    assert small["score"] == 0, "784: a piece under 4,096 nodes at 4,096 and 16,384 reads nothing the score counts"


def test_the_compact_form_is_what_report_28_and_the_board_keep():
    found = scored(lambda n: (plane(n), random_graph(n), *lattices_melted(n)))
    compact = L.compact(found)
    assert {k: compact[k] for k in ("score", "by", "chain", "to_n", "top_n", "points", "points_of", "einstein")} == {
        "score": 57, "by": "empty", "chain": "empty", "to_n": 65536, "top_n": 65536, "points": 15, "points_of": 15,
        "einstein": True}
    assert compact["items"] == {item: 3 for item in L.ITEMS} and {"empty", "random"} <= set(compact["parts"])
    assert L.zero(256) == {"score": 0, "by": None, "chain": None, "to_n": None, "d": None, "mean_degree": None,
                           "top_n": 256, "points": 0,
                           "points_of": 15, "items": None, "einstein": False, "parts": {}}


def test_the_margins_are_the_ones_the_known_answers_kept():
    table = L.margins()
    from graph_scale_dynamics.research import score_known_answers as K
    judged = json.loads(K.JUDGED.read_text(encoding="utf-8"))
    assert judged["passes"]
    kept = judged["margins"]
    assert table["relative"] == kept["relative"] and table["tau"] == kept["tau"]


ROOT = Path(__file__).resolve().parents[2]
node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_law_page_draws_the_score_the_reader_writes(tmp_path):
    def per_size(n):
        cube = held(CUBIC, n)
        return cube, random_graph(n), melted(HONEYCOMB, n), cube, melted(TESSERACT, n)
    chains = law(per_size)
    payload = {"chains": chains, "score": L.score(chains, references=REFS)}
    assert payload["score"]["score"] == 57 and payload["score"]["points"] == L.POINTS
    path = tmp_path / "score.json"
    path.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
    result = subprocess.run([node, str(ROOT / "tests/ui/candidate_smoke.js"), str(ROOT / "graph_scale_dynamics/resources/ui")],
                            capture_output=True, text=True, timeout=180, env={**os.environ, "GSD_SCORE_PAYLOAD": str(path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the flow and the score drawn from the reader's payload" in result.stdout


def test_report_28_keeps_every_law_s_score_and_counts_them():
    from graph_scale_dynamics.reporting import every_chain_report as ECR
    from tests.unit.test_report_28_scores_every_chain import _measurements
    law_id = "a" * 64
    section = ECR.every_chain_section({"measurements": _measurements(law_id),
                                       "candidates": [{"candidate_id": law_id, "spec": {}}]})
    score = section["laws"][law_id]["score"]
    assert set(score) == {"score", "by", "chain", "to_n", "d", "mean_degree", "top_n", "points", "points_of",
                          "items", "einstein", "parts"} and score["top_n"] == 16384
    summary = section["scores"]
    assert summary["contract"] == L.CONTRACT and summary["laws"] == 1
    assert summary["above_zero"] == int(score["score"] > 0) and summary["weights"] == dict(L.WEIGHTS)
    found = ECR.score_summary({
        "a": {"score": {"score": 17, "by": "lattice", "chain": "honeycomb", "to_n": 65536, "top_n": 65536}},
        "b": {"score": {"score": 0, "by": None, "chain": None, "to_n": None, "top_n": 65536}},
        "c": {"score": {"score": 29, "by": "empty", "chain": "empty", "to_n": 16384, "top_n": 16384}}, "d": {}})
    assert (found["laws"], found["above_zero"], found["by"]) == (3, 2, {"lattice": 1, "empty": 1})
    assert [t["law"] for t in found["top"]] == ["c", "a"] and found["top"][0]["score"] == 29


def test_a_control_s_given_started_at_its_answer_counts_as_a_shaped_start_not_the_random_one():
    two = {"rungs": [{"n": n, "seeds": 3, "empty": side(**refused(n)), "given": side(**plane(n))} for n in SIZES]}
    assert L.score(two, references=REFS)["by"] == "random", "a given chain whose start nothing names: the historical random graph"
    spec = {"sampling_contract": {"given_start_by_law": {"law-1": {"family": "family_square_torus"}},
                                  "given_start": {"family": "family_cubic_torus"}}}
    assert L.given_family(spec, "law-1") == "family_square_torus" and L.given_family(spec, "law-2") == "family_cubic_torus"
    assert L.given_family({}, "law-1") is None
    found = L.score(two, references=REFS, first_given=L.given_family(spec, "law-1"))
    assert (found["score"], found["by"], found["chain"], found["to_n"]) == (17, "kept", "given", 65536), \
        "a lattice start whose fate is not read counts as kept: an unread fate is no move"
    assert L.CONTRACT == "gsd-law-score-9"


def test_the_score_says_what_dimension_it_read_and_a_ring_is_marked():
    found = scored(lambda n: (plane(n), random_graph(n), *lattices_melted(n)))
    assert found["d"] == 2.0 and not L.is_ring(found["d"]) and L.compact(found)["d"] == 2.0
    assert found["mean_degree"] == 4.0 and L.compact(found)["mean_degree"] == 4.0
    rings = scored(lambda n: (ring(n), random_graph(n), *lattices_melted(n)))
    assert rings["score"] > 0 and rings["d"] == 1.0 and L.is_ring(rings["d"]), "a ring scores; its d says it is one"
    assert rings["mean_degree"] == 2.0
    assert L.zero()["d"] is None and not L.is_ring(None)


def _cubic_held(moved):
    def per_size(n):
        values = dict(held(CUBIC, n), d_s=2.6)
        return refused(n), refused(n), refused(n), values, refused(n)
    chains = law(per_size)
    for rung in chains["rungs"]:
        if moved is not None:
            rung["more_given"]["cubic"]["moved"] = {"mean": moved, "median": moved}
    five = {"rungs": [{"n": n, "fates": {"cubic": {"fate": "holds"}}} for n in SIZES]}
    return L.score(chains, five, references=REFS)


def test_a_lattice_the_law_leaves_still_scores_1_the_lowest_and_says_why():
    still = _cubic_held(0.01)
    assert (still["score"], still["by"], still["chain"]) == (1, "still", "cubic")
    top = still["sizes"][-1]["chains"]["cubic"]
    assert top["kind"] == "still" and top["value"] == 1.0 and "still: the lattice kept its own mean degree" in top["how"]
    moving = _cubic_held(0.2)
    assert moving["by"] == "kept" and moving["score"] > 1, "more than 0.05 accepted moves an edge is not still"
    unread = _cubic_held(None)
    assert (unread["score"], unread["by"]) == (moving["score"], "kept"), "no accepted moves read: the score of 8"
    assert L.compact(still)["by"] == "still" and L.WHO["still"] == "a lattice start, still"


def test_a_still_lattice_is_one_at_its_own_degree_and_not_full():
    chain = {"key": "cubic", "name": "cubic", "family": CUBIC}
    side = {"mean_degree": {"mean": 6.0}, "moved": {"median": 0.01}, "ended_at_cap": {"seeds": 0, "of": 3}}
    assert L.still_at(chain, {"cubic": side})
    assert not L.still_at(chain, {"cubic": dict(side, mean_degree={"mean": 6.4})}), "5% off its degree at most"
    assert not L.still_at(chain, {"cubic": dict(side, ended_at_cap={"seeds": 2, "of": 3})}), "full is not still"
    assert not L.still_at({"key": "honeycomb", "name": "honeycomb", "family": HONEYCOMB},
                          {"honeycomb": dict(side, mean_degree={"mean": 3.0})}), "only the six starts have a degree"
    assert L.lattice_name({"key": "given", "name": "given", "family": "periodic_square_lattice"}) == "square"
