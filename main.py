from __future__ import annotations
import argparse, json, os, secrets, shutil, signal, stat, subprocess, sys, time

_EARLY_NATIVE_THREADS = str(max(1, int(os.environ.get("GSD_NATIVE_THREADS", "1"))))
for _native_key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_native_key] = _EARLY_NATIVE_THREADS
from importlib.resources import files as resource_files
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.operations.browser_launch import browser_launcher
from graph_scale_dynamics.operations.service_restart import (
    _back_off, _launched, _service_crash_disposition,
)
from graph_scale_dynamics.operations.folder_guard import (
    FLEET_PID_FILE, SERVE_PID_FILE, live_fleet, live_in_folder, on_record, postgres_running, record_this_process,
    reap_orphaned_fleet_lock as _reap_orphaned_fleet_lock, unlink_if_ours,
)
from graph_scale_dynamics.operations import campaign_control, power_sidecar
from graph_scale_dynamics.operations.process_ownership import interrupt_on, owned_env
from graph_scale_dynamics.scheduling.campaign_limits import campaign_wall_seconds
from graph_scale_dynamics.db.connection import (
    DatabaseOperationalError, display_target, resolve_target, service_database_reference,
)
from graph_scale_dynamics.domain.model import CandidateState, POLICY_RULE_VERSION, content_hash
from graph_scale_dynamics.domain.version import BUILD_NUMBER

DATABASE_LOST_EXIT_CODE = 7

DEFAULT_HOME_CAMPAIGN_SPEC = "campaign_engine_survey.json"


def _engine_required(spec: dict) -> list[str]:
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    return [] if is_engine_campaign(spec) else [
        "the spec declares no decision engine (an `engine` block with its contract); campaigns "
        "without one are refused"]
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.scheduling.cpu import cpu_topology, choose_auto_slots
from graph_scale_dynamics.scheduling.concurrency import (
    CPU_BACKOFF_PERCENT, CPU_TARGET_PERCENT, FLOOR_SLOTS, CpuSlope, HostCpuMeter, RAMP_CONTRACT,
    STEP_HOLD_SECONDS, STEP_SLOTS, cold_start_slots, connection_headroom, prior_cpu_per_slot,
    ramp_ceiling, ramp_decision,
)
from graph_scale_dynamics.scheduling.campaign import validate_campaign
from graph_scale_dynamics.scheduling import worker_count
from graph_scale_dynamics.scheduling.provenance import (
    freeze_campaign_spec,
    provenance_mismatches,
)
from graph_scale_dynamics.research.proposal_intelligence import SEARCH_SPACE_VERSION


def startup_banner() -> None:
    print(f"Graph Scale Dynamics — Build {BUILD_NUMBER}", flush=True)
    print(f"Project root: {ROOT}", flush=True)
    _pg_bin = os.environ.get("GSD_POSTGRES_SYSTEM_BIN", "").strip()
    print(("Database: PostgreSQL host binaries via GSD_POSTGRES_SYSTEM_BIN=" + _pg_bin +
           " in the folder-local userns container (folder-contained state)") if _pg_bin else
          "Database: PostgreSQL 17.10 embedded OCI/userns container (folder-contained state)", flush=True)


def read_config_file(value: str) -> dict:
    path = Path(value).expanduser()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    packaged = resource_files("graph_scale_dynamics.resources").joinpath("configs", path.name)
    if packaged.is_file():
        return json.loads(packaged.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"configuration file not found: {value}")


read_spec_file = read_config_file


def _calibration_table_path(var: Path) -> Path:
    from graph_scale_dynamics.calibration import resolve_table
    path, _document, _kind = resolve_table(ROOT, var)
    return path


def paths(args):
    var = Path(args.var).expanduser()
    if not var.is_absolute():
        var = ROOT / var
    var = var.resolve()
    try:
        var.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            f"state directory must remain beneath project root {ROOT}: {var}"
        ) from exc
    if os.environ.get("GSD_INTEGRATION_TEST") == "1":
        schema = os.environ.get("GSD_TEST_SCHEMA")
        if not schema:
            raise ValueError("GSD_INTEGRATION_TEST requires GSD_TEST_SCHEMA")
        database = resolve_target(f"folder-schema:{schema}")
    else:
        database = resolve_target("folder")
    return database, var / "blobs", var


