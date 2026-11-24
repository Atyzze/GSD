from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.measurements import starts as the_starts
from graph_scale_dynamics.observability import starts_reading as F
from graph_scale_dynamics.observability import space_score as S
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import starts_check as C  # noqa: E402
from tests.support.readings import readings

READINGS = readings(ROOT)
INPUTS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
CRITERION = INPUTS / "starts_known_answers_criterion.json"
HONEYCOMB, CUBIC, TESSERACT = "periodic_honeycomb_lattice", "periodic_cubic_quotient", "periodic_tesseract_quotient"
N = 4096


def side(se: float = 0.0, seeds: int = 3, **values) -> dict:
    return {key: {"mean": value, "se": se, "seeds": seeds} for key, value in values.items()}


RANDOM = dict(mean_degree=6.0, triangles_per_node=0.01, squares_per_node=0.05, giant_fraction=1.0, kappa=-0.5,
              reach=5.0, d_s=4.0, d_V=5.0, d_B=4.5, d_w=2.0)
SHAPES = {HONEYCOMB: dict(RANDOM, mean_degree=3.0, triangles_per_node=0.0, squares_per_node=0.0, kappa=0.0, reach=37.0,
                          d_s=1.9, d_V=2.0, d_B=2.0),
          CUBIC: dict(RANDOM, triangles_per_node=0.0, squares_per_node=3.0, kappa=0.0, reach=12.0, d_s=2.6, d_V=2.8,
                      d_B=2.7, d_w=2.1),
          TESSERACT: dict(RANDOM, mean_degree=8.0, triangles_per_node=0.0, squares_per_node=6.0, kappa=0.0, reach=8.0,
                          d_s=3.0, d_V=3.2, d_B=3.1, d_w=2.2)}
WIRED = {HONEYCOMB: 10.0, CUBIC: 5.0, TESSERACT: 4.0}
REFS = {family: {N: {"start": side(**values), "random_reach": WIRED[family]}} for family, values in SHAPES.items()}
MELTED = {family: dict(RANDOM, mean_degree=SHAPES[family]["mean_degree"], reach=WIRED[family],
                       d_s=4.0 + i, d_V=5.0 + i, d_B=4.5 + i) for i, family in enumerate(SHAPES)}
NAMES = (("honeycomb", HONEYCOMB), ("cubic", CUBIC), ("tesseract", TESSERACT))
HELD = {family: dict(values, triangles_per_node=0.01, squares_per_node=values["squares_per_node"] * 0.98)
        for family, values in SHAPES.items()}


def law(from_empty: dict, random: dict, honeycomb: dict, cubic: dict, tesseract: dict, *, n: int = N) -> dict:
    return {"rungs": [rung(n, from_empty, random, honeycomb, cubic, tesseract)],
            "every_chain": [{"name": "empty", "key": "empty", "start": "the empty graph"},
                            {"name": "random", "key": "given", "start": "random_mean_degree_6.0"},
                            *({"name": name, "key": name, "start": family} for name, family in NAMES)]}


def rung(n, from_empty, random, honeycomb, cubic, tesseract, se: float = 0.0) -> dict:
    return {"n": n, "seeds": 3, "empty": side(se, **from_empty), "given": side(se, **random),
            "more_given": {"honeycomb": side(se, **honeycomb), "cubic": side(se, **cubic),
                           "tesseract": side(se, **tesseract)}}


def read(chains: dict) -> dict:
    return F.law_reading(chains, references=REFS)


def at(degree: float, **more) -> dict:
    return dict(RANDOM, mean_degree=degree, reach=5.0 * 6.0 / degree, d_s=4.0 + degree / 6, **more)


