from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.measurements import starts as the_starts
from graph_scale_dynamics.measurements.calibration import SIZES_A_LAW_RUNS
from graph_scale_dynamics.observability import starts_reading as F
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import study_design as SD
from graph_scale_dynamics.research import dimension_rule as R
from graph_scale_dynamics.scheduling.campaign import validate_campaign
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.scheduling.limits import work_budget
from tests.support import designs

ROOT = Path(__file__).resolve().parents[2]
LAW = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
EIGHT = ["empty", "random", "square", "triangular", "cubic", "bcc", "fcc", "tesseract"]
LATTICES_RUN = {"square": (2, 4), "triangular": (2, 6), "cubic": (3, 6), "bcc": (3, 8), "fcc": (3, 12),
                "tesseract": (4, 8)}
LADDER = [64, 256, 1024, 4096, 16384, 65536]
BUDGETS = {int(n): int(units) for n, units in designs.a_design()["ladder"]["budgets"]}


def _design() -> dict:
    return designs.a_design()


def _spec(index: int = 0) -> dict:
    design = _design()
    return SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][index], index)


def test_a_start_is_defined_once_and_eight_run():
    assert [start.name for start in the_starts.run()] == EIGHT
    assert {start.name: (start.dimension, start.neighbours) for start in the_starts.lattices_run()} == LATTICES_RUN
    known = the_starts.known_lattices()
    assert [start.name for start in known if not start.runs] == ["honeycomb"], (
        "the honeycomb is a family of the calibration table and no start: no term tells it from a random graph")
    assert [(s.dimension, s.neighbours) for s in known] == sorted((s.dimension, s.neighbours) for s in known), (
        "listed by dimension, then by neighbours")
    assert len({start.name for start in the_starts.STARTS}) == len(the_starts.STARTS)
    assert len({start.family for start in known}) == len(known)
    assert the_starts.named("fcc").family == "periodic_face_centred_cubic_lattice"
    assert the_starts.of_family("periodic_tesseract_quotient").name == "tesseract"
    assert the_starts.declared()[0] == {"name": "random", "family": "random_at_drawn_degree"}
    with pytest.raises(ValueError):
        the_starts.named("empty").declared()
    with pytest.raises(ValueError):
        the_starts.named("random").edges(64)


@pytest.mark.parametrize("name", sorted(LATTICES_RUN))
def test_each_lattice_start_is_built_at_every_size_a_law_runs_with_the_neighbours_it_is_defined_with(name):
    start = the_starts.named(name)
    assert all(start.reaches(n) for n in SIZES_A_LAW_RUNS), "a start is built at exactly the size, or it is no start"
    for n in (64, 256, 1024, 4096):
        edges = np.asarray(start.edges(n), dtype=np.int64)
        degree = np.bincount(edges.reshape(-1), minlength=n)
        assert len(degree) == n and set(degree.tolist()) == {start.neighbours}, (name, n)
        assert len({(int(a), int(b)) for a, b in edges}) == len(edges) == start.neighbours * n // 2
        assert bool((edges[:, 0] != edges[:, 1]).all())


def test_every_list_of_lattices_is_the_definition_s():
    known = the_starts.known_lattices()
    assert F.LATTICES == {start.family: (start.name, start.dimension) for start in known}
    assert F.NAMED == {start.name: start.family for start in known}
    assert list(R.LATTICES) == [start.name for start in known] and R.GROWN == {"empty": "empty", "given": "random"}
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import history_reading
    import law_rows
    assert law_rows.LATTICES == history_reading.LATTICES == tuple(start.name for start in known)
    assert law_rows.LATTICE_DEGREE == history_reading.LATTICE_DEGREE == {s.name: s.neighbours for s in known}


