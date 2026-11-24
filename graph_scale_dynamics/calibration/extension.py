from __future__ import annotations

import time
from pathlib import Path

from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import (
    _worker_init, extension_ladder, family_ladder, plan_extension_cells, suite_families,
)


def run_extension(document: dict, path: Path, families: list[dict], gate_families: list[dict], *,
                  seeds: int, gate_seeds: int, gate_max_nodes: int | None, workers: int | None = None,
                  log=print, waivers: list[dict] | None = None, root: str | None = None) -> dict:
    from graph_scale_dynamics.calibration.admission import Admission
    from graph_scale_dynamics.calibration.suite import _gib, _memory_holders, run_suite

    plan = plan_extension_cells(families, seeds=seeds)
    snapshot = Admission().decide(0, 0)
    log(f"calibration: memory for cells: available {_gib(snapshot['available_bytes'])} of "
        f"{_gib(snapshot['total_bytes'])}, less the floor {_gib(snapshot['reserve_bytes'])}, leaves "
        f"{_gib(snapshot['budget_bytes'])}; shared memory on the host:")
    for line in _memory_holders():
        log(f"calibration:     {line}")
    return run_suite(document, path, gate_families, seeds=gate_seeds, max_nodes=gate_max_nodes,
                     workers=workers, log=log, waivers=waivers, root=root, plan=plan)