def test_two_chains_meet_within_their_tolerances_and_part_beyond_them():
    a = side(**RANDOM)
    assert F.pair_distance(a, side(**dict(RANDOM, d_s=4.1)))["distance"] == pytest.approx(0.667, abs=0.001)
    apart = F.pair_distance(a, side(**dict(RANDOM, d_s=4.3)))
    assert apart == {"distance": 2.0, "worst": "d_s"}
    assert F.pair_distance(a, side(**dict(RANDOM, mean_degree=6.1)))["distance"] == pytest.approx(0.82, abs=0.01), (
        "2% of a quantity a node")
    assert F.pair_distance(a, {})["distance"] is None, "nothing both read: no distance, so never met"


def test_a_quantity_one_seed_read_is_not_compared():
    one = side(**RANDOM)
    one["d_B"] = {"mean": 9.0, "se": None, "seeds": 1}
    assert F.pair_distance(side(**RANDOM), one) == {"distance": 0.0, "worst": "d_s"}
    unsaid = side(**RANDOM)
    unsaid["d_B"] = {"mean": 9.0, "se": None}
    assert F.pair_distance(side(**RANDOM), unsaid)["distance"] == 0.0, "a summary that names no seeds counts one"


def test_two_chains_are_apart_past_their_tolerance_and_three_standard_errors_together():
    near, far = side(0.1, **dict(RANDOM, d_s=4.5)), side(0.1, **dict(RANDOM, d_s=4.6))
    past = 0.15 + F.NOISE_SIGMAS * math.hypot(0.1, 0.1)
    assert F.pair_distance(side(0.1, **RANDOM), near)["distance"] == pytest.approx(0.5 / past, abs=0.01)
    assert F.pair_distance(side(0.1, **RANDOM), far)["distance"] == pytest.approx(0.6 / past, abs=0.01)
    assert 0.5 / past < F.MET < 0.6 / past, "met short of the tolerance and three standard errors, apart past them"
    assert 0.5 / max(0.15, F.NOISE_SIGMAS * math.hypot(0.1, 0.1)) > F.MET, "the first reading's larger read it apart"
    assert F.rule()["apart_when"] == "gap > tolerance + noise_sigmas * combined standard error"


def test_the_reach_is_compared_within_five_percent_of_itself_and_energy_not_at_all():
    a = side(**RANDOM)
    assert F.pair_distance(a, side(**dict(RANDOM, reach=5.2)))["distance"] == pytest.approx(0.2 / 0.26, abs=0.01)
    assert F.pair_distance(a, side(**dict(RANDOM, reach=5.4)))["distance"] > F.MET
    assert F.pair_distance(side(**dict(RANDOM, energy_per_node=-1.0)),
                           side(**dict(RANDOM, energy_per_node=-3.0)))["distance"] == 0.0
    assert "energy_per_node" not in F.COMPARED and set(F.COMPARED) == set(S.COMPARED) - {"energy_per_node", "d_w"}


def test_the_walk_dimension_is_not_compared_and_a_count_s_noise_is_at_least_a_poisson_count_s():
    a, b = side(**RANDOM), side(**dict(RANDOM, d_w=3.0))
    assert "d_w" not in F.COMPARED and F.pair_distance(a, b)["distance"] == 0.0
    near = side(**dict(RANDOM, squares_per_node=RANDOM["squares_per_node"] + 0.01))
    noise = F.counting_noise(RANDOM["squares_per_node"], RANDOM["squares_per_node"] + 0.01, 1024, 3, 3)
    assert noise == pytest.approx(math.sqrt((0.05 + 0.06) * 1024 / 3) / 1024)
    tolerance = S._margin("squares_per_node", 0.05, 0.06)
    assert F.pair_distance(a, near, 1024)["distance"] == pytest.approx(0.01 / (tolerance + F.NOISE_SIGMAS * noise), abs=0.01)
    assert F.pair_distance(a, near)["distance"] == pytest.approx(0.01 / tolerance, abs=0.01), "no size, no count's noise"
    assert set(F.COUNTS) == {"triangles_per_node", "squares_per_node"}


