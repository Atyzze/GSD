from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

pytestmark = [pytest.mark.usefixtures("isolated_postgres_schema"),
              pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")]

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}


def _science():
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _law(beta: float) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta)))
    return dsl.fingerprint(spec), spec


def _bundle(root: Path, laws) -> Path:
    folder = root / "study_176_2026-11-26T10-38-46Z"
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"study_id": "176", "built_utc": "2026-11-26T10:38:46Z",
                                                   "build_number": 880, "science": _science()}))
    with gzip.open(folder / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (law, spec, score) in enumerate(laws):
            handle.write(json.dumps({"campaign_id": "11", "candidate_id": law, "code": f"S176C11G{i + 1}",
                                     "spec": spec, "law_score": {"score": score}}) + "\n")
    (folder / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": []}))
    return folder


def _held(repo, campaign_id) -> set[str]:
    return {r["candidate_id"] for r in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (str(campaign_id),)).fetchall()}


def test_a_dex_in_the_import_folder_seeds_the_study_and_its_own_dex_carries_it_on(isolated_postgres_schema,
                                                                                  tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import focus, study_seed
    from graph_scale_dynamics.operations import study_design as SD
    init_db(isolated_postgres_schema.dsn)
    best, best_spec = _law(0.188203)
    next_one, next_spec = _law(0.3)
    made = D.merge([D.read_part(_bundle(tmp_path, [(best, best_spec, 38), (next_one, next_spec, 19)]))],
                   science=_science(), made_by={"study": "176"})
    root = tmp_path / "177" / "main"
    dropped = D.write(made, root / "import", "176")
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        found = D.absorb(repo, root / "import")
        assert [f["bundle"] for f in found] == [D.name_of(dropped)] and found[0]["laws_standing"] == 2
        assert D.absorb(repo, root / "import") == [], "a dex is read in once"
        seeded = study_seed.seeded_campaign(repo, "177")
        assert _held(repo, seeded) == {best, next_one}
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert state["current"]["law"] == best and state["current"]["chosen_by"] == focus.BY_BUNDLE, (
            "the focus takes the dex's best law at its first step, on its score in the dex")
        assert state["depth_now"]["law"] == best
        assert "(score 38 in dex_176_" in focus.reading(repo)["doing"]

        written = D.write_folder(repo, root, blobs=None, build=882)
        assert written.parent == root / D.FOLDER and written.name.startswith("dex_177_")
        again = D.read_part(written)
        assert set(again["laws"]) == {best, next_one}, "the study's own dex carries every law it was seeded with"
        assert D.standing(again["laws"][best], _science()["sha256"]) == 38
        assert D.name_of(dropped) in {s["name"] for s in again["sources"]}
        assert D.keep(repo, root, blobs=None) is None, "written once an hour"
        assert D.written(repo)["counts"]["laws"] == 2
        from graph_scale_dynamics.services.api import focus_route
        monkeypatch.setattr(focus_route, "import_folder", lambda: root / "import")
        monkeypatch.setattr(focus_route, "blobs_of", lambda found: None)
        pressed = focus_route.act(repo, {"do": "dex"})
        assert pressed["ok"] and Path(pressed["dex"]).parent == root / D.FOLDER
        assert focus_route.answer(repo)["dex"]["folder"] == str(root / D.FOLDER)


def test_no_outlier_before_a_law_scores_and_an_early_one_yields_to_a_scoring_law(isolated_postgres_schema,
                                                                                 monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import outliers as OUT
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        blind = sorted(focus.own_campaigns(repo, "177"), key=int)
        flicker = study_map._insert(repo, blind[3], H12)
        outlier = {"candidate_id": flicker, "campaign": blind[3], "outlier": {"probe": "d_V", "n": 1024, "value": 3.5,
                                                                             "seeds_over": [0, 1, 2], "seeds": 3}}
        monkeypatch.setattr(OUT, "next_outlier", lambda *a, **k: dict(outlier, score=0, graph=10))
        scored: list[dict] = []
        monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
        focus.step(repo, force=True)
        assert focus.load(repo)["current"] is None, "no outlier while no law of the study scores"

        state = focus.load(repo)
        focus.start_next(repo, state, chosen={"candidate_id": flicker, "campaign": blind[3], "score": 0})
        focus.depth_next(repo, state, [])
        focus.save(repo, state)
        old_depth = state["campaigns"][focus.DEPTH]
        assert state["depth_now"]["law"] == flicker, "as 881 took it: score 0, no word of why"

        real = study_map._insert(repo, blind[1], dict(H12, dynamics=dict(H12["dynamics"], beta=0.3)))
        scored.append({"candidate_id": real, "campaign": blind[1], "score": 1, "graph": 2, "label": "S177C2G2"})
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert flicker in state["set_aside"] and state["current"]["law"] == real
        assert state["current"]["chosen_by"] == focus.BY_SCORE
        assert state["campaigns"][focus.DEPTH] != old_depth, "the depth worker leaves the law set aside"
        from graph_scale_dynamics.operations import campaign_control as control
        assert control.is_paused(repo, old_depth)
        assert _held(repo, state["campaigns"][focus.DEPTH]) == {real} and state["depth_now"]["law"] == real
        assert focus.load(repo)["depth_done"][flicker]["left"] == "no longer a contender"


def test_the_dex_reads_the_chains_of_its_own_laws_alone(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.reporting import study_tables as T
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        blind = sorted(focus.own_campaigns(repo, "177"), key=int)
        kept = study_map._insert(repo, blind[0], H12)
        other = study_map._insert(repo, blind[0], dict(H12, dynamics=dict(H12["dynamics"], beta=0.4)))
        for law in (kept, other):
            repo.insert_job(job_id=f"job-{law[:8]}", campaign_id=blind[0], candidate_id=law, kind="simulate",
                            stage="base", n=64, seed=0, spec={})
        repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=?", (blind[0],))
        store = BlobStore(tmp_path / "blobs")
        rows = list(T.chain_rows(repo, [blind[0]], store, laws={kept}))
        assert [r["candidate_id"] for r in rows] == [kept] and rows[0]["evidence"].startswith("no compact evidence")
        assert list(T.chain_rows(repo, [blind[0]], store, laws=set())) == []
        assert {r["candidate_id"] for r in T.chain_rows(repo, [blind[0]], store)} == {kept, other}


def test_a_law_in_several_campaigns_opens_in_the_one_it_was_drawn_or_seeded_in(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_seed
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        made = focus.load(repo)["campaigns"]
        blind = sorted(focus.own_campaigns(repo, "177"), key=int)
        seeded = study_seed.seeded_campaign(repo, "177")
        assert focus.home_campaign(repo, [made[focus.DEPTH], made[focus.SEEDS], blind[3]]) == blind[3]
        assert focus.home_campaign(repo, [made[focus.DEPTH], seeded, made[focus.NEIGHBOURS]]) == seeded
        assert focus.home_campaign(repo, [made[focus.DEPTH], made[focus.NEIGHBOURS]]) == made[focus.NEIGHBOURS]
        assert focus.home_campaign(repo, []) is None


def test_a_law_skipped_on_881_but_left_to_the_depth_worker_is_dropped_for_the_law_in_focus(isolated_postgres_schema,
                                                                                           monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        blind = sorted(focus.own_campaigns(repo, "177"), key=int)
        flicker = study_map._insert(repo, blind[3], H12)
        state = focus.begin(repo, "177", law=flicker[:12], tree=ROOT)
        old_depth = state["campaigns"][focus.DEPTH]
        assert state["depth_now"]["law"] == flicker
        focus.skip(repo, flicker[:12])
        assert flicker in focus.load(repo)["contenders"], "as 881 left it: skipped, still the depth worker's law"
        seeded = study_map._insert(repo, blind[1], dict(H12, dynamics=dict(H12["dynamics"], beta=0.3)))
        scored = [{"candidate_id": seeded, "campaign": blind[1], "score": 27, "graph": 37, "label": "S177-C2-G37"}]
        monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert flicker not in state["contenders"] and state["current"]["law"] == seeded
        assert state["campaigns"][focus.DEPTH] != old_depth and state["depth_now"]["law"] == seeded
        assert any(e.get("depth_dropped") == flicker[:12] for e in state["events"])
        needs = {n["what"]: n for n in focus.reading(repo)["current"]["needs"]}
        assert set(needs) == {"its kind", "ring 0.1", "its depth", "its seeds", "every ring", "each term switched off"}
        assert not needs["its kind"]["done"] and "not read at N=16,384" in needs["its kind"]["said"]