def _census_task(task: dict) -> dict:
    from graph_scale_dynamics.calibration import structure
    from graph_scale_dynamics.calibration.cells import build_graph

    family = suite_families([task["family"]])[0]
    started = time.monotonic()
    try:
        n, edges = build_graph(family, task["parameter"], task["seed"])
        record = structure.measure(n, edges)
    except Exception as exc:  # noqa: BLE001
        record = {"contract": structure.STRUCTURE_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
    record["backfilled_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return dict(task, structure=record, elapsed=round(time.monotonic() - started, 3))


def _task_process_main(task: dict, conn) -> None:
    from graph_scale_dynamics.calibration.cells import _cell_process_setup

    _cell_process_setup(task.get("parent_pid"))
    _worker_init()
    task = dict(task)
    run = task.pop("run")
    try:
        result = run(task)
    except BaseException as exc:  # noqa: BLE001
        result = dict(task, status="failed", error=f"{type(exc).__name__}: {exc}")
    try:
        import resource
        result["peak_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except (ImportError, OSError, ValueError):
        pass
    result["elapsed_seconds"] = result.get("elapsed")
    try:
        conn.send(result)
    finally:
        conn.close()


def _task_in_pool(task: dict) -> dict:
    task = dict(task)
    return task.pop("run")(task)


def census_memory(document: dict) -> dict:
    from graph_scale_dynamics.calibration import structure

    cells = {}
    for key, cell in (document.get("cells") or {}).items():
        record = cell.get("structure")
        if isinstance(record, dict) and isinstance(record.get("peak_rss_bytes"), int) and not record.get("error"):
            cells[key] = {"family": cell.get("family"), "n": cell.get("n"), "status": "ok",
                          "peak_rss_bytes": record["peak_rss_bytes"], "mean_rss_bytes": record.get("mean_rss_bytes")}
    largest: dict[str, dict] = {}
    for row in (structure.committed_census_memory() or {}).get("rows") or []:
        if isinstance(row.get("peak_rss_bytes"), int) and isinstance(row.get("n"), int) and not row.get("error"):
            if row["n"] > (largest.get(row.get("family")) or {}).get("n", 0):
                largest[row.get("family")] = row
    for family, row in sorted(largest.items()):
        cells[f"the build's measurement: {family}"] = {
            "family": family, "n": row["n"], "status": "ok",
            "peak_rss_bytes": row["peak_rss_bytes"], "mean_rss_bytes": row.get("mean_rss_bytes")}
    return cells


def census_plan(document: dict, families: list[dict]) -> list[dict]:
    from graph_scale_dynamics.calibration import structure
    from graph_scale_dynamics.calibration.cells import cell_key

    cells = document.get("cells") or {}
    todo = []
    for family in families:
        for rung in family_ladder(family) + extension_ladder(family):
            seed = 0
            while True:
                key = cell_key(family["name"], rung["parameter"], seed)
                cell = cells.get(key)
                if cell is None or not structure.wanted(family, seed):
                    break
                has = isinstance(cell.get("structure"), dict) and not cell["structure"].get("error")
                if cell.get("status") == "ok" and (not has or structure.cut_off(cell["structure"])):
                    todo.append({"key": key, "family": family["name"], "parameter": rung["parameter"],
                                 "seed": seed, "n": rung["n"]})
                seed += 1
    todo.sort(key=lambda t: (t["n"], t["family"], t["seed"]))
    return todo


def add_structure(document: dict, path: Path, gate_families: list[dict], *, gate_seeds: int,
                  gate_max_nodes: int | None, families: list[str] | None = None, workers: int | None = None,
                  log=print, waivers: list[dict] | None = None, root: str | None = None,
                  save_every_seconds: float = 60.0, admission=None) -> dict:
    todo = census_plan(document, suite_families(families))

    def record(cell: dict, result: dict) -> str | None:
        s = dict(result["structure"])
        for key in ("peak_rss_bytes", "mean_rss_bytes"):
            if isinstance(result.get(key), int) and not s.get("error"):
                s[key] = int(result[key])
        cell["structure"] = s
        if s.get("error"):
            return None
        held = f" peak {s['peak_rss_bytes'] / 1024 ** 3:.2f} GiB" if "peak_rss_bytes" in s else ""
        return f"gap={s.get('gap')} diameter={s.get('diameter_lower')}{held}"

    return _backfill(document, path, gate_families, todo, _census_task, record, "structure", "census",
                     gate_seeds=gate_seeds, gate_max_nodes=gate_max_nodes, workers=workers, log=log,
                     waivers=waivers, root=root, save_every_seconds=save_every_seconds, memory=census_memory,
                     admission=admission)


def add_margins(document: dict, path: Path, gate_families: list[dict], *, gate_seeds: int,
                gate_max_nodes: int | None, families: list[str] | None = None, workers: int | None = None,
                log=print, waivers: list[dict] | None = None, root: str | None = None, max_n: int | None = None,
                save_every_seconds: float = 60.0, admission=None) -> dict:
    from graph_scale_dynamics.calibration.margins import margin_task, margins_plan
    todo = margins_plan(document, suite_families(families), max_n=max_n)
    mismatched = []

    def record(cell: dict, result: dict) -> str | None:
        found = dict(result["margins"])
        if found.get("error"):
            cell["d_s_margins"] = found
            return None
        if not found.pop("matches_the_cell", True):
            mismatched.append(result["key"])
            found["mismatch"] = {"measured_d_s": found.get("d_s"), "cell_d_s": result.get("stored_d_s")}
        found.pop("d_s", None)
        cell["d_s_margins"] = found
        return (f"plateau {found['plateau'].get('delta_aicc')} whole range {found['whole_range'].get('delta_aicc')}"
                + ("  (d_s differs from the cell's)" if "mismatch" in found else ""))

    done = _backfill(document, path, gate_families, todo, margin_task, record, "margins", "cell",
                     gate_seeds=gate_seeds, gate_max_nodes=gate_max_nodes, workers=workers, log=log,
                     waivers=waivers, root=root, save_every_seconds=save_every_seconds, admission=admission)
    return dict(done, mismatched=mismatched)


def _backfill(document: dict, path: Path, gate_families: list[dict], todo: list[dict], task_fn, record_fn,
              label: str, noun: str, *, gate_seeds: int, gate_max_nodes: int | None, workers: int | None,
              log, waivers: list[dict] | None, root: str | None, save_every_seconds: float,
              memory=None, admission=None) -> dict:
    from graph_scale_dynamics.calibration.suite import default_workers

    workers = default_workers() if workers is None else int(workers)
    started = time.monotonic()
    added = failed = 0
    last_save = time.monotonic()
    blocked: list[dict] = []

    log(f"{label}: {len(todo)} {noun}(s) to read" + (f" with up to {workers} at once, as memory admits them"
                                                    if workers else " inline"))

    def save(final: bool = False) -> None:
        nonlocal last_save
        if final:
            T.refresh(document, gate_families, seeds=gate_seeds, max_nodes=gate_max_nodes, waivers=waivers,
                      root=root)
        T.write(document, path)
        last_save = time.monotonic()

    def finish(result: dict) -> None:
        nonlocal added, failed
        cell = (document.get("cells") or {}).get(result["key"])
        if not isinstance(cell, dict):
            return
        said = record_fn(cell, result)
        added += said is not None
        failed += said is None
        log(f"{label}: [{added + failed:>4}/{len(todo)}] {result['family']:<30} n={result['n']:>8} "
            f"seed={result['seed']} {said if said is not None else 'failed'} ({result['elapsed']:.1f}s)")
        if time.monotonic() - last_save >= save_every_seconds:
            save()

    def arrived(result: dict, _running: int = 1) -> None:
        if "structure" not in result and "margins" not in result:
            from graph_scale_dynamics.calibration.cells import cell_key
            error = {"error": f"worker: {result.get('error') or 'no result'}"}
            result = {"key": cell_key(result["family"], result["parameter"], result["seed"]),
                      "family": result["family"], "parameter": result["parameter"], "seed": result["seed"],
                      "n": result["n"], "elapsed": 0.0, "structure": dict(error), "margins": dict(error)}
        elif isinstance(result.get("elapsed_seconds"), (int, float)):
            result = dict(result, elapsed=result["elapsed_seconds"])
        finish(result)

    try:
        if workers <= 0:
            for task in todo:
                finish(task_fn(task))
        else:
            from graph_scale_dynamics.calibration.admission import Admission
            from graph_scale_dynamics.calibration.suite import _run_in_workers
            _run_in_workers(todo, workers=workers, admission=admission or Admission(), document=document,
                            log=log, task_args=lambda task: dict(task, run=task_fn), finish=arrived,
                            blocked=blocked, root=root, science="", cell_target=_task_process_main,
                            small_target=_task_in_pool, memory=memory,
                            progress=lambda: f"{label}: {added + failed:,} of {len(todo):,} done")
    except BaseException:
        T.write(document, path)
        raise
    save(final=True)
    return {"added": added, "failed": failed, "planned": len(todo), "blocked": blocked,
            "elapsed_seconds": round(time.monotonic() - started, 1)}
