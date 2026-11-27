from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}
SCIENCE = {"contract": "gsd-science-contract-2", "sha256": "a" * 64, "engine": "0.840.0"}


def _start(repo, **made):
    from graph_scale_dynamics.operations import study_design as SD
    return SD.start(repo, SD.design_for(ROOT, "176"), json.loads(json.dumps(SURVEY)), tree=ROOT,
                    log=lambda *_a: None, **made)


def _law(beta: float) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta)))
    return dsl.fingerprint(spec), spec


def _bundle(root: Path, name: str, laws: list, regions: list, science=SCIENCE, study="174") -> Path:
    folder = root / name
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"study_id": study, "built_utc": "2026-11-25T12:00:00Z",
                                                   "science": science}))
    with gzip.open(folder / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (law, spec, score) in enumerate(laws):
            handle.write(json.dumps({"campaign_id": "3", "candidate_id": law, "candidate_number": i, "spec": spec,
                                     "law_score": {"score": score}}) + "\n")
    (folder / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": regions}))
    return folder


def test_study_176_starts_ten_blind_batches_an_empty_seeded_campaign_and_its_focus(isolated_postgres_schema):
    from graph_scale_dynamics.db.decision_store import let_through_campaigns, study_batches
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.scheduling import work_groups
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _start(repo)
        campaigns = {str(c["campaign_id"]): c["spec"] for c in repo.all_campaigns()}
        kinds = {cid: (spec["study_design"]["kind"], spec["study_design"]["group"]) for cid, spec in campaigns.items()}
        assert sorted(kinds.values()) == sorted([("blind", "A")] * 10 + [("seed", "N")] + [("focus", "N")] * 2
                                                + [("focus", "D")])
        seeded = next(cid for cid, kind in kinds.items() if kind[0] == "seed")
        blind = sorted((cid for cid, kind in kinds.items() if kind[0] == "blind"), key=int)
        assert campaigns[seeded]["search_policy"]["kind"] == "hand"
        assert dict(map(tuple, campaigns[seeded]["engine"]["policy"]["gate_shares"]))["starts_alike"] == 1.0
        assert repo.conn.execute("SELECT COUNT(*) AS n FROM campaign_candidates WHERE campaign_id=?",
                                 (seeded,)).fetchone()["n"] == 0
        assert set(let_through_campaigns(repo.conn)) == set(blind), "the seeded and focus laws stay out of the ledger"
        learning = {cid for cid, _ in study_batches(repo, blind[0], Policy.from_spec(campaigns[blind[0]]))}
        assert learning == set(blind), "and out of the batches a gate learns from"
        state = focus.load(repo)
        assert state["study"] == "176" and state["current"] is None, "the focus waits for the first scoring law"
        assert work_groups.shares(repo) == {"A": 0.5, "N": 0.25, "D": 0.25}
        work_groups.set_shares(repo, {"A": 3, "N": 1})
        _start(repo, made={i: cid for i, cid in enumerate(blind + [seeded])})
        assert len(repo.all_campaigns()) == 14, "a start again makes nothing twice"
        assert work_groups.shares(repo) == {"A": 0.75, "N": 0.25}, "a split the operator set is never reset"
    finally:
        repo.close()


def test_a_bundle_seeds_its_scoring_laws_and_its_regions_a_second_appends_only_what_is_new_and_a_third_is_refused(
        isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus, study_seed
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _start(repo)
        holder, holder_spec = _law(0.188203)
        other, other_spec = _law(0.5)
        quiet, quiet_spec = _law(0.9)
        region = {"number": 3, "name": "GG#3", "kind": "ring", "laws": [holder], "labels": ["C3-G17"],
                  "members": 9, "ranges": {"beta": [0.17, 0.2]}, "alike_to": 0.2, "boundaries": [],
                  "mapped_utc": "2026-11-25T11:00:00Z"}
        first = _bundle(tmp_path, "study_174_a", [(holder, holder_spec, 19), (other, other_spec, 5),
                                                  (quiet, quiet_spec, 0)], [region])
        record = study_seed.seed(repo, first, science=SCIENCE)
        seeded = study_seed.seeded_campaign(repo, "176")
        laws = {row["candidate_id"] for row in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (seeded,)).fetchall()}
        assert laws == {holder, other}, "every law the bundle scores, and none it does not"
        assert record["laws_added"] == 2 and record["regions"] == ["Z3"] and record["scoring"] == 2
        state = focus.load(repo)
        assert [r["name"] for r in state["regions"]] == ["Z3"] and state["regions"][0]["seeded_from"]["bundle"] == (
            "study_174_a")
        assert state["region_of"] == {holder: 3} and state["region_count"] == 3
        done = {d["law"]: d for d in state["done"]}
        assert done[holder]["stage"] == focus.MAPPED and done[holder]["of"] == seeded, (
            "a law mapped where it came from is not mapped again here")
        assert focus.reading(repo)["seeded"][0]["bundle"] == "study_174_a"

        grew = dict(region, ranges={"beta": [0.15, 0.2]})
        newer = dict(region, number=1, name="GG#1", laws=[other], ranges={"beta": [0.45, 0.55]})
        second = _bundle(tmp_path, "study_174_b", [(holder, holder_spec, 19), (other, other_spec, 5)],
                         [grew, newer])
        again = study_seed.seed(repo, second, science=SCIENCE)
        assert again["laws_added"] == 0 and again["regions"] == ["Z1"] and again["regions_grown"] == ["Z3"]
        known = {r["name"]: r for r in focus.load(repo)["regions"]}
        assert sorted(known) == ["Z1", "Z3"] and known["Z3"]["ranges"]["beta"] == [0.15, 0.2], (
            "a newer bundle of the same study widens the region it already gave")
        with pytest.raises(ValueError, match="study_174_b was read already"):
            study_seed.seed(repo, second, science=SCIENCE)
        elsewhere = _bundle(tmp_path, "study_175_a", [(holder, holder_spec, 19)], [region], study="175")
        assert study_seed.seed(repo, elsewhere, science=SCIENCE)["regions"] == ["Z4"], (
            "another study's region keeps its number unless it is taken")
        if shutil.which("zstd"):
            archive = tmp_path / "study_174_c.tar.zst"
            tar = subprocess.run(["tar", "-C", str(tmp_path), "-cf", "-", "study_174_b"], check=True,
                                 capture_output=True).stdout
            subprocess.run(["zstd", "-q", "-o", str(archive)], input=tar, check=True)
            found = study_seed.read(archive)
            assert found["name"] == "study_174_c" and {e["law"] for e in found["scoring"]} == {holder, other}
    finally:
        repo.close()


def test_the_map_page_seeds_and_refuses_what_is_not_a_bundle(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _start(repo)
        with pytest.raises(ValueError, match="nothing at"):
            focus.act(repo, {"do": "seed", "bundle": str(tmp_path / "nothing")})
        (tmp_path / "empty").mkdir()
        with pytest.raises(ValueError, match="holds 0 dexes or study bundles"):
            focus.act(repo, {"do": "seed", "bundle": str(tmp_path / "empty")})
    finally:
        repo.close()


def test_a_bundle_of_another_science_brings_its_laws_alone_each_run_here_from_nothing(isolated_postgres_schema,
                                                                                      tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus, study_seed
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _start(repo)
        holder, holder_spec = _law(0.188203)
        other, other_spec = _law(0.5)
        region = {"number": 3, "name": "GG#3", "kind": "ring", "laws": [holder], "labels": ["C3-G17"], "members": 9,
                  "ranges": {"beta": [0.17, 0.2]}, "alike_to": 0.2, "boundaries": []}
        old = _bundle(tmp_path, "study_170_old", [(holder, holder_spec, 19), (other, other_spec, 5)], [region],
                      science={"contract": "gsd-science-contract-2", "sha256": "b" * 64, "engine": "0.700.0"})
        record = study_seed.seed(repo, old, science=SCIENCE)
        seeded = study_seed.seeded_campaign(repo, "176")
        laws = {row["candidate_id"] for row in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (seeded,)).fetchall()}
        assert laws == {holder, other}, "its laws are in the seeded campaign, run here from nothing"
        assert record["carried"] is False and record["laws_only"] == 2 and record["laws_standing"] == 0
        assert record["regions"] == [] and "engine" in record["science_differ"], "no score and no region carried"
        state = focus.load(repo)
        assert study_seed.standing(state) == {}, "no law stands on a score another science read"
        assert set(study_seed.records(state)[0]["laws_only"]) == {holder, other}
        study_seed.release(repo, "study_170_old")
        assert study_seed.let_go(focus.load(repo)) == {holder, other}, "unticked, its laws are let go like any seed's"
    finally:
        repo.close()
