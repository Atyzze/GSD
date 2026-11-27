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
UP, DOWN = 0.57, 0.33


def _science():
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _law(beta: float) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta)))
    return dsl.fingerprint(spec), spec


def _dex(work: Path, folder: Path, laws) -> Path:
    from graph_scale_dynamics.operations import dex as D
    bundle = work / "study_177_2026-11-26T19-33-48Z"
    (bundle / "tables").mkdir(parents=True)
    (bundle / "study.json").write_text(json.dumps({"study_id": "177", "built_utc": "2026-11-26T19:33:48Z",
                                                   "build_number": 885, "science": _science()}))
    with gzip.open(bundle / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (code, law, spec) in enumerate(laws):
            handle.write(json.dumps({"campaign_id": "12", "candidate_id": law, "code": code, "spec": spec,
                                     "law_score": {"score": 1}, "graph": i + 1}) + "\n")
    (bundle / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": []}))
    part = D.read_part(bundle)
    part["chains"] = [{"law": law, "n": 64, "seed": 0, "replicate": 0, "chain": 0, "init": "empty", "moves": 64000,
                       "ran": True, "accepted_moves": 9, "final_edges": 9, "peak_edges": 9, "max_degree": 3,
                       "work_units": 9, "termination": "certified", "science": _science()["sha256"],
                       "source": part["name"], "study": "177"} for _c, law, _s in laws]
    return D.write(D.merge([part], science=_science(), made_by={"study": "177", "build": 885}), folder, "177")


def test_the_first_zone_is_searched_by_stepping_and_halving_each_parameter_and_its_central_law_pushed(
        isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import dex_check, focus, push, study, study_seed, zone_search
    from graph_scale_dynamics.research import perturb as P
    from graph_scale_dynamics.scheduling import work_groups
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    laws = [("S176-C12-G1", *_law(0.188203)), ("S176-C12-G2", *_law(0.19)), ("S176-C12-G3", *_law(0.192))]
    dropped = _dex(tmp_path / "work", study.make_import_folder(var), laws)
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=lambda *_a: None)
        recorded = D.read_part(dropped)["chains"]
        monkeypatch.setattr(dex_check, "decided", lambda *_a: True)
        monkeypatch.setattr(dex_check, "chains_here", lambda repo, campaign_id, blobs, wanted, **_k: [
            dict(row, source="study 178's folder") for row in recorded if row["law"] in wanted])
        assert dex_check.keep(repo, var.parent, blobs=None, force=True)["chosen"] == "S176-C12-G2"
        centre = {}

        def kind(campaign, law, n):
            spec = (repo.candidate(law, campaign) or {}).get("spec") or {}
            if not centre or len(spec.get("terms") or []) != len(centre["spec"]["terms"]):
                return {"kind": "moved", "curves": {}}
            for path in P.parameters(centre["spec"]):
                was, now = P.value_of(centre["spec"], path), P.value_of(spec, path)
                change = (now - was) / was
                if not -DOWN < change < UP:
                    return {"kind": "moved", "curves": {}}
            return {"kind": "made", "curves": {}}

        from graph_scale_dynamics.observability import likeness
        held = repo.conn.execute("SELECT campaign_id, candidate_id FROM campaign_candidates LIMIT 1").fetchone()
        assert zone_search.reading(repo, held["campaign_id"], held["candidate_id"], 4096) is None, "unread: no reading"
        assert likeness.rows_of(repo, held["campaign_id"], held["candidate_id"]) == []
        version = repo.campaign_analysis_contract(str(held["campaign_id"]))
        for n in (256, 1024, 4096, 16384):
            repo.conn.execute("INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,"
                              "created_utc) VALUES(?,?,?,?,?,?)",
                              (held["campaign_id"], held["candidate_id"], n, version,
                               json.dumps({"mean_degree": {"mean": 4.0}, "d_s": {"mean": 1.5 * (n / 256) ** 0.25},
                                           "seeds": 3}), "2026-11-27T02:00:00Z"))
        rows = likeness.rows_of(repo, held["campaign_id"], held["candidate_id"])
        assert [row["n"] for row in rows] == [256, 1024, 4096, 16384]
        found = likeness.curves(rows, 4096)
        assert found["mean_degree"]["form"] == "constant" and found["d_s"]["form"] == "power"
        assert found["d_s"]["b"] == pytest.approx(0.25) and found["d_s"]["to_n"] == 4096
        repo.conn.execute("DELETE FROM rung_summaries WHERE campaign_id=? AND candidate_id=?",
                          (held["campaign_id"], held["candidate_id"]))
        monkeypatch.setattr(zone_search, "reading", lambda repo, campaign, law, n: kind(campaign, law, n))
        focus.step(repo, force=True)
        state = focus.load(repo)
        current = state["current"]
        assert current["chosen_by"] == focus.BY_ZONE and current["points"] == {} and "search" in current, (
            "the rule's zone is searched, no ring drawn")
        centre["spec"] = focus._spec_of(repo, current["of"], current["law"])
        for _ in range(40):
            focus.step(repo, force=True)
            state = focus.load(repo)
            if state.get("current") is None or state["current"].get("stage") in focus.ENDED:
                focus.step(repo, force=True)
                state = focus.load(repo)
                break
        done = state["done"][-1]
        assert done["stage"] == focus.MAPPED, done.get("why")
        search = done["search"]
        lines = search["lines"]
        assert (lines["beta +"]["lo"], lines["beta +"]["hi"]) == (0.55, 0.6), (
            "stepped out 10%, 20%, 40%, 80% and halved three times: the edge within an eighth of the step")
        assert (lines["beta -"]["lo"], lines["beta -"]["hi"]) == (0.325, 0.35)
        assert (lines["term 1 c0 +"]["lo"], lines["term 1 c0 -"]["hi"]) == (0.55, 0.35)
        assert lines["swap +"]["hi"] is None and "a share cannot leave 0 to 1" in lines["swap +"]["why"]
        assert all(edge["held"] for edge in search["edges"].values()), "every edge held at 16,384"
        assert search["stands"] == {"alike": 2, "of": 2, "share": state["plan"]["neighbourhood"]["confirm_share"]}
        central = search["central"]
        spec = focus._spec_of(repo, central["of"], central["law"])
        assert P.value_of(spec, ("dynamics", "beta")) == pytest.approx(centre["spec"]["dynamics"]["beta"] * 1.1125)
        entry = next(e for e in push.entries(state) if e["law"] == central["law"])
        assert entry["by"].startswith("zone ") and central["law"] in state["contenders"], (
            "its central law joins the end of the push list, as the operator's own pushes do")
        assert push.laws(state)[-1] == central["law"] and push.laws(state)[0] == state["depth_now"]["law"], (
            "the law the depth worker holds stays first; the central law waits at the end until the operator moves it")
        edges = state["campaigns"][zone_search.EDGES]
        spec_e = repo.campaign(edges)["spec"]
        assert spec_e["ladder"] == [64, 256, 1024, 4096] and spec_e["study_design"]["focus"]["part"] == "E"
        assert work_groups.tier_of({"design_kind": "focus", "focus_part": "E"}) == work_groups.ZONE_TIER
        bench = search["benchmark"]
        rings = sum(count for _r, count in state["plan"]["neighbourhood"]["radii"])
        assert bench["ring_method"]["neighbours"] == rings and bench["ring_method"]["runs"] == rings * 3 * 5
        assert bench["calls"]["held"] == bench["calls"]["edges"] > 0
        assert done.get("region"), "the zone is placed as a region"
        assert study_seed.seeded_campaign(repo, "178") == current["of"]