def test_the_dimension_rule_has_a_band_and_an_own_dimension_for_every_lattice_start():
    R.calibration.cache_clear()
    cal = R.calibration()
    assert set(cal["lattice_bands"]) == set(cal["lattice_d"]) == {s.name for s in the_starts.known_lattices()}
    assert (cal["lattice_bands"]["honeycomb"], cal["lattice_bands"]["cubic"], cal["lattice_bands"]["tesseract"]) == (
        [1.5, 2.5], [2.5, 3.5], [3.0, 5.0]), "the three the dimension test's criterion names, as committed"
    assert cal["lattice_d"]["cubic"] == {"1024": 2.8897, "4096": 2.8247, "16384": 2.8864}, \
        "and as the final probes measured them (808, dimension_test_criterion_4.json)"
    assert cal["lattice_d"]["tesseract"]["16384"] == 3.6372 and cal["lattice_d"]["honeycomb"]["1024"] == 1.9329
    for name, (dimension, _neighbours) in LATTICES_RUN.items():
        by_dimension = {2: [1.5, 2.5], 3: [2.5, 3.5], 4: [3.0, 5.0]}[dimension]
        assert cal["lattice_bands"][name] == by_dimension, "the band the criterion gives a lattice of its dimension"
    for name in ("square", "triangular", "bcc", "fcc"):
        assert cal["lattice_d"][name] == {"1024": float(LATTICES_RUN[name][0])}, "its dimension, which it reads"
        assert R.own_d(cal, name, 65536) == float(LATTICES_RUN[name][0])


def _judged(d: float) -> dict:
    return {"verdict": "dimensional", "d": d, "sizes": [1024, 4096], "reach_exponent": 0.4}


def test_a_chain_from_any_of_the_eight_starts_is_given_its_kind():
    cal = R.calibration()
    assert R.kind_of("empty", _judged(2.0), cal) == R.kind_of("given", _judged(2.0), cal) == "grown"
    kept = {"square": 2.1, "triangular": 1.9, "cubic": 3.0, "bcc": 2.9, "fcc": 3.2, "tesseract": 4.0}
    assert {name: R.kind_of(name, _judged(d), cal) for name, d in kept.items()} == dict.fromkeys(kept, "kept_d")
    changed = {"square": 3.1, "triangular": 1.2, "bcc": 2.2, "fcc": 4.1}
    assert {name: R.kind_of(name, _judged(d), cal) for name, d in changed.items()} == dict.fromkeys(changed, "changed")
    assert R.kind_of("fcc", {"verdict": "not_dimensional", "d": None, "sizes": []}, cal) is None
    from graph_scale_dynamics.decisions.starts_rule import in_start_order
    shuffled = {name: {} for name in ("tesseract", "fcc", "given", "square", "empty", "cubic", "bcc", "triangular")}
    assert [name for name, _ in in_start_order(shuffled)] == ["empty", "given", "square", "triangular", "cubic", "bcc",
                                                             "fcc", "tesseract"]


def test_the_design_lists_the_eight_starts_and_gives_each_size_its_prior_window():
    design = _design()
    assert design["starts"] == the_starts.declared(), "the design's starts are the definition's, in its order"
    assert [c["kind"] for c in design["campaigns"]] == ["blind"] and design["law_budget"] == 1000
    assert "strata" not in design and design["finds"] is False
    assert design["ladder"]["base"] == LADDER[:4] and design["ladder"]["deep"] == LADDER[4:]
    assert dict(map(tuple, design["ladder"]["budgets"])) == BUDGETS


def test_its_campaign_is_valid_and_runs_eight_chains_to_65536():
    spec = _spec()
    assert validate_campaign(spec) == []
    policy = Policy.from_spec(spec)
    assert policy.every_chain and policy.dimension_extends and policy.dense_cap == 16.0
    assert list(policy.ladder()) == LADDER and spec["budgets"]["max_n"] == LADDER[-1]
    assert [work_budget(spec, n) for n in policy.ladder()] == [BUDGETS[n] for n in LADDER]
    assert spec["sampling_contract"]["given_starts"] == the_starts.declared()
    assert spec["sampling_contract"]["hold_structure"] is True
    assert spec["search_policy"]["grid"]["local_moves"] == ["toggle"], "no driven law is drawn"
    assert "strata" not in json.dumps(spec["search_policy"]["grid"])
    for n in policy.ladder():
        made = one_shot_policy(spec, n, "5" * 64, LAW)
        assert [made["given_start"]["name"]] + [start["name"] for start in made["more_given"]] == EIGHT[1:]
        assert made["work_budget"] == work_budget(spec, n)


def test_a_seed_s_chains_are_grown_by_one_call_with_no_deadline():
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    spec = _spec()
    policy = one_shot_policy(spec, 64, "5" * 64, LAW)
    seen = []

    def simulate(law, n, seed, **asked):
        seen.append(asked)
        chains = [asked["given_start"]] + list(asked["more_given"])
        assert len(chains) == 7 and all(chain.get("edges") is not None for chain in chains)
        raise _Seen

    class _Seen(Exception):
        pass

    with pytest.raises(_Seen):
        run_one_shot(LAW, 64, 0, one_shot=policy, simulate=simulate, clock=lambda: 1000.0)
    assert len(seen) == 1, "one call grows every chain of the seed"
    assert not any("deadline" in key or "window" in key for key in seen[0]), (
        "and no clock reaches the engine: the chains run one after another to the chunk's end")