def test_the_groups_are_the_fewest_in_which_every_two_chains_met():
    assert F.groups(["a", "b", "c"], {"a|b": 0.4, "b|c": 0.5, "a|c": 1.5}) == [["a", "b"], ["c"]]
    assert F.groups(["a", "b", "c"], {"a|b": 0.9, "b|c": 0.2, "a|c": 1.5}) == [["a"], ["b", "c"]], "the nearer pair"
    assert F.groups(["a", "b", "c"], {"a|b": 0.5, "b|c": 0.5, "a|c": 0.5}) == [["a", "b", "c"]]
    assert F.groups(["a", "b"], {"a|b": None}) == [["a"], ["b"]], "two chains that share no quantity never meet"
    assert F.pair_key("b", "a") == F.pair_key("a", "b") == "a|b"


def test_a_lattice_is_read_against_its_own_start():
    cubic, held = SHAPES[CUBIC], HELD[CUBIC]
    fate = F.lattice_fate(side(**held), CUBIC, N, REFS)
    assert fate["fate"] == "holds" and fate["kept"] == 1.0 and fate["degree_moved"] == 0.0
    start = F.lattice_fate(side(**cubic), CUBIC, N, REFS)
    assert start["fate"] == "unmoved" and start["like_start"]["distance"] == 0.0, "the start itself, which nothing moved"
    assert F.lattice_fate(side(**dict(held, reach=5.0)), CUBIC, N, REFS)["fate"] == "melted", "a random wiring's reach"
    partly = F.lattice_fate(side(**dict(held, reach=5.0 * 2.4 ** 0.65)), CUBIC, N, REFS)
    assert partly["fate"] == "partly" and partly["kept"] == 0.65, "a small world: kept 0.5 to 0.8"
    assert F.lattice_fate(side(**dict(held, reach=5.0 * 2.4 ** 0.8)), CUBIC, N, REFS)["fate"] == "holds"
    stretched = F.lattice_fate(side(**dict(held, reach=5.0 * 2.4 ** 2.5)), CUBIC, N, REFS)
    assert stretched["fate"] == "stretched" and stretched["kept"] == 2.5
    changed = F.lattice_fate(side(**dict(held, mean_degree=8.0)), CUBIC, N, REFS)
    assert changed["fate"] == "changed" and changed["degree_moved"] == pytest.approx(0.333, abs=0.001)
    became = F.lattice_fate(side(**held), TESSERACT, N, REFS)
    assert became["fate"] == "changed" and became["kept"] == pytest.approx(math.log(3) / math.log(2), abs=0.001)
    dust = side(**dict(held, giant_fraction=0.002, reach=None))
    assert F.lattice_fate(dust, CUBIC, N, REFS)["fate"] == "fell_apart"
    dense = dict(side(**dict(held, mean_degree=17.0, reach=None)), ended_at_cap={"seeds": 2, "of": 3})
    assert F.lattice_fate(dense, CUBIC, N, REFS)["fate"] == "dense"
    once = dict(side(**held), ended_at_cap={"seeds": 1, "of": 3})
    assert F.lattice_fate(once, CUBIC, N, REFS)["fate"] == "holds", "one seed of three at the cap is not the chain's"
    assert F.lattice_fate(side(**cubic), CUBIC, 2048, REFS) == {"fate": None,
                                                               "why": "no reference for this start at this size"}
    assert F.lattice_fate(side(**dict(held, reach=None)), CUBIC, N, REFS)["fate"] is None


def test_unmoved_is_every_quantity_its_start_reads():
    start = side(**SHAPES[CUBIC])
    assert F.unmoved(side(**SHAPES[CUBIC]), start)
    assert not F.unmoved(side(**dict(SHAPES[CUBIC], squares_per_node=2.999)), start), "one square fewer in a thousand"
    assert not F.unmoved(side(**dict(SHAPES[CUBIC], kappa=None)), start), "a quantity the start reads, not read"
    assert F.unmoved(side(**dict(SHAPES[CUBIC], d_s=9.9)), start), "the probes' noise is not the graph moving"


