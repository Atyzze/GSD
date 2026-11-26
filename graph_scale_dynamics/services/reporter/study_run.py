from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STUDY_RUN_CONTRACT = "gsd-study-report-run-1"
GIB = 1024 ** 3
CAMPAIGN_SNAPSHOT_MULTIPLE = 5.0
CAMPAIGN_FLOOR_BYTES = 3 * GIB
MEMORY_SHARE = 0.7
REPORT_CHILD_FLOOR_BYTES = 512 * 1024 ** 2
TERMINAL = ("complete", "complete_with_errors", "error", "unchanged")
COST_NAME = "study_run_cost.json"
MEASURED_MARGIN = 1.25
TRANSPORT = "in place (548)"
REPORT_CHILD_SHARE = 0.5


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _rss() -> int:
    import psutil
    return int(psutil.Process().memory_info().rss)


class LocalChannel:
    nice = False

    def __init__(self, campaign_id: str, root: Path, *, db: str, progress: Path, request_id: str,
                 workers: int = 1, memory_budget: int | None = None, api=None):
        from graph_scale_dynamics.domain.model import utc_now
        self.campaign_id, self.root, self.db, self.progress = str(campaign_id), Path(root), str(db), Path(progress)
        self.workers, self.memory_budget, self.api = max(1, int(workers)), memory_budget, api
        self.resident_after = 0
        self._phase = {"state": "requested", "campaign_id": self.campaign_id, "request_id": request_id,
                       "trigger_source": "quiet", "requested_utc": utc_now(), "stage": None, "error": None,
                       "paused": False, "diagnostics": {}}
        self._write()

    def _write(self) -> None:
        keep = {k: v for k, v in self._phase.items() if k != "diagnostics"}
        cycle = (self._phase.get("diagnostics") or {}).get("cycle") or {}
        keep["seconds"] = cycle.get("total_seconds")
        keep["report_pool"] = cycle.get("report_pool")
        _atomic_json(self.progress, keep)

    def state(self, campaign_id: str) -> dict:
        return dict(self._phase)

    def phase(self, campaign_id: str, *, state=None, stage=None, error=None, snapshot_revision=None,
              started=False, finished=False, diagnostics=None) -> dict:
        from graph_scale_dynamics.domain.model import utc_now
        for key, value in (("state", state), ("stage", stage), ("snapshot_revision", snapshot_revision),
                           ("diagnostics", diagnostics)):
            if value is not None:
                self._phase[key] = value
        if error is not None:
            self._phase["error"] = error or None
        if started:
            self._phase["started_utc"] = utc_now()
        if finished:
            self._phase["finished_utc"] = utc_now()
        self._write()
        return dict(self._phase)

    def revisions(self, campaign_id: str) -> dict:
        from graph_scale_dynamics.db.repo import Repo
        from graph_scale_dynamics.research.report_pipeline import report_revision_preflight
        with Repo(self.db) as repo:
            return report_revision_preflight(repo, campaign_id)

    def publish(self, campaign_id: str, name: str, payload: dict) -> None:
        target = self.root / "manifest.json" if name == "manifest" else self.root / "reports" / f"{name}.json"
        _atomic_json(target, payload)
        if name == "manifest":
            try:
                from graph_scale_dynamics.db.repo import Repo
                from graph_scale_dynamics.reporting.cycle_record import cycle_row
                row = cycle_row(payload)
                if row:
                    with Repo(self.db) as repo:
                        repo.record_report_cycle(row)
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self, campaign_id: str, *, spill_to: Path) -> tuple[dict, dict]:
        import resource

        from graph_scale_dynamics.db.repo import Repo
        from graph_scale_dynamics.reporting.snapshot_transport import in_transport_types, volume
        from graph_scale_dynamics.research.report_pipeline import collect_replication_snapshot
        from graph_scale_dynamics.operations.report_session import apply_snapshot_session_policy
        apply_snapshot_session_policy()
        before = _rss()
        stages, mark = [], {"key": None, "t": time.monotonic()}

        def progress(update: dict) -> None:
            key = (str(update.get("campaign_id") or campaign_id), str(update.get("stage") or ""))
            if key != mark["key"]:
                now = time.monotonic()
                if mark["key"] is not None:
                    stages.append({"campaign_id": mark["key"][0], "stage": mark["key"][1],
                                   "seconds": round(now - mark["t"], 3)})
                mark.update(key=key, t=now)
                self.phase(campaign_id, stage=f"snapshot · campaign {key[0]} · {key[1]}")

        with Repo(self.db) as repo:
            snapshot = collect_replication_snapshot(repo, campaign_id, progress=progress)
        progress({"campaign_id": campaign_id, "stage": "types"})
        self.phase(campaign_id, stage="snapshot · collected; converting it in place to the types the reports read")
        replication = in_transport_types(snapshot)
        del snapshot
        self.resident_after = _rss()
        progress({"campaign_id": "", "stage": "done"})
        try:
            size = volume(replication)
        except Exception:  # noqa: BLE001
            size = {}
        return replication, {"compressed_bytes": 0, "decompressed_bytes": int(size.get("json_bytes") or 0),
                             "size_estimated": bool(size.get("estimated")), "parts": size.get("parts") or [],
                             "other_part_bytes": size.get("other_json_bytes"), "scratch_bytes": 0,
                             "resident_bytes": max(0, self.resident_after - before),
                             "peak_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
                             "spilled": False, "stages": stages,
                             "storage_target": "collected in the study runner's campaign worker, converted in place"}

    def pool_size(self, trigger_source, transfer: dict, reports: int) -> tuple[int, str]:
        import psutil
        measured = int(_read_json(self.root / COST_NAME).get("child_private_peak_bytes") or 0)
        each = max(REPORT_CHILD_FLOOR_BYTES, int(MEASURED_MARGIN * measured) if measured
                   else int(REPORT_CHILD_SHARE * int(transfer.get("resident_bytes") or 0)))
        available = int(psutil.virtual_memory().available)
        budget = min(available // 2, int(self.memory_budget)) if self.memory_budget else available // 2
        by_memory = max(1, budget // each)
        workers = max(1, min(self.workers, int(reports), by_memory))
        return workers, (f"{workers} children: this campaign's share of {self.workers} cores, {reports} reports, memory "
                         f"for {by_memory} at {each / GIB:.2f} GiB each ({'measured' if measured else 'guessed'})")

    def fetch(self, path: str) -> bytes:
        if self.api is None:
            raise RuntimeError("the API is not reachable from the study runner, so the runtime evidence is not fetched")
        return self.api.fetch_bytes(path, timeout=60.0)


def campaign_cost(base: Path, campaign: str, children: int = 1) -> tuple[int, str]:
    from graph_scale_dynamics.operations.report_home import root_for
    root = root_for(base, campaign)
    measured = _read_json(root / COST_NAME)
    worker = int(measured.get("worker_peak_bytes") or 0)
    child = max(REPORT_CHILD_FLOOR_BYTES, int(measured.get("child_private_peak_bytes") or 0))
    if worker > 0 and measured.get("transport") == TRANSPORT:
        held = int(measured.get("worker_resident_bytes") or worker)
        return max(CAMPAIGN_FLOOR_BYTES, int(MEASURED_MARGIN * max(worker, held + children * child))), "measured"
    cycle = _read_json(root / "manifest.json").get("cycle") or {}
    resident = int(cycle.get("snapshot_resident_bytes") or 0)
    if resident > 0:
        each = max(REPORT_CHILD_FLOOR_BYTES, int(REPORT_CHILD_SHARE * resident))
        return max(CAMPAIGN_FLOOR_BYTES, int(MEASURED_MARGIN * (resident + children * each))), "guessed"
    size = int(cycle.get("snapshot_decompressed_bytes") or 0)
    return max(CAMPAIGN_FLOOR_BYTES, int(CAMPAIGN_SNAPSHOT_MULTIPLE * size)), "guessed"


def _number(campaign: str):
    return (0, int(campaign)) if str(campaign).isdigit() else (1, str(campaign))


def plan(campaigns: list[str], base: Path, *, cores: int | None = None, available: int | None = None) -> dict:
    import psutil
    cores = int(cores or os.cpu_count() or 1)
    available = int(available if available is not None else psutil.virtual_memory().available)
    budget = int(available * MEMORY_SHARE)
    guess = {c: campaign_cost(base, c) for c in campaigns}
    order = sorted(campaigns, key=_number)
    fit, used = 0, 0
    for campaign in sorted(campaigns, key=lambda c: -guess[c][0]):
        if fit and used + guess[campaign][0] > budget:
            break
        fit, used = fit + 1, used + guess[campaign][0]
    at_once = max(1, min(len(campaigns) or 1, cores, fit))
    each = max(1, cores // at_once)
    costs = guess
    measured = sum(1 for c in campaigns if costs[c][1] == "measured")
    return {"at_once": at_once, "report_workers_each": each, "order": order, "budget_bytes": budget,
            "costs": {c: costs[c][0] for c in campaigns},
            "memory_budget_each": budget // at_once,
            "why": (f"{at_once} campaign{'s' if at_once != 1 else ''} at a time of {len(campaigns)}, with {each} of "
                    f"the {cores} cores each. What each is expected to hold: "
                    + ", ".join(f"campaign {c} {costs[c][0] / GIB:.1f} GiB" for c in order)
                    + f" ({measured} measured on its last report, the rest guessed from its last snapshot), within "
                    f"{budget / GIB:.1f} GiB, {MEMORY_SHARE:.0%} of the {available / GIB:.1f} GiB free.")}


def unchanged(base: Path, campaign: str, db: str) -> str | None:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.operations.report_home import root_for
    from graph_scale_dynamics.research.report_pipeline import report_revision_preflight
    manifest = _read_json(root_for(base, campaign) / "manifest.json")
    last = (manifest.get("report_revisions") or {}).get("report_revision")
    if str(manifest.get("cycle_state") or "").upper() != "COMPLETE" or not last:
        return None
    if int(manifest.get("build_number") or 0) != int(BUILD_NUMBER):
        return None
    try:
        with Repo(db) as repo:
            now = report_revision_preflight(repo, campaign).get("report_revision")
    except Exception:  # noqa: BLE001
        return None
    return f"unchanged since its cycle of {manifest.get('generation_finished_utc')} (revision {last})" \
        if now == last else None


def _api(api_base: str | None, token_file: str | None):
    if not api_base or not token_file or not Path(token_file).is_file():
        return None
    from graph_scale_dynamics.operations.internal_api import InternalAPI
    return InternalAPI(api_base, token_file, timeout=30.0)


def run_worker(args) -> int:
    import resource

    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.operations.report_home import root_for
    from graph_scale_dynamics.services.reporter import main as report_main
    root = root_for(Path(args.base), args.campaign)
    channel = LocalChannel(args.campaign, root, db=args.db, progress=Path(args.progress_dir) / f"{args.campaign}.json",
                           request_id=args.request_id, workers=args.workers, memory_budget=args.memory_budget,
                           api=_api(args.api_base, args.token_file))
    channel.nice = bool(getattr(args, "gentle", False))
    code = report_main.run_report_cycle(channel, args.campaign, root)
    cycle = (channel.state(args.campaign).get("diagnostics") or {}).get("cycle") or {}
    _atomic_json(root / COST_NAME, {
        "worker_peak_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        "worker_resident_bytes": channel.resident_after or None, "transport": TRANSPORT,
        "snapshot_peak_bytes": int(cycle.get("snapshot_peak_bytes") or 0) or None,
        "child_private_peak_bytes": int(report_main.CHILD_PRIVATE_PEAK["bytes"]),
        "children": int((cycle.get("report_pool") or {}).get("workers") or 1),
        "snapshot_bytes": int(cycle.get("snapshot_decompressed_bytes") or 0), "measured_utc": utc_now()})
    return code


def run(args) -> int:
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.operations.process_ownership import owned_env
    campaigns = [c for c in str(args.campaigns).split(",") if c]
    progress = Path(args.progress)
    folder = progress.parent
    layout = plan(campaigns, Path(args.base))
    if getattr(args, "gentle", False):
        layout.update(report_workers_each=1, why="one campaign's cycle beside a running fleet: one report at a time, "
                                                  "niced")
    record = {"contract": STUDY_RUN_CONTRACT, "request_id": args.request_id, "pid": os.getpid(),
              "started_utc": utc_now(), "finished": False, **layout,
              "campaigns": {c: {"state": "queued"} for c in campaigns}}
    for campaign in campaigns:
        why = unchanged(Path(args.base), campaign, args.db)
        if why:
            record["campaigns"][campaign] = {"state": "unchanged", "stage": why, "seconds": 0.0}
    _atomic_json(progress, record)
    started = time.monotonic()
    waiting = [c for c in layout["order"] if record["campaigns"][c]["state"] == "queued"]
    running = {}
    while waiting or running:
        while waiting and len(running) < layout["at_once"]:
            reserved = sum(layout["costs"][c] for c in running)
            fits = [c for c in waiting if reserved + layout["costs"][c] <= layout["budget_bytes"]]
            if running and not fits:
                break
            campaign = (fits or waiting)[0]
            waiting.remove(campaign)
            cmd = [sys.executable, "-m", "graph_scale_dynamics.services.reporter.study_run", "--worker",
                   "--campaign", campaign, "--db", args.db, "--base", str(args.base), "--progress-dir", str(folder),
                   "--request-id", args.request_id, "--workers", str(layout["report_workers_each"]),
                   "--memory-budget", str(max(layout["memory_budget_each"], layout["costs"][campaign]))]
            if args.api_base and args.token_file:
                cmd += ["--api-base", args.api_base, "--token-file", args.token_file]
            if getattr(args, "gentle", False):
                cmd.append("--gentle")
            log = open(folder / f"{campaign}.log", "ab")
            running[campaign] = (subprocess.Popen(cmd, stdout=log, stderr=log, env=owned_env()), log, time.monotonic())
            record["campaigns"][campaign] = {"state": "running", "started_utc": utc_now()}
        for campaign, (process, log, begun) in list(running.items()):
            seen = _read_json(folder / f"{campaign}.json")
            entry = dict(record["campaigns"][campaign], **{k: seen.get(k) for k in ("state", "stage", "error", "report_pool")
                                                          if seen.get(k) is not None})
            code = process.poll()
            if code is not None:
                log.close()
                running.pop(campaign)
                entry["seconds"] = round(time.monotonic() - begun, 1)
                entry["exit_code"] = code
                if entry.get("state") not in TERMINAL:
                    entry["state"] = "error"
                    entry["error"] = entry.get("error") or f"the campaign's worker exited with {code} before it finished"
            record["campaigns"][campaign] = entry
        record["seconds"] = round(time.monotonic() - started, 1)
        _atomic_json(progress, record)
        if waiting or running:
            time.sleep(1.0)
    record.update(finished=True, finished_utc=utc_now(), seconds=round(time.monotonic() - started, 1))
    _atomic_json(progress, record)
    return 0 if all(v.get("state") != "error" for v in record["campaigns"].values()) else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="every campaign's report cycle at once")
    parser.add_argument("--db", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--request-id", default="manual")
    parser.add_argument("--api-base")
    parser.add_argument("--token-file")
    parser.add_argument("--campaigns")
    parser.add_argument("--progress")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--campaign")
    parser.add_argument("--progress-dir")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget", type=int)
    parser.add_argument("--gentle", action="store_true",
                        help="one report at a time, niced: a cycle beside a running fleet")
    args = parser.parse_args(argv)
    return run_worker(args) if args.worker else run(args)


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
