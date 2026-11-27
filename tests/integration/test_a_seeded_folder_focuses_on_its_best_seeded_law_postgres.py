from __future__ import annotations

import gzip
import json
import shutil
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


def _start(repo):
    from graph_scale_dynamics.operations import study_design as SD
    return SD.start(repo, SD.design_for(ROOT, "176"), json.loads(json.dumps(SURVEY)), tree=ROOT,
                    log=lambda *_a: None)


def _law(beta: float) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta)))
    return dsl.fingerprint(spec), spec


def _bundle(root: Path, name: str, laws: list, regions: list, study="174") -> Path:
    folder = root / name
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"study_id": study, "built_utc": "2026-11-25T13:04:19Z",
                                                   "science": SCIENCE}))
    with gzip.open(folder / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (law, spec, score, code) in enumerate(laws):
            row = {"campaign_id": "2", "candidate_id": law, "candidate_number": i, "spec": spec,
                   "law_score": {"score": score}}
            if code:
                row.update(code=code, graph=int(code.rsplit("G", 1)[1]))
            handle.write(json.dumps(row) + "\n")
    (folder / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": regions}))
    return folder


def _three(tmp_path):
    best, best_spec = _law(0.188203)
    next_, next_spec = _law(0.5)
    low, low_spec = _law(0.9)
    region = {"number": 3, "name": "GG#3", "kind": "ring", "laws": [next_], "labels": ["C2-G17"],
              "members": 9, "ranges": {"beta": [0.45, 0.55]}, "alike_to": 0.2, "boundaries": [],
              "mapped_utc": "2026-11-25T11:00:00Z"}
    folder = tmp_path / "import"
    folder.mkdir()
    bundle = _bundle(folder, "study_174_2026-11-25T13-04-19Z",
                     [(best, best_spec, 38, "S174C2G3187"), (next_, next_spec, 19, None), (low, low_spec, 0, None)],
                     [region])
    return folder, bundle, best, next_, low


def _open(dsn):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(dsn)
    repo = Repo(dsn)
    _start(repo)
    return repo


def test_a_folder_seeded_from_a_bundle_focuses_on_its_best_seeded_law_at_its_next_step(isolated_postgres_schema,
                                                                                         tmp_path):
    from graph_scale_dynamics.operations import focus, study_seed
    repo = _open(isolated_postgres_schema.dsn)
    try:
        _folder, bundle, best, next_, low = _three(tmp_path)
        record = study_seed.seed(repo, bundle, science=SCIENCE)
        assert record["laws_standing"] == 2 and record["laws_added"] == 2
        assert focus.best(repo, "176") and focus.load(repo)["current"] is None, "nothing scores in this folder yet"
        focus.step(repo, force=True)
        state = focus.load(repo)
        current = state["current"]
        assert current["law"] == best, "the bundle's best law, 38 in study 174, is in focus at once"
        assert current["standing"] == "bundle" and current["origin"]["code"] == "S174-C2-G3187"
        assert current["origin"]["score"] == 38 and current["kind"] is None
        assert current["label"] == f"S176-C{current['of']}-{best[:8]}", "its code here: the study, its campaign"
        assert best in state["contenders"], "and the depth seeker takes it at once"
        reading = focus.reading(repo)
        assert "on its bundle's score (38 in study 174's bundle) until this folder reads it at N=16,384" in reading[
            "doing"]
        assert "its neighbours wait for its own kind at N=16,384" in reading["doing"]
        ranked = {e["candidate_id"]: e for e in focus.best(repo, "176")}
        assert set(ranked) == {best, next_} and low not in ranked, "only what the bundle scores"
        assert ranked[next_]["origin"]["code"] == "S174-C2-" + next_[:8], "an older bundle names it by its id"
        focus.advance(repo, state)
        assert state["current"]["stage"] == focus.NEIGHBOURHOOD, "its neighbours are not judged before its own kind"
    finally:
        repo.close()


def test_a_bundle_read_already_is_refused_with_its_reason_and_one_that_adds_nothing_too(isolated_postgres_schema,
                                                                                         tmp_path):
    from graph_scale_dynamics.operations import focus, imports, study_seed
    repo = _open(isolated_postgres_schema.dsn)
    try:
        folder, bundle, best, next_, low = _three(tmp_path)
        study_seed.seed(repo, bundle, science=SCIENCE)
        with pytest.raises(ValueError, match="was read already"):
            study_seed.seed(repo, bundle, science=SCIENCE)
        copy = folder / "study_174_copy"
        shutil.copytree(bundle, copy)
        with pytest.raises(ValueError, match="identical to study_174_2026-11-25T13-04-19Z"):
            study_seed.seed(repo, copy, science=SCIENCE)
        shutil.rmtree(copy)
        best_spec = study_seed.read(bundle)["specs"][best]
        same = _bundle(tmp_path, "study_174_later", [(best, best_spec, 40, "S174C2G3187")], [])
        with pytest.raises(ValueError, match="adds nothing: its 1 scoring laws are in this study's map already"):
            study_seed.seed(repo, same, science=SCIENCE)
        rows = {r["bundle"]: r for r in focus.reading(repo)["seeded"]}
        assert list(rows) == ["study_174_2026-11-25T13-04-19Z"], "one row a bundle"
        listed = imports.listing(folder, seeded=focus.load(repo)["seeded"], ours=SCIENCE)["bundles"]
        assert [(b["bundle"], b["seeded"]["selected"]) for b in listed] == [("study_174_2026-11-25T13-04-19Z", True)]
        done = imports.synchronize(repo, folder, ["study_174_2026-11-25T13-04-19Z"])
        assert done["kept"] == ["study_174_2026-11-25T13-04-19Z"] and not done["read_in"] and not done["refused"]
    finally:
        repo.close()


def test_a_bundle_unticked_and_synchronized_leaves_the_focus_and_the_map_its_readings_kept(isolated_postgres_schema,
                                                                                            tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import focus, imports, study_seed
    monkeypatch.setattr(study_seed, "_science_of_this_folder", lambda: SCIENCE)
    repo = _open(isolated_postgres_schema.dsn)
    try:
        folder, bundle, best, next_, low = _three(tmp_path)
        name = "study_174_2026-11-25T13-04-19Z"
        assert imports.synchronize(repo, folder, [name])["read_in"][0]["bundle"] == name
        focus.step(repo, force=True)
        state = focus.load(repo)
        seeded = study_seed.campaign_of(state)
        assert state["current"]["law"] == best and [r["name"] for r in state["regions"]] == ["Z3"]
        done = imports.synchronize(repo, folder, [])
        assert done["let_go"][0]["bundle"] == name and done["let_go"][0]["regions_off"] == ["Z3"]
        state = focus.load(repo)
        assert state["regions"] == [] and next_ not in (state.get("region_of") or {}), "its regions off the map"
        assert state["current"] is None and best not in state["contenders"], "no longer focused on or taken deeper"
        assert focus.best(repo, "176") == [], "its laws leave the focus's lists"
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert not (state.get("lists") or {}).get("focus") and not (state.get("lists") or {}).get("depth")
        held = {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (seeded,)).fetchall()}
        assert {best, next_} <= held, "the readings already taken are kept: its laws stay in the seeded campaign"
        row = next(b for b in focus.reading(repo)["seeded"] if b["bundle"] == name)
        assert row["selected"] is False and row["let_go_utc"]
        back = imports.synchronize(repo, folder, [name])
        assert back["read_in"][0]["regions_back"] == ["Z3"]
        state = focus.load(repo)
        assert [r["name"] for r in state["regions"]] == ["Z3"] and best in {
            e["candidate_id"] for e in focus.best(repo, "176")}, "ticked again, it is in the map again"
    finally:
        repo.close()


def test_a_law_s_code_reads_the_same_in_the_focus_on_its_page_and_in_the_bundle(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.operations import focus, law_code, study_seed
    from graph_scale_dynamics.reporting import study_tables
    from graph_scale_dynamics.services.api import campaign_manager, readings_route
    repo = _open(isolated_postgres_schema.dsn)
    try:
        _folder, bundle, best, other, _low = _three(tmp_path)
        study_seed.seed(repo, bundle, science=SCIENCE)
        seeded = study_seed.campaign_of(focus.load(repo))
        for i in range(3):
            repo.insert_job(job_id=f"other-{i}", campaign_id=seeded, candidate_id=other, kind="simulate",
                            stage="base", n=64, seed=i, spec={})
        repo.insert_job(job_id="best-0", campaign_id=seeded, candidate_id=best, kind="simulate", stage="base", n=64,
                        seed=0, spec={})
        want = f"S176-C{seeded}-G4"
        assert law_code.of(repo, seeded, best) == want
        assert focus.label(repo, seeded, best) == want
        assert next(e for e in focus.best(repo, "176") if e["candidate_id"] == best)["label"] == want
        rows = {r["candidate_id"]: r for r in study_tables.law_rows(repo, [seeded], {})}
        assert (rows[best]["code"], rows[best]["graph"]) == (want, 4), "the bundle carries the same code"
        page = readings_route._named(repo, focus.load(repo), seeded, best)
        assert page["code"] == want and page["origin"]["code"] == "S174-C2-G3187" and page["origin"]["standing"] == (
            "bundle")
        listed = {r["campaign_id"]: r for r in campaign_manager.campaign_list(repo)}
        assert listed[seeded]["study"] == "176", "the dashboard reads each campaign's study to name its laws"
        assert law_code.parse(want) == {"study": "176", "campaign": seeded, "graph": 4, "law": None}
        assert law_code.same(want, f"C{seeded}-G4") and not law_code.same(want, f"S174C{seeded}G4")
    finally:
        repo.close()