def test_every_class_on_a_law_written_by_hand():
    shapes, melted = HELD, MELTED
    cases = {
        "one_space": law(shapes[CUBIC], shapes[CUBIC], shapes[CUBIC], shapes[CUBIC], shapes[CUBIC]),
        "grows": law(shapes[CUBIC], RANDOM, melted[HONEYCOMB], shapes[CUBIC], melted[TESSERACT]),
        "converts": law(at(4.0), RANDOM, melted[HONEYCOMB], shapes[CUBIC], shapes[CUBIC]),
        "selects": law(at(4.0), RANDOM, melted[HONEYCOMB], shapes[CUBIC], melted[TESSERACT]),
        "holds": law(at(4.0), RANDOM, shapes[HONEYCOMB], shapes[CUBIC], shapes[TESSERACT]),
        "forgets": law(RANDOM, RANDOM, RANDOM, RANDOM, RANDOM),
        "remembers": law(at(4.0), at(12.0), melted[HONEYCOMB], melted[CUBIC], melted[TESSERACT]),
    }
    for expected, chains in cases.items():
        reading = read(chains)
        assert reading["class"] == expected, (expected, reading["rungs"][0]["groups"], reading["rungs"][0]["fates"])
        assert reading["class_name"] == dict(F.CLASSES)[expected] and reading["classes_by_n"] == {str(N): expected}
    one = read(cases["one_space"])["rungs"][0]
    assert one["groups"] == [["empty", "random", "honeycomb", "cubic", "tesseract"]]
    assert {name: f["fate"] for name, f in one["fates"].items()} == {"honeycomb": "melted", "cubic": "holds",
                                                                     "tesseract": "changed"}
    assert ["cubic", "tesseract"] in read(cases["converts"])["rungs"][0]["groups"]
    assert ["empty", "cubic"] in read(cases["grows"])["rungs"][0]["groups"]
    forgets = read(cases["forgets"])["rungs"][0]
    assert {f["fate"] for f in forgets["fates"].values()} == {"melted"}, "a random graph keeps no lattice's reach"
    assert len(read(cases["remembers"])["rungs"][0]["groups"]) >= 3
    lone = law(RANDOM, {}, {}, {}, {})
    assert read(lone)["class"] == "not_read" and read(lone)["rungs"][0]["chains"] == ["empty"]
    unmoved = read(law(at(4.0), RANDOM, SHAPES[HONEYCOMB], SHAPES[CUBIC], SHAPES[TESSERACT]))
    assert unmoved["class"] == "remembers" and {f["fate"] for f in unmoved["rungs"][0]["fates"].values()} == {"unmoved"}
    half = {family: dict(values, reach=WIRED[family] * (values["reach"] / WIRED[family]) ** 0.65)
            for family, values in HELD.items()}
    partly = read(law(at(4.0), RANDOM, half[HONEYCOMB], half[CUBIC], half[TESSERACT]))
    assert partly["class"] == "remembers" and {f["fate"] for f in partly["rungs"][0]["fates"].values()} == {"partly"}
    frozen = read(law(SHAPES[CUBIC], RANDOM, melted[HONEYCOMB], SHAPES[CUBIC], melted[TESSERACT]))
    assert frozen["class"] == "remembers" and frozen["rungs"][0]["fates"]["cubic"]["fate"] == "unmoved"


def test_the_chains_are_named_by_the_campaign_s_starts_or_by_the_starts_names():
    reading = read(law(RANDOM, RANDOM, RANDOM, RANDOM, RANDOM))
    assert [(c["name"], c["start"], c["lattice"]) for c in reading["chains"]] == [
        ("empty", None, None), ("random", "random_mean_degree_6.0", None), ("honeycomb", HONEYCOMB, 2),
        ("cubic", CUBIC, 3), ("tesseract", TESSERACT, 4)]
    bare = {"rungs": law(RANDOM, RANDOM, RANDOM, RANDOM, RANDOM)["rungs"], "given_name": "random"}
    assert [c["start"] for c in F.law_reading(bare, references=REFS)["chains"]] == [None, None, HONEYCOMB, CUBIC,
                                                                                  TESSERACT]
    two = F.law_reading({"rungs": [{"n": N, "empty": side(**RANDOM), "given": side(**at(4.0))}]}, references=REFS)
    assert [c["name"] for c in two["chains"]] == ["empty", "given"] and two["class"] == "remembers"


