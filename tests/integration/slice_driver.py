from __future__ import annotations

import json
import re
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def rr(*args: str, var: Path, database: str) -> subprocess.CompletedProcess[str]:
    schema = database.split(":", 1)[1] if database.startswith("folder-schema:") else None
    if not schema:
        raise ValueError("integration slice requires a folder-schema:NAME database reference")
    env = dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=schema)
    return subprocess.run(
        [sys.executable, "main.py", "--var", str(var), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=1200,
    )


FLEET_LOCK_HELD = "another Graph Scale Dynamics fleet already owns this database"


def require(result: subprocess.CompletedProcess[str], context: str) -> None:
    if result.returncode == 0:
        return
    if FLEET_LOCK_HELD in (result.stdout or ""):
        raise AssertionError(
            f"{context} could not start: {FLEET_LOCK_HELD}.\n"
            "This is an environment precondition, not a failure of the slice. A "
            "previous fleet was killed rather than stopped and its PostgreSQL "
            "session still holds the advisory lock; it is released when that "
            "backend exits. Check for an orphaned `main.py run` and wait for or "
            "end it, then re-run.\n"
            + _lock_owner_note(result)
        )
    if result.returncode == 75 or "detected runtime drift" in (result.stdout or ""):
        import importlib.util
        spec = importlib.util.find_spec("graph_scale_dynamics")
        origin = Path(spec.origin).resolve().parents[1] if spec and spec.origin else None
        raise AssertionError(
            f"{context} failed (75, deployment provenance fence).\n"
            f"This tree: {ROOT}\n"
            f"`import graph_scale_dynamics` from outside it resolves to: {origin}\n"
            "If they differ, the editable install points at another checkout: run "
            "`pip install -e . --break-system-packages` (or tools/prepare_environment.sh) "
            "from this tree and re-run. If they match, the tree was edited during the run.\n"
            f"stdout tail:\n{result.stdout[-1500:]}"
        )
    raise AssertionError(
        f"{context} failed ({result.returncode})\nstdout:\n{result.stdout[-4000:]}"
        f"\nstderr:\n{result.stderr[-4000:]}"
    )


def _lock_owner_note(result: subprocess.CompletedProcess[str]) -> str:
    try:
        from graph_scale_dynamics.db.connection import resolve_target
        from graph_scale_dynamics.db.repo import Repo

        with Repo(resolve_target("folder", auto_provision=False)) as repo:
            rows = repo.conn.execute(
                "SELECT a.pid, a.backend_start, a.state FROM pg_locks l "
                "JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE l.locktype = 'advisory' AND l.granted"
            ).fetchall()
    except Exception as exc:
        return f"(could not read the lock holder: {type(exc).__name__}: {exc})"
    if not rows:
        return ("The lock is no longer held, so it was released between the refusal "
                "and this check: the orphan exited. A retry should pass.")
    owners = ", ".join(f"pid {row['pid']} (backend started {row['backend_start']}, "
                       f"{row['state']})" for row in rows)
    return f"Advisory lock currently held by: {owners}"


def run_engine(var_dir: Path, database: str) -> None:
    shutil.rmtree(var_dir, ignore_errors=True)
    require(rr("init", var=var_dir, database=database), "init")
    require(rr("benchmark", var=var_dir, database=database), "benchmark")
    started = rr("campaign", "start", "--spec", "tests/fixtures/campaign_slice_engine.json",
                 var=var_dir, database=database)
    require(started, "campaign start")
    match = re.search(r"^Campaign (\S+) created", started.stdout, re.MULTILINE)
    if match is None:
        raise AssertionError(
            f"campaign start output carried no campaign id:\n{started.stdout[-2000:]}"
        )
    campaign = match.group(1)
    submitted = rr("candidate", "submit", "--campaign", campaign,
                   "--file", "candidate_sparse_anchor.json",
                   var=var_dir, database=database)
    require(submitted, "candidate submit")
    candidate = submitted.stdout.strip().splitlines()[-1]
    fleet = rr("run", "--campaign", campaign, "--workers", "2", "--wall", "180", "--no-dashboard",
               var=var_dir, database=database)

    from graph_scale_dynamics.db.repo import Repo

    with Repo(database) as repo:
        count = lambda sql: [tuple(dict(r).values()) for r in repo.conn.execute(sql, (campaign,)).fetchall()]
        print("JOBS", count("SELECT n,status,COUNT(*) FROM jobs WHERE campaign_id=? GROUP BY n,status ORDER BY n,status"), flush=True)
        print("ANALYSES", count("SELECT n,status,COUNT(*) FROM analysis_queue WHERE campaign_id=? GROUP BY n,status ORDER BY n"), flush=True)
        print("REBUILDS", count("SELECT status,COUNT(*) FROM candidate_evidence_rebuilds WHERE campaign_id=? GROUP BY status"), flush=True)
        print("SUMMARIES", count("SELECT n FROM rung_summaries WHERE campaign_id=? ORDER BY n"), flush=True)
        print("DECISIONS", count("SELECT at_n,action,rule,next_n,jobs_created,jobs_seen FROM engine_decisions WHERE campaign_id=? ORDER BY decision_id"), flush=True)
        print("STATE", count("SELECT state,state_reason FROM campaign_candidates WHERE campaign_id=?"), flush=True)
        roots = [var_dir, ROOT / "var", ROOT / "instance", ROOT / "runtime"]
        for root in roots:
            for log in sorted(root.rglob("*.jsonl")) if root.exists() else []:
                try:
                    hits = [l for l in log.read_text(errors="replace").splitlines()
                            if "engine_decision_failed" in l or "engine_decisions" in l]
                except OSError:
                    continue
                if hits:
                    print("LOG", log, *[l[:600] for l in hits[-6:]], sep="\n  ", flush=True)
        print("FLEET OUTPUT", (fleet.stdout or "")[-1500:], (fleet.stderr or "")[-1500:], sep="\n", flush=True)
        import traceback
        from graph_scale_dynamics.db.decision_store import DecisionStore

        class _Quiet:
            def write(self, *args, **kwargs):
                print("STORE LOG", args, kwargs, flush=True)

        store = DecisionStore(repo, _Quiet(), repo.campaign(campaign))
        print("AWAITING", store.laws_awaiting_decision(campaign), flush=True)
        print("PENDING", repo.candidate_evidence_pending(campaign, candidate, __import__(
            "graph_scale_dynamics.measurements.version", fromlist=["ANALYSIS_VERSION"]).ANALYSIS_VERSION), flush=True)
        try:
            evidence = store.law_evidence(campaign, candidate)
            print("EVIDENCE", {k: (sorted(v) if isinstance(v, dict) else v) for k, v in evidence.items()
                               if k != "phenotype"}, "phenotype" in evidence and evidence["phenotype"] is not None, flush=True)
        except Exception:
            print("EVIDENCE RAISED", traceback.format_exc()[-2500:], flush=True)
        require(fleet, "fleet")
        rows = repo.conn.execute(
            "SELECT at_n,next_n,action,rule,jobs_created FROM engine_decisions WHERE campaign_id=? AND candidate_id=? "
            "ORDER BY decision_id", (campaign, candidate)).fetchall()
        trail = [(r["at_n"], r["action"], r["rule"], r["next_n"], r["jobs_created"]) for r in rows]
        print("ENGINE TRAIL", trail, flush=True)
        assert trail and trail[0] == (None, "run_next", "start", 64, 3), trail
        assert len(trail) >= 4 and trail[1] == (64, "run_next", "base_block", 256, 3), trail
        assert trail[2] == (256, "run_next", "base_block", 1024, 3), trail
        assert trail[-1][1] == "done" and trail[-1][0] == 1024, trail
        row = repo.candidate(candidate, campaign)
        assert row["state"] == "DONE", (row["state"], row.get("state_reason"))
        diagnostics = {int(r["n"]): r["diagnostics"] for r in repo.rung_diagnostics(campaign, candidate)}
        print("DIAGNOSTICS", {n: (d["seeds"], d["observables"]["energy_per_node"], d["chain_seconds"])
                               for n, d in diagnostics.items()}, flush=True)
        assert sorted(diagnostics) == [64, 256, 1024], sorted(diagnostics)
        for n, d in diagnostics.items():
            assert d["seeds"] == 3 and d["seeds_with_moments"] == 3, (n, d)
            assert d["observables"]["energy_per_node"]["half_chains"] == 12, (n, d["observables"])
            assert d["chain_seconds"]["empty"] > 0 and d["chain_seconds"]["given"] > 0, (n, d["chain_seconds"])
        budgets = {}
        for job in repo.jobs(campaign, kind="simulate"):
            execution = json.loads(job["spec_json"])["execution"] if isinstance(job.get("spec_json"), str) else job["spec"]["execution"]
            budgets.setdefault(int(job["n"]), set()).add(int(execution["one_shot"]["work_budget"]))
        assert budgets == {n: {units} for n, units in SLICE_BUDGETS.items()}, budgets
        from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
        assert repo.base_block_phenotype(candidate, ANALYSIS_VERSION, campaign) is not None, "no phenotype written"
        assert repo.campaign(campaign)["status"] == "completed"
        check_the_record(repo, var_dir, campaign, candidate)


def check_the_record(repo, var_dir: Path, campaign: str, candidate: str) -> None:
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.artifact_store.chain_record import read_record
    from graph_scale_dynamics.decisions.replay import replay_matches

    store = BlobStore(var_dir / "blobs")
    sizes = {}
    for job in repo.jobs(campaign, kind="simulate"):
        if job.get("status") != "done":
            continue
        n = int(job["n"])
        row = repo.conn.execute("SELECT record_artifact FROM artifact_retention WHERE artifact_hash=?",
                                (job["result_artifact"],)).fetchone()
        assert row and row["record_artifact"], ("no chain record", job["job_id"])
        record = read_record(store, row["record_artifact"])
        sizes.setdefault(n, []).append(store.stat(row["record_artifact"]).st_size)
        assert record["n"] == n and record["candidate_id"] == candidate
        chains = {block["start"]: block for block in record["chains"]}
        for chain in ("empty", "given"):
            block = chains[chain]
            assert block["graph"]["edges"] >= 0 and len(block["graph"]["sha256"]) == 64
            columns = block["trajectory"]["columns"]
            assert block["trajectory"]["points"] > 0 and "energy" in columns and "term0.coefficient" in columns
            assert any(v is not None for v in columns.get("triangles") or []), (chain, sorted(columns))
            assert sum((block["accounting"] or {}).get("counts", {}).values()) > 0, chain
        for chain in chains.values():
            late = chain["late_change"]
            assert "snapshots" not in chain and late is not None and 0.0 <= late["overlap"] <= 1.0, (chain["start"], late)
        assert all("certificate" in chunk for chunk in record["sampling_checkpoints"])
        cost = json.loads(repo.conn.execute("SELECT resource_json FROM attempts WHERE job_id=? AND exit_code=0",
                                            (job["job_id"],)).fetchone()["resource_json"])["cost"]
        assert cost["child"]["io"] and "cpu_seconds" in cost["bookkeeping"], cost
    print("CHAIN RECORD BYTES", {n: (len(v), sum(v) // max(1, len(v))) for n, v in sorted(sizes.items())}, flush=True)
    for row in repo.conn.execute("SELECT n,metrics_json FROM measurements WHERE campaign_id=? AND candidate_id=?",
                                 (campaign, candidate)).fetchall():
        metrics = json.loads(row["metrics_json"])
        for key in ("census", "log_diameter", "move_accounting", "descent", "couplings"):
            assert metrics.get(key) is not None, (row["n"], key)
        assert metrics["census"]["empty"]["largest_component"]["diameter"]["lower_bound"] is not None
        assert metrics["census"]["given"] is not None
    for row in repo.conn.execute("SELECT n,summary_json FROM rung_summaries WHERE campaign_id=? AND candidate_id=?",
                                 (campaign, candidate)).fetchall():
        summary = json.loads(row["summary_json"])
        for key in ("census", "withheld", "equilibration_structural_split", "couplings", "log_diameter_unknown"):
            assert key in summary, (row["n"], key)
    decisions = [dict(r) for r in repo.conn.execute(
        "SELECT action,rule,reason,next_n,at_n,priority,facts_json,inputs_json,context_json FROM engine_decisions "
        "WHERE campaign_id=? AND candidate_id=?", (campaign, candidate)).fetchall()]
    assert decisions and all(d["context_json"] for d in decisions)
    for decision in decisions:
        if decision["inputs_json"] is None:
            continue
        verdict = replay_matches(dict(decision, inputs=decision["inputs_json"]))
        assert verdict["matches"], (decision["rule"], verdict)
    spec_row = repo.conn.execute("SELECT regime,beta,locality,swap_share,reduced_basis_json FROM candidate_specs "
                                 "WHERE candidate_id=?", (candidate,)).fetchone()
    assert spec_row["regime"] and spec_row["beta"] is not None and json.loads(spec_row["reduced_basis_json"])


LET_THROUGH = {"let_through_from": 256, "confirm_after": 2, "known_result_after": 1}
SLICE_BUDGETS = {64: 2 * 10 ** 12, 256: 4 * 10 ** 12, 1024: 6 * 10 ** 12}


def every_chain_spec(path: Path, let_through: bool = False) -> Path:
    design = json.loads((ROOT / "tests" / "fixtures" / "a_design_of_four_starts.json").read_text())
    spec = json.loads((ROOT / "tests" / "fixtures" / "campaign_slice_engine.json").read_text())
    from graph_scale_dynamics.decisions.gates import LET_THROUGH_RULE
    from graph_scale_dynamics.scheduling.ladder_spec import engine_ladder
    spec["name"] = "every chain slice"
    spec["engine"]["policy"] = dict(spec["engine"]["policy"], every_chain=True)
    if let_through:
        spec["engine"]["policy"].update(LET_THROUGH, let_through_rule=LET_THROUGH_RULE)
    engine_ladder(spec, base_sizes=[64, 256, 1024], deep_sizes=[], seeds=3, budgets=dict(SLICE_BUDGETS),
                  audit_fraction=float(spec["engine"]["policy"].get("audit_fraction", 0.1)))
    spec["budgets"] = dict(spec["budgets"], max_n=1024)
    spec["sampling_contract"] = dict(spec.get("sampling_contract") or {}, given_starts=design["starts"])
    spec["limits"] = dict(spec["limits"], mean_degree_cap_armed_from_n=64)
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def run_every_chain(var_dir: Path, database: str, let_through: bool = False) -> None:
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.artifact_store.chain_record import read_record
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.replay import replay_matches
    from graph_scale_dynamics.services.api import readings_route

    shutil.rmtree(var_dir, ignore_errors=True)
    var_dir.mkdir(parents=True)
    spec_path = every_chain_spec(var_dir / "every_chain_campaign.json", let_through)
    require(rr("init", var=var_dir, database=database), "init")
    require(rr("benchmark", var=var_dir, database=database), "benchmark")
    started = rr("campaign", "start", "--spec", str(spec_path), var=var_dir, database=database)
    require(started, "campaign start")
    campaign = re.search(r"^Campaign (\S+) created", started.stdout, re.MULTILINE).group(1)
    submitted = rr("candidate", "submit", "--campaign", campaign, "--file", "candidate_sparse_anchor.json",
                   var=var_dir, database=database)
    require(submitted, "candidate submit")
    candidate = submitted.stdout.strip().splitlines()[-1]
    fleet = rr("run", "--campaign", campaign, "--workers", "2", "--wall", "600", "--no-dashboard",
               var=var_dir, database=database)
    given_chains = [start["name"] for start in json.loads(spec_path.read_text())["sampling_contract"]["given_starts"]]
    with Repo(database) as repo:
        count = lambda sql: [tuple(dict(r).values()) for r in repo.conn.execute(sql, (campaign,)).fetchall()]
        print("JOBS", count("SELECT n,status,COUNT(*) FROM jobs WHERE campaign_id=? GROUP BY n,status ORDER BY n,status"), flush=True)
        print("ANALYSES", count("SELECT n,status,COUNT(*) FROM analysis_queue WHERE campaign_id=? GROUP BY n,status ORDER BY n"), flush=True)
        print("FLEET OUTPUT", (fleet.stdout or "")[-1500:], (fleet.stderr or "")[-1500:], sep="\n", flush=True)
        require(fleet, "fleet")
        decisions = [dict(r) for r in repo.conn.execute(
            "SELECT action,rule,reason,next_n,at_n,priority,facts_json,inputs_json FROM engine_decisions "
            "WHERE campaign_id=? AND candidate_id=? ORDER BY decision_id", (campaign, candidate)).fetchall()]
        trail = [(d["at_n"], d["action"], d["rule"], d["next_n"]) for d in decisions]
        print("ENGINE TRAIL", trail, flush=True)
        assert len(trail) >= 3 and trail[1][:3] == (64, "run_next", "base_block"), trail
        assert trail[-1][0] == 1024 and trail[-1][1] != "run_next", trail
        decided = [d for d in decisions if d["inputs_json"] and d["at_n"]]
        assert decided, trail
        if let_through:
            from graph_scale_dynamics.db.decision_store import let_through_ledger
            from graph_scale_dynamics.decisions.engine import Policy
            policies = [json.loads(d["inputs_json"])["policy"] for d in decided]
            assert all(p["let_through_rule"] for p in policies), "every decision was made under 784's rule"
            ledger = let_through_ledger(repo.conn, "slice", fresh=True)
            document = ledger.document(Policy.from_spec(json.loads(spec_path.read_text())))
            print("LET THROUGH LEDGER", json.dumps(document["gates"]), document["signatures_total"], flush=True)
            assert document["decisions_read"] >= len(decided)
            signed = [json.loads(d["facts_json"]).get("signature") for d in decided if int(d["at_n"]) >= 256]
            assert all(signed), "every decision from let_through_from carries the law's signature"
        for decision in decided:
            inputs = json.loads(decision["inputs_json"])
            facts = json.loads(decision["facts_json"])
            assert sorted(inputs["chains"]) == sorted(given_chains), sorted(inputs.get("chains") or {})
            assert sorted(facts["chains"]) == sorted(["empty", *given_chains]), facts.get("chains")
            verdict = replay_matches(dict(decision, inputs=decision["inputs_json"]))
            assert verdict["matches"], (decision["rule"], verdict)
        for row in repo.conn.execute("SELECT n,metrics_json FROM measurements WHERE campaign_id=? AND candidate_id=?",
                                     (campaign, candidate)).fetchall():
            metrics = json.loads(row["metrics_json"])
            more = given_chains[1:]
            every = sorted(["empty", "given", *more])
            assert "more_given" not in metrics["census"] and sorted(metrics["census"]) == every, row["n"]
            assert sorted(metrics.get("more_meeting_readings") or {}) == sorted(more), row["n"]
            assert sorted(metrics["chain_probes"]) == sorted(["given", *more]), row["n"]
            assert sorted(set(metrics["chains_course"]) & set(every)) == every, row["n"]
            assert sorted(set(metrics["chain_mixing"]) & set(every)) == every, row["n"]
            assert set(every) <= set(metrics["descent"]["chains"]), row["n"]
            assert metrics["chain_probes"]["given"]["d_s"] is not None, "the random start's chain is read by every probe"
        diagnostics = {int(r["n"]): r["diagnostics"] for r in repo.rung_diagnostics(campaign, candidate)}
        assert sorted(diagnostics) == [64, 256, 1024], sorted(diagnostics)
        for n, d in diagnostics.items():
            assert d["every_chain"]["observables"]["energy_per_node"]["half_chains"] == 5 * 3 * 2, (n, d["every_chain"])
        store = BlobStore(var_dir / "blobs")
        for job in repo.jobs(campaign, kind="simulate"):
            if job.get("status") != "done":
                continue
            row = repo.conn.execute("SELECT record_artifact FROM artifact_retention WHERE artifact_hash=?",
                                    (job["result_artifact"],)).fetchone()
            record = read_record(store, row["record_artifact"])
            assert sorted(chain["start"] for chain in record["chains"][2:]) == sorted(given_chains[1:]), job["job_id"]
        page = readings_route.structure(repo, campaign, candidate)
        assert [c["name"] for c in page["chains"]["every_chain"]] == ["empty", *given_chains]
        assert page["given_start"].startswith("the random start, random_mean_degree_")
        json.dumps(page, allow_nan=False)
        print("LET THROUGH SLICE OK" if let_through else "EVERY CHAIN SLICE OK", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--var", type=Path, required=True)
    parser.add_argument("--engine", action="store_true", help="accepted for compatibility; the engine slice is the only slice")
    parser.add_argument("--every-chain", action="store_true", help="598: a law with five chains")
    parser.add_argument("--let-through", action="store_true", help="784: the every-chain slice under one let-through rule")
    args = parser.parse_args(argv)
    schema = os.environ.get("GSD_TEST_SCHEMA")
    if not schema:
        raise SystemExit("GSD_TEST_SCHEMA is required for the isolated integration slice")
    database = f"folder-schema:{schema}"
    try:
        if args.let_through:
            run_every_chain(args.var, database, let_through=True)
        else:
            (run_every_chain if args.every_chain else run_engine)(args.var, database)
    finally:
        shutil.rmtree(args.var, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
