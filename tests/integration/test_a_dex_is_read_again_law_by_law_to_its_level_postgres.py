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
G = 10 ** 9


def _science():
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _law(beta: float, terms=None) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta),
                              terms=terms if terms is not None else H12["terms"]))
    return dsl.fingerprint(spec), spec


def _chain(law: str, n: int, seed: int, source: str) -> dict:
    return {"law": law, "n": n, "seed": seed, "replicate": 0, "chain": 0, "init": "empty", "moves": 1000 * n,
            "ran": True, "accepted_moves": 400 * n, "final_edges": 2 * n, "peak_edges": 2 * n + 3, "max_degree": 6,
            "work_units": 5000 * n, "termination": "certified", "science": _science()["sha256"], "source": source,
            "study": "177"}


def _dex(work: Path, folder: Path, laws, *, verify_to=None) -> Path:
    from graph_scale_dynamics.operations import dex as D
    bundle = work / "study_177_2026-11-26T19-33-48Z"
    (bundle / "tables").mkdir(parents=True)
    (bundle / "study.json").write_text(json.dumps({"study_id": "177", "built_utc": "2026-11-26T19:33:48Z",
                                                   "build_number": 885, "science": _science()}))
    with gzip.open(bundle / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        for i, (code, law, spec, score) in enumerate(laws):
            handle.write(json.dumps({"campaign_id": "12", "candidate_id": law, "code": code, "spec": spec,
                                     "law_score": {"score": score}, "graph": i + 1}) + "\n")
    (bundle / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": []}))
    part = D.read_part(bundle)
    part["chains"] = [_chain(law, n, seed, part["name"]) for _c, law, _s, _sc in laws
                      for n in (64, 256, 1024, 4096) for seed in (0, 1, 2)]
    made = D.merge([part], science=_science(), made_by={"study": "177", "build": 885}, verify_to=verify_to)
    return D.write(made, folder, "177")


def _laws():
    two = H12["terms"][:2]
    found = [("S176-C12-G1", *_law(0.188203), 1), ("S176-C12-G2", *_law(0.19), 1), ("S176-C12-G3", *_law(0.192), 1),
             ("S177-C11-G37", *_law(0.3, two), 38), ("S177-C12-G565", *_law(0.302, two), 27)]
    return found, {code: law for code, law, _spec, _score in found}


def _job(repo, campaign: str, law: str, n: int, seed: int, *, status: str = "queued") -> str:
    from graph_scale_dynamics.db.decision_store import queue_priority
    job_id = f"dex-{campaign}-{law[:10]}-{n}-{seed}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=n,
                    seed=seed, spec={}, priority=queue_priority(10, n))
    repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
    return job_id


def _order(repo, campaign: str) -> list[str]:
    return [r["candidate_id"] for r in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=? ORDER BY admission_sequence",
        (str(campaign),)).fetchall()]


def test_a_dex_in_the_import_folder_before_the_start_is_read_in_at_the_start_to_n_4096_and_claimed_law_by_law(
        isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import study, study_seed
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.scheduling import work_groups
    from graph_scale_dynamics.services.worker import main as W
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    folder = study.make_import_folder(var)
    assert folder == (tmp_path / "178" / "main" / "import") and folder.is_dir(), "the import folder from the start"
    laws, by = _laws()
    _dex(tmp_path / "work", folder, laws)
    said: list[str] = []
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=said.append)
        dex = study_seed.seeded_campaign(repo, "178")
        assert any("read in at the study's start: 5 laws" in line for line in said), said
        spec = repo.campaign(dex)["spec"]
        assert spec["ladder"] == [64, 256, 1024, 4096] and spec["study_design"]["verify_to"] == 4096
        assert spec["budgets"]["max_n"] == 4096 and "extension_ladder" not in spec, (
            "a dex is read again at the base, N=64 to 4,096, unless it asks for more")
        order = _order(repo, dex)
        assert set(order[:3]) == {by["S176-C12-G1"], by["S176-C12-G2"], by["S176-C12-G3"]}
        assert order[3:] == [by["S177-C11-G37"], by["S177-C12-G565"]], (
            "read by term set, the larger first, so a zone's laws finish together; B's score of 38 does not jump it")

        first, second, third = order[:3]
        for law, n, seed in ((second, 64, 0), (first, 256, 0), (first, 64, 1), (second, 64, 1)):
            _job(repo, dex, law, n, seed)
        claimed = []
        while (job := repo.claim_job("w", ("simulate",), campaigns=(dex,), order=work_groups.BY_LAW)) is not None:
            claimed.append((job["candidate_id"], int(job["n"]), int(job["seed"])))
        assert claimed == [(first, 64, 1), (first, 256, 0), (second, 64, 0), (second, 64, 1)], (
            "every run of the first law before the next law's")

        repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=?", (dex,))
        _job(repo, dex, first, 16384, 0)
        _job(repo, dex, third, 1024, 0)
        monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
        monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * G))
        monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: G // 10)
        monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
        offered = [bounds for campaigns, _under, bounds in W.offers(repo.worker_allocation(claimable=True), {})
                   if campaigns == (dex,)]
        assert offered == [{"order": work_groups.BY_LAW, "max_n": 4096}, {"order": work_groups.BY_LAW}]
        job = W.claim_simulation_for_owner(repo, "w2")
        assert (job["candidate_id"], int(job["n"])) == (third, 1024), (
            "a deeper size of a dex campaign made before 888 waits until every law has read to N=4,096")