def test_the_reading_starts_at_1024_and_says_how_the_starts_moved_across_the_sizes():
    apart = [at(4.0), RANDOM, MELTED[HONEYCOMB], MELTED[CUBIC], MELTED[TESSERACT]]
    alike = [RANDOM] * 5
    merging = {"rungs": [rung(256, *apart), rung(1024, *apart), rung(N, *alike)],
               "every_chain": law(*alike)["every_chain"]}
    reading = F.law_reading(merging, references=REFS)
    assert [r["n"] for r in reading["rungs"]] == [1024, N], "below 1,024 the probes cannot tell a lattice from bias"
    trend = reading["trend"]
    assert trend["way"] == "merging" and trend["groups"] == [5, 1] and len(trend["joined"]) == 10
    assert trend["parted"] == [] and trend["apart"] == 0
    assert reading["class"] == "forgets" and reading["classes_by_n"]["1024"] == "remembers" and reading["top_n"] == N
    splitting = dict(merging, rungs=[rung(1024, *alike), rung(N, *apart)])
    assert F.law_reading(splitting, references=REFS)["trend"]["way"] == "splitting"
    steady = dict(merging, rungs=[rung(1024, *alike), rung(N, *alike)])
    assert F.law_reading(steady, references=REFS)["trend"]["way"] == "steady"
    shapes = [at(4.0), RANDOM, SHAPES[HONEYCOMB], SHAPES[CUBIC], SHAPES[TESSERACT]]
    wider = [at(4.0), RANDOM, SHAPES[HONEYCOMB], dict(SHAPES[CUBIC], reach=24.0), SHAPES[TESSERACT]]
    drift = F.law_reading(dict(merging, rungs=[rung(1024, *shapes), rung(N, *wider)]), references=REFS)["trend"]
    assert drift["way"] == "steady" and drift["apart"] == 10 and drift["closing"] == []
    def trend(first, last):
        return F.law_reading(dict(merging, rungs=[rung(1024, *first), rung(N, *last)]), references=REFS)["trend"]
    together = [RANDOM, RANDOM, MELTED[HONEYCOMB], SHAPES[CUBIC], SHAPES[CUBIC]]
    lattices_apart = [at(4.0), at(4.0), MELTED[HONEYCOMB], SHAPES[CUBIC], dict(SHAPES[CUBIC], d_s=3.6)]
    both_apart = [at(4.0), RANDOM, MELTED[HONEYCOMB], SHAPES[CUBIC], dict(SHAPES[CUBIC], d_s=3.6)]
    parted = trend(together, lattices_apart)
    assert parted["way"] == "splitting" and parted["parted"] == ["cubic|tesseract"] and parted["joined"] == []
    joined = trend(both_apart, together)
    assert joined["way"] == "merging" and joined["joined"] == ["cubic|tesseract", "empty|random"]
    regrouping = trend(lattices_apart, [at(4.0), RANDOM, MELTED[HONEYCOMB], SHAPES[CUBIC], SHAPES[CUBIC]])
    assert regrouping["way"] == "regrouping"
    assert regrouping["joined"] == ["cubic|tesseract"] and regrouping["parted"] == ["empty|random"]
    closing = trend(both_apart, [at(4.0), RANDOM, MELTED[HONEYCOMB], SHAPES[CUBIC], dict(SHAPES[CUBIC], d_s=3.2)])
    assert closing["way"] == "steady" and closing["closing"] == ["cubic|tesseract"]
    assert F.law_reading(dict(merging, rungs=[rung(N, *alike)]), references=REFS)["trend"] is None
    assert F.law_reading({"rungs": [rung(256, *alike)]}, references=REFS)["class"] == "not_read"