def test_a_law_s_eight_chains_run_and_are_read_and_decided_chain_by_chain():
    from tests.support.engines import require_rust_engine
    require_rust_engine()
    from graph_scale_dynamics.artifact_store.chain_record import build_record
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.decisions.decider import _rungs
    from graph_scale_dynamics.decisions.every_chain import EMPTY, decide_every_chain
    from graph_scale_dynamics.decisions.evidence import _b143_rung_sampling_state, _rung_cell
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scaleflow import engine_door
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    spec = _spec()
    law_id = fingerprint(LAW)
    policy = dict(one_shot_policy(spec, 64, law_id, LAW), max_sweeps_multiplier=2)
    rows, records = [], {}
    for seed in range(3):
        envelope = run_one_shot(LAW, 64, seed, one_shot=policy, record_points=40,
                                simulate=engine_door.simulate_of("rust"))
        metrics, _ = analyze_one_shot_envelope(envelope, seed=seed)
        assert set(metrics["census"]) == {"empty", "given", *EIGHT[2:]}
        records[seed] = build_record(envelope)
        assert [chain["start"] for chain in records[seed]["chains"]] == ["empty", "given", *EIGHT[2:]]
        rows.append({"n": 64, "seed": seed, "metrics": metrics})
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from outputs_of_a_law import plain
    by_python = run_one_shot(LAW, 64, 0, one_shot=policy, record_points=40, simulate=engine_door.run_simulation)
    assert plain(build_record(by_python)) == plain(records[0]), (
        "the Python engine grows the same eight chains to the same record, the clock's readings left out")

    class Repo:
        def measurements(self, law, version, campaign_id):
            return rows

    class Seeds:
        def seed_rows(self, campaign_id, law):
            return {}

    store = DecisionStore(Repo(), None, {"campaign_id": "1", "spec": spec})
    summary = rung_summary([r["metrics"] for r in rows])
    states = {64: _b143_rung_sampling_state(spec, 64, summary, [r["metrics"] for r in rows])}
    chains = store.law_chains("1", law_id, states, [64])["chains"]
    assert list(chains) == EIGHT[1:]
    assert all(cells[64]["measurement_seed_count"] == 3 for cells in chains.values())
    rungs = {EMPTY: _rungs(Seeds(), "1", law_id, {64: _rung_cell(spec, 64, summary, states[64])})}
    rungs.update({name: _rungs(Seeds(), "1", law_id, cells) for name, cells in chains.items()})
    decision = decide_every_chain(law_id, rungs, Policy.from_spec(spec))
    assert set(decision.facts["chains"]) == set(EIGHT)
    assert decision.action == "run_next" and decision.next_n == 256, "the base block goes on for every law"


def _law_on_its_starts(refs: dict, sizes: list[int]) -> tuple[dict, list]:
    cubic = refs["periodic_cubic_quotient"]
    rungs = [{"n": n, "empty": cubic[n]["start"], "given": cubic[n]["start"],
              "more_given": {s.name: refs[s.family][n]["start"] for s in the_starts.lattices_run()}} for n in sizes]
    return {"given_name": "random", "rungs": rungs}, the_starts.declared()


def test_all_six_lattice_chains_are_read_against_the_table_s_references():
    from tests.support.calibration_table import skip_if_references_owed
    skip_if_references_owed()
    refs = F.table_references()
    sizes = [1024, 4096, 16384, 65536]
    assert all(n in refs[start.family] for start in the_starts.lattices_run() for n in sizes)
    chains, declared = _law_on_its_starts(refs, sizes)
    reading = F.law_reading(chains, declared, structure=True)
    assert [chain["name"] for chain in reading["chains"]] == EIGHT
    assert [chain["lattice"] for chain in reading["chains"]] == [None, None, 2, 2, 3, 3, 3, 4]
    assert reading["references"] is True and "unreferenced" not in reading
    for rung in reading["rungs"]:
        assert rung["chains"] == EIGHT and rung["unreferenced"] == []
        assert {name: fate["fate"] for name, fate in rung["fates"].items()} == dict.fromkeys(LATTICES_RUN, "unmoved")
        assert ["empty", "random", "cubic"] in rung["groups"], "the chains given the cubic start's values group with it"
    assert reading["at_n"] == 65536 and set(reading["classes_by_n"]) == {str(n) for n in sizes}