def test_a_dex_may_ask_to_be_read_deeper_and_a_law_read_to_its_level_is_judged_without_its_decision(
        isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import dex_check, focus, study, study_seed
    from graph_scale_dynamics.operations import study_design as SD
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    folder = study.make_import_folder(var)
    laws, by = _laws()
    dropped = _dex(tmp_path / "work", folder, laws, verify_to=16384)
    assert D.read_part(dropped)["verify_to"] == 16384
    design = SD.design_for(ROOT, "178")
    assert SD.verify_level(design) == 4096 and SD.verify_level(design, 16384) == 16384
    assert SD.verify_level(design, 10 ** 7) == 65536 and SD.verify_level(design, 100) == 4096
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=lambda *_a: None)
        dex = study_seed.seeded_campaign(repo, "178")
        assert repo.campaign(dex)["spec"]["ladder"] == [64, 256, 1024, 4096, 16384]
        first = by["S176-C12-G1"]
        for n in (64, 256, 1024, 4096):
            for seed in range(3):
                _job(repo, dex, first, n, seed, status="done")
        assert dex_check.read_to_level(repo, dex) == set(), "read to 4,096 is not yet its level of 16,384"
        for seed in range(3):
            _job(repo, dex, first, 16384, seed, status="done")
        _job(repo, dex, by["S176-C12-G2"], 64, 0, status="done")
        assert dex_check.read_to_level(repo, dex) == {first}
        recorded = D.read_part(dropped)["chains"]
        monkeypatch.setattr(dex_check, "decided", lambda *_a: False)
        monkeypatch.setattr(dex_check, "chains_here", lambda repo, campaign_id, blobs, wanted, **_k: [
            dict(row, source="study 178's folder") for row in recorded if row["law"] in wanted])
        found = dex_check.keep(repo, var.parent, blobs=None, force=True)
        assert found["checked"] == 1 and found["owed"] == 4
        from graph_scale_dynamics.scheduling import work_groups
        assert work_groups.verifying(repo) == focus.load(repo)["dex_check"]["verify_to"] == 16384, (
            "while the check is open the Dex laws run only to the level the dex asks")
        from graph_scale_dynamics.operations import focus
        check = focus.load(repo)["dex_check"]
        assert check["laws"][first]["verdict"] == "confirmed" and check["laws"][first]["agree"] == 12
        assert check["verify_to"] == 16384


def test_a_new_copy_of_the_dex_is_written_when_something_new_turns_up(isolated_postgres_schema, tmp_path,
                                                                       monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import dex as D
    from graph_scale_dynamics.operations import focus, study
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    study.make_import_folder(var)
    written: list[str] = []
    scoring: set[str] = {"a" * 64}

    def write(repo, root, *, blobs, build=None, why=None):
        state = focus.load(repo)
        repo.set_flag(D.FLAG, json.dumps({"at": clock[0], "why": why, **D.held_now(state),
                                          "laws": sorted(law[:D.KEPT_ID] for law in scoring)}))
        written.append(why)
        return Path(root) / D.FOLDER / "dex.tar.zst"

    clock = [1_000_000.0]
    monkeypatch.setattr(D, "write_folder", write)
    monkeypatch.setattr(D, "scoring_here", lambda repo, study: set(scoring))
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=lambda *_a: None)

        def keep(at: float):
            clock[0] = at
            return D.keep(repo, var.parent, blobs=None, now=at)

        assert keep(1_000_000.0) is not None and written == ["an hour since the last"], "the first at once"
        scoring.add("b" * 64)
        assert keep(1_000_300.0) is None, "never twice within ten minutes"
        assert keep(1_000_700.0) is not None and written[-1] == "1 law scoring here that the last dex does not hold"
        assert keep(1_001_400.0) is None, "nothing new: no new copy"
        state = focus.load(repo)
        state["regions"] = [{"number": 1, "name": "Z1"}]
        focus.save(repo, state)
        assert keep(1_001_430.0) is None, "looked at once a minute"
        assert keep(1_001_500.0) is not None and written[-1] == "1 zone mapped since the last dex"
        state = focus.load(repo)
        state["dex_check"] = {"counts": {"confirmed": 3}}
        focus.save(repo, state)
        assert keep(1_002_200.0) is not None and written[-1] == "3 laws of the dex verified here since the last dex"
        assert keep(1_005_900.0) is not None and written[-1] == "an hour since the last"


def test_working_now_groups_the_runs_of_one_law_with_its_progress(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus, study, study_seed, zone_live
    init_db(isolated_postgres_schema.dsn)
    var = tmp_path / "178" / "main" / "var"
    folder = study.make_import_folder(var)
    laws, by = _laws()
    _dex(tmp_path / "work", folder, laws)
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, json.loads(json.dumps(SURVEY)), var=var, tree=ROOT, study="178", log=lambda *_a: None)
        dex = study_seed.seeded_campaign(repo, "178")
        first = by["S176-C12-G1"]
        for seed in range(3):
            _job(repo, dex, first, 64, seed, status="done")
        for seed in range(3):
            _job(repo, dex, first, 256, seed)
        assert repo.claim_job("w1", ("simulate",), campaigns=(dex,), order="by_law")["candidate_id"] == first
        assert repo.claim_job("w2", ("simulate",), campaigns=(dex,), order="by_law")["candidate_id"] == first
        found = zone_live.reading(repo, focus.load(repo))
        assert len(found["running"]) == 2 and len(found["laws"]) == 1
        row = found["laws"][0]
        assert row["law"] == first and row["role"] == zone_live.DEX and row["label"] == "S178-C14-G1"
        assert (row["done"], row["planned"], row["running"], row["queued"]) == (3, 12, 2, 1)
        assert row["now"] == [{"n": 256, "seeds": [0, 1]}] and row["sizes"] == [64, 256, 1024, 4096]
        assert 0.25 <= row["progress"] < 0.5, "three of twelve runs done, two under way"