def test_the_lowest_energy_names_its_group_and_whether_it_stands_apart():
    chains = law(*([dict(RANDOM, energy_per_node=-1.0)] * 3), dict(RANDOM, energy_per_node=-1.01),
                 dict(SHAPES[TESSERACT], energy_per_node=-2.0))
    top = read(chains)["rungs"][0]
    assert top["lowest_energy"] == {"group": ["tesseract"], "apart": True}
    level = law(*([dict(RANDOM, energy_per_node=-1.0)] * 4), dict(SHAPES[TESSERACT], energy_per_node=-1.01))
    assert read(level)["rungs"][0]["lowest_energy"] == {"group": ["tesseract"], "apart": False}, "within 2%"
    assert read(law(*([RANDOM] * 5)))["rungs"][0]["lowest_energy"] is None, "no energy read (report 28)"


def test_report_28_keeps_each_law_s_reading_compact():
    reading = read(law(HELD[CUBIC], RANDOM, MELTED[HONEYCOMB], HELD[CUBIC], MELTED[TESSERACT]))
    out = F.compact(reading)
    assert out["class"] == "grows" and out["by_n"][str(N)][0] == "grows" and out["at_n"] == out["top_n"] == N
    assert out["fates"]["cubic"] == ["holds", 1.0] and set(out["fates"]) == {"honeycomb", "cubic", "tesseract"}
    assert "trend" not in out and out["top_dense"] is False and out["references"] is True, "one size has no trend"
    json.dumps(out, allow_nan=False)


def test_a_law_is_read_at_its_largest_size_two_chains_read():
    alike = [RANDOM] * 5
    crossed = {"rungs": [rung(1024, *alike), rung(N, dict(RANDOM, mean_degree=16.5), {}, {}, {}, {})],
               "every_chain": law(*alike)["every_chain"]}
    reading = F.law_reading(crossed, references=REFS)
    assert reading["class"] == "forgets" and reading["at_n"] == 1024 and reading["top_n"] == N
    assert reading["top_dense"] is True and reading["classes_by_n"] == {"1024": "forgets", str(N): "not_read"}
    assert reading["trend"] is None, "one size read by two chains has nothing to move across"
    compact = F.compact(reading)
    assert compact["class"] == "forgets" and compact["at_n"] == 1024 and set(compact["fates"]) == {
        "honeycomb", "cubic", "tesseract"}, "the fates of the size the law is read at"
    never = F.law_reading({"rungs": [rung(N, RANDOM, {}, {}, {}, {})]}, references=REFS)
    assert never["class"] == "not_read" and never["at_n"] is None and never["top_dense"] is False


def test_report_28_reads_the_starts_of_every_law_it_scores():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    from graph_scale_dynamics.reporting import every_chain_report as ECR
    from tests.unit.test_report_28_scores_every_chain import _measurements
    law_id = "a" * 64
    snapshot = {"measurements": _measurements(law_id),
                "candidates": [{"candidate_id": law_id, "spec": {"dynamics": {"zero_temperature": True}}}]}
    section = ECR.every_chain_section(snapshot)
    five = section["laws"][law_id]["starts_reading"]
    assert five["class"] in dict(F.CLASSES) and list(five["by_n"]) == ["1024", "4096", "16384"]
    assert set(five["fates"]) == {"cubic"}, "the cubic chain read against its start, the random start a generic"
    counts = section["starts_reading"]
    assert counts["contract"] == F.CONTRACT and sum(counts["classes"].values()) == section["laws_scored"] == 1
    assert counts["by_temperature"] == {"zero": {five["class"]: 1}} and counts["references"] is True
    unknown = ECR.starts_reading_classes({"x": {"starts_reading": {"class": "forgets"}}, "y": {}}, {"x": {"terms": []}})
    assert unknown["classes"] == {"forgets": 1, "not_read": 1}
    assert unknown["by_temperature"] == {"finite": {"forgets": 1}, "not known": {"not_read": 1}}, (
        "no switch is a finite temperature; no spec is not known")