def _write_dashboard_admin_capability(var: Path, *, port: int, base_path: str, token: str):
    prefix = ("/" + str(base_path or "").strip("/")) if base_path else ""
    local_url = f"http://127.0.0.1:{port}{prefix}/"
    admin_url = local_url + f"#admin={token}"
    run_dir = var / "run"
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    if stat.S_IMODE(run_dir.stat().st_mode) != 0o700:
        raise PermissionError(f"dashboard runtime directory is not private: {run_dir}")

    path = run_dir / "dashboard-admin"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(admin_url + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            raise PermissionError(f"dashboard admin capability is not private: {path}")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    return path, local_url, admin_url, prefix


def _lan_address() -> str | None:
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    documentation = ("192.0.2.", "198.51.100.", "203.0.113.")
    return None if address.startswith(("127.", *documentation)) or address == "0.0.0.0" else address


def _dashboard_process_environment(base_env: dict[str, str], capability_file: Path) -> dict[str, str]:
    proc_env = dict(base_env)
    proc_env.pop("GSD_DASHBOARD_ADMIN_TOKEN", None)
    proc_env["GSD_DASHBOARD_ADMIN_FILE"] = str(capability_file)
    return proc_env


def _write_internal_api_capability(var: Path) -> Path:
    run_dir = var / "run"
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    path = run_dir / "internal-api-token"
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (token + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def _stop_folder_postgres(*, timeout: float = 75.0) -> bool:
    if os.environ.get("GSD_INTEGRATION_TEST") == "1":
        return True
    helper = ROOT / "tools" / "postgres_instance.py"
    try:
        completed = subprocess.run([sys.executable, str(helper), "stop"], cwd=ROOT,
                                   timeout=timeout, text=True, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"PostgreSQL shutdown helper failed: {type(exc).__name__}: {exc}")
        return False
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if output:
        print(output)
    if completed.returncode != 0:
        print(f"PostgreSQL shutdown helper exited {completed.returncode}")
        return False
    print("folder-local PostgreSQL stopped cleanly")
    return True


def _verify_installation_identity(expected_fingerprint: str, *, root: Path = ROOT,
                                  expected_build: int = BUILD_NUMBER) -> str:
    from graph_scale_dynamics.domain.version import DeploymentProvenanceFence, source_fingerprint

    build_file = root / "BUILD_NUMBER"
    if build_file.is_file():
        try:
            disk_build = int(build_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            raise DeploymentProvenanceFence(
                f"could not verify on-disk build identity: {exc}"
            ) from exc
        if disk_build != expected_build:
            raise DeploymentProvenanceFence(
                f"on-disk build changed from {expected_build} to {disk_build}"
            )
    observed = source_fingerprint(root)
    if observed != expected_fingerprint:
        raise DeploymentProvenanceFence(
            f"runtime source fingerprint changed: expected {expected_fingerprint}, observed {observed}"
        )
    return observed


def cmd_init(args):
    db, blobs, var = paths(args)
    init_db(db)
    blobs.mkdir(parents=True, exist_ok=True)
    print(f"initialized {display_target(db)} and {blobs}")


def cmd_benchmark(args):
    from graph_scale_dynamics.measurements.benchmarks import run_battery
    db, _, _ = paths(args)
    init_db(db)
    report = run_battery(seed=1)
    with Repo(db) as repo:
        repo.record_benchmark(ANALYSIS_VERSION, report["passed"], report)
    for check in report["checks"]:
        print(("PASS  " if check["passed"] else "FAIL  ") + check["name"])
    print(f"analyzer benchmark battery ({ANALYSIS_VERSION}):", "PASSED" if report["passed"] else "FAILED")
    return 0 if report["passed"] else 1


def cmd_calibration_rekey(args):
    from graph_scale_dynamics.calibration.rekey import rekey, render
    _, _, var = paths(args)
    budget = None if (args.budget is not None and args.budget <= 0) else args.budget
    report = rekey(var=var, sample=args.sample, budget_seconds=budget,
                   workers=args.workers, deep=args.deep,
                   inert_observables=args.inert_observable,
                   apply=args.apply, justification=args.justification)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print()
        print(render(report))
    return 0 if report["status"] in ("VERIFIED", "APPLIED", "NOTHING_STALE") else 2


def cmd_rebuild_phenotypes(args):
    from graph_scale_dynamics.research.phenotype_rebuild import rebuild_phenotypes, render
    db, _, _ = paths(args)
    report = rebuild_phenotypes(db, campaign_id=args.campaign,
                                apply=args.apply, limit=args.limit)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


def cmd_audit(args):
    from graph_scale_dynamics.operations.audit import (
        audit_state, repair_missing_derived_blobs, report_exit_code,
    )
    db, blobs, _ = paths(args)
    repair_report = None
    with Repo(db) as repo:
        if args.repair_missing_derived:
            if not args.yes:
                print("refusing derived-blob repair without --yes")
                return 2
            lock_name = "gsd:fleet"
            if not repo.acquire_service_lock(lock_name):
                print("refusing derived-blob repair while a research fleet owns this database")
                return 3
            try:
                repair_report = repair_missing_derived_blobs(repo, blobs)
            finally:
                repo.release_service_lock(lock_name)
        report = audit_state(
            repo.conn, blobs, verify_hashes=not args.metadata_only,
            include_orphans=not args.no_orphans, max_detail=max(0, args.max_detail),
            statement_timeout_ms=max(0, int(args.timeout)) * 1000,
        )
    if repair_report is not None:
        report["repair_missing_derived"] = repair_report
    print(json.dumps(report, indent=2, sort_keys=True))
    return report_exit_code(report, args.fail_on)


def cmd_backup(args):
    from graph_scale_dynamics.operations.backup import create_backup
    db, blobs, var = paths(args)
    report = create_backup(db, blobs, Path(args.output), allow_live=args.allow_live, var=var)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_restore(args):
    from graph_scale_dynamics.operations.backup import restore_backup, restore_var_state
    if live := live_in_folder(ROOT):
        print(f"refusing to restore: {live}. Stop it first; nothing was changed.")
        return 2
    db, blobs, var = paths(args)
    manifest = restore_backup(Path(args.backup), db, blobs, force=args.force)
    restored = restore_var_state(Path(args.backup), manifest, var, force=args.force)
    print(f"restored build {manifest.get('build')}'s backup of {manifest.get('created_utc')}: the database, "
          f"{manifest['blobs']['count']:,} blobs and {len(restored)} state file(s)")
    return 0


def _fmt_bytes(value: int | float | None) -> str:
    value = float(value or 0)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TiB"


def _campaign_id_arg(args) -> str | None:
    return (getattr(args, "campaign_id", None) or "").strip() or None


def _campaign_rows_with_storage(repo: Repo) -> list[dict]:
    from graph_scale_dynamics.operations.campaign_control import reporting_focus
    home = str(reporting_focus(repo) or "")
    rows = []
    for campaign in repo.all_campaigns():
        profile = repo.campaign_storage_profile(campaign["campaign_id"])
        stats = repo.campaign_stats(campaign["campaign_id"])
        rows.append(campaign | {"storage": profile, "stats": stats,
                                "is_home": campaign["campaign_id"] == home})
    return rows


def _print_campaign_table(repo: Repo) -> list[dict]:
    rows = _campaign_rows_with_storage(repo)
    if not rows:
        print("no campaigns")
        return []
    print("#  campaign  role          status      candidates   jobs       DB logical   blobs       exclusive    compute")
    for index, row in enumerate(rows, 1):
        stats = row["stats"]
        jobs = sum(int(v or 0) for v in (stats.get("job_counts") or {}).values())
        storage = row["storage"]
        marker = " *home*" if row["is_home"] else ""
        role = str(row.get("campaign_role") or ("confirmation" if row["spec"].get("mode") == "confirmation" else "discovery"))
        print(f"{index:<2} {row['campaign_id']:<8} {role:<13} {row['status']:<11} "
              f"{int(stats.get('candidates') or 0):>10} {jobs:>7}   "
              f"{_fmt_bytes(storage.get('db_logical_bytes')):>10}   "
              f"{_fmt_bytes(storage.get('blob_bytes')):>9}   "
              f"{_fmt_bytes(storage.get('exclusive_blob_bytes')):>9}   "
              f"{stats.get('compute_seconds', 0)/3600:>7.1f}h{marker}")
    print("\nDB logical is attributable row payload, not PostgreSQL relation-page usage. ")
    print("blobs/exclusive = physical retained blob bodies; evicted logical artifact identities remain in provenance.")
    return rows


def _confirm_action(prompt: str, *, yes: bool = False, echo: str | None = None) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(prompt + " (refusing without --yes in a non-interactive shell)")
        return False
    if echo is not None:
        print(prompt)
        return input(f"type {echo!r} to confirm, anything else aborts: ").strip() == echo
    return input(prompt + " [y/N] ").strip().lower() in {"y", "yes"}


def _delete_campaign_easy(repo: Repo, campaign_id: str, *, yes: bool = False,
                          cascade: bool = False) -> int:
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        print(f"unknown campaign {campaign_id}")
        return 2
    children = repo.dependent_campaigns(campaign_id)
    if children and not cascade:
        print("campaign has dependent child campaigns: " + ", ".join(c["child_campaign_id"] for c in children))
        print("rerun with --cascade to delete those campaign records too")
        return 2
    if not _confirm_action(
            f"DELETE campaign {campaign_id}: discard its database research state "
            f"(raw blobs remain GC-eligible).",
            yes=yes, echo=str(campaign_id)):
        print("nothing deleted")
        return 1
    if cascade:
        for child in reversed(children):
            code = _delete_campaign_easy(repo, child["child_campaign_id"], yes=True, cascade=True)
            if code:
                return code
    from graph_scale_dynamics.operations.maintenance import exclusive_maintenance
    with exclusive_maintenance(repo):
        print(f"fencing queued/leased work for {campaign_id}...", flush=True)
        stopped = repo.stop_campaign_work(campaign_id, reason="campaign deleted by operator")
        print(f"deleting {campaign_id} with indexed, bounded database cleanup...", flush=True)
        removed = repo.delete_campaign(
            campaign_id, force=True,
            progress=lambda message: print(message, flush=True),
        )
        if repo.get_flag("home_campaign", "") == campaign_id:
            repo.set_flag("home_campaign", "")
    print(json.dumps({"campaign": campaign_id, "stopped": stopped, "deleted": removed},
                     indent=2, sort_keys=True))
    print("raw blobs are retained until reference-aware GC: `python main.py artifacts gc`")
    return 0


def _archive_campaign_cli(repo: Repo, blobs: Path, campaign_id: str, *, yes: bool = False,
                          allow_incomplete: bool = False) -> int:
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        print(f"unknown campaign {campaign_id}")
        return 2
    profile = repo.campaign_storage_profile(campaign_id)
    unmeasured = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM jobs j WHERE j.campaign_id=? AND j.result_artifact IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM measurements m WHERE m.campaign_id=j.campaign_id "
        "AND m.input_artifact=j.result_artifact)", (campaign_id,),
    ).fetchone()["c"] or 0)
    if not _confirm_action(
            f"ARCHIVE {campaign_id}: verify/condense {_fmt_bytes(profile.get('blob_bytes'))} of raw blobs; "
            f"finish analysis for {unmeasured} unmeasured run(s); retain compact evidence in the database; "
            "retire live rows; and make unshared blobs GC-eligible?",
            yes=yes):
        print("nothing archived")
        return 1
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.operations.campaign_archive import archive_campaign
    report = archive_campaign(
        repo, BlobStore(blobs), campaign_id,
        progress=lambda message: print(message, flush=True),
        allow_incomplete=allow_incomplete,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print("archive complete. Raw graph blobs are no longer required by this campaign. ")
    print("Preview reclaimable storage with `python main.py artifacts gc`; apply GC when convenient.")
    return 0


def _campaign_manager(repo: Repo, blobs: Path) -> int:
    rows = _print_campaign_table(repo)
    if not rows or not sys.stdin.isatty():
        return 0
    print("\nActions take a CAMPAIGN ID, not a row number:")
    print("  a <id> archive   d <id> delete   s <id> stop   u <id> report on   q quit")
    while True:
        raw = input("campaign> ").strip()
        if not raw or raw.lower() in {"q", "quit", "exit"}:
            return 0
        parts = raw.split()
        known = {str(row["campaign_id"]) for row in rows}
        if len(parts) != 2 or parts[1] not in known:
            print("use a campaign id, e.g. `d 5`. Known ids: "
                  + ", ".join(sorted(known, key=lambda v: (len(v), v)))
                  + "   (from the `campaign` column, not the `#` column)")
            continue
        action, cid = parts[0].lower(), parts[1]
        if action == "a":
            code = _archive_campaign_cli(repo, blobs, cid)
        elif action == "d":
            code = _delete_campaign_easy(repo, cid)
        elif action == "s":
            print(json.dumps(repo.stop_campaign_work(cid), indent=2, sort_keys=True))
            code = 0
        elif action == "u":
            campaign = repo.campaign(cid)
            if campaign and campaign["status"] == "active" and campaign["spec"].get("mode") == "continuous":
                repo.set_flag("home_campaign", cid)
                print(f"reports now follow {cid}")
                code = 0
            else:
                print("reports can only follow an active continuous campaign")
                code = 2
        else:
            print("unknown action")
            continue
        if code == 0:
            rows = _print_campaign_table(repo)


def _store_campaign_report_artifact(repo: Repo, blobs: Path, value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"based-on report not found: {value}")
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    store = BlobStore(blobs)
    staging = store.staging_dir("campaign-report-" + secrets.token_hex(8))
    target = staging / path.name
    try:
        shutil.copy2(path, target)
        digest, size = store.commit_file(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    suffix = path.suffix.lower()
    media = {".json": "application/json", ".html": "text/html", ".md": "text/markdown"}.get(
        suffix, "application/octet-stream")
    repo.register_external_artifact(digest, size, media, {
        "kind": "campaign-motivation-report",
        "source_name": path.name,
    })
    return digest, digest


def _new_campaign_from_spec(repo: Repo, blobs: Path, spec: dict, *,
                            parent_campaign_id: str | None = None,
                            reason: str | None = None, based_on_report: str | None = None,
                            search_seed: int | None = None, role: str | None = None) -> dict:
    artifact, report_sha = _store_campaign_report_artifact(repo, blobs, based_on_report)
    return campaign_control.create_campaign(
        repo, spec, parent_campaign_id=parent_campaign_id, reason=reason,
        search_seed=search_seed, role=role,
        report_artifact=artifact, report_sha256=report_sha)


def _print_campaign_provenance(repo: Repo, campaign_id: str, var: Path, output: str | None = None) -> int:
    campaign = repo.campaign(str(campaign_id))
    if campaign is None:
        print(f"unknown campaign {campaign_id}")
        return 2
    payload = {
        "research_instance_id": repo.research_instance_id(),
        "campaign_id": campaign["campaign_id"],
        "campaign_role": campaign.get("campaign_role"),
        "parent_campaign_id": campaign.get("parent_campaign_id"),
        "campaign_series_id": campaign.get("campaign_series_id"),
        "status": campaign.get("status"),
        "created_utc": campaign.get("created_utc"),
        "created_build": campaign.get("created_build"),
        "created_runtime_fingerprint": campaign.get("created_runtime_fingerprint"),
        "search_seed": campaign.get("search_seed"),
        "science_contract_hash": campaign.get("science_contract_hash"),
        "search_policy_hash": campaign.get("search_policy_hash"),
        "resource_policy_hash": campaign.get("resource_policy_hash"),
        "experiment_config_hash": campaign.get("experiment_config_hash"),
        "spec_fingerprint": campaign.get("spec_hash"),
        "change_reason": campaign.get("change_reason"),
        "based_on_report_artifact": campaign.get("based_on_report_artifact"),
        "based_on_report_sha256": campaign.get("based_on_report_sha256"),
        "provenance_contract": campaign.get("provenance_contract"),
        "provenance_mismatches": provenance_mismatches(campaign),
        "events": repo.campaign_events(str(campaign_id)),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if output:
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = ROOT / path
    else:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = var / "reports" / f"campaign-provenance_campaign-{campaign_id}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    print(f"provenance JSON: {path}")
    return 0


def cmd_campaign(args):
    db, blobs, var = paths(args)
    init_db(db)
    with Repo(db) as repo:
        if args.sub is None:
            return _campaign_manager(repo, blobs)
        if args.sub == "list":
            _print_campaign_table(repo)
            return 0
        if args.sub == "provenance":
            return _print_campaign_provenance(repo, args.campaign_id, var, getattr(args, "output", None))
        if args.sub == "use":
            campaign_id = _campaign_id_arg(args)
            campaign = repo.campaign(campaign_id) if campaign_id else None
            if campaign is None:
                print(f"unknown campaign {campaign_id}")
                return 2
            if campaign["status"] != "active":
                print(f"refusing to use {campaign['status']} campaign {campaign_id} as home")
                return 2
            if campaign["spec"].get("mode") != "continuous":
                print("refusing to set a non-continuous campaign as the home discovery campaign")
                return 2
            if repo.campaign_link(campaign_id) is not None:
                print("refusing to set a linked confirmation campaign as the home discovery campaign")
                return 2
            repo.set_flag("home_campaign", campaign_id)
            print(f"home campaign set to {campaign_id}")
            return 0
        if args.sub == "reopen":
            campaign_id = _campaign_id_arg(args)
            campaign = repo.campaign(campaign_id) if campaign_id else None
            if campaign is None:
                print(f"unknown campaign {campaign_id}")
                return 2
            if campaign.get("status") == "active":
                print(f"Campaign {campaign_id} is already active")
                return 0
            if not _scientific_contract_matches_current(campaign["spec"]):
                _refuse_foreign_contract(campaign_id, campaign["spec"])
                return 2
            outcome = campaign_control.reopen(
                repo, campaign_id, reason=getattr(args, "reason", None)
                or "operator resumed closed immutable discovery campaign")
            if not outcome["ok"]:
                print(f"refusing Campaign {campaign_id}: {outcome['problem']}")
                return 2
            print(f"Campaign {campaign_id} reopened with its original immutable policy "
                  f"and search seed {outcome['search_seed']}")
            if campaign["spec"].get("mode") == "continuous":
                print(f"existing candidate/evidence history is retained; home campaign set to {campaign_id}")
            else:
                print(f"existing candidate/evidence history is retained; run explicitly with --campaign {campaign_id}")
            return 0
        if args.sub in {"pause", "resume"}:
            campaign_id = _campaign_id_arg(args)
            act = campaign_control.pause if args.sub == "pause" else campaign_control.resume
            done = act(repo, campaign_id, reason=getattr(args, "reason", None)
                       or f"operator {args.sub}d the campaign from the command line")
            if not done["ok"]:
                print(done["problem"], file=sys.stderr)
                return 2
            print(f"campaign {campaign_id} is {done.get('state')}: {done['reading']}")
            return 0
        if args.sub == "close":
            campaign_id = _campaign_id_arg(args)
            if not campaign_id or repo.campaign(campaign_id) is None:
                print(f"unknown campaign {campaign_id}")
                return 2
            stopped = repo.stop_campaign_work(campaign_id)
            if repo.get_flag("home_campaign", "") == campaign_id:
                repo.set_flag("home_campaign", "")
            children = [link["child_campaign_id"]
                        for link in repo.child_campaigns(campaign_id)
                        if link.get("status") == "active"]
            cascaded = {}
            if children and not getattr(args, "keep_children", False):
                for child in children:
                    cascaded[child] = repo.stop_campaign_work(
                        child, reason=f"parent campaign {campaign_id} was closed")
            print(json.dumps({"campaign": campaign_id, **stopped,
                              "linked_confirmations_closed": sorted(cascaded)},
                             indent=2, sort_keys=True))
            print("campaign stopped; all queued/leased work was fenced immediately")
            if cascaded:
                print(f"also closed {len(cascaded)} linked confirmation campaign(s): "
                      + ", ".join(sorted(cascaded)))
            elif children:
                print(f"left {len(children)} linked confirmation campaign(s) active: "
                      + ", ".join(sorted(children)))
            return 0
        if args.sub == "delete":
            campaign_id = _campaign_id_arg(args)
            if not campaign_id:
                print("campaign id required")
                return 2
            return _delete_campaign_easy(repo, campaign_id, yes=bool(args.yes),
                                         cascade=bool(args.cascade))
        if args.sub == "archive":
            campaign_id = _campaign_id_arg(args)
            if not campaign_id:
                print("campaign id required")
                return 2
            return _archive_campaign_cli(repo, blobs, campaign_id, yes=bool(args.yes),
                                         allow_incomplete=bool(args.allow_incomplete))

        spec = read_spec_file(args.spec)
        problems = validate_campaign(spec) + _engine_required(spec)
        if problems:
            print("refusing invalid campaign specification:")
            for problem in problems:
                print(f"  - {problem}")
            return 2
        if str(spec.get("analysis_version")) != ANALYSIS_VERSION:
            print(f"refusing to create a new campaign on legacy analysis contract "
                  f"{spec.get('analysis_version')}; new campaigns must use {ANALYSIS_VERSION}")
            return 2
        benchmark = repo.benchmark(ANALYSIS_VERSION)
        if not (benchmark and benchmark["passed"]):
            if args.allow_unvalidated_analyzer:
                print("warning: analyzer benchmark battery has not passed for this analysis version")
            else:
                print("refusing to start: the analyzer benchmark battery must pass first "
                      "(run `python3 main.py benchmark`), per review section 10")
                return 1
        try:
            created = _new_campaign_from_spec(
                repo, blobs, spec,
                parent_campaign_id=getattr(args, "parent", None),
                reason=getattr(args, "reason", None),
                based_on_report=getattr(args, "based_on_report", None),
                search_seed=getattr(args, "search_seed", None),
            )
        except (FileNotFoundError, ValueError, KeyError) as exc:
            print(f"refusing campaign creation: {exc}")
            return 2
        campaign_id = created["campaign_id"]
        print(campaign_id)
        print(
            f"Campaign {campaign_id} created · search={created.get('search_policy_hash','')[:12]} "
            f"resource={created.get('resource_policy_hash','')[:12]} "
            f"science={created.get('science_contract_hash','')[:12]}"
        )
        from graph_scale_dynamics.scheduling.limits import describe as describe_limits
        print(describe_limits(spec))
        from graph_scale_dynamics.scheduling.reach import describe as describe_reach
        print(describe_reach(spec))
        return 0


def cmd_compute_control(args):
    db, _, _ = paths(args)
    init_db(db)
    paused = args.cmd == "pause"
    with Repo(db) as repo:
        repo.set_flag("paused", "1" if paused else "0")
        cancellation = (
            repo.operator_pause_cancel_active_work(reason="user cancelled by CLI PAUSE")
            if paused else None
        )
    if paused:
        print(
            "compute paused immediately; active scientific leases fenced and returned to queue"
            + (
                f" ({cancellation.get('jobs_user_cancelled', 0)} simulation, "
                f"{cancellation.get('analysis_user_cancelled', 0)} analysis, "
                f"{cancellation.get('rebuilds_user_cancelled', 0)} rebuild)"
                if cancellation is not None else ""
            )
        )
    else:
        print("compute resumed")
    return 0


def cmd_workload(args):
    from graph_scale_dynamics.scheduling import work_groups
    db, _, _ = paths(args)
    init_db(db)
    with Repo(db) as repo:
        code, said = work_groups.command(repo, args.split, args.system_cpus)
    print(said, file=sys.stderr if code else sys.stdout)
    return code


def cmd_focus(args):
    from graph_scale_dynamics.operations import focus
    db, _, _ = paths(args)
    init_db(db)
    with Repo(db) as repo:
        code, said = focus.command(repo, args.study, args.law, args.show)
    print(said, file=sys.stderr if code else sys.stdout)
    return code


def cmd_extend_only(args):
    db, _, _ = paths(args)
    init_db(db)
    with Repo(db) as repo:
        campaign_id = str(args.campaign)
        if repo.campaign(campaign_id) is None:
            print(f"refused: no campaign {campaign_id}", file=sys.stderr)
            return 2
        if args.on == args.off:
            state = repo.campaign_extend_only(campaign_id)
            print(f"campaign {campaign_id}: "
                  + ("extend-only; the proposer will not add candidates"
                     if state else "open; the proposer tops up as usual"))
            return 0
        state = repo.set_campaign_extend_only(campaign_id, bool(args.on))
        if state:
            print(f"campaign {campaign_id} is now extend-only. No new candidates.\n"
                  "Queued jobs, the analysis backlog, continuation waves and any rung\n"
                  "the controller decides to climb all continue. A campaign with\n"
                  "nothing left to extend goes idle, which is the finished state.")
        else:
            print(f"campaign {campaign_id} is open again; the proposer tops it up")
        return 0


def cmd_artifacts(args):
    db, blobs, _ = paths(args)
    init_db(db)
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    store = BlobStore(blobs)
    with Repo(db) as repo:
        if args.sub == "gc":
            from graph_scale_dynamics.operations.artifact_gc import collect_artifacts
            if args.apply and args.confirm != "GC":
                print("refusing destructive artifact GC: add --confirm GC")
                return 2
            report = collect_artifacts(repo, store, apply=bool(args.apply))
        elif args.sub == "retention":
            from graph_scale_dynamics.operations.artifact_retention import retention_summary
            report = retention_summary(repo, args.campaign)
        else:
            return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _proposal_campaign(repo: Repo, explicit: str | None) -> str:
    from graph_scale_dynamics.operations.campaign_control import reporting_focus
    campaign_id = (explicit or str(reporting_focus(repo) or "")).strip()
    if not campaign_id:
        raise ValueError("no --campaign supplied and no active continuous campaign to default to")
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        raise ValueError(f"unknown campaign {campaign_id}")
    if campaign["spec"].get("mode") != "continuous":
        raise ValueError("proposal intelligence applies only to continuous discovery campaigns")
    return campaign_id


def cmd_proposal(args):
    db, _, _ = paths(args)
    init_db(db)
    with Repo(db) as repo:
        try:
            campaign_id = _proposal_campaign(repo, getattr(args, "campaign", None))
        except ValueError as exc:
            print(str(exc))
            return 2
        campaign = repo.campaign(campaign_id)
        mode = str(((campaign or {}).get("spec") or {}).get("proposer", {})
                   .get("family_memory", {}).get("mode", "shadow"))
        print(json.dumps({"campaign_id": campaign_id, "mode": mode}, sort_keys=True))
        return 0

def cmd_candidate_submit(args):
    db, _, _ = paths(args)
    repo = Repo(db)
    campaign = repo.campaign(args.campaign)
    if campaign is None:
        print(f"unknown campaign {args.campaign}")
        return 2
    raw = read_config_file(args.file)
    problems = dsl.validate(raw, complexity_budget=campaign["spec"].get("complexity_budget", 6),
                            operator_whitelist=campaign["spec"].get("operator_whitelist"))
    normalized = dsl.normalize(raw) if not problems else raw
    fingerprint = dsl.fingerprint(raw) if not problems else content_hash(raw)
    repo.insert_candidate(fingerprint, args.campaign, normalized,
                          normalized.get("dynamics", {}).get("kind", "unknown"),
                          dsl.complexity(normalized), CandidateState.PROPOSED.value)
    if problems:
        print(f"submitted with static problems (controller will reject): {problems}")
    print(fingerprint)
    return 0


def _service_cmd(module, db, blobs, campaign, var, extra=()):
    return [sys.executable, "-m", module, "--db", service_database_reference(db), "--campaign", campaign,
            *(("--blobs", str(blobs)) if module in (
                "graph_scale_dynamics.services.executor.main", "graph_scale_dynamics.services.maintenance.main", "graph_scale_dynamics.services.controller.main"
            ) else ()),
            "--var", str(var), *extra]


IDENTITY_SCAN_KEY = "candidate_identity_scan"


def quarantine_invalid_candidate_identities(repo: Repo, var: Path | None = None) -> list[str]:
    quarantined: list[str] = []
    contract = getattr(dsl, "IDENTITY_CONTRACT", None) or getattr(dsl, "CONTRACT", "dsl")
    mark_path = (Path(var) / IDENTITY_SCAN_KEY).with_suffix(".json") if var else None
    watermark, covered = None, 0
    if mark_path and mark_path.is_file():
        try:
            mark = json.loads(mark_path.read_text(encoding="utf-8"))
            if str(mark.get("contract")) == str(contract):
                watermark = mark.get("through_created_utc")
                covered = int(mark.get("covered") or 0)
        except (OSError, ValueError):
            watermark = None

    if watermark:
        cursor = repo.conn.execute(
            "SELECT candidate_id,spec_json,created_utc FROM candidate_specs "
            "WHERE created_utc > ? ORDER BY created_utc", (watermark,))
    else:
        cursor = repo.conn.execute(
            "SELECT candidate_id,spec_json,created_utc FROM candidate_specs "
            "ORDER BY created_utc")

    scanned, newest = 0, watermark
    for row in cursor:
        scanned += 1
        created = row["created_utc"] if "created_utc" in row.keys() else None
        if created and (newest is None or created > newest):
            newest = created
        spec = json.loads(row["spec_json"])
        problems = dsl.execution_identity_problems(spec, row["candidate_id"])
        if not problems:
            continue
        reason = "candidate execution identity invalid: " + "; ".join(problems)
        repo.quarantine_candidate_identity(row["candidate_id"], reason)
        quarantined.append(row["candidate_id"])

    if newest and mark_path is not None:
        try:
            mark_path.parent.mkdir(parents=True, exist_ok=True)
            mark_path.write_text(json.dumps({
                "contract": str(contract), "through_created_utc": newest,
                "covered": covered + scanned,
                "reading": ("specs created at or before this timestamp were verified "
                            "under this identity contract and are not re-verified on "
                            "restart. Delete this file to force a full rescan."),
            }, indent=1), encoding="utf-8")
        except OSError:
            pass
    if scanned:
        print(f"candidate identity scan: {scanned} new spec(s) verified"
              + (f", {covered} covered by a previous scan" if covered else ""))
    return quarantined


def _analyzer_capacity(total_slots: int) -> int:
    total = max(1, int(total_slots))
    configured = os.environ.get("GSD_ANALYZERS")
    if configured is not None:
        return max(0, min(total, int(configured)))
    try:
        import psutil
        available = int(psutil.virtual_memory().available)
    except Exception:  # pragma: no cover
        return min(total, 2)
    reserve = max(256 * 1024 ** 2, int(os.environ.get(
        "GSD_ANALYZER_SLOT_BYTES", str(1536 * 1024 ** 2)
    )))
    memory_slots = max(1, available // reserve)
    return min(total, memory_slots)


RAMP_TICK_SECONDS = 4.0
RAMP_LOG = os.environ.get("GSD_RAMP_LOG", "") not in ("", "0", "false", "no")


RAMP_SLOPE_FLAG = "concurrency_cpu_per_slot"


def _learned_slope(repo) -> CpuSlope:
    logical = cpu_topology()[1]
    slope = CpuSlope(prior_cpu_per_slot(logical))
    try:
        kept = json.loads(repo.get_flag(RAMP_SLOPE_FLAG, "") or "{}")
        if int(kept.get("logical") or 0) == logical and float(kept.get("cpu_per_slot") or 0) > 0:
            slope = CpuSlope(slope.prior, value=float(kept["cpu_per_slot"]),
                             samples=int(kept.get("samples") or 0))
    except (TypeError, ValueError):
        pass
    return slope


def _concurrency_ramp_tick(repo, *, state: dict, baseline: int, ceiling: int,
                           spawn_executor) -> str | None:
    from graph_scale_dynamics.scheduling.memory import (
        host_available_floor_bytes, host_memory_launch_guard, system_memory)
    active = int(repo.get_flag("compute_active_slots", str(baseline)) or baseline)
    try:
        snapshot = repo.scheduler_snapshot() or {}
        memory = system_memory()
        guard = host_memory_launch_guard(snapshot=memory)
        row = repo.conn.execute(
            "SELECT (SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database()) used,"
            "current_setting('max_connections')::INTEGER limit_,"
            "(SELECT COUNT(*) FROM jobs WHERE status='leased')"
            "+(SELECT COUNT(*) FROM analysis_queue WHERE status='leased') running").fetchone()
        slope = state.get("slope") or state.setdefault("slope", _learned_slope(repo))
        cpu, running = state["meter"].sample(), int(row["running"] or 0)
        settled = time.monotonic() - float(state["stepped_at"]) >= STEP_HOLD_SECONDS
        if settled and slope.observe(running, cpu) is not None:
            repo.set_flag(RAMP_SLOPE_FLAG, json.dumps(slope.as_dict() | {"logical": cpu_topology()[1]}))
        decision = ramp_decision(
            active=active, baseline=baseline, ceiling=ceiling, running=running,
            cpu_per_slot=slope.value,
            host_cpu_percent=cpu,
            available_bytes=memory.available,
            floor_bytes=host_available_floor_bytes(memory.total),
            connection_headroom=connection_headroom(connections=int(row["used"]),
                                                    limit=int(row["limit_"])),
            runnable=(int(snapshot.get("queued_simulations", 0) or 0)
                      + int(snapshot.get("analysis_backlog", 0) or 0)),
            seconds_since_step=time.monotonic() - float(state["stepped_at"]),
            launch_allowed=bool(guard["allowed"]),
            launch_reasons=tuple(guard["reasons"]),
        )
    except Exception as exc:
        key = f"error:{type(exc).__name__}"
        if state.get("limiter") == key:
            return None
        state["limiter"] = key
        return f"concurrency ramp: holding at {active} slot(s); {type(exc).__name__}: {exc}"[:300]
    if decision.slots == active and decision.limiter == state.get("limiter"):
        return None
    state["limiter"] = decision.limiter
    if decision.slots != active:
        slope.mark(running, cpu)
        for slot in range(int(state["spawned"]), decision.slots):
            spawn_executor(slot)
        state["spawned"] = max(int(state["spawned"]), decision.slots)
        state["stepped_at"] = time.monotonic()
        repo.set_flag("compute_active_slots", str(decision.slots))
        repo.set_flag("compute_total_slots", str(state["spawned"]))
    repo.emit("concurrency_ramp", decision.as_dict() | {
        "from_slots": active, "processes": int(state["spawned"]), "ceiling": int(ceiling),
        "running": running, "host_cpu_percent": cpu, "learned": slope.as_dict()})
    return (f"concurrency ramp: {decision.action} {active} -> {decision.slots} slot(s) "
            f"({int(state['spawned'])} executor process(es), ceiling {ceiling}); {decision.reason}")


def cmd_sweep(args):
    import json as _json
    from graph_scale_dynamics.operations.startup_reaper import sweep as _sweep, survey_namespaces
    from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir
    var = Path(args.var).expanduser()
    if (live := live_fleet(var if var.is_absolute() else ROOT / var)) and not args.no_children:
        print(f"refusing to sweep: {live}")
        return 2
    blobs = (var if var.is_absolute() else ROOT / var).resolve() / "blobs"
    try:
        current = choose_volatile_dir(namespace=f"blobstore:{blobs}",
                                      allow_persistent_fallback=False).get("path")
    except Exception:
        current = None
    survey = survey_namespaces(current)
    print(f"volatile namespaces: {len(survey['namespaces'])} total, "
          f"{survey['stale_bytes'] / (1 << 30):.1f} GiB stale of "
          f"{survey['total_bytes'] / (1 << 30):.1f} GiB")
    for entry in survey["namespaces"][:20]:
        print(f"  {entry['bytes'] / (1 << 30):7.2f} GiB  {entry['status']:8s} {entry['path']}")
    result = _sweep(ROOT, keep=current, children=not args.no_children, dry_run=args.dry_run)
    if args.dry_run:
        print("dry run: nothing was deleted")
    print(_json.dumps({k: v for k, v in result.items() if k in ("children",)}, default=str)[:400])
    return 0


def cmd_selftest(args):
    from tools.selftest import main as selftest_main
    argv = (["--quick"] if args.quick else []) + (["--no-postgres"] if args.no_postgres else [])
    argv += ["--window-seeds", str(args.window_seeds)]
    return selftest_main(argv)


def cmd_hardware(args):
    from graph_scale_dynamics.operations.hardware_diagnosis import diagnose_hardware
    return diagnose_hardware(args, build_number=BUILD_NUMBER)

def cmd_status(args):
    db, _, _ = paths(args)
    repo = Repo(db)
    campaign = repo.campaign(args.campaign)
    if campaign is None:
        print(f"unknown campaign {args.campaign}")
        return 2
    jobs = repo.jobs(args.campaign)
    counts = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    print(f"campaign {args.campaign}: {campaign['status']}; jobs {counts}")
    for candidate in repo.candidates(args.campaign):
        print(f"  {candidate['candidate_id'][:16]}  {candidate['state']:<18} {candidate['state_reason'] or ''}")
    return 0


def cmd_report(args):
    db, _, var = paths(args)
    repo = Repo(db)
    campaign = repo.campaign(args.campaign)
    if campaign is None:
        print(f"unknown campaign {args.campaign}")
        return 2
    out = {
        "campaign": args.campaign, "status": campaign["status"],
        "candidates": [],
    }
    proposal_rows = repo.proposal_assessments(args.campaign)
    proposals_by_candidate = {}
    for row in proposal_rows:
        proposals_by_candidate.setdefault(row["candidate_id"], []).append(row)
    contract = repo.campaign_analysis_contract(args.campaign)
    out["analysis_version"] = contract
    for candidate in repo.candidates(args.campaign):
        cid = candidate["candidate_id"]
        rungs = repo.rung_summaries(cid, contract, args.campaign)
        decisions = repo.engine_decisions(args.campaign, cid)
        out["candidates"].append({
            "candidate_id": cid, "state": candidate["state"],
            "state_reason": candidate["state_reason"], "spec": candidate["spec"],
            "proposal_assessments": proposals_by_candidate.get(cid, []),
            "compute": repo.candidate_rung_compute(args.campaign, cid),
            "rungs": rungs, "engine_decisions": decisions,
        })
        print(f"\ncandidate {cid[:16]}  [{candidate['state']}]")
        if candidate["state_reason"]:
            print(f"  reason: {candidate['state_reason']}")
        def fmt(measure):
            if not measure or measure.get("mean") is None:
                return "invalid"
            se = measure.get("se")
            return f"{measure['mean']:.3f}" + (f" ± {se:.3f}" if se else "")

        for rung in rungs:
            summary = rung["summary"]
            print(f"  N={rung['n']:>6}: d_V {fmt(summary.get('d_V'))} "
                  f"(valid {summary.get('d_V_valid_fraction'):.2f}) | d_s {fmt(summary.get('d_s'))} "
                  f"(valid {summary.get('d_s_valid_fraction'):.2f}) | mean degree {fmt(summary.get('mean_degree'))} "
                  f"| connected {fmt(summary.get('connected_fraction'))} "
                  f"| log-diam flags {summary.get('log_diameter_flags')}/{summary.get('seeds')}")
        for decision in decisions:
            print(f"  decision {decision['created_utc']} at N={decision['at_n']}: {decision['action']} "
                  f"by {decision['rule']} ({decision['reason']})")
    report_path = var / "reports" / f"report_{args.campaign}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, indent=1))
    print(f"\nfull audit json: {report_path}")
    return 0


def _resource_telemetry_baseline_seconds(*, power_thermal_disabled: bool) -> float:
    return 0.0


def _engine_toolchain() -> dict:
    candidates = [Path.home() / ".cargo" / "bin", Path.home() / ".local" / "bin", ROOT / ".venv" / "bin"]
    extra = os.pathsep.join(str(c) for c in candidates if c.is_dir())
    path = os.environ.get("PATH", "") + (os.pathsep + extra if extra else "")
    return {"cargo": shutil.which("cargo", path=path), "maturin": shutil.which("maturin", path=path),
            "path": path}


def _default_engine_available() -> bool:
    import importlib
    from graph_scale_dynamics.services.worker import engine_registry
    importlib.invalidate_caches()
    importlib.reload(engine_registry)
    engines = engine_registry.available_engines()
    return bool((engines.get(engine_registry.ENGINE_RUST) or {}).get("available"))


def _refuse_without_default_engine() -> int | None:
    from graph_scale_dynamics.services.worker.engine_registry import (
        ENGINE_ENV, ENGINE_RUST, requested_engine, rust_engine_current_after_build, stale_rust_engine)
    wanted = requested_engine(None)
    stale = stale_rust_engine() if wanted == ENGINE_RUST else None
    if wanted != ENGINE_RUST or (_default_engine_available() and not stale):
        return None
    tools = _engine_toolchain()
    if tools["cargo"] and tools["maturin"]:
        print(f"engine: {stale or 'gsd_engine_rs is not installed'}; building it now with "
              "tools/build_engine.sh (about a minute the first time)", flush=True)
        result = subprocess.run(["bash", str(ROOT / "tools" / "build_engine.sh")], cwd=ROOT,
                                env=dict(os.environ, PATH=tools["path"]))
        if result.returncode == 0 and _default_engine_available() and rust_engine_current_after_build():
            print("engine: gsd_engine_rs built and installed", flush=True)
            return None
        print("refusing to start: tools/build_engine.sh did not produce a current gsd_engine_rs "
              f"(exit {result.returncode}); see its output above. Set {ENGINE_ENV}=python to "
              "measure on the Python engine on purpose.")
        return 2
    print(f"refusing to start: the Rust engine is the default and {stale or 'is not importable here'}, "
          "and no cargo/maturin toolchain was found to build it. Run "
          "./tools/prepare_environment.sh (installs rustup and maturin, builds the extension), "
          f"or set {ENGINE_ENV}=python to measure on the Python engine on purpose.")
    return 2


def cmd_run(args):
    refused = _refuse_without_default_engine()
    if refused is not None:
        return refused
    """Run one supervised fleet per PostgreSQL database."""
    from graph_scale_dynamics.operations.leftovers import at_start as end_leftovers
    end_leftovers(ROOT)
    if live := live_in_folder(ROOT, SERVE_PID_FILE):
        print(f"refusing to start: {live}. Stop it first; the fleet serves its own dashboard.")
        return 2
    publisher = None if power_sidecar.publisher_pid(ROOT) is not None else power_sidecar.ensure_publisher(ROOT)
    from graph_scale_dynamics.operations.scratch_namespace import enter as enter_scratch, refusal
    entered = enter_scratch(ROOT, name_others=True)
    print(f"scratch: {entered}", flush=True)
    if (back := entered.get("restored")) is not None:
        print(f"scratch: {back['files']:,} file(s), {back['bytes'] / (1 << 30):.2f} GiB, moved back from "
              f"var/scratch_parked, where its holder had parked them when the scratch sat idle"
              + (f"; {back['left']:,} left there ({back['error']})" if back.get("left") else ""), flush=True)
    if refusal(entered):
        print(refusal(entered), file=sys.stderr, flush=True)
        power_sidecar.stop_publisher(ROOT, started=publisher)
        return 2
    from graph_scale_dynamics.observability.console import install as install_console, restore as restore_console
    old_streams = install_console("supervisor")
    try:
        db, blobs, var = paths(args)
        init_db(db)
        blobs.mkdir(parents=True, exist_ok=True)
        repo = Repo(db)
        lock_name = "gsd:fleet"
        if not repo.acquire_service_lock(lock_name):
            if not _reap_orphaned_fleet_lock(repo, var, lock_name):
                repo.close()
                print("refusing to start: another Graph Scale Dynamics fleet already owns this database")
                return 3
        fleet_record = record_this_process(var / FLEET_PID_FILE)
        if fleet_record is None:
            print(f"could not record the fleet pid in {var / FLEET_PID_FILE}; an orphaned lock from this run will "
                  "need `tools/postgres_instance.py` or a wait to clear")
        owns_folder_runtime = os.environ.get("GSD_INTEGRATION_TEST") != "1"
        try:
            if getattr(args, "study", None) is not None:
                from graph_scale_dynamics.operations.study import study_choice
                refused = study_choice(args.study, spec=getattr(args, "spec", None), var=var, root=ROOT,
                                       starting=True)
                if refused:
                    print(refused)
                    return 2
            from graph_scale_dynamics.services.calibration_gate import (
                CalibrationGateError, ensure_probe_calibration,
            )
            try:
                calibration_status = ensure_probe_calibration(var, build_number=BUILD_NUMBER, root=ROOT)
            except CalibrationGateError as exc:
                print(f"refusing to start: {exc}")
                return 3
            return _cmd_run_locked(args, repo, db, blobs, var, calibration_status=calibration_status)
        finally:
            try:
                repo.release_service_lock(lock_name)
            finally:
                unlink_if_ours(var / FLEET_PID_FILE, fleet_record)
                repo.close()
                if owns_folder_runtime and (other := live_fleet(var)):
                    print(f"fleet drained; folder-local PostgreSQL left running: {other}")
                elif owns_folder_runtime:
                    print("fleet drained; stopping owned folder-local PostgreSQL instance")
                    _stop_folder_postgres()
                if not live_fleet(var):
                    _release_the_scratch_if_empty()
    finally:
        power_sidecar.stop_publisher(ROOT, started=publisher)
        restore_console(old_streams)


def _release_the_scratch_if_empty() -> None:
    from graph_scale_dynamics.operations.scratch_namespace import release_line, release_when_empty
    try:
        line = release_line(release_when_empty(ROOT))
    except Exception as exc:  # noqa: BLE001
        line = f"scratch: kept; whether it was empty could not be read ({type(exc).__name__}: {exc})"
    if line:
        print(line, flush=True)


def _wait_for_the_database(exc: Exception, waits: dict[str, float]) -> None:
    if time.monotonic() - waits.get("said_at", float("-inf")) >= 30.0:
        waits["said_at"] = time.monotonic()
        print(f"database: {exc}; the fleet waits for it (the watchdog decides)", flush=True)
    time.sleep(2.0)


def _scientific_contract_matches_current(spec: dict) -> bool:
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    return (str(spec.get("analysis_version")) == ANALYSIS_VERSION
            and str((spec.get("policy") or {}).get("rule_version")) == POLICY_RULE_VERSION
            and str(spec.get("search_space_version")) == str(SEARCH_SPACE_VERSION)
            and is_engine_campaign(spec))


def _scientific_contract_key(spec: dict) -> tuple[str, str, str]:
    return (str(spec.get("analysis_version")),
            str((spec.get("policy") or {}).get("rule_version")),
            str(spec.get("search_space_version")))


def _refuse_foreign_contract(campaign_id: str, spec: dict) -> None:
    from graph_scale_dynamics.decisions.engine import ENGINE_VERSION
    print(
        f"campaign {campaign_id} was created under analysis={spec.get('analysis_version')} / "
        f"policy={(spec.get('policy') or {}).get('rule_version')} / engine="
        f"{(spec.get('engine') or {}).get('contract')}; this build executes only analysis "
        f"{ANALYSIS_VERSION} / policy {POLICY_RULE_VERSION} / engine {ENGINE_VERSION}. Refusing. "
        f"main.py campaign close {campaign_id}; main.py campaign start --spec campaign_engine_survey.json; "
        "main.py campaign use <new id>."
    )


def _incompatible_active_campaigns(repo: Repo, *, excluding: str | None = None,
                                   target_spec: dict | None = None) -> list[dict]:
    if target_spec is None:
        target_key = (str(ANALYSIS_VERSION), str(POLICY_RULE_VERSION), str(SEARCH_SPACE_VERSION))
    else:
        target_key = _scientific_contract_key(target_spec)
    return [campaign for campaign in repo.active_campaigns()
            if campaign["campaign_id"] != excluding
            and _scientific_contract_key(campaign["spec"]) != target_key]


def _resolve_run_target(args, repo: Repo) -> tuple[str | None, dict] | None:
    explicit_campaign = getattr(args, "campaign", None)
    if explicit_campaign:
        stored = repo.campaign(explicit_campaign)
        if stored is None:
            print(f"unknown campaign {explicit_campaign}")
            return None
        if stored["status"] != "active":
            print(f"refusing to run {stored['status']} campaign {explicit_campaign}")
            return None
        mismatches = provenance_mismatches(stored)
        if mismatches:
            print(f"refusing Campaign {explicit_campaign}: immutable provenance mismatch")
            for mismatch in mismatches:
                print(f"  - {mismatch}")
            return None
        if not _scientific_contract_matches_current(stored["spec"]):
            _refuse_foreign_contract(explicit_campaign, stored["spec"])
            return None
        print(f"resuming stored campaign {explicit_campaign} with its immutable spec")
        return explicit_campaign, stored["spec"]

    explicit_spec = getattr(args, "spec", None)
    if explicit_spec:
        print(f"explicit campaign spec requested: {explicit_spec}")
        return None, read_spec_file(explicit_spec)

    from graph_scale_dynamics.operations import campaign_control
    stale = campaign_control.clear_stale_focus(repo)
    if stale:
        print(f"stored reporting campaign {stale} is no longer active; cleared it")
    home = str(campaign_control.reporting_focus(repo) or "")
    if home:
        stored = repo.campaign(home)
        if stored is not None and stored["status"] == "active":
            mismatches = provenance_mismatches(stored)
            if mismatches:
                print(f"refusing Campaign {home}: immutable provenance mismatch")
                for mismatch in mismatches:
                    print(f"  - {mismatch}")
                return None
            if not _scientific_contract_matches_current(stored["spec"]):
                _refuse_foreign_contract(home, stored["spec"])
                return None
            print(f"resuming campaign {home} with its immutable spec")
            return home, stored["spec"]

    plausible = [
        campaign for campaign in repo.active_campaigns()
        if campaign["spec"].get("mode") == "continuous"
        and repo.campaign_link(campaign["campaign_id"]) is None
    ]
    if len(plausible) == 1:
        selected = plausible[0]
        mismatches = provenance_mismatches(selected)
        if mismatches:
            print(f"refusing Campaign {selected['campaign_id']}: immutable provenance mismatch")
            for mismatch in mismatches:
                print(f"  - {mismatch}")
            return None
        if not _scientific_contract_matches_current(selected["spec"]):
            _refuse_foreign_contract(selected["campaign_id"], selected["spec"])
            return None
        print("resuming sole active primary discovery campaign "
              f"{selected['campaign_id']} with its immutable spec")
        return selected["campaign_id"], selected["spec"]
    if len(plausible) > 1:
        print("refusing to guess between multiple active primary discovery campaigns:")
        for campaign in plausible:
            print(f"  - {campaign['campaign_id']}")
        print("choose one with `python main.py campaign use --campaign <id>` or "
              "pass `python main.py run --campaign <id>`")
        return None

    sole_active = repo.active_campaigns()
    if len(sole_active) == 1:
        selected = sole_active[0]
        mismatches = provenance_mismatches(selected)
        if mismatches:
            print(f"refusing sole active Campaign {selected['campaign_id']}: immutable provenance mismatch")
            for mismatch in mismatches:
                print(f"  - {mismatch}")
            return None
        if not _scientific_contract_matches_current(selected["spec"]):
            _refuse_foreign_contract(selected["campaign_id"], selected["spec"])
            return None
        role = selected.get("campaign_role") or selected["spec"].get("mode") or "research"
        print(f"resuming sole active {role} campaign {selected['campaign_id']} with its immutable spec")
        return selected["campaign_id"], selected["spec"]
    if len(sole_active) > 1:
        print("active non-home experiments exist; refusing to auto-create a new discovery campaign:")
        for campaign in sole_active:
            role = campaign.get("campaign_role") or campaign["spec"].get("mode") or "research"
            print(f"  - {campaign['campaign_id']}: {role}")
        print("pass `python main.py run --campaign <id>` or stop/fence the experiments you do not want running")
        return None

    existing = repo.all_campaigns()
    if existing:
        print("refusing to create a new default campaign: campaigns already exist and none "
              "is active or set as home:")
        for campaign in existing:
            print(f"  - {campaign['campaign_id']}: {campaign.get('status')}")
        print("choose with `main.py campaign use <id>` or `run --campaign <id>`, resume a closed one "
              "with `main.py campaign reopen <id>`, or create deliberately with `run --spec <file>`")
        return None
    default_spec = DEFAULT_HOME_CAMPAIGN_SPEC
    print(f"no campaigns exist; creating the default study from {default_spec}")
    return None, read_spec_file(default_spec)


def _refuse_study(args, repo: Repo, var: Path, starting: bool) -> bool:
    from graph_scale_dynamics.operations.study import study_choice
    refused = study_choice(getattr(args, "study", None), spec=getattr(args, "spec", None), repo=repo, var=var,
                           root=ROOT, starting=starting)
    if refused:
        print(refused)
    return bool(refused)


def _cmd_run_locked(args, repo: Repo, db: str, blobs: Path, var: Path, calibration_status: dict | None = None):
    try:
        from graph_scale_dynamics.observability.evidence_sources import TeeStdout, supervisor_log_path
        if not isinstance(sys.stdout, TeeStdout):
            sys.stdout = TeeStdout(sys.stdout, supervisor_log_path(var))
            sys.stderr = TeeStdout(sys.stderr, supervisor_log_path(var))
    except Exception as exc:
        print(f"supervisor log tee unavailable: {type(exc).__name__}: {exc}")
    try:
        from graph_scale_dynamics.operations.startup_reaper import sweep as _startup_sweep
        from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir as _cvd
        try:
            _current = _cvd(namespace=f"blobstore:{Path(blobs).resolve()}",
                            allow_persistent_fallback=False).get("path")
        except Exception:
            _current = None
        _startup_sweep(ROOT, keep=_current, log=lambda m: print(m, flush=True))
    except Exception as exc:
        print(f"startup sweep skipped: {type(exc).__name__}: {exc}", flush=True)
    print(f"coordinator backend: {repo.backend}")
    resolved = _resolve_run_target(args, repo)
    if resolved is None or _refuse_study(args, repo, var, resolved[0] is None):
        return 2
    stored_campaign_id, spec = resolved
    if stored_campaign_id is None:
        spec = freeze_campaign_spec(spec)
    problems = validate_campaign(spec, stored=bool(stored_campaign_id))
    if problems:
        target = (f"stored campaign {stored_campaign_id}" if stored_campaign_id
                  else "the requested specification")
        print(f"refusing invalid campaign specification for {target}:")
        for problem in problems:
            print(f"  - {problem}")
        if stored_campaign_id:
            print("  a stored spec is immutable: if this build added a requirement that an "
                  "existing campaign cannot meet, the build is wrong, not the campaign")
        return 2
    if not _scientific_contract_matches_current(spec):
        _refuse_foreign_contract(stored_campaign_id or "requested-spec", spec)
        return 2
    version = ANALYSIS_VERSION
    benchmark = repo.benchmark(version)
    if not (benchmark and benchmark["passed"]):
        from graph_scale_dynamics.db.repo import analyzer_identity
        from graph_scale_dynamics.measurements.benchmarks import benchmark_workers, run_battery
        prior = repo.benchmark_any_identity(version) if hasattr(repo, "benchmark_any_identity") else None
        workers = benchmark_workers()
        if prior is None:
            reason = "no battery recorded for this analysis version"
        elif not prior.get("passed"):
            reason = "the last recorded battery failed"
        elif prior.get("runtime_fingerprint") != analyzer_identity():
            reason = (f"recorded under analyzer {prior.get('runtime_fingerprint') or 'unknown'}, "
                      f"this is {analyzer_identity()}")
        else:
            reason = "recorded under a different numerical environment"
        print(f"analyzer benchmark battery: {reason}; running it now on {workers} core(s)")
        started = time.monotonic()
        report = run_battery(seed=1)
        repo.record_benchmark(version, report["passed"], report)
        elapsed = time.monotonic() - started
        if not report["passed"]:
            failed = [c["name"] for c in report["checks"] if not c["passed"]]
            print(f"battery FAILED ({failed}); refusing to research with an unvalidated analyzer")
            return 1
        print(f"battery passed ({len(report['checks'])} checks in {elapsed:.1f}s); "
              f"cached against analyzer {analyzer_identity()}")
        print(f"battery passed ({len(report['checks'])} checks)")
    if stored_campaign_id is not None:
        campaign_id = stored_campaign_id
        if getattr(args, "search_seed", None) is not None:
            existing_seed = int((repo.campaign(campaign_id) or {}).get("search_seed"))
            if int(args.search_seed) != existing_seed:
                print(f"refusing --search-seed {args.search_seed}: Campaign {campaign_id} is immutable and uses search seed {existing_seed}")
                return 2
    else:
        from graph_scale_dynamics.operations.study import start_study
        campaign_id = start_study(repo, spec, search_seed=getattr(args, "search_seed", None),
                                  default=not getattr(args, "spec", None), var=var, study=getattr(args, "study", None))
    campaign = repo.campaign(campaign_id)
    incompatible = _incompatible_active_campaigns(repo, excluding=campaign_id, target_spec=spec)
    if incompatible:
        print("refusing to launch one fleet across campaigns with different scientific contracts:")
        for old in incompatible:
            old_spec = old["spec"]
            print(f"  - {old['campaign_id']}: analysis={old_spec.get('analysis_version')} / "
                  f"policy={(old_spec.get('policy') or {}).get('rule_version')} / "
                  f"search={old_spec.get('search_space_version')}")
        print("stop/fence them first with `uv run python main.py campaign close CAMP`; "
              "their evidence is preserved.")
        return 2
    if campaign["status"] != "active" and spec.get("mode") == "continuous":
        if not getattr(args, "reopen", False):
            print(f"refusing to start: campaign {campaign_id} is {campaign['status']}. "
                  f"To resume it: `main.py campaign reopen {campaign_id}` or `run --reopen`; "
                  "to run another campaign: `main.py campaign use <id>` or `run --campaign <id>`")
            return 2
        repo.set_campaign_status(campaign_id, "active")
        print(f"reopened campaign {campaign_id} (--reopen)")
    from graph_scale_dynamics.services.proposer.main import proposal_target_banner
    print(proposal_target_banner(repo.active_campaigns()), flush=True)
    from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
    try:
        engine_name, _run, engine_fingerprint = resolve_engine(None)
    except ValueError as exc:
        print(f"refusing to start: {exc}")
        return 2
    print(f"engine: {engine_name} ({engine_fingerprint}); every attempt records this", flush=True)
    explicit_workers = args.workers > 0
    if args.workers <= 0:
        physical, logical = cpu_topology()
        configured = os.environ.get("GSD_AUTO_WORKERS")
        override = None if configured is None else int(configured)
        physical_cap = max(1, int(os.environ.get("GSD_AUTO_PHYSICAL_CAP", "16")))
        logical_cap = max(1, int(os.environ.get("GSD_AUTO_LOGICAL_CAP", "32")))
        use_smt = not bool(getattr(args, "physical_cores_only", False))
        available_slots = choose_auto_slots(physical=physical, logical=logical,
                                            override=override, use_smt=use_smt,
                                            physical_safety_cap=physical_cap,
                                            logical_safety_cap=logical_cap)
        args.workers = available_slots if override is not None else cold_start_slots(available_slots)
        basis = ("explicit GSD_AUTO_WORKERS override" if override is not None
                 else f"one step; the ramp learns the size, of {available_slots} logical threads/SMT (cap {logical_cap})"
                 if use_smt else f"one step; the ramp learns the size, of {available_slots} physical cores (cap {physical_cap})")
        print(f"compute slots: host exposes {physical} physical cores / {logical} logical threads; "
              f"starting at {args.workers} ({basis}). Override with --workers K. Shared adaptively between "
              "graph evolution and analysis; the memory governor defers only very large N jobs, and only while RAM is actually short")
    from graph_scale_dynamics.scheduling.cpu import fleet_ceiling, held_slots
    if explicit_workers:
        slot_floor, slot_ceiling = held_slots(args.workers, os.environ)
    else:
        slot_ceiling = ramp_ceiling(baseline=args.workers, logical=cpu_topology()[1],
                                    override=fleet_ceiling(os.environ, *cpu_topology()))
        slot_floor = min(args.workers, FLOOR_SLOTS)
    slot_most = worker_count.most_slots(slot_ceiling, cpu_topology()[1], os.environ)
    print(f"concurrency ramp ({RAMP_CONTRACT}):{args.workers} slot(s) to start, never fewer than {slot_floor} "
          f"nor more than {slot_ceiling}, "
          f"+{STEP_SLOTS} every {STEP_HOLD_SECONDS:.0f}s while work is queued. It learns what one child costs the host "
          f"from each step, steps halfway to {CPU_TARGET_PERCENT:.0f}% host CPU, stops at the memory floor, the "
          "PostgreSQL connection budget or an empty queue, and above "
          f"{CPU_BACKOFF_PERCENT:.0f}% gives back what is over the target, down to its floor")
    from graph_scale_dynamics.domain.version import (
        DEPLOYMENT_FENCE_EXIT_CODE, DeploymentProvenanceFence, ensure_build_number,
        source_fingerprint,
    )
    fingerprint = source_fingerprint(ROOT)
    build_number, build_id = ensure_build_number(repo, fingerprint)
    print(f"build {build_number} ({build_id}): installation-stable runtime source id")

    def assert_installation_unchanged(stage: str) -> str:
        try:
            return _verify_installation_identity(fingerprint)
        except DeploymentProvenanceFence as exc:
            raise DeploymentProvenanceFence(f"{stage}: {exc}") from exc
    _stage_clock = [time.monotonic()]

    _stage_log: list[tuple[str, float]] = []

    def stage(name: str) -> None:
        now = time.monotonic()
        elapsed = now - _stage_clock[0]
        _stage_clock[0] = now
        _stage_log.append((name, elapsed))
        if elapsed >= 0.5:
            print(f"startup: {name} took {elapsed:.1f}s")

    def stage_total() -> None:
        total = sum(e for _, e in _stage_log)
        print(f"startup: {len(_stage_log)} attributed stage(s) totalling {total:.1f}s")

    quarantined = quarantine_invalid_candidate_identities(repo, var=var)
    stage("candidate identity scan")
    if quarantined:
        print("quarantined candidate identities that cannot match execution: "
              + ", ".join(cid[:16] for cid in quarantined))
    repo._write("DELETE FROM service_heartbeats")
    stage("clearing service heartbeats")
    wall = float(args.wall) if args.wall is not None else campaign_wall_seconds(spec)
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    runtime_store = BlobStore(blobs)
    stage("blob store open")
    from graph_scale_dynamics.operations.scratch_relief import at_fleet_start
    at_fleet_start(repo, runtime_store, var=var)
    stage("scratch repair and relief")
    runtime_tmp = runtime_store.volatile_root / "runtime"
    runtime_tmp.mkdir(parents=True, exist_ok=True)
    runtime_log = runtime_tmp / "log"
    runtime_log.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        GSD_RUNTIME_FINGERPRINT=fingerprint,
        GSD_RUNTIME_LOG_DIR=str(runtime_log),
        TMPDIR=str(runtime_tmp),
        TMP=str(runtime_tmp),
        TEMP=str(runtime_tmp),
    )
    native_threads = str(max(1, int(os.environ.get("GSD_NATIVE_THREADS", "1"))))
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[key] = native_threads
    if bool(getattr(args, "no_power_telemetry", False)):
        env["GSD_DISABLE_POWER_TELEMETRY"] = "1"
    else:
        env.pop("GSD_DISABLE_POWER_TELEMETRY", None)
    services: list[dict] = []
    dashboard_admin_token = secrets.token_urlsafe(24)
    dashboard_admin_file = None
    internal_api_file = None
    dashboard_local_url = None
    dashboard_admin_url = None
    dashboard_prefix = (("/" + str(getattr(args, "base_path", "")).strip("/"))
                        if getattr(args, "base_path", "") else "")
    api_port = int(getattr(args, "api_port", 0) or (int(args.port) + 1))
    report_root = var / "reports" / f"live_campaign_{campaign_id}"
    if not getattr(args, "no_dashboard", False):
        (dashboard_admin_file, dashboard_local_url, dashboard_admin_url,
         dashboard_prefix) = _write_dashboard_admin_capability(
            var, port=args.port, base_path=getattr(args, "base_path", ""),
            token=dashboard_admin_token,
        )
        internal_api_file = _write_internal_api_capability(var)

    def launch(record: dict) -> subprocess.Popen:
        assert_installation_unchanged("supervisor child launch")
        module = record["module"]
        if record.get("api"):
            cmd = [
                sys.executable, "-m", "graph_scale_dynamics.services.api.main",
                "--db", service_database_reference(db), "--blobs", str(blobs),
                "--port", str(api_port), "--bind", "127.0.0.1",
                "--report-campaign", str(campaign_id), "--report-root", str(report_root),
                "--internal-token-file", str(internal_api_file),
                "--snapshot-tmp", str(runtime_tmp),
                "--exploration-map-mode", "lazy", "--past-research-mode", "lazy",
            ]
        elif module == "graph_scale_dynamics.services.web.main":
            cmd = [sys.executable, "-m", module, "--port", str(args.port), "--bind", str(args.bind),
                   "--api-port", str(api_port), "--reports", str(report_root),
                   "--internal-token-file", str(internal_api_file)]
            for allowed in getattr(args, "allow_host", []) or []:
                cmd += ["--allow-host", allowed]
            if getattr(args, "base_path", ""):
                cmd += ["--base-path", str(args.base_path)]
        else:
            cmd = _service_cmd(module, db, blobs, campaign_id, var, record.get("extra", ()))
        proc_env = dict(env)
        if record.get("api"):
            proc_env = _dashboard_process_environment(proc_env, dashboard_admin_file)
        slot = next((record.get("extra", ())[i + 1]
                     for i, value in enumerate(record.get("extra", ())[:-1])
                     if value == "--slot"), None)
        service_name = "api" if record.get("api") else module.split(".")[-2]
        proc_env["GSD_DATABASE_APPLICATION_NAME"] = (
            f"gsd-{service_name}-{slot}" if slot is not None else f"gsd-{service_name}"
        )
        proc_env = owned_env(proc_env)
        from graph_scale_dynamics.observability.console_log import popen_logged
        proc = popen_logged(cmd, source=proc_env["GSD_DATABASE_APPLICATION_NAME"][5:], var=var,
                            cwd=ROOT, env=proc_env, start_new_session=True)
        record["proc"] = proc
        record["suspended"] = False
        return proc

    def spawn(module, extra=(), *, api=False, critical=True, group="control", start=True):
        record = {"module": module, "extra": tuple(extra), "api": api,
                  "critical": bool(critical), "group": str(group), "proc": None,
                  "crashes": [], "disabled": False, "suspended": not bool(start)}
        services.append(record)
        return launch(record) if start else None

    def suspend_group(group: str) -> int:
        records = [r for r in services if r.get("group") == group and not r.get("disabled")]
        live = [r["proc"] for r in records if r.get("proc") is not None and r["proc"].poll() is None]
        import contextlib
        for proc in live:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
        from graph_scale_dynamics.artifact_store.resume_state import STOP_GRACE_SECONDS
        from graph_scale_dynamics.domain.cadence import ticks
        from graph_scale_dynamics.operations.startup_reaper import fleet_children_running
        limit = time.monotonic() + (STOP_GRACE_SECONDS + ticks(1) if group == "compute" else ticks(1))
        while time.monotonic() < limit and (any(p.poll() is None for p in live)
                                             or (group == "compute" and fleet_children_running(ROOT))):
            time.sleep(0.2)
        for proc in (p for p in live if p.poll() is None):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
        if group == "compute":
            from graph_scale_dynamics.operations.startup_reaper import stop_fleet_children
            stop_fleet_children(ROOT, log=lambda message: print(message, flush=True))
        for record in records:
            record["proc"], record["suspended"] = None, True
        return len(records)

    def resume_group(group: str) -> int:
        resumed = 0
        for record in services:
            if (record.get("group") != group or record.get("disabled")
                    or not record.get("suspended") or record.get("held")):
                continue
            launch(record)
            resumed += 1
        return resumed

    def teardown(sig=signal.SIGTERM):
        for record in services:
            proc = record["proc"]
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    pass

    def drain(grace: float | None = None) -> None:
        from graph_scale_dynamics.artifact_store.resume_state import FLEET_STOP_GRACE_SECONDS
        from graph_scale_dynamics.operations.startup_reaper import fleet_children_running, stop_fleet_children
        teardown(signal.SIGTERM)
        limit = time.monotonic() + (FLEET_STOP_GRACE_SECONDS if grace is None else grace)
        while time.monotonic() < limit and (fleet_children_running(ROOT) or any(
                record["proc"] is not None and record["proc"].poll() is None for record in services)):
            time.sleep(0.15)
        teardown(signal.SIGKILL)
        stop_fleet_children(ROOT, log=lambda message: print(message, flush=True))
        for record in services:
            proc = record["proc"]
            if proc is None:
                continue
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)

    analyzer_count = _analyzer_capacity(slot_ceiling)
    campaign_control.claim_home_if_unset(repo, campaign_id)
    from graph_scale_dynamics.db.connection import (
        POSTGRES_INSTANCE_HELPER, _read_local_postgres_env,
    )
    from graph_scale_dynamics.services.db_watchdog import Watchdog
    try:
        _pg_socket_dir = Path(_read_local_postgres_env()["POSTGRES_SOCKET"]).expanduser().resolve()
    except Exception:
        _pg_socket_dir = ROOT / "instance" / "postgres" / "socket"
    db_watchdog = Watchdog(
        socket_dir=_pg_socket_dir,
        postgres_dir=ROOT / "instance" / "postgres",
        connect=lambda: Repo(db).close(),
        helper=POSTGRES_INSTANCE_HELPER if POSTGRES_INSTANCE_HELPER.is_file() else None,
        owns_instance=os.environ.get("GSD_INTEGRATION_TEST") != "1",
        log=lambda line: print(line, flush=True),
        emit=lambda kind, payload: repo.emit(kind, payload),
    )
    calibration_synced_mtime = None
    calibration_sync_logged_at = 0.0
    initially_paused = repo.get_flag("paused", "0") == "1"
    if initially_paused:
        startup_cancelled = repo.operator_pause_cancel_active_work(
            reason="user-cancelled work fenced on PAUSED supervisor startup"
        )
        if any(int(startup_cancelled.get(k, 0) or 0) for k in (
                "jobs_user_cancelled", "analysis_user_cancelled", "rebuilds_user_cancelled")):
            print(
                "PAUSED startup recovery: fenced stale active work immediately; "
                f"{startup_cancelled.get('jobs_user_cancelled', 0)} simulation, "
                f"{startup_cancelled.get('analysis_user_cancelled', 0)} analysis and "
                f"{startup_cancelled.get('rebuilds_user_cancelled', 0)} rebuild lease(s) returned to queue"
            )
    repo.set_flag("compute_total_slots", str(args.workers))
    repo.set_flag("compute_active_slots", "0" if initially_paused else str(args.workers))
    repo.set_flag("resource_calibration_id", "")
    repo.set_flag("resource_governor_phase", "host_managed")
    repo.set_flag("compute_max_analyzers", str(analyzer_count))
    stale_analysis = repo.cancel_unclaimable_analysis_work(
        reason=f"Build {BUILD_NUMBER} startup fenced work from closed/terminal campaigns"
    )
    stage("fencing unclaimable analysis rows (all campaigns)")
    if stale_analysis:
        print(f"fenced {stale_analysis} stale analysis queue rows that are no longer claimable")
    queued = repo.ensure_analysis_queue(version)
    stage("analysis queue backfill (all campaigns)")
    superseded_analysis = repo.cancel_superseded_analysis_work(version)
    stage("cancelling superseded analysis rows (all campaigns)")
    if superseded_analysis:
        print(
            f"Build {BUILD_NUMBER} recovery compacted {superseded_analysis} queued analysis "
            "artifact(s) superseded by longer cumulative runs"
        )
    initial_active_slots = int(repo.get_flag("compute_active_slots", str(args.workers)) or 0)
    allocation = repo.refresh_scheduler_state(
        analysis_version=version,
        total_slots=initial_active_slots,
        max_analyzers=min(analyzer_count, initial_active_slots),
    )
    stage("scheduler state refresh")
    if queued:
        print(f"analysis queue synchronized for {version}: "
              f"{allocation['analysis_backlog']} pending")
    stage_total()
    shared = ("--total-slots", str(slot_most), "--max-analyzers", str(analyzer_count))
    deadline = None if wall is None else time.monotonic() + wall

    stop_signals = interrupt_on().__enter__()
    exit_code = 0
    try:
        telemetry_poll = max(0.5, float(os.environ.get("GSD_RESOURCE_TELEMETRY_SECONDS", str(RAMP_TICK_SECONDS))))
        power_thermal_disabled = bool(getattr(args, "no_power_telemetry", False))
        telemetry_baseline = _resource_telemetry_baseline_seconds(
            power_thermal_disabled=power_thermal_disabled
        )
        print(
            f"resource telemetry: resource-telemetry-2; sampling every {telemetry_poll:g}s; "
            "CPU power/temperature are observational only and never limit GSD concurrency"
            + ("; power/thermal sensors disabled by operator" if power_thermal_disabled else "")
        )
        if telemetry_baseline:
            print(
                "resource telemetry advisory: for cleaner energy attribution, keep this host at "
                "base load now and avoid unrelated gaming/compiles/heavy workloads during the run; "
                "samples remain usable but are explicitly treated as noisy when interference is detected"
            )
        spawn("graph_scale_dynamics.services.telemetry.main", ("--poll", str(telemetry_poll),
                                      "--baseline-seconds", str(telemetry_baseline)), critical=False)
        if telemetry_baseline:
            time.sleep(telemetry_baseline + min(2.0, telemetry_poll))
        repo.set_flag("compute_active_slots", "0" if initially_paused else str(args.workers))
        repo.set_flag(worker_count.MOST_FLAG, str(slot_most))
        repo.set_flag("resource_governor_phase", "paused" if initially_paused else "host_managed")
        spawn("graph_scale_dynamics.services.maintenance.main", shared, critical=False)
        if spec.get("proposer"):
            spawn("graph_scale_dynamics.services.proposer.main", critical=False)
        spawn("graph_scale_dynamics.services.controller.main")
        def _spawn_executor(slot: int, *, start: bool = True) -> None:
            spawn("graph_scale_dynamics.services.executor.main", (*shared, "--slot", str(slot)),
                  group="compute", start=start)

        for slot in range(args.workers):
            _spawn_executor(slot, start=not initially_paused)
        if not getattr(args, "no_dashboard", False):
            spawn("graph_scale_dynamics.services.api.main", api=True)
            spawn("graph_scale_dynamics.services.web.main", critical=False)

        resource_note = (
            f"; {args.workers} configured executor slots exposed directly; "
            "CPU/firmware owns thermal and power throttling; GSD power/temperature telemetry is diagnostic only"
        )
        compute_note = ("0 resident executor processes while PAUSED"
                        if initially_paused else f"{args.workers} executor processes available")
        print(f"research runtime up: home campaign {campaign_id}; "
              f"{compute_note}, up to {analyzer_count} analysis slots"
              + ("; autonomous proposer targets the home discovery campaign"
                 if spec.get("proposer") else "") + resource_note
              )
        home = ((repo.campaign(campaign_id) or {}).get("spec") if campaign_id else None) or spec
        from graph_scale_dynamics.scheduling.limits import describe as describe_limits
        print(describe_limits(home))
        from graph_scale_dynamics.scheduling.reach import describe as describe_reach
        print(describe_reach(home))
        from graph_scale_dynamics.scheduling.base_block import (
            anchor_n as _anchor_n, base_sizes as _base_sizes, extension_sizes as _extension_sizes)
        _base = list(_base_sizes(home))
        _extension = list(_extension_sizes(home))
        print(f"ladder: base block {_base} for every admitted law")
        if _extension:
            print(f"ladder: extension {_extension} above the anchor N={_anchor_n(home)}, "
                  "bought one rung at a time by the decision engine (docs/DECISIONS.md)")
        else:
            print("ladder: no extension_ladder declared, so no rung above the anchor "
                  "can ever be bought")
        if not getattr(args, "no_dashboard", False):
            if args.bind in ("127.0.0.1", "localhost", "::1"):
                print(f"dashboard: {dashboard_local_url}")
            else:
                mode = "unauthenticated view-only; pause/resume needs the admin link"
                lan = _lan_address() or "<this-machine-LAN-IP>"
                print(f"dashboard: listening on {args.bind}:{args.port}{dashboard_prefix or '/'} ({mode}); "
                      f"open http://{lan}:{args.port}{dashboard_prefix}/ from your phone")
            print(f"dashboard admin capability: {dashboard_admin_file} (mode 0600; secret not printed); "
                  "on another device, its link with this machine's address for 127.0.0.1 is admin there too")
            print(f"dashboard architecture: web :{args.port} -> loopback API :{api_port}; reports run only when asked, for the selected campaign, and only while no work is in flight (508)")
        print("stop with Ctrl-C; rerun the same command to resume durable work")
        if (not getattr(args, "no_dashboard", False)
                and not getattr(args, "no_browser", False)):
            try:
                import webbrowser
                webbrowser.open(browser_launcher(var, dashboard_admin_url), new=2)
            except Exception:
                pass

        next_source_check = 0.0
        next_ramp_tick = 0.0
        ramp_state = {"meter": HostCpuMeter(), "spawned": args.workers,
                      "stepped_at": time.monotonic(), "limiter": None}
        pause_observed = initially_paused
        database_waits: dict[str, float] = {}
        while True:
            try:
                now = time.monotonic()
                db_state = db_watchdog.tick(now)
                try:
                    _cal_path = (Path(calibration_status["path"]) if (calibration_status or {}).get("path")
                                 else _calibration_table_path(var))
                    _cal_mtime = _cal_path.stat().st_mtime if _cal_path.is_file() else None
                    if _cal_mtime is not None and _cal_mtime != calibration_synced_mtime:
                        repo.set_flag("calibration_artifact_json", _cal_path.read_text(encoding="utf-8"))
                        repo.set_flag("calibration_artifact_path", str(_cal_path))
                        calibration_synced_mtime = _cal_mtime
                        if time.monotonic() - calibration_sync_logged_at >= 60.0:
                            calibration_sync_logged_at = time.monotonic()
                            print(f"calibration artifact synced to ledger ({_cal_path.stat().st_size} bytes)", flush=True)
                except Exception as exc:
                    print(f"calibration sync skipped: {type(exc).__name__}: {exc}", flush=True)
                try:
                    repo.publish_runtime_imports("supervisor")
                except Exception:
                    pass
                if db_state == "drain":
                    print("database unreachable and not recoverable; draining the fleet "
                          "(durable state is preserved; rerun the same command once the "
                          "database is back)", flush=True)
                    exit_code = DATABASE_LOST_EXIT_CODE
                    break
                if db_state == "degraded":
                    time.sleep(2.0)
                    continue
                paused_now = repo.get_flag("paused", "0") == "1"
                if paused_now != pause_observed:
                    pause_observed = paused_now
                    if paused_now:
                        repo.set_flag("compute_active_slots", "0")
                        cancelled = repo.operator_pause_cancel_active_work(
                            reason="user cancelled by PAUSE; partial scientific work discarded and unit returned to queue"
                        )
                        count = suspend_group("compute")
                        repo._write("DELETE FROM service_heartbeats WHERE service LIKE 'executor-%'")
                        print(
                            "pause requested: active scientific work cancelled immediately; "
                            f"{cancelled.get('jobs_user_cancelled', 0)} simulation, "
                            f"{cancelled.get('analysis_user_cancelled', 0)} analysis and "
                            f"{cancelled.get('rebuilds_user_cancelled', 0)} rebuild lease(s) returned to queue; "
                            f"suspended {count} compute supervisor(s)"
                        )
                    else:
                        repo.set_flag("compute_active_slots", str(worker_count.resumed(repo, slot_most, args.workers)))
                        repo.set_flag("resource_governor_phase", "host_managed")
                        ramp_state |= {"meter": HostCpuMeter(), "stepped_at": time.monotonic(),
                                       "limiter": None}
                        count = resume_group("compute")
                        print(f"resume: restarted {count} suspended compute process(es)")
                worker_target = worker_count.tick(repo, services=services, state=ramp_state, most=slot_most,
                                                  paused=paused_now, launch=launch, spawn=_spawn_executor, now=now)
                if now >= next_ramp_tick and not paused_now and worker_target is None:
                    next_ramp_tick = now + RAMP_TICK_SECONDS
                    ramp_line = _concurrency_ramp_tick(
                        repo, state=ramp_state, baseline=slot_floor,
                        ceiling=slot_ceiling, spawn_executor=_spawn_executor)
                    if ramp_line and RAMP_LOG:
                        print(ramp_line, flush=True)
                if now >= next_source_check:
                    next_source_check = now + 2.0
                    try:
                        assert_installation_unchanged("supervisor watchdog")
                    except DeploymentProvenanceFence as exc:
                        repo.emit("deployment_fleet_fenced", {
                            "expected_source_fingerprint": fingerprint,
                            "reason": str(exc),
                        })
                        print(
                            "deployment provenance fence: runtime installation changed underneath "
                            "the active fleet; draining without accepting further work. Restart this "
                            "build after the update completes."
                        )
                        exit_code = DEPLOYMENT_FENCE_EXIT_CODE
                        break
                if deadline is not None and now > deadline:
                    print("wall limit reached; tearing down fleet")
                    break
                if not repo.fleet_has_work(version):
                    break
                deployment_exit = False
                for record in services:
                    if record.get("disabled") or record.get("suspended"):
                        continue
                    proc = record["proc"]
                    if proc is None and now >= (record.get("retry_at") or float("inf")):
                        if _launched(launch, record, now):
                            _back_off(repo, services, record, None)
                    if proc is None or proc.poll() is None:
                        continue
                    if proc.returncode == DEPLOYMENT_FENCE_EXIT_CODE:
                        repo.emit("deployment_fleet_fenced", {
                            "service": record["module"],
                            "returncode": proc.returncode,
                            "reason": "child supervisor observed deployment provenance drift",
                        })
                        print(
                            f"deployment provenance fence: {record['module']} detected runtime drift; "
                            "draining the fleet instead of restarting services"
                        )
                        exit_code = DEPLOYMENT_FENCE_EXIT_CODE
                        deployment_exit = True
                        break
                    disposition, delay = _service_crash_disposition(record, now)
                    if disposition == "backoff":
                        record["proc"] = None
                        _back_off(repo, services, record, now + delay)
                        continue
                    if disposition == "fatal":
                        raise RuntimeError(
                            f"{record['module']} entered a crash loop "
                            f"({len(record['crashes'])} exits/minute)"
                        )
                    assert delay is not None
                    print(f"service {record['module']} exited {proc.returncode}; "
                          f"restarting in {delay:.2f}s")
                    time.sleep(delay)
                    _launched(launch, record, time.monotonic())
                if deployment_exit:
                    break
                time.sleep(0.5)
            except DatabaseOperationalError as exc:
                _wait_for_the_database(exc, database_waits)
    except KeyboardInterrupt:
        print("\ninterrupt: stopping fleet and killing in-flight engine children "
              "(durable state is preserved)")
        exit_code = 130
    except DeploymentProvenanceFence as exc:
        print(f"deployment provenance fence: {exc}; draining fleet and requiring restart")
        exit_code = DEPLOYMENT_FENCE_EXIT_CODE
    except Exception as exc:
        print(f"fleet stopped: {type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        drain()
        if dashboard_admin_file is not None:
            dashboard_admin_file.unlink(missing_ok=True)
        if internal_api_file is not None:
            internal_api_file.unlink(missing_ok=True)
        stop_signals.__exit__(None, None, None)

    if exit_code:
        return exit_code
    args.campaign = campaign_id
    return cmd_status(args)


def cmd_candidate_show(args):
    db, _, _ = paths(args)
    repo = Repo(db)
    if getattr(args, "campaign", None):
        rows = repo.conn.execute(
            "SELECT candidate_id,campaign_id FROM candidates WHERE campaign_id=? AND candidate_id LIKE ? || '%'",
            (args.campaign, args.id)).fetchall()
    else:
        rows = repo.conn.execute(
            "SELECT candidate_id,campaign_id FROM candidates WHERE candidate_id LIKE ? || '%'",
            (args.id,)).fetchall()
    if len(rows) != 1:
        print(f"{'no' if not rows else len(rows)} campaign memberships match prefix {args.id!r}; "
              "pass --campaign when the same law is used more than once")
        return 1
    candidate = repo.candidate(rows[0]["candidate_id"], rows[0]["campaign_id"])
    from graph_scale_dynamics.dsl import dsl
    verified = dsl.fingerprint(candidate["spec"]) == candidate["candidate_id"]
    print(f"candidate {candidate['candidate_id']}")
    print(f"state {candidate['state']} | campaign {candidate['campaign_id']} | "
          f"lineage {candidate['lineage_parent'] or 'fresh'}")
    print(f"fingerprint recomputed from spec: {'VERIFIED' if verified else 'MISMATCH'}")
    print(json.dumps(candidate["spec"], indent=2, sort_keys=True))
    return 0 if verified else 2


def cmd_candidate(args):
    return cmd_candidate_show(args) if args.sub == "show" else cmd_candidate_submit(args)


def cmd_serve(args):
    already_running = postgres_running(ROOT)
    db, blobs, var = paths(args)
    if live := live_fleet(var) or live_in_folder(ROOT, FLEET_PID_FILE):
        print(f"refusing to serve: {live}. The fleet serves its own dashboard; stop it first.")
        return 2
    with on_record(var / SERVE_PID_FILE):
        return _serve(args, db, blobs, var, owns_folder_runtime=(
            os.environ.get("GSD_INTEGRATION_TEST") != "1" and not already_running))


def _serve(args, db, blobs: Path, var: Path, *, owns_folder_runtime: bool):
    init_db(db)
    from graph_scale_dynamics.services.calibration_gate import (
        CalibrationGateError, ensure_probe_calibration,
    )
    try:
        calibration_status = ensure_probe_calibration(var, build_number=BUILD_NUMBER, root=ROOT)
    except CalibrationGateError as exc:
        print(f"refusing to serve: {exc}")
        if owns_folder_runtime:
            _stop_folder_postgres()
        return 3
    with Repo(db) as repo:
        campaign_id = str(campaign_control.reporting_focus(repo) or "")
        if not campaign_id:
            print("no active campaign in this folder; create one before serve")
            if owns_folder_runtime:
                _stop_folder_postgres()
            return 2
        try:
            _cal_path = Path(calibration_status["path"])
            repo.set_flag("calibration_artifact_json", _cal_path.read_text(encoding="utf-8"))
            repo.set_flag("calibration_artifact_path", str(_cal_path))
        except Exception as exc:
            print(f"calibration ledger cache not written: {type(exc).__name__}: {exc}")
    api_port = int(getattr(args, "api_port", 0) or (int(args.port) + 1))
    report_root = var / "reports" / f"live_campaign_{campaign_id}"
    token = secrets.token_urlsafe(24)
    admin_file, _, _, _ = _write_dashboard_admin_capability(
        var, port=args.port, base_path=getattr(args, "base_path", ""), token=token
    )
    internal_file = _write_internal_api_capability(var)
    written = {f: f.read_text(encoding="utf-8") for f in (admin_file, internal_file)}
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    runtime_tmp = BlobStore(blobs).volatile_root / "runtime"
    runtime_tmp.mkdir(parents=True, exist_ok=True)
    runtime_log = runtime_tmp / "log"
    runtime_log.mkdir(parents=True, exist_ok=True)
    base_env = dict(
        os.environ, PYTHONPATH=str(ROOT), TMPDIR=str(runtime_tmp),
        TMP=str(runtime_tmp), TEMP=str(runtime_tmp), GSD_RUNTIME_LOG_DIR=str(runtime_log),
    )
    base_env = owned_env(base_env)
    base_env.pop("GSD_DASHBOARD_ADMIN_TOKEN", None)
    base_env.pop("GSD_DASHBOARD_ADMIN_FILE", None)
    api_env = _dashboard_process_environment(base_env, admin_file)
    api_env["GSD_DATABASE_APPLICATION_NAME"] = "gsd-api"
    web_env = dict(base_env, GSD_DATABASE_APPLICATION_NAME="gsd-web")
    processes: list[subprocess.Popen] = []
    stop_signals = interrupt_on().__enter__()
    try:
        api_cmd = [sys.executable, "-m", "graph_scale_dynamics.services.api.main", "--db", service_database_reference(db),
                   "--blobs", str(blobs), "--port", str(api_port), "--bind", "127.0.0.1",
                   "--report-campaign", campaign_id, "--report-root", str(report_root),
                   "--internal-token-file", str(internal_file), "--snapshot-tmp", str(runtime_tmp),
                   "--exploration-map-mode", "off", "--past-research-mode", "off"]
        processes.append(subprocess.Popen(api_cmd, cwd=ROOT, env=api_env, start_new_session=True))
        web_cmd = [sys.executable, "-m", "graph_scale_dynamics.services.web.main", "--port", str(args.port), "--bind", str(args.bind),
                   "--api-port", str(api_port), "--reports", str(report_root),
                   "--internal-token-file", str(internal_file)]
        for allowed in getattr(args, "allow_host", []) or []:
            web_cmd += ["--allow-host", allowed]
        if getattr(args, "base_path", ""):
            web_cmd += ["--base-path", str(args.base_path)]
        processes.append(subprocess.Popen(web_cmd, cwd=ROOT, env=web_env, start_new_session=True))
        print(f"dashboard web: http://127.0.0.1:{args.port}/ · loopback API :{api_port} · reports by the quiet report")
        while all(proc.poll() is None for proc in processes):
            time.sleep(0.5)
        return next((proc.returncode for proc in processes if proc.poll() is not None), 0) or 0
    except KeyboardInterrupt:
        return 130
    finally:
        for proc in processes:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
        for capability, content in written.items():
            unlink_if_ours(capability, content)
        stop_signals.__exit__(None, None, None)
        fleet_now = live_fleet(var) if owns_folder_runtime else None
        if owns_folder_runtime and fleet_now:
            print(f"dashboard control plane drained; folder-local PostgreSQL left running: {fleet_now}")
        elif owns_folder_runtime:
            print("dashboard control plane drained; stopping owned folder-local PostgreSQL instance")
            _stop_folder_postgres()


SHIPPED_PARTS = ("docs", "graph_scale_dynamics", "tools", "tests", "engine_rs", "runtime", "calibration", ".git",
                 "README.md", "LICENSE", "BUILD_NUMBER", "pyproject.toml", "uv.lock", "main.py", "setup.py")


def shipped_part(var: Path) -> str | None:
    root = ROOT.resolve()
    resolved = Path(var).resolve()
    for name in SHIPPED_PARTS:
        part = root / name
        if resolved == part or part in resolved.parents:
            return f"`{name}`"
    return None


def cmd_reset(args) -> int:
    root = ROOT.resolve()
    var = root / (args.var or "var")
    targets = [root / "instance", var, root / ".env.postgres"]
    present = [path for path in targets if path.exists()]

    print(f"project root: {root}")
    if not present:
        print("nothing to reset; this folder is already clean")
        return 0
    if (shipped := shipped_part(var)) is not None:
        raise SystemExit(f"refusing to reset: --var {args.var} is {shipped}, part of the tree as it was shipped, not a "
                         "state directory; nothing was deleted")
    for path in present:
        resolved = path.resolve()
        if resolved == root:
            raise SystemExit("refusing to delete the project root itself")
        if root not in resolved.parents:
            raise SystemExit(f"refusing to delete outside the project root: {resolved}")
    if live := live_fleet(var) or live_in_folder(root):
        print(f"refusing to reset: {live}. Stop it first; nothing was deleted.")
        return 2
    for path in present:
        kind = "directory" if path.is_dir() else "file"
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else path.stat().st_size
        print(f"  will delete {kind:<9} {path.relative_to(root)}  ({size / 1e6:.1f} MB)")
    print("\nThis destroys all campaigns, candidates, measurements, decisions,")
    print("artifacts and PostgreSQL state in this folder. It cannot be undone.")
    print("Take a backup first with: uv run python main.py backup --output backups/pre-reset")

    if not args.yes:
        from graph_scale_dynamics.operations.study_record import reset_phrase
        expected = reset_phrase(var)
        typed = input(f"\nType '{expected}' to confirm: ").strip()
        if typed != expected:
            print("confirmation did not match; nothing was deleted")
            return 1

    helper = root / "tools" / "postgres_instance.py"
    if helper.is_file() and (root / "instance").exists():
        print("stopping folder-local PostgreSQL...")
        result = subprocess.run([sys.executable, str(helper), "stop"], cwd=root,
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  stop failed: {(result.stderr or result.stdout).strip().splitlines()[-1:] or ['no output']}")
            print("refusing to delete a data directory that may be in use; nothing was deleted")
            return 3

    from graph_scale_dynamics.operations.scratch_namespace import stop_holder
    if stop_holder(root):
        print("stopped this folder's scratch holder")
    for path in present:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink()
        print(f"  deleted {path.relative_to(root)}")

    print("\nreset complete. The next database command recreates the instance:")
    print("  uv run python main.py run")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="main.py: see docs/TOOLS.md")
    parser.add_argument("--var", default="var",
                        help="state directory beneath this project root; defaults to ./var")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="apply schema migrations and create local blob storage")
    reset = sub.add_parser(
        "reset", help="delete this folder's PostgreSQL instance, blobs and all research state")
    reset.add_argument("--yes", action="store_true",
                       help="skip the interactive confirmation ('reset study <id>', the study this folder recorded)")
    sub.add_parser("benchmark")


    sweep_cmd = sub.add_parser(
        "sweep",
        help="end this folder's orphaned fleet children; name the volatile namespaces (none deleted)")
    sweep_cmd.add_argument("--dry-run", action="store_true", help="report only, delete nothing")
    sweep_cmd.add_argument("--no-children", action="store_true", help="skip orphaned children")
    selftest = sub.add_parser(
        "selftest",
        help="run the whole deploy sequence and every verification lane in one go")
    selftest.add_argument("--quick", action="store_true", help="skip the 300-second vertical slice")
    selftest.add_argument("--no-postgres", action="store_true")
    selftest.add_argument("--window-seeds", type=int, default=3)
    hardware = sub.add_parser("hardware", help="diagnose CPU power/temperature sensors used by the dashboard")
    hardware.add_argument("--sample-seconds", type=float, default=0.5,
                          help="interval used to derive RAPL watts (default: 0.5)")
    hardware.add_argument("--membw-wait-seconds", type=float, default=6.0,
                          help="seconds to wait for the 4 s memory-bandwidth collector's first sample (default: 6)")
    audit = sub.add_parser("audit", help="cross-check PostgreSQL state and blob integrity")
    audit.add_argument("--metadata-only", action="store_true")
    audit.add_argument("--no-orphans", action="store_true")
    audit.add_argument(
        "--repair-missing-derived", action="store_true",
        help="detach metadata only for missing optional analysis-curve blobs; "
             "raw/provenance blobs are never auto-repaired",
    )
    audit.add_argument("--yes", action="store_true",
                       help="required with --repair-missing-derived")
    audit.add_argument("--max-detail", type=int, default=100)
    audit.add_argument("--fail-on", choices=("error", "warning"), default="error")
    audit.add_argument("--timeout", type=int, default=1800,
                       help="per-statement timeout in seconds for this audit only; "
                            "0 disables it. The fleet's 300s runtime default is "
                            "meant for short transactions, not a full report.")
    backup = sub.add_parser("backup", help="create a quiescent PostgreSQL plus blob backup")
    backup.add_argument("--output", required=True)
    backup.add_argument("--allow-live", action="store_true",
                        help="back up a running fleet; retention waits while the backup holds the maintenance lock, "
                             "but a body evicted before the backup started is not in it")
    restore = sub.add_parser("restore", help="restore a backup into this folder (its database, blobs and state)")
    restore.add_argument("backup")
    restore.add_argument("--force", action="store_true",
                         help="replace a folder that already holds blobs, a database or state")
    sub.add_parser("pause", help="pause new simulation and analysis claims")
    sub.add_parser("resume", help="resume simulation and analysis claims")
    rekeyp = sub.add_parser(
        "calibration-rekey",
        help="re-stamp a stale calibration table after verifying a sample, instead "
             "of recomputing all of it (dry by default)")
    rekeyp.add_argument("--sample", type=int, default=40,
                        help="how many cells to recompute and compare; default 40")
    rekeyp.add_argument("--budget", type=float, default=180.0,
                        help="WALL seconds at the worker count the sample may cost; "
                             "default 180. Pass 0 for no budget")
    rekeyp.add_argument("--workers", type=int, default=None,
                        help="worker processes; defaults to cpu_count-1, as the suite does")
    rekeyp.add_argument("--deep", action="store_true",
                        help="sample the LARGEST cell of every family instead of the "
                             "cheapest; thorough for size-dependent changes and slow")
    rekeyp.add_argument("--inert-observable", action="append", default=None,
                        metavar="NAME",
                        help="name an observable the change is confined to. If no "
                             "calibration cell records it, the change cannot move a "
                             "stored value and the justification is composed for you. "
                             "Repeatable. Refused if the observable IS recorded.")
    rekeyp.add_argument("--apply", action="store_true")
    rekeyp.add_argument("--justification", default=None,
                        help="why this change could not move a stored value; "
                             "required with --apply and recorded on the table")
    rekeyp.add_argument("--json", action="store_true")
    rebuild = sub.add_parser(
        "rebuild-phenotypes",
        help="rebuild stored phenotypes from rung summaries already recorded (dry by default)")
    rebuild.add_argument("--campaign", default=None)
    rebuild.add_argument("--apply", action="store_true",
                         help="write the rebuilt records; without this nothing is written")
    rebuild.add_argument("--limit", type=int, default=None)
    rebuild.add_argument("--json", action="store_true")
    workload = sub.add_parser("workload", help="the groups' shares and the CPUs the system keeps")
    workload.add_argument("--split", default=None, help="e.g. A=1,B=1; '' treats every campaign alike")
    workload.add_argument("--system-cpus", default=None, help="CPUs no child runs on, e.g. 0,16; '' for none")
    focus = sub.add_parser("focus", help="best laws one at a time: neighbours, seeds, depth, beside the blind draw")
    focus.add_argument("--study", required=True)
    focus.add_argument("--law", default=None)
    focus.add_argument("--show", action="store_true")
    extend = sub.add_parser("extend-only",
                            help="close a campaign to new candidates, or reopen it")
    extend.add_argument("campaign")
    extend.add_argument("--on", action="store_true", help="stop proposing new candidates")
    extend.add_argument("--off", action="store_true", help="resume proposing")
    campaign = sub.add_parser("campaign", help="inspect/manage campaigns; no subcommand opens the manager")
    campaign_sub = campaign.add_subparsers(dest="sub", required=False)
    campaign_sub.add_parser("list", help="list campaigns with logical DB and raw-blob sizes")
    start = campaign_sub.add_parser("start", help="create a new immutable experimental campaign")
    start.add_argument("--spec", required=True)
    start.add_argument("--allow-unvalidated-analyzer", action="store_true")
    start.add_argument("--parent", help="optional parent campaign for experimental lineage")
    start.add_argument("--reason", help="why this experimental campaign is being created")
    start.add_argument("--based-on-report", help="ingest the report artifact that motivated this campaign")
    start.add_argument("--search-seed", type=int, help="explicit proposer RNG seed; default is a fresh random 63-bit seed")
    provenance = campaign_sub.add_parser("provenance", help="show immutable campaign manifest and lifecycle events")
    provenance.add_argument("campaign_id")
    provenance.add_argument("--output", help="JSON destination; default is a timestamped file under var/reports/")
    use = campaign_sub.add_parser("use", help="set the default home discovery campaign")
    use.add_argument("campaign_id", nargs="?")
    reopen = campaign_sub.add_parser("reopen", help="reactivate a closed immutable unlinked campaign in place")
    reopen.add_argument("campaign_id", nargs="?")
    reopen.add_argument("--reason")
    for held_name, held_help in (
            ("pause", "stop a campaign spending the fleet, keeping every unit of its work"),
            ("resume", "let a paused campaign claim work again")):
        held = campaign_sub.add_parser(held_name, help=held_help)
        held.add_argument("campaign_id", nargs="?")
        held.add_argument("--reason")
    close = campaign_sub.add_parser("close", help="stop/fence a campaign without deleting evidence")
    close.add_argument("campaign_id", nargs="?")
    close.add_argument("--keep-children", action="store_true",
                       help="do not close linked confirmation campaigns")
    delete = campaign_sub.add_parser("delete", help="stop/fence then delete a campaign immediately")
    delete.add_argument("campaign_id", nargs="?")
    delete.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    delete.add_argument("--cascade", action="store_true", help="also delete linked child campaigns")
    archive = campaign_sub.add_parser("archive", help="condense blob evidence into PostgreSQL and retire raw campaign rows")
    archive.add_argument("campaign_id", nargs="?")
    archive.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    archive.add_argument("--allow-incomplete", action="store_true",
                         help="scan to the end and record every missing or corrupt blob before aborting; an archive with any error "
                              "never retires live evidence")
    artifacts = sub.add_parser("artifacts", help="inspect or reclaim content-addressed artifact storage")
    artifacts_sub = artifacts.add_subparsers(dest="sub", required=True)
    gc = artifacts_sub.add_parser("gc", help="dry-run safe unreferenced-artifact garbage collection")
    gc.add_argument("--apply", action="store_true", help="delete unreferenced database rows and blob files; requires a paused, drained fleet")
    gc.add_argument("--confirm", default="", help="with --apply, must be exactly GC")
    retention = artifacts_sub.add_parser(
        "retention", help="artifact storage by retention class and body state"
    )
    retention.add_argument("--campaign", help="only the artifacts of one campaign")
    proposal = sub.add_parser("proposal", help="a campaign's graded proposal intelligence, fixed by its spec")
    proposal_sub = proposal.add_subparsers(dest="sub", required=True)
    proposal_status = proposal_sub.add_parser("status", help="show the effective proposal mode")
    proposal_status.add_argument("--campaign", help="defaults to the stored home campaign")
    candidate = sub.add_parser("candidate")
    candidate_sub = candidate.add_subparsers(dest="sub", required=True)
    submit = candidate_sub.add_parser("submit")
    submit.add_argument("--campaign", required=True)
    submit.add_argument("--file", required=True)
    show = candidate_sub.add_parser("show", help="print the exact canonical spec of a candidate")
    show.add_argument("--id", required=True, help="candidate id or unique prefix")
    show.add_argument("--campaign", help="campaign membership when a law appears in multiple campaigns")
    run = sub.add_parser("run", help="one-command sustained research runtime with dashboard + integrated numbered reports")
    run.add_argument("--reopen", action="store_true",
                     help="reopen the selected campaign if it is closed; without this, run refuses")
    run.add_argument("--study", default=None, help="a new folder's first start: the committed study to start "
                     "(e.g. 162), recorded in var/study.json; omitted, the default study")
    run.add_argument("--spec", default=None,
                     help="a campaign spec (a JSON path, or a packaged config's name); in a new folder it starts that one "
                          "campaign instead of the default study (start from a copy of "
                          "graph_scale_dynamics/resources/configs/campaign_engine_survey.json); omitted resumes the "
                          "home campaign, or starts the default study in a new folder")
    run.add_argument("--workers", type=int, default=0,
                     help="0 = auto: use logical CPU threads up to 32; override explicitly or with GSD_AUTO_WORKERS")
    run.add_argument("--physical-cores-only", action="store_true",
                     help="auto mode: use one slot per physical core instead of SMT siblings")
    run.add_argument("--port", type=int, default=8765, help="public web/dashboard port")
    run.add_argument("--api-port", type=int, default=None,
                     help="loopback API port; default is public port + 1")
    run.add_argument("--bind", default="0.0.0.0",
                     help="dashboard listen address; defaults to 0.0.0.0 for trusted-LAN monitoring")
    run.add_argument("--allow-host", action="append", default=[],
                     help="additional dashboard hostname allowed by DNS-rebinding protection")
    run.add_argument("--base-path", default="",
                     help="external dashboard URL prefix such as /research behind a path-based reverse proxy")
    run.add_argument("--exploration-map-mode", choices=("lazy", "always", "off"), default="lazy",
                     help="dashboard exploration-map payload: lazy on demand (default), always, or off")
    run.add_argument("--past-research-mode", choices=("lazy", "always", "off"), default="lazy",
                     help="dashboard past-research payload: lazy on demand (default), always, or off")
    run.add_argument("--wall", type=float, default=None)
    run.add_argument("--no-browser", action="store_true",
                     help="do not auto-open the dashboard in the default browser")
    run.add_argument("--no-dashboard", action="store_true",
                     help="run the canonical fleet without starting the local API/dashboard")
    run.add_argument("--campaign", default=None,
                     help="resume this stored campaign (full fleet incl proposer) instead of the spec file")
    run.add_argument("--search-seed", type=int, default=None,
                     help="fresh campaign only: fixed proposer/search RNG seed; omitted = cryptographically random")
    run.add_argument("--no-power-telemetry", action="store_true",
                     help="operational test mode: suppress CPU package power and temperature sensors; CPU/memory telemetry and research continue")
    status = sub.add_parser("status")
    status.add_argument("--campaign", required=True)
    report = sub.add_parser("report")
    report.add_argument("--campaign", required=True)
    serve = sub.add_parser("serve", help="serve the dashboard and integrated numbered reports without starting the fleet")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--api-port", type=int, default=None)
    serve.add_argument("--bind", default="0.0.0.0")
    serve.add_argument("--allow-host", action="append", default=[])
    serve.add_argument("--base-path", default="")
    serve.add_argument("--exploration-map-mode", choices=("lazy", "always", "off"), default="lazy")
    serve.add_argument("--past-research-mode", choices=("lazy", "always", "off"), default="lazy")
    return parser


def main(argv=None) -> int:
    startup_banner()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not [a for a in argv if not a.startswith("-")]:
        argv = list(argv) + ["run"]
    args = parser.parse_args(argv)
    return {"run": cmd_run, "init": cmd_init, "benchmark": cmd_benchmark,
            "reset": cmd_reset,
            "hardware": cmd_hardware, "selftest": cmd_selftest, "sweep": cmd_sweep, "audit": cmd_audit, "backup": cmd_backup, "restore": cmd_restore,
            "pause": cmd_compute_control, "resume": cmd_compute_control,
            "extend-only": cmd_extend_only, "workload": cmd_workload, "focus": cmd_focus,
            "rebuild-phenotypes": cmd_rebuild_phenotypes,
            "calibration-rekey": cmd_calibration_rekey,
            "campaign": cmd_campaign, "artifacts": cmd_artifacts, "proposal": cmd_proposal,
            "candidate": cmd_candidate, "status": cmd_status,
            "report": cmd_report, "serve": cmd_serve}[args.cmd](args) or 0


def _cli_var_directory(argv: list[str]) -> Path:
    value = "var"
    for index, token in enumerate(argv):
        if token == "--var" and index + 1 < len(argv):
            value = argv[index + 1]
            break
        if token.startswith("--var="):
            value = token.split("=", 1)[1]
            break
    var = Path(value).expanduser()
    if not var.is_absolute():
        var = ROOT / var
    var = var.resolve()
    var.relative_to(ROOT.resolve())
    return var


def cli_entrypoint() -> int:
    from graph_scale_dynamics.observability.console import install_append_log, restore_append_log

    argv = list(sys.argv[1:])
    state = None
    try:
        if argv and argv[0] != "run":
            var = _cli_var_directory(argv)
            state = install_append_log(var / "log" / "main.log", argv=[sys.executable, str(Path(__file__).name), *argv])
    except Exception as exc:
        print(f"warning: could not open append-only main console log: {exc}", file=sys.stderr, flush=True)
    try:
        return main(argv)
    finally:
        restore_append_log(state)


if __name__ == "__main__":
    raise SystemExit(cli_entrypoint())