def _groups_by_every_partition(names: list, distances: dict) -> list:
    def partitions(items):
        if not items:
            yield []
            return
        first, rest = items[0], items[1:]
        for smaller in partitions(rest):
            for index in range(len(smaller)):
                yield smaller[:index] + [[first] + smaller[index]] + smaller[index + 1:]
            yield [[first]] + smaller

    order = {name: i for i, name in enumerate(names)}
    best, best_key = None, None
    for partition in partitions(list(names)):
        pairs = [distances.get(F.pair_key(a, b)) for group in partition for i, a in enumerate(group)
                 for b in group[i + 1:]]
        if any(d is None or d > F.MET for d in pairs):
            continue
        total = 0.0
        for d in pairs:
            total += d
        ordered = sorted((sorted(g, key=order.get) for g in partition), key=lambda g: order[g[0]])
        key = (len(ordered), round(total, 9), [[order[n] for n in g] for g in ordered])
        if best_key is None or key < best_key:
            best, best_key = ordered, key
    return best or [[name] for name in names]


def test_eight_chains_are_grouped_as_every_partition_would_group_them_without_walking_them_all(monkeypatch):
    rng = random.Random(769)
    for trial in range(1500):
        count = rng.randint(0, 8)
        chosen = EIGHT[:count] if trial % 2 else rng.sample(EIGHT, count)
        draw = (lambda: rng.choice([0.0, 0.5, 1.0, 1.0, 2.0, None]), lambda: rng.uniform(0.0, 1.2),
                lambda: rng.choice([0.25, 0.25, 0.25, 3.0]), lambda: round(rng.uniform(0.0, 2.0), 1),
                lambda: rng.uniform(0.0, 0.99))[trial % 5]
        distances = {F.pair_key(a, b): draw() for a, b in itertools.combinations(chosen, 2)}
        assert F.groups(chosen, distances) == _groups_by_every_partition(chosen, distances), (chosen, distances)
    alike = {F.pair_key(a, b): 0.3 for a, b in itertools.combinations(EIGHT, 2)}
    one_apart = dict(alike, **{F.pair_key("fcc", other): 3.0 for other in EIGHT if other != "fcc"})
    walked = []
    every = F._partitions_that_meet

    def counted(*args, **kwargs):
        for partition in every(*args, **kwargs):
            walked.append(partition)
            yield partition
    monkeypatch.setattr(F, "_partitions_that_meet", counted)
    assert F.groups(EIGHT, alike) == [EIGHT] and walked == [], "eight chains alike are one group at once"
    assert F.groups(EIGHT, one_apart) == [[name for name in EIGHT if name != "fcc"], ["fcc"]]
    assert 0 < len(walked) < 100, f"{len(walked)} of the 4,140 partitions of eight chains walked for one size"


def test_the_page_draws_a_law_s_eight_chains_as_the_fleet_wrote_them(tmp_path):
    import gzip
    import os
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    written = ROOT / "tests" / "fixtures" / "law_page_of_eight_chains.json.gz"
    payload = json.loads(gzip.decompress(written.read_bytes()).decode("utf-8"))
    five = payload["starts_reading"]
    assert [chain["name"] for chain in five["chains"]] == EIGHT and five["references"] is True
    assert [rung["n"] for rung in five["rungs"]] == [1024, 4096], "the sparse anchor law on the eight starts, grown here on build 823"
    assert all(set(rung["fates"]) == set(LATTICES_RUN) and rung["unreferenced"] == [] for rung in five["rungs"])
    assert [chain["name"] for chain in payload["chains"]["every_chain"]] == EIGHT
    path = tmp_path / "chains.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run([node, str(ROOT / "tests/ui/candidate_smoke.js"),
                             str(ROOT / "graph_scale_dynamics/resources/ui")], capture_output=True, text=True,
                            timeout=180, env={**os.environ, "GSD_TWO_CHAINS_PAYLOAD": str(path),
                                              "GSD_CHAINS_EXPECTED": ",".join(EIGHT)})
    assert result.returncode == 0 and "two chains drawn from the reader's payload" in result.stdout, (
        result.stdout[-1500:] + result.stderr[-1500:])
