#!/usr/bin/env python3
from __future__ import annotations

import _thread
import argparse
import contextlib
import functools
import json
import signal
import sys
import threading
import time
from pathlib import Path


def _find_root() -> Path | None:
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for candidate in [start, *start.parents]:
            if (candidate / "graph_scale_dynamics" / "db" / "connection.py").is_file():
                return candidate
    return None


_ROOT = _find_root()
if _ROOT is not None:
    sys.path.insert(0, str(_ROOT))

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import suite_families
from graph_scale_dynamics.calibration.suite import load_waivers, run_suite
from graph_scale_dynamics.services.calibration_core import (
    DEFAULT_CANDIDATE, DEFAULT_FLOOR, DEFAULT_NS, DEFAULT_RAMP, run_probes, run_sweep_scan,
)


def _clock(seconds: float) -> str:
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, whole_seconds = divmod(rest, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{whole_seconds:02d}s"


ENDS_IT_FROM_OUTSIDE = (signal.SIGTERM, signal.SIGHUP)


@contextlib.contextmanager
def stopped_only_through_this_process(log):
    heard = {"by": "Ctrl-C", "exit": 128 + int(signal.SIGINT)}
    if threading.current_thread() is not threading.main_thread():
        yield heard
        return

    def ended(signum, _frame) -> None:
        for each in ENDS_IT_FROM_OUTSIDE:
            signal.signal(each, signal.SIG_IGN)
        heard.update(by=signal.Signals(signum).name, exit=128 + int(signum))
        raise KeyboardInterrupt

    before = {each: signal.signal(each, ended) for each in ENDS_IT_FROM_OUTSIDE
              if signal.getsignal(each) is signal.SIG_DFL}
    over = threading.Event()
    watcher = mask = None
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        from multiprocessing import resource_tracker
        resource_tracker.ensure_running()
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})

        def wait() -> None:
            while not over.is_set():
                if signal.sigtimedwait({signal.SIGINT}, 0.5) is not None:
                    with contextlib.suppress(OSError):
                        log("")
                        log("calibration: Ctrl-C: stopping, and ending the cells that are running")
                    _thread.interrupt_main()
                    return

        watcher = threading.Thread(target=wait, name="gsd-calibration-ctrl-c", daemon=True)
        watcher.start()

    def as_it_was() -> None:
        over.set()
        if watcher is not None:
            watcher.join(timeout=2.0)
            while signal.sigtimedwait({signal.SIGINT}, 0) is not None:
                pass
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        for each, handler in before.items():
            signal.signal(each, handler)

    try:
        yield heard
    except KeyboardInterrupt:
        over.set()
        raise
    except BaseException:
        as_it_was()
        raise
    as_it_was()


def _set_aside(table: Path, history: Path) -> Path | None:
    import shutil
    target = history / f"unusable_table_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    try:
        history.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(table, target)
    except OSError:
        return None
    return target if target.read_bytes() == table.read_bytes() else None


def _end_what_still_runs() -> None:
    import multiprocessing
    for child in multiprocessing.active_children():
        child.terminate()
    for child in multiprocessing.active_children():
        child.join(timeout=5.0)


