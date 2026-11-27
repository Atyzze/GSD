from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.usefixtures("isolated_postgres_schema"),
              pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")]

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
DYNAMICS = {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
            "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30}
CUBE = {"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}}
GRADIENT = {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}}
OVERLAP = {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}
UP, DOWN = 0.57, 0.33


def _science():
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _law(terms: list[dict], beta: float) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize({"dsl_version": 1, "init": "empty", "dynamics": dict(DYNAMICS, beta=beta), "terms": terms})
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


def test_the_zones_are_searched_one_after_another_the_first_s_laws_passed_over_and_the_dex_carries_them(
        isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import dex_check, focus, study, zone_search
    from graph_scale_dynamics.research import perturb as P
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    first = [("S176-C12-G1", *_law([CUBE, GRADIENT, OVERLAP], 0.188203)),
             ("S176-C12-G2", *_law([CUBE, GRADIENT, OVERLAP], 0.19)),
             ("S176-C12-G3", *_law([CUBE, GRADIENT, OVERLAP], 0.192))]
    second = [("S177-C12-G7", *_law([CUBE, OVERLAP], 0.188203)), ("S177-C12-G8", *_law([CUBE, OVERLAP], 0.19))]
    dropped = _dex(tmp_path / "work", study.make_import_folder(var), first + second)
    reference = {3: first[1][2], 2: second[0][2]}
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=lambda *_a: None)
        recorded = D.read_part(dropped)["chains"]
        monkeypatch.setattr(dex_check, "decided", lambda *_a: True)
        monkeypatch.setattr(dex_check, "chains_here", lambda repo, campaign_id, blobs, wanted, **_k: [
            dict(row, source="study 178's folder") for row in recorded if row["law"] in wanted])
        assert dex_check.keep(repo, var.parent, blobs=None, force=True)["chosen"] == "S176-C12-G2"
        from graph_scale_dynamics.scheduling import work_groups
        assert work_groups.verifying(repo) is None, "the check done, the Dex laws run past its level again"

        def kind(campaign, law, n):
            spec = (repo.candidate(law, campaign) or {}).get("spec") or {}
            ref = reference.get(len(spec.get("terms") or []))
            if ref is None or zone_search.signature_of(spec) != zone_search.signature_of(ref):
                return {"kind": "moved", "curves": {}}
            for path in P.parameters(ref):
                change = (P.value_of(spec, path) - P.value_of(ref, path)) / P.value_of(ref, path)
                if not -DOWN < change < UP:
                    return {"kind": "moved", "curves": {}}
            return {"kind": "made", "curves": {}}

        monkeypatch.setattr(zone_search, "reading", lambda repo, campaign, law, n: kind(campaign, law, n))
        for _ in range(80):
            focus.step(repo, force=True)
            state = focus.load(repo)
            if len(state.get("zones") or []) == 2:
                break
        found = state["zones"]
        assert found[0]["centre"] == first[1][1], "the rule's first zone, S176-C12-G2's"
        assert [z["stage"] for z in found] == [focus.MAPPED, focus.MAPPED], [z.get("why") for z in found]
        assert found[1]["centre"] in {second[0][1], second[1][1]}, "the second term set's family is the next zone"
        first_zone = found[0]
        assert first_zone["box"]["term 1 c0"]["up"] == 0.55 and first_zone["box"]["term 1 c0"]["down"] == 0.325
        assert first_zone["held_to"] == 16384 and first_zone["central"]["law"]
        over = dex_check.searched(repo, state)
        assert over[first[0][1]].startswith("inside ") and over[first[2][1]].startswith("inside "), over
        assert over[first[1][1]].startswith("the centre of "), "the first zone's laws are passed over"
        assert [z["centre"] for z in state["zones_chosen"]] == [first[1][1], found[1]["centre"]]
        assert state["zone_chosen"]["chosen"] is None and state["zone_chosen"]["passed_over"] == 5, (
            "no zone is left: the focus goes back to the score")
        assert sum(len(r.get("zones") or []) for r in state["regions"]) == 2
        shown = dex_check.reading(state)
        assert [z["stage"] for z in shown["zones"]] == ["mapped", "mapped"] and shown["zones"][0]["edges"] > 0

        made = D.of_folder(repo, blobs=None, import_folder=var.parent / "import", build=891)
        held = {e["law"] for e in made["laws"]}
        assert {z["central"]["law"] for z in found} <= held, "each zone's central law is in the dex"
        assert sum(len(r.get("zones") or []) for r in made["regions"]) == 2
        assert D.document(made)["counts"]["zones"] == 2
        written = D.write(made, tmp_path / "export", "178")
        part = D.read_part(written)
        carried = [z for r in part["regions"] for z in r.get("zones") or []]
        assert [z["centre"] for z in carried] == [z["centre"] for z in found]
        assert zone_search.passed_over(carried, {law: e["spec"] for law, e in part["laws"].items()}).keys() >= {
            law for _c, law, _s in first + second}, "a dex read in passes over every law its zones hold"
    said = subprocess.run([sys.executable, str(ROOT / "tools" / "dex.py"), "zones", str(written), "--as-verified"],
                          capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert f"{found[0]['label']}: mapped, made" in said and "held to 16384" in said, said
    assert "the next zone: none" in said and "laws passed over" in said, said