def test_the_reading_keeps_its_shares_and_the_space_score_s_tolerances():
    assert (F.KEPT_AT_LEAST, F.KEPT_AT_MOST) == (0.5, 2.0)
    assert F.KEPT_AT_LEAST < F.KEPT_HOLDS < 1.0 < F.KEPT_AT_MOST
    assert F.FROM_N == S.FROM_N == 1024 and F.rule()["tolerances"] == S.MARGINS
    assert F.tolerance("d_s", 3.0, 3.1) == S.MARGINS["dimension"] and F.tolerance("reach", 10.0, 9.0) == 0.5


def test_the_table_s_references_are_this_tree_s_and_cover_the_studies_sizes():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    refs = F.table_references()
    assert refs, ("the calibration table holds no current cell of a lattice start with its reading as a start: a "
                  "fleet measures them with its table at its first start")
    assert set(F.LATTICES) <= set(refs)
    for family in F.LATTICES:
        by_n = refs[family]
        assert sorted(by_n) == [1024, 4096, 16384, 65536, 262144, 1048576], family
        for n, ref in by_n.items():
            start = ref["start"]
            assert start["reach"]["seeds"] >= F.MIN_SEEDS and start["reach"]["mean"] > ref["random_reach"] > 0, (
                family, n)
            assert abs(start["mean_degree"]["mean"] - the_starts.of_family(family).neighbours) < 1e-9


def test_a_folder_whose_table_holds_no_current_start_reads_no_lattice_s_fate(monkeypatch, tmp_path):
    from graph_scale_dynamics import calibration
    F.table_references.cache_clear()
    try:
        monkeypatch.setattr(calibration, "durable_artifact_path", lambda root=None: tmp_path / "no_table.json")
        assert F.table_references() == {}
        reading = F.law_reading(law(*([HELD[CUBIC]] * 5)))
        assert reading["references"] is False and reading["class"] != "one_space"
        assert {f["fate"] for f in reading["rungs"][0]["fates"].values()} == {None}
    finally:
        monkeypatch.undo()
        F.table_references.cache_clear()


def _criterion() -> dict:
    return json.loads(CRITERION.read_text(encoding="utf-8"))


def test_the_known_answers_were_read_by_this_reading_against_the_table_s_references():
    run = json.loads((INPUTS / "starts_known_answers_judged.json").read_text(encoding="utf-8"))
    criterion = _criterion()
    assert run["contract"] == C.CHECK_CONTRACT and run["reading_contract"] == F.CONTRACT
    assert run["criterion"]["sha256"] == hashlib.sha256(CRITERION.read_bytes()).hexdigest()
    assert run["written_utc"] > criterion["committed_utc"]
    assert run["references_from"] == "the calibration table's cells of the lattice starts"
    assert run["references_sha256"] == hashlib.sha256(json.dumps(F.table_references(), sort_keys=True)
                                                      .encode("utf-8")).hexdigest()
    assert run["rule"] == F.rule(), "the committed run was read by another rule: run the check again"
    assert run["sizes"] == criterion["sizes"] and run["first_seed"] == 0 and not run["held_out"]
    assert [case["id"] for case in run["cases"]] == [case["id"] for case in criterion["cases"]]
    for case, expected in zip(run["cases"], criterion["cases"], strict=True):
        for n, row in case["sizes"].items():
            rung = {"class": row["class"], "groups": row["groups"],
                    "fates": {name: {"fate": fate[0]} for name, fate in row["fates"].items()}}
            assert C.judge_rung(rung, C.expected_at(expected, int(n))) == row["failures"], (case["id"], n)
        assert case["passed"] == (not any(r["failures"] for r in case["sizes"].values())
                                  and not case["law"]["failures"]), case["id"]