def measure_the_table_whole(root: Path, var: Path, *, workers: int | None = None, log=None) -> int:
    from graph_scale_dynamics.calibration.cells import plan_cells, plan_extension_cells
    from graph_scale_dynamics.calibration.extension import run_extension
    from graph_scale_dynamics.calibration.fingerprint import analysis_version
    from graph_scale_dynamics.calibration.suite import default_workers
    from graph_scale_dynamics.operations.scratch_holders import name_other_folders
    from tools.collect_calibration import collect, say_collected

    log = log or functools.partial(print, flush=True)
    full = C.profile() == C.PROFILE_FULL
    seeds = C.AUTHORITATIVE_SEEDS if full else C.reduced_seeds()
    max_nodes = None if full else C.reduced_max_nodes()
    out = C.durable_artifact_path(root) if full else C.non_authoritative_artifact_path(var)
    families = suite_families()
    waivers = load_waivers(var)
    plan = plan_cells(families, seeds=seeds, max_nodes=max_nodes)
    past = plan_extension_cells(families, seeds=C.EXTENSION_SEEDS) if full else []
    workers = default_workers() if workers is None else int(workers)

    document = T.load(out)
    if out.exists() and (document is None or not T.verify(document, families, seeds=seeds, max_nodes=max_nodes,
                                                           waivers=waivers, root=str(root))["usable"]):
        kept = _set_aside(out, C.history_dir(var))
        if kept is None:
            log(f"the file at {out} is not a table this tree can go on from (another suite's, or not readable), and "
                f"no copy of it could be written under {C.history_dir(var)}: move it away and type the command again")
            return 2
        log(f"the file at {out} is not a table this tree can go on from (another suite's, or not readable): copied, "
            f"byte for byte, to {kept}, and a new table is measured in its place")
        document = None
    if document is None:
        document = T.new_table(families, seeds=seeds, max_nodes=max_nodes, authoritative=full,
                               profile="full" if full else "reduced", root=str(root))
    document["authoritative"] = full
    document["profile"] = {"name": "full" if full else "reduced", "seeds": int(seeds), "max_nodes": max_nodes,
                           "families": [family["name"] for family in families]}
    kept_now = len(T.classify_cells(document, plan + past, str(root))[T.CELL_CURRENT])

    if full:
        log(f"== the calibration table, measured whole: {len(plan):,} cells on {len(families)} families' ladders at "
            f"{seeds} seeds, {len(past)} past the ladders, then the collection ==")
    else:
        log(f"== a rehearsal of the calibration table ({C.ENV_PROFILE}=reduced): {len(plan):,} cells on "
            f"{len(families)} families' ladders at {seeds} seed(s), to {max_nodes:,} nodes, nothing past the ladders, "
            "then the collection; NOT the table a study reads ==")
    log(f"   the table: {out} ({analysis_version(str(root))}, suite {C.SUITE_VERSION})")
    log(f"   measured and kept so far: {kept_now:,} of {len(plan) + len(past):,} cells")
    log(f"   up to {workers} cells at once, as memory admits them; a paused cell is a python3 in state T at 0% CPU"
        if workers else "   one cell at a time, in this process")
    log("   Ctrl-C stops it: every finished cell is kept, and the same command goes on from there")
    started = time.monotonic()
    heard = {"by": "Ctrl-C", "exit": 128 + int(signal.SIGINT)}
    try:
        with stopped_only_through_this_process(log) as heard:
            name_other_folders(root, log=lambda line: log(f"calibration: scratch: {line}"))
            run_suite(document, out, families, seeds=seeds, max_nodes=max_nodes, workers=workers, log=log,
                      waivers=waivers, root=str(root))
            if full:
                log(f"== the {len(past)} cells past the ladders, {C.EXTENSION_SEEDS} seeds each; charted, never "
                    "gating ==")
                run_extension(document, out, families, families, seeds=C.EXTENSION_SEEDS, gate_seeds=seeds,
                              gate_max_nodes=None, workers=workers, log=log, waivers=waivers, root=str(root))
            T.write(document, out)
            packed = collect(root, out.parent.parent if full else out.parent, table_path=out)
            closing = say_collected(packed)
            log("")
            log(f"== done in {_clock(time.monotonic() - started)} on this clock ==")
            for line in closing:
                log(line)
    except KeyboardInterrupt:
        _end_what_still_runs()
        on_disk = T.load(out) or {"cells": {}}
        kept_now = len(T.classify_cells(on_disk, plan + past, str(root))[T.CELL_CURRENT])
        with contextlib.suppress(OSError):
            log("")
            log(f"Stopped by {heard['by']} after {_clock(time.monotonic() - started)}. {kept_now:,} of "
                f"{len(plan) + len(past):,} cells are measured and kept in {out}; a cell that was running is not, "
                "and starts again from its beginning.")
            log("Type the same command to go on: it measures no finished cell again.")
        return int(heard["exit"])
    whole = len(T.classify_cells(document, plan + past, str(root))[T.CELL_CURRENT]) == len(plan) + len(past)
    return 0 if whole and (document.get("deviation") or {}).get("verdict") == "PASS" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/probe_calibration.py: see docs/TOOLS.md")
    parser.add_argument("--whole", action="store_true",
                        help="767: measure the table whole and stop: every family's ladder at "
                             f"{C.AUTHORITATIVE_SEEDS} seeds, the cells past the ladders, then the collection, "
                             "ending on the gate's verdict in plain words and the one file to send. Ctrl-C keeps "
                             "every finished cell and the same command goes on from there; "
                             f"{C.ENV_PROFILE}=reduced makes a rehearsal of it under <var>")
    parser.add_argument("--probes", action="store_true",
                        help="run the pipeline trial against the release anchors")
    parser.add_argument("--sweep-scan", action="store_true",
                        help="measure ESS response to sweep budget per N")
    parser.add_argument("--probe-ladders", action="store_true",
                        help="run (or resume) the calibration suite over the families")
    parser.add_argument("--extend", action="store_true",
                        help="524: measure the rungs past each family's ladder (contract.LADDER_EXTENSIONS, "
                             f"to about 4 M nodes, {C.EXTENSION_SEEDS} seeds unless --seeds); charted, never gating")
    parser.add_argument("--structure", action="store_true",
                        help="524: add the structure census to every cell that should carry one and does not, "
                             "without re-running a probe; 532: as many at once as memory admits")
    parser.add_argument("--margins", action="store_true",
                        help="532: add d_s's two AICc margins (the plateau's and the whole range's) to every cell "
                             "measured before cells recorded them; d_s alone, checked against the cell's value")
    parser.add_argument("--seeds", type=int, default=None,
                        help=f"seeds per cell (default {C.AUTHORITATIVE_SEEDS} for the suite, "
                             "2 for the pipeline trial and the scan); fewer makes a reduced table")
    parser.add_argument("--max-nodes", type=int, default=None,
                        help="truncate family ladders; makes a reduced table")
    parser.add_argument("--families", type=str, default="",
                        help="comma-separated family subset; makes a reduced table")
    parser.add_argument("--workers", type=int, default=None,
                        help="the most cells or tasks at once (0 = inline; default cpu_count-1); memory "
                             "decides how many of them run")
    parser.add_argument("--recompute", action="store_true",
                        help="discard existing cells and measure every cell again (deliberate)")
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--ns", type=str, default="")
    parser.add_argument("--ramp", type=str, default="")
    parser.add_argument("--candidate", type=Path, action="append", default=None,
                        help="reference Hamiltonian spec; repeatable for multiple references")
    parser.add_argument("--record-points", type=int, default=2000,
                        help="trajectory recording resolution for scan runs")
    parser.add_argument("--var", type=Path, default=None,
                        help="workspace var for a reduced table and waivers (default <root>/var)")
    parser.add_argument("--out", type=Path, default=None,
                        help="table path; default is the durable table for an authoritative "
                             "run and <var>/calibration/probe_calibration.json otherwise")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = _ROOT or Path.cwd()
    var = (args.var or (root / "var")).resolve()
    if args.whole:
        beside = [flag for flag, given in (
            ("--probes", args.probes), ("--sweep-scan", args.sweep_scan), ("--probe-ladders", args.probe_ladders),
            ("--extend", args.extend), ("--structure", args.structure), ("--margins", args.margins),
            ("--seeds", args.seeds is not None), ("--max-nodes", args.max_nodes is not None),
            ("--families", bool(args.families)), ("--recompute", args.recompute), ("--out", args.out is not None),
            ("--json", args.json)) if given]
        if beside:
            parser.error(f"--whole measures the table as the folder's profile says and takes --workers and --var "
                         f"only, not {', '.join(beside)}")
        return measure_the_table_whole(root, var, workers=args.workers)
    if not (args.probes or args.sweep_scan or args.probe_ladders or args.extend or args.structure or args.margins):
        parser.error("nothing to do: pass --whole, --probes, --sweep-scan, --probe-ladders, --extend, --structure "
                     "and/or --margins")

    from graph_scale_dynamics.domain.version import BUILD_NUMBER

    family_names = [f for f in args.families.split(",") if f] or None
    families = suite_families(family_names)
    suite_seeds = args.seeds if args.seeds is not None else C.AUTHORITATIVE_SEEDS
    authoritative = (args.probe_ladders and suite_seeds >= C.AUTHORITATIVE_SEEDS
                     and args.max_nodes is None and family_names is None)
    if args.extend and args.probe_ladders and not authoritative:
        parser.error("--extend adds to the authoritative table; run it without reducing options")
    durable = C.durable_artifact_path(root)
    if args.out is not None:
        out = args.out.resolve()
    elif args.probe_ladders and not authoritative:
        out = C.non_authoritative_artifact_path(var)
    else:
        out = durable
    if args.probe_ladders and not authoritative and out == durable:
        parser.error("a reduced run (--seeds below "
                     f"{C.AUTHORITATIVE_SEEDS}, --max-nodes or --families) must not overwrite "
                     f"the durable table {durable}; pass --out")
    waivers = load_waivers(var)
    log = (lambda *_: None) if args.json else print
    if args.extend or args.probe_ladders or args.structure or args.margins:
        from graph_scale_dynamics.operations.scratch_holders import name_other_folders
        name_other_folders(root, log=lambda line: log(f"calibration: scratch: {line}"))

    document = None if args.recompute else T.load(out)
    if document is not None and document.get("contract") != C.CONTRACT:
        log(f"{out} is not a {C.CONTRACT} document; starting a new table there")
        document = None
    if document is None:
        document = T.new_table(families if args.probe_ladders else suite_families(),
                               seeds=suite_seeds if args.probe_ladders else C.AUTHORITATIVE_SEEDS,
                               max_nodes=args.max_nodes if args.probe_ladders else None,
                               authoritative=authoritative if args.probe_ladders else (out == durable),
                               profile=("full" if authoritative else "reduced"), root=str(root))

    if args.probe_ladders:
        document["authoritative"] = bool(authoritative)
        document["profile"] = {"name": "full" if authoritative else "reduced",
                               "seeds": int(suite_seeds), "max_nodes": args.max_nodes,
                               "families": [f["name"] for f in families]}
        log(f"== calibration suite: {len(families)} families, {suite_seeds} seed(s), "
            f"{'no truncation' if args.max_nodes is None else f'ladders <= {args.max_nodes} nodes'}, "
            f"{'authoritative' if authoritative else 'NOT authoritative'} -> {out} ==")
        run = run_suite(document, out, families, seeds=suite_seeds, max_nodes=args.max_nodes,
                        workers=args.workers, log=log, waivers=waivers, root=str(root))
        deviation = document.get("deviation") or {}
        log(f"  {deviation.get('summary_line')} ({run.get('cells_computed')} computed, "
            f"{run.get('cells_reused')} reused, {run.get('elapsed_seconds')}s)")
        for name, family in deviation.get("families", {}).items():
            log(f"  {name}: verdict {family['verdict']} · trends {family['trends']} · "
                f"false-confidence readings {family['false_confidence_readings']}")

    if args.extend or args.structure or args.margins:
        from graph_scale_dynamics.calibration.extension import add_margins, add_structure, run_extension
        gate_profile = document.get("profile") or {}
        gate_seeds = int(gate_profile.get("seeds") or C.AUTHORITATIVE_SEEDS)
        gate_max = gate_profile.get("max_nodes")
        gate_families = suite_families(gate_profile.get("families") or None)
        if args.extend:
            seeds = args.seeds if args.seeds is not None else C.EXTENSION_SEEDS
            log(f"== calibration extension: {len(families)} families past their ladders, {seeds} seed(s) "
                f"-> {out}; charted, never gating ==")
            run = run_extension(document, out, families, gate_families, seeds=seeds, gate_seeds=gate_seeds,
                                gate_max_nodes=gate_max, workers=args.workers, log=log, waivers=waivers,
                                root=str(root))
            log(f"  {run.get('cells_computed')} computed, {run.get('cells_reused')} reused, "
                f"{len(run.get('blocked') or [])} blocked, {run.get('elapsed_seconds')}s")
        if args.structure:
            log(f"== structure census for every cell without one -> {out} ==")
            done = add_structure(document, out, gate_families, gate_seeds=gate_seeds, gate_max_nodes=gate_max,
                                 families=[f["name"] for f in families], workers=args.workers, log=log,
                                 waivers=waivers, root=str(root))
            log(f"  {done['added']} census(es) added, {done['failed']} failed, {len(done['blocked'])} blocked, "
                f"{done['elapsed_seconds']}s")
        if args.margins:
            log(f"== d_s margins for every cell without them -> {out} ==")
            done = add_margins(document, out, gate_families, gate_seeds=gate_seeds, gate_max_nodes=gate_max,
                               families=[f["name"] for f in families], workers=args.workers, log=log,
                               waivers=waivers, root=str(root), max_n=args.max_nodes)
            log(f"  {done['added']} cell(s) given their margins, {done['failed']} failed, {len(done['blocked'])} "
                f"blocked, {len(done['mismatched'])} whose d_s differs from the value they hold, "
                f"{done['elapsed_seconds']}s")

    if args.probes:
        log("== pipeline trial: release anchors through the real pipeline ==")
        from graph_scale_dynamics.services.calibration_gate import record_pipeline_trial
        probes = run_probes(seeds=args.seeds if args.seeds is not None else 2)
        record_pipeline_trial(document, probes, suite_fingerprint=document.get("suite_fingerprint"),
                              build_number=BUILD_NUMBER)
        for row in probes["rows"]:
            measured = "refused" if row["measured"] is None else f"{row['measured']:.4f}"
            log(f"  [{row['status']:^6}] {row['anchor']}: {row['channel']} "
                f"= {measured} (theory {row['theory']:.4f}, tol {row['tolerance']})")
        for closure in probes["einstein"]:
            for variant in closure["closures"]:
                log(f"  einstein {closure['anchor']}: d_s {closure['d_s_measured']:.4f} "
                    f"vs 2*d_f/d_w = {variant['d_s_from_relation']:.4f} "
                    f"(residual {variant['residual']:+.4f}, d_f from {variant['d_f_source']})")

    if args.sweep_scan:
        ns = tuple(int(x) for x in args.ns.split(",") if x) or DEFAULT_NS
        ramp = tuple(int(x) for x in args.ramp.split(",") if x) or DEFAULT_RAMP
        seeds = args.seeds if args.seeds is not None else 2
        candidates = args.candidate or [root / DEFAULT_CANDIDATE]
        section = document.get("sweep_scan") if isinstance(document.get("sweep_scan"), dict) else None
        if not section or "references" not in section:
            section = {"references": {}}
        for spec_path in candidates:
            log(f"== sweep scan [{Path(spec_path).stem}]: N in {ns}, ramp {ramp}, "
                f"{seeds} seed(s), floor {args.floor}, {args.record_points} record points ==")
            scan = run_sweep_scan(spec_path=spec_path, ns=ns, ramp=ramp, seeds=seeds,
                                  floor=args.floor, record_points=args.record_points,
                                  verbose=not args.json)
            log(f"  required sweeps: {scan['required_sweeps']} "
                f"| law: {scan['law'].get('best', scan['law']['status'])}")
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            section["references"][str(scan.get("reference") or "reference")] = dict(
                scan, generated_utc=now, build_number=int(BUILD_NUMBER))
            section["generated_utc"] = now
            section["build_number"] = int(BUILD_NUMBER)
            from graph_scale_dynamics.calibration.fingerprint import science_fingerprint
            section["science_fingerprint"] = science_fingerprint()
        document["sweep_scan"] = section

    T.write(document, out)
    if args.json:
        print(json.dumps(document, indent=2, default=float))
    else:
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
