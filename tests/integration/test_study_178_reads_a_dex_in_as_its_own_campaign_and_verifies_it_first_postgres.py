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
STARTS = ("empty", "random")


def _science():
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _law(beta: float, terms=None) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta),
                              terms=terms if terms is not None else H12["terms"]))
    return dsl.fingerprint(spec), spec


def _control() -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import standing_controls as S
    spec = dsl.normalize(S.laws(S.load_criterion())[0]["spec"])
    return dsl.fingerprint(spec), spec


def _chain(law: str, n: int, seed: int, init: str, source: str, **changed) -> dict:
    row = {"law": law, "n": n, "seed": seed, "replicate": 0, "chain": 0, "init": init, "moves": 1000 * n, "ran": True,
           "accepted_moves": 400 * n, "final_edges": 2 * n, "peak_edges": 2 * n + 3, "max_degree": 6,
           "work_units": 5000 * n, "termination": "certified", "science": _science()["sha256"], "source": source,
           "study": "177"}
    return dict(row, **changed)


def _dex(root: Path, laws) -> Path:
    from graph_scale_dynamics.operations import dex as D
    folder = root / "study_177_2026-11-26T19-33-48Z"
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"study_id": "177", "built_utc": "2026-11-26T19:33:48Z",
                                                   "build_number": 885, "science": _science()}))
    with gzip.open(folder / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (code, law, spec, score) in enumerate(laws):
            handle.write(json.dumps({"campaign_id": "12", "candidate_id": law, "code": code, "spec": spec,
                                     "law_score": {"score": score}, "graph": i + 1}) + "\n")
    (folder / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": []}))
    part = D.read_part(folder)
    part["chains"] = [_chain(law, n, seed, init, part["name"]) for _code, law, _spec, _score in laws
                      for n in (64, 256) for seed in (0, 1) for init in STARTS]
    made = D.merge([part], science=_science(), made_by={"study": "177", "build": 885})
    return D.write(made, root / "177" / "main" / "import", "177")


def _held(repo, campaign_id) -> set[str]:
    return {r["candidate_id"] for r in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (str(campaign_id),)).fetchall()}


def test_study_178_reads_a_dex_in_as_its_own_campaign_verifies_every_law_first_and_takes_the_first_zone(
        isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import dex_check, focus, study_seed
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import zone_choice as Z
    init_db(isolated_postgres_schema.dsn)
    two = H12["terms"][:2]
    a1, a1_spec = _law(0.188203)
    a2, a2_spec = _law(0.19)
    a3, a3_spec = _law(0.192)
    a4, a4_spec = _law(0.2)
    b1, b1_spec = _law(0.3, two)
    b2, b2_spec = _law(0.302, two)
    control, control_spec = _control()
    laws = [("S176-C12-G1", a1, a1_spec, 1), ("S176-C12-G2", a2, a2_spec, 1), ("S176-C12-G3", a3, a3_spec, 1),
            ("S176-C12-G4", a4, a4_spec, 1), ("S177-C11-G37", b1, b1_spec, 38), ("S177-C12-G565", b2, b2_spec, 27),
            ("S176-C15-G1", control, control_spec, 17)]
    root = tmp_path / "177" / "main"
    dropped = _dex(tmp_path, laws)
    with Repo(isolated_postgres_schema.dsn) as repo:
        design = SD.design_for(ROOT, "178")
        assert len(set(design["search_seeds"])) == 10 and not any(
            set(design["search_seeds"]) & set(SD.design_for(ROOT, s).get("search_seeds") or [])
            for s in SD.designed_studies(ROOT) if s != "178"), "ten new search seeds"
        SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        kinds = sorted((c["spec"]["study_design"]["kind"], c["spec"]["study_design"]["group"])
                       for c in repo.all_campaigns())
        assert kinds == sorted([("blind", "A")] * 10 + [("focus", "N")] * 2 + [("focus", "D")]), (
            "the blind draw and the focus's three campaigns; no seeded campaign made in advance")
        with pytest.raises(ValueError, match="no seeded campaign"):
            study_seed.seeded_campaign(repo, "178")
        state = focus.load(repo)
        assert state["dex_first"] is True and state["current"] is None
        focus.step(repo, force=True)
        assert focus.load(repo)["current"] is None and "idle: no law scores" in focus.reading(repo)["doing"]

        found = D.absorb(repo, root / "import")
        assert [f["bundle"] for f in found] == [D.name_of(dropped)] and found[0]["laws_added"] == 7
        made = study_seed.seeded_campaign(repo, "178")
        spec = repo.campaign(made)["spec"]
        assert spec["study_design"]["kind"] == "seed" and spec["study_design"]["dex"] is True
        assert spec["study_design"]["campaign"] == 10 and spec["search_policy"]["kind"] == "hand"
        assert _held(repo, made) == {a1, a2, a3, a4, b1, b2, control}, "the dex is its own campaign"

        focus.step(repo, force=True)
        state = focus.load(repo)
        assert state["current"] is None and state["contenders"] == {} and not state.get("depth_now"), (
            "nothing is taken into focus or pushed deeper while the dex is verified, its score of 38 included")
        assert focus.reading(repo)["doing"].startswith("verifying the dex first: 0 of 7 laws read again")

        decided: set[str] = set()
        here = {law: [dict(c, source="study 178's folder") for c in D.read_part(dropped)["chains"] if c["law"] == law]
                for law in _held(repo, made)}
        here[a4][-1]["accepted_moves"] += 1
        here[b2] = [dict(c, moves=c["moves"] + 1) for c in here[b2]]
        monkeypatch.setattr(dex_check, "decided", lambda repo, campaign_id, law: law in decided)
        monkeypatch.setattr(dex_check, "chains_here", lambda repo, campaign_id, blobs, wanted, **_k: [
            row for law in sorted(wanted) for row in here[law]])

        decided |= {a1, a2}
        assert dex_check.keep(repo, root, blobs=None, force=True) == {"checked": 2, "owed": 5, "chosen": None,
                                                                     "none": False}
        focus.step(repo, force=True)
        reading = focus.reading(repo)
        assert reading["current"] is None
        assert reading["doing"].startswith("verifying the dex first: 2 of 7 laws read again (2 confirmed, 0 denied")
        listed = {row["law"]: row for row in reading["dex_check"]["laws"]}
        assert set(listed) == {a1, a2} and listed[a1]["agree"] == 8 and listed[a1]["code"] == "S176-C12-G1"

        decided |= {a3, a4, b1, b2, control}
        checked = dex_check.keep(repo, root, blobs=None, force=True)
        assert checked == {"checked": 5, "owed": 0, "chosen": "S176-C12-G2", "none": False}
        zone = focus.load(repo)["zone_chosen"]
        assert zone["centre"] == a2 and zone["chosen"]["near"] == 3 and zone["campaign"] == made
        assert zone["counts"] == {"confirmed": 5, "denied": 1, "unmatched": 1, "controls": 1, "laws": 7}
        assert "3 verified laws within 0.1 of S176-C12-G2" in zone["why"] and "1 standing control never chosen" in zone[
            "why"], "B1 scores 38 and B2 is unmatched: the zone is A's, its denied A4 left out"
        rows = focus.reading(repo)["dex_check"]["laws"]
        assert [r["verdict"] for r in rows][:2] == [Z.DENIED, Z.UNMATCHED], "what differs is listed first"
        assert rows[0]["first_differ"]["accepted_moves"][1] == rows[0]["first_differ"]["accepted_moves"][0] + 1

        focus.step(repo, force=True)
        state = focus.load(repo)
        assert state["current"]["law"] == a2 and state["current"]["of"] == made
        assert state["current"]["chosen_by"] == focus.BY_ZONE and state["zone_chosen"]["taken_utc"]
        assert state["depth_now"] is None, "the zone's centre is the zone search's; its central law will be pushed"
        assert "the centre of the first zone, chosen to confirm fast: the most verified laws" in focus.reading(repo)[
            "doing"]
        assert dex_check.keep(repo, root, blobs=None, force=True) is None, "a zone chosen is chosen once"

        from graph_scale_dynamics.services.api import focus_route
        monkeypatch.setattr(focus_route, "import_folder", lambda: root / "import")
        page = focus_route.answer(repo)
        assert page["focus"]["dex_check"]["zone"]["code"] == "S176-C12-G2"
        assert len(page["focus"]["dex_check"]["laws"]) == 7


def test_a_dex_let_go_while_it_is_verified_frees_the_focus_and_study_177_keeps_its_way(isolated_postgres_schema,
                                                                                       tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import dex_check, focus, study_seed
    from graph_scale_dynamics.operations import study_design as SD
    init_db(isolated_postgres_schema.dsn)
    best, best_spec = _law(0.188203)
    root = tmp_path / "177" / "main"
    dropped = _dex(tmp_path, [("S176-C11-G82", best, best_spec, 38)])
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "178"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        D.absorb(repo, root / "import")
        focus.step(repo, force=True)
        assert focus.load(repo)["current"] is None and dex_check.waiting(focus.load(repo))
        study_seed.release(repo, D.name_of(dropped))
        assert not dex_check.waiting(focus.load(repo)), "the operator's untick still lets a dex go"
        assert dex_check.keep(repo, root, blobs=None, force=True) is None
        assert focus.reading(repo)["doing"].startswith("idle: no law scores")

    design = SD.design_for(ROOT, "177")
    assert SD.dex_entry(design) is None and SD.entry_of(design, 10)["kind"] == "seed", (
        "177's seeded campaign is made in advance, as it was")
    assert SD.entry_of(SD.design_for(ROOT, "178"), 10)["verified_first"] is True
    with pytest.raises(ValueError, match="has no campaign 11"):
        SD.entry_of(SD.design_for(ROOT, "178"), 11)
