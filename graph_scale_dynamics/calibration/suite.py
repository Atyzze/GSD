from __future__ import annotations

import concurrent.futures as cf
import math
import multiprocessing
import os
import platform
import signal
import statistics
import time
from collections import deque
from pathlib import Path

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.admission import (
    GROWTH_BYTES, GROWTH_WINDOW_SECONDS, PAUSE_MARGIN_BYTES, Admission, CellMemory, cell_pricing, mean_of, need_beside,
    pressure, remaining_bytes, rss_bytes, shed_line, still_to_take, timeline, to_continue, typical_shares,
)
from graph_scale_dynamics.calibration.cells import (
    _cell_process_main, _worker_init, _worker_measure, plan_cells, suite_families,
)

SMALL_CELL_NODES = 20000
ADMISSION_POLL_SECONDS = 30.0


HOLD_LOG_SECONDS = 300.0
HOLD_FIRST_SECONDS = 120.0
WATCH_SECONDS = 1.0
TRACE_SECONDS = 5.0
JOIN_SECONDS = 4.0
HEAD_PATIENCE_SECONDS = 1200.0
SHED_LIMIT = 2
PROGRESS_LOG_SECONDS = 600.0


def _gib(value: float) -> str:
    return f"{value / 1024 ** 3:.1f} GiB"


def _hold_line(running: int, workers: int, task: dict, predicted: int, basis: str, inflight: int,
               decision: dict, *, held: int | None = None, priced: int | None = None,
               counted: dict | None = None) -> str:
    if held is not None and counted is not None:
        running_part = (f"the running cells hold {_gib(held)} and may still take {_gib(inflight)} as admission "
                        f"counts it ({_gib(counted['typical_growth_bytes'])} to where they settle and "
                        f"{_gib(counted['spike_room_bytes'])} for the largest spike); this cell would need "
                        f"{_gib(decision.get('counted_bytes') or 0)} with the pause margin")
    elif held is not None and priced is not None:
        running_part = (f"the running cells hold {_gib(held)} of the {_gib(priced)} they are priced and may take "
                        f"{_gib(inflight)} more")
    else:
        running_part = f"the running cells may take {_gib(inflight)} more"
    return (f"calibration: {running} of {workers} worker(s) busy; memory, not CPU, holds the next cell "
            f"({task['key']}, n={task['n']:,}, priced {_gib(predicted)} by {basis}): available "
            f"{_gib(decision['available_bytes'])} less the floor {_gib(decision['reserve_bytes'])} leaves "
            f"{_gib(decision['budget_bytes'])}, and {running_part}.")


def _memory_holders() -> list[str]:
    try:
        from graph_scale_dynamics.observability.shared_memory import holders, summary_lines
        return summary_lines(holders()) or ["no large tmpfs or shared-memory holder found"]
    except Exception as exc:  # noqa: BLE001
        return [f"holders unavailable: {type(exc).__name__}: {exc}"]


class CalibrationGateError(RuntimeError):
    pass


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def default_workers() -> int:
    explicit = os.environ.get(C.ENV_WORKERS)
    if explicit is not None and explicit.strip():
        return max(0, int(explicit))
    return max(1, (os.cpu_count() or 2) - 1)


class _Estimator:
    def __init__(self):
        self.samples: list[tuple[float, float]] = []

    def add(self, n: int, elapsed: float) -> None:
        if n > 0 and elapsed > 0:
            self.samples.append((math.log(n), math.log(elapsed)))

    def predict(self, n: int) -> float | None:
        if len(self.samples) < 3:
            return None
        xs = [s[0] for s in self.samples]
        ys = [s[1] for s in self.samples]
        mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        if sxx <= 1e-12:
            return math.exp(mean_y)
        b = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
        b = min(max(b, 0.8), 2.0)
        a = mean_y - b * mean_x
        return math.exp(a + b * math.log(max(1, n)))

    def remaining(self, pending: list[dict], parallelism: int) -> float | None:
        if not pending:
            return 0.0
        predictions = [self.predict(t["n"]) for t in pending]
        if any(p is None for p in predictions):
            return None
        return sum(predictions) / max(1, parallelism)


def run_suite(document: dict, path: Path, families: list[dict], *, seeds: int,
              max_nodes: int | None, workers: int | None = None, log=print,
              admission: Admission | None = None, waivers: list[dict] | None = None,
              root: str | None = None, cell_callback=None, plan: list[dict] | None = None) -> dict:
    workers = default_workers() if workers is None else int(workers)
    admission = admission or Admission()
    plan = plan if plan is not None else plan_cells(families, seeds=seeds, max_nodes=max_nodes)
    classes = T.classify_cells(document, plan, root)
    current = set(classes[T.CELL_CURRENT])
    todo = [task for task in plan if task["key"] not in current]
    total = len(plan)
    done = len(current)
    started = time.monotonic()
    science = FP.science_fingerprint()
    estimator = _Estimator()
    blocked: list[dict] = []
    computed = 0
    run = {"started_utc": _utc(), "host": platform.node(), "workers": workers,
           "profile": (document.get("profile") or {}).get("name"),
           "cells_reused": done, "cells_planned": total}
    log(f"calibration: {done} of {total} cells current; computing {len(todo)}"
        + (f" with {workers} worker(s)" if workers else " inline"))
    if not todo:
        run.update({"finished_utc": _utc(), "cells_computed": 0, "elapsed_seconds": 0.0,
                    "blocked": []})
        T.record_run(document, run)
        return run

    def finish(cell: dict, running: int = 1) -> None:
        nonlocal done, computed
        done += 1
        computed += 1
        T.checkpoint(document, cell, path, families, seeds=seeds, max_nodes=max_nodes,
                     waivers=waivers, root=root)
        if cell.get("status") == "ok":
            estimator.add(int(cell.get("n") or 0), float(cell.get("elapsed_seconds") or 0.0))
        pending = [t for t in todo if t["key"] not in document["cells"]]
        remaining = estimator.remaining(pending, max(1, int(running)))
        channels = " ".join(
            f"{ch}={'refused' if not v.get('valid') else format(v['value'], '.3f')}"
            for ch, v in sorted((cell.get("channels") or {}).items()))
        log(f"calibration: [{done:>4}/{total}] {cell['family']:<24} n={cell.get('n', '?'):>8} "
            f"seed={cell['seed']:<2} {channels or cell.get('error', '')} "
            f"({cell.get('elapsed_seconds', 0):.1f}s) elapsed {_fmt_duration(time.monotonic() - started)}"
            f", remaining ~{_fmt_duration(remaining)}")
        if cell_callback is not None:
            cell_callback(cell)

    def task_args(task: dict) -> dict:
        args = dict(task, cell_fingerprint=FP.cell_fingerprint(task["family"], root),
                    science_fingerprint=science)
        measured = (document.get("cells") or {}).get(task["key"])
        if T.its_probes_are_current(measured, root):
            args["its_probes_are_current"] = measured
        return args

    if workers <= 0:
        for task in todo:
            finish(_worker_measure(task_args(task)))
    else:
        _run_in_workers(todo, workers=workers, admission=admission, document=document, log=log,
                        task_args=task_args, finish=finish, blocked=blocked, root=root, science=science,
                        progress=lambda: f"{done:,} of {total:,} cells done")
    blocked_key = "blocked_cells" if not any(t.get("extension") for t in plan) else "extension_blocked_cells"
    if blocked:
        document[blocked_key] = blocked
    else:
        document.pop(blocked_key, None)
    T.refresh(document, families, seeds=seeds, max_nodes=max_nodes, waivers=waivers, root=root)
    T.write(document, path)
    run.update({"finished_utc": _utc(), "cells_computed": computed,
                "elapsed_seconds": round(time.monotonic() - started, 1), "blocked": blocked})
    T.record_run(document, run)
    T.write(document, path)
    return run


class _LargeCell:
    only_its_start = False

    def __init__(self, context, task: dict, args: dict, price: int, basis: str, target=_cell_process_main, *,
                 typical: int | None = None, strict: bool = False):
        receive, send = context.Pipe(duplex=False)
        self.process = context.Process(target=target, args=(dict(args, parent_pid=os.getpid()), send),
                                       daemon=True, name=f"gsd-calibration-cell {task['key']}")
        self.process.start()
        send.close()
        self.receive = receive
        self.task, self.price, self.basis = task, int(price), basis
        self.only_its_start = isinstance(args.get("its_probes_are_current"), dict)
        self.typical = int(price if typical is None else typical)
        self.strict = bool(strict)
        self.started = time.monotonic()
        self.held = 0
        self.result = None
        self.paused_at: float | None = None
        self.paused_seconds = 0.0
        self.pauses = 0
        self.window: deque = deque()
        self.trace: list[tuple[float, int]] = []

    def active_seconds(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        paused = self.paused_seconds + (now - self.paused_at if self.paused_at is not None else 0.0)
        return max(0.0, now - self.started - paused)

    def read(self) -> int:
        now = time.monotonic()
        self.held = int(rss_bytes(self.process.pid) or 0)
        if self.paused_at is None:
            self.window.append((now, self.held))
            while self.window and now - self.window[0][0] > GROWTH_WINDOW_SECONDS:
                self.window.popleft()
            ran = self.active_seconds(now)
            if not self.trace or ran - self.trace[-1][0] >= TRACE_SECONDS:
                self.trace.append((ran, self.held))
        return self.held

    def growth(self) -> int:
        return self.held - min(v for _t, v in self.window) if self.window else 0

    def view(self) -> CellMemory:
        return CellMemory(key=self.task["key"], started=self.started, price=self.price, typical=self.typical,
                          held=self.held, growth=self.growth(), paused=self.paused_at is not None,
                          paused_at=self.paused_at, strict=self.strict)

    def pause(self) -> bool:
        if self.paused_at is not None:
            return True
        try:
            os.kill(self.process.pid, signal.SIGSTOP)
        except OSError:
            return False
        self.paused_at = time.monotonic()
        self.pauses += 1
        self.window.clear()
        return True

    def resume(self) -> float:
        if self.paused_at is None:
            return 0.0
        try:
            os.kill(self.process.pid, signal.SIGCONT)
        except OSError:
            pass
        waited = time.monotonic() - self.paused_at
        self.paused_seconds += waited
        self.paused_at = None
        self.window.clear()
        return waited

    def done(self) -> bool:
        if self.result is not None:
            return True
        try:
            if self.receive.poll():
                self.result = self.receive.recv()
                return True
        except (EOFError, OSError):
            return True
        return not self.process.is_alive()

    def collect(self) -> dict | None:
        self.done()
        if self.paused_at is not None:
            try:
                os.kill(self.process.pid, signal.SIGCONT)
            except OSError:
                pass
        self.process.join(timeout=JOIN_SECONDS)
        self.receive.close()
        record = self.result
        if isinstance(record, dict) and self.only_its_start:
            self.paused_at = None
        elif isinstance(record, dict):
            self.paused_at = None
            record["paused_seconds"] = round(self.paused_seconds, 1)
            if self.paused_seconds and isinstance(record.get("elapsed_seconds"), (int, float)):
                record["elapsed_seconds"] = round(max(0.0, float(record["elapsed_seconds"]) - self.paused_seconds), 3)
            if self.trace:
                record["memory_timeline"] = timeline(self.trace)
                record["mean_rss_bytes"] = mean_of(self.trace)
        return record

    def stop(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            if self.paused_at is not None:
                try:
                    os.kill(self.process.pid, signal.SIGCONT)
                except OSError:
                    pass
            self.process.join(timeout=JOIN_SECONDS)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=JOIN_SECONDS)
        try:
            self.receive.close()
        except OSError:
            pass


def _failed_cell(task: dict, error: str, root, science: str) -> dict:
    return {"family": task["family"], "parameter": task["parameter"], "seed": task["seed"], "n": task["n"],
            "status": "failed", "error": error, "cell_fingerprint": FP.cell_fingerprint(task["family"], root),
            "science_fingerprint": science, "channels": {}, "computed_utc": _utc(), "host": platform.node(),
            "elapsed_seconds": 0.0}


def _run_in_workers(todo: list[dict], *, workers: int, admission: Admission, document: dict, log,
                    task_args, finish, blocked: list[dict], root, science: str,
                    cell_target=_cell_process_main, small_target=_worker_measure,
                    patience: float = HEAD_PATIENCE_SECONDS, watch: float = WATCH_SECONDS,
                    hold_first: float = HOLD_FIRST_SECONDS, memory=None, progress=None) -> None:
    import multiprocessing.connection as mpc

    context = multiprocessing.get_context("spawn")
    small_pool = cf.ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_worker_init)
    small: dict[cf.Future, tuple[dict, int]] = {}
    large: list[_LargeCell] = []
    pending = list(todo)
    memory = memory or (lambda doc: doc.get("cells"))
    price = cell_pricing(memory(document))
    share = typical_shares(memory(document))
    head_since: dict[str, float] = {}
    sheds: dict[str, int] = {}
    strict: set[str] = set()
    last_hold_log = 0.0
    last_start = time.monotonic()
    last_wait_log = 0.0
    last_progress_log = time.monotonic()
    holders_shown = False

    def said() -> str:
        return f"; {progress()}" if progress is not None else ""

    def running() -> int:
        return sum(1 for f in small if not f.done()) + sum(1 for c in large if not c.done())

    def settles(family: str, cost: int) -> int:
        return int(cost * share(family)[0])

    def reprice() -> None:
        nonlocal price, share
        price = cell_pricing(memory(document))
        share = typical_shares(memory(document))
        for cell in large:
            cost, basis = price(cell.task["family"], cell.task["n"])
            if int(cost) != cell.price or basis != cell.basis:
                cell.price, cell.basis = int(cost), basis
            cell.typical = settles(cell.task["family"], cell.price)

    def counted_now() -> list[CellMemory]:
        views = [c.view() for c in large if not c.done()]
        views += [CellMemory(key=t["key"], started=0.0, price=cost, typical=cost)
                  for future, (t, cost) in small.items() if not future.done()]
        return views

    def queue_again(cell: _LargeCell, why: str) -> None:
        key = cell.task["key"]
        sheds[key] = sheds.get(key, 0) + 1
        if sheds[key] >= SHED_LIMIT:
            reason = (f"ended {sheds[key]} times: the host could not hold it inside its floor beside what "
                      "else runs here")
            log(f"calibration: BLOCKED {key}: {reason}")
            blocked.append({"key": key, "n": cell.task["n"], "reason": reason})
        else:
            strict.add(key)
            pending.insert(0, cell.task)
            log(f"calibration: {key} is queued again ({why}); it starts again when everything running could "
                "peak beside it")

    try:
        while pending or small or large:
            for future in [f for f in small if f.done()]:
                task, _cost = small.pop(future)
                try:
                    cell = future.result()
                except Exception as exc:  # noqa: BLE001
                    cell = _failed_cell(task, f"worker: {type(exc).__name__}: {exc}", root, science)
                finish(cell, running() + 1)
                reprice()
            for proc in [c for c in large if c.done()]:
                large.remove(proc)
                cell = proc.collect()
                if cell is None and proc.process.exitcode == -signal.SIGKILL:
                    log(f"calibration: {proc.task['key']} was ended from outside (SIGKILL, the kernel's "
                        "out-of-memory killer or by hand) after "
                        f"{_fmt_duration(proc.active_seconds())}, holding {_gib(proc.held)}")
                    queue_again(proc, "ended from outside")
                    continue
                if cell is None:
                    cell = _failed_cell(proc.task, f"its process ended with exit code {proc.process.exitcode} "
                                        "and sent no record (ended from outside, or out of memory)", root, science)
                finish(cell, running() + 1)
                reprice()

            now_mem = admission.decide(0, 0)
            floor, available = now_mem["reserve_bytes"], now_mem["available_bytes"]
            for cell in large:
                cell.read()
            asked = pressure([c.view() for c in large if c.paused_at is None],
                             [c.view() for c in large if c.paused_at is not None], available, floor)
            if asked and asked[0][0] == "end":
                victim = next(c for c in large if c.task["key"] == asked[0][1].key)
                was = "paused" if victim.paused_at is not None else "running"
                victim.stop()
                large.remove(victim)
                log(f"calibration: memory shed: available {_gib(available)} is under the shed line "
                    f"{_gib(shed_line(floor))}; ended the youngest {was} cell, {victim.task['key']} "
                    f"(n={victim.task['n']:,}, held {_gib(victim.held)}, priced {_gib(victim.price)}, "
                    f"{_fmt_duration(victim.active_seconds())} in)")
                queue_again(victim, "shed")
                continue
            for _action, view in asked:
                cell = next(c for c in large if c.task["key"] == view.key)
                if cell.pause():
                    ahead = [c for c in large if c.paused_at is None and c.started < cell.started
                             and c.growth() >= GROWTH_BYTES]
                    log(f"calibration: paused {cell.task['key']} (holds {_gib(cell.held)}, climbed "
                        f"{_gib(view.growth)} in {GROWTH_WINDOW_SECONDS:g} s, may take "
                        f"{_gib(remaining_bytes(cell.price, cell.held))} more): available {_gib(available)} "
                        f"less the floor {_gib(floor)} and the {_gib(PAUSE_MARGIN_BYTES)} margin leaves "
                        f"{_gib(max(0, available - floor - PAUSE_MARGIN_BYTES))}, and {len(ahead)} older "
                        f"climbing cell(s) claim {_gib(sum(remaining_bytes(c.price, c.held) for c in ahead))} of "
                        f"it. It keeps its memory and its progress; {sum(c.paused_at is None for c in large)} "
                        f"running, {sum(c.paused_at is not None for c in large)} paused{said()}")
            chosen = to_continue([c.view() for c in large if c.paused_at is None],
                                 [c.view() for c in large if c.paused_at is not None], available, floor,
                                 time.monotonic())
            if chosen is not None:
                cell = next(c for c in large if c.task["key"] == chosen.key)
                waited = cell.resume()
                log(f"calibration: continued {cell.task['key']} after {_fmt_duration(waited)} paused (holds "
                    f"{_gib(cell.held)}, may take {_gib(remaining_bytes(cell.price, cell.held))} more); "
                    f"{sum(c.paused_at is None for c in large)} running, "
                    f"{sum(c.paused_at is not None for c in large)} paused{said()}")

            paused_now = [c for c in large if c.paused_at is not None]
            started_one = not paused_now
            held_back = None
            while started_one and pending and running() < workers:
                started_one = False
                views = counted_now()
                for index, task in enumerate(list(pending)):
                    predicted, basis = price(task["family"], task["n"])
                    large_cell = task["n"] > SMALL_CELL_NODES
                    candidate = CellMemory(key=task["key"], started=time.monotonic(), price=predicted,
                                           typical=settles(task["family"], predicted) if large_cell else predicted,
                                           strict=task["key"] in strict)
                    need = need_beside(candidate, views)
                    decision = admission.decide(predicted, 0, need_bytes=need + PAUSE_MARGIN_BYTES)
                    if not decision["fits_ever"]:
                        log(f"calibration: BLOCKED {task['key']}: {decision['reason']}")
                        blocked.append({"key": task["key"], "n": task["n"], "reason": decision["reason"]})
                        pending.remove(task)
                        started_one = True
                        break
                    if decision["allowed"]:
                        args = task_args(task)
                        if not large_cell:
                            small[small_pool.submit(small_target, args)] = (task, predicted)
                        else:
                            large.append(_LargeCell(context, task, args, predicted, basis, target=cell_target,
                                                    typical=candidate.typical, strict=candidate.strict))
                            log(f"calibration: started {task['key']} (n={task['n']:,}, priced {_gib(predicted)} "
                                f"by {basis}, counted {_gib(candidate.typical)} until it climbs"
                                f"{', and whole: it was ended once' if candidate.strict else ''}); "
                                f"{running()} running{said()}")
                        pending.remove(task)
                        strict.discard(task["key"])
                        head_since.pop(task["key"], None)
                        last_start = time.monotonic()
                        started_one = True
                        break
                    if index == 0:
                        counted = still_to_take(views)
                        held_back = (task, predicted, basis, decision, counted)
                        since = head_since.setdefault(task["key"], time.monotonic())
                        if running() and time.monotonic() - since >= patience:
                            break

            if not (small or large):
                if pending:
                    task = pending[0]
                    predicted, _basis = price(task["family"], task["n"])
                    decision = admission.decide(predicted, 0, need_bytes=predicted + PAUSE_MARGIN_BYTES)
                    now = time.monotonic()
                    if now - last_wait_log >= ADMISSION_POLL_SECONDS:
                        last_wait_log = now
                        log(f"calibration: waiting for host memory before {task['key']}: "
                            f"{decision['reason']}; no time limit applies")
                    time.sleep(ADMISSION_POLL_SECONDS)
                continue

            now = time.monotonic()
            if progress is not None and now - last_progress_log >= PROGRESS_LOG_SECONDS:
                last_progress_log = now
                longest = max((c.active_seconds() for c in large), default=0.0)
                log(f"calibration: {progress()}; {sum(c.paused_at is None for c in large) + len(small)} running, "
                    f"{sum(c.paused_at is not None for c in large)} paused, {len(pending)} not started"
                    + (f"; the longest running has worked {_fmt_duration(longest)}" if large else ""))
            if (pending and running() < workers and now - last_start >= hold_first
                    and now - last_hold_log >= HOLD_LOG_SECONDS):
                if paused_now:
                    last_hold_log = now
                    log(f"calibration: {running()} of {workers} worker(s) busy, {len(paused_now)} of them paused "
                        f"({', '.join(c.task['key'] for c in paused_now)}); nothing new starts until they "
                        "continue")
                elif held_back is not None:
                    last_hold_log = now
                    task, predicted, basis, decision, counted = held_back
                    log(_hold_line(running(), workers, task, predicted, basis, counted["bytes"], decision,
                                   held=sum(c.held for c in large), counted=counted)
                        + ("" if holders_shown else " Shared memory held elsewhere on the host comes off the top:"))
                    if not holders_shown:
                        holders_shown = True
                        for text in _memory_holders():
                            log(f"calibration:     {text}")

            timeout = min(0.5, watch) if small else watch
            if large:
                mpc.wait([c.receive for c in large] + [c.process.sentinel for c in large], timeout=timeout)
            else:
                cf.wait(list(small), timeout=timeout, return_when=cf.FIRST_COMPLETED)
    finally:
        for cell in large:
            cell.stop()
        small_pool.shutdown(wait=False, cancel_futures=True)


def load_waivers(var: Path) -> list[dict]:
    import json
    path = C.waivers_path(var)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data if isinstance(data, list) else (data.get("waivers") if isinstance(data, dict) else [])
    return [w for w in (items or []) if isinstance(w, dict) and w.get("family") and w.get("channel")]


def resolve_table(root: Path, var: Path) -> tuple[Path, dict | None, str]:
    durable = C.durable_artifact_path(root)
    document = T.load(durable)
    if document is not None:
        return durable, document, "durable"
    working = C.non_authoritative_artifact_path(var)
    return working, T.load(working), "working"


def ensure_calibration(root: Path | None = None, var: Path | None = None, *, log=print,
                       dev_mode: bool | None = None, profile: str | None = None,
                       workers: int | None = None, families=None) -> dict:
    root = Path(root) if root is not None else C.repository_root()
    var = Path(var) if var is not None else root / "var"
    dev_mode = C.dev_mode() if dev_mode is None else bool(dev_mode)
    profile = profile or C.profile()
    fams = suite_families(families)
    waivers = load_waivers(var)
    durable_path = C.durable_artifact_path(root)
    working_path = C.non_authoritative_artifact_path(var)
    status: dict = {"profile": profile, "dev_mode": dev_mode, "computed": 0, "reused": 0,
                    "notices": [], "science_fingerprint": FP.science_fingerprint()}

    def notice(text: str) -> None:
        status["notices"].append(text)
        log(f"calibration: {text}")

    durable = T.load(durable_path)
    status["table_source"] = "in_tree" if durable is not None else "none_found"
    status["table_source_path"] = str(durable_path) if durable is not None else None
    def from_the_seed(why: str):
        examined = []
        for candidate in C.candidate_table_paths(root):
            recovered = T.load(candidate)
            if recovered is None:
                examined.append(f"{candidate}: {'unreadable' if candidate.exists() else 'absent'}")
                continue
            checked = T.verify(recovered, fams, seeds=C.AUTHORITATIVE_SEEDS, max_nodes=None, waivers=waivers)
            if not checked["usable"]:
                examined.append(f"{candidate}: not usable ({'; '.join(checked['notices'][:1]) or 'refused'})")
                continue
            status["table_source"] = "shipped_seed"
            status["table_source_path"] = str(candidate)
            examined.append(f"{candidate}: used")
            status["candidates_examined"] = examined
            notice(f"{why}; starting from this tree's seed and verifying it here rather than recomputing from zero. "
                   "Candidates: " + "; ".join(examined))
            return recovered
        status["candidates_examined"] = examined
        return None

    if durable is None:
        durable = from_the_seed(f"no table at {durable_path}")
    authoritative_seeds = C.AUTHORITATIVE_SEEDS
    report = T.verify(durable, fams, seeds=authoritative_seeds, max_nodes=None, waivers=waivers)
    if durable is not None and not report["usable"]:
        for text in report["notices"]:
            notice(text)
        kept = T.history_copy(durable, C.history_dir(var), "unusable_table")
        status["table_source"], status["table_source_path"] = "none_found", None
        durable = from_the_seed(f"the durable table at {durable_path} cannot be resumed from (copied to {kept})")
        report = T.verify(durable, fams, seeds=authoritative_seeds, max_nodes=None, waivers=waivers)
    if status["table_source"] == "none_found":
        notice(f"no usable table at {durable_path} and no usable seed in this tree; every cell will be "
               "measured. Candidates: " + ("; ".join(status.get("candidates_examined") or []) or "none"))
    for text in report["notices"]:
        notice(text)

    from graph_scale_dynamics.calibration import owed as OWED
    owed_now = OWED.recalibration_owed() if durable is not None else None
    if owed_now:
        notice(f"a recalibration is owed ({OWED.reason(owed_now)}): every cell stale under this tree's code is measured")

    if durable is not None and not owed_now:
        origin = durable.get("origin") or {}
        if status["table_source"] == "shipped_seed":
            from graph_scale_dynamics.calibration import adopt as ADOPT
            spot = ADOPT.spot_check(durable)
            status["spot_check"] = {k: spot[k] for k in ("sampled", "worst_deviation", "worst_host_spread")} | {
                "moved": [m["cell"] for m in spot["moved"]]}
            moved = {m["family"] for m in spot["moved"]}
            for cell in (durable.get("cells") or {}).values():
                if str(cell.get("family")) in moved:
                    cell["cell_fingerprint"] = "moved-at-the-spot-check"
            notice(f"spot check: {spot['sampled']} cell(s) measured again here, "
                   + (f"{len(spot['moved'])} moved ({', '.join(sorted(moved))}: their cells are measured again)"
                      if moved else f"none moved (worst deviation {spot['worst_deviation']:.1e})"))
            T.mark_adopted(durable, source="the archive's seed", notices=report["notices"])
            notice(f"the archive's seed adopted after verification ({report['cells']['current']} current, "
                   f"{report['cells']['stale']} stale, {report['cells']['missing']} missing)")
        elif not report["science_fingerprint_matches"] and not origin.get("adopted"):
            T.mark_adopted(durable, source="a different science fingerprint", notices=report["notices"])
            notice("table adopted across a science fingerprint change and re-verified; "
                   "stale cells, if any, are recomputed")

    if profile == C.PROFILE_FULL:
        seeds, max_nodes, authoritative, path = authoritative_seeds, None, True, durable_path
        document = durable if durable is not None else T.new_table(
            fams, seeds=seeds, max_nodes=None, authoritative=True, profile=profile)
        if durable is not None and not durable.get("authoritative"):
            notice("the durable table is stamped non-authoritative; it is completed to the "
                   "authoritative seed count in place")
            document["authoritative"] = True
            document["profile"] = {"name": profile, "seeds": seeds, "max_nodes": None}
    else:
        if durable is not None and report["complete"] and report["authoritative"]:
            seeds, max_nodes, authoritative, path, document = authoritative_seeds, None, True, durable_path, durable
            notice("reduced profile requested but an authoritative table is present and complete; "
                   "using it")
        else:
            seeds, max_nodes, authoritative, path = C.reduced_seeds(), C.reduced_max_nodes(), False, working_path
            document = T.load(working_path)
            wreport = T.verify(document, fams, seeds=seeds, max_nodes=max_nodes, waivers=waivers)
            if document is None or not wreport["usable"]:
                document = T.new_table(fams, seeds=seeds, max_nodes=max_nodes, authoritative=False,
                                       profile=profile)
            document["authoritative"] = False
            document["profile"] = {"name": profile, "seeds": seeds, "max_nodes": max_nodes}
            notice(f"reduced profile: {seeds} seed(s), ladders truncated at {max_nodes} nodes; "
                   f"the table at {path} is NOT authoritative and never overwrites "
                   f"{durable_path}")

    classes = T.refresh(document, fams, seeds=seeds, max_nodes=max_nodes, waivers=waivers)
    status["reused"] = len(classes[T.CELL_CURRENT])
    if document["plan"]["complete"]:
        T.restamp_header(document, fams, seeds=seeds, max_nodes=max_nodes)
        log(f"calibration: table at {path} verified: {status['reused']} cells reused, "
            f"0 computed; verdict {document['deviation'].get('verdict')}")
        T.write(document, path)
    else:
        log(f"calibration: table at {path}: {document['plan']['current']} current, "
            f"{document['plan']['stale']} stale, {document['plan']['missing']} missing, "
            f"{document['plan']['failed']} failed of {document['plan']['total_cells']}; "
            "running the suite in the foreground, no time limit")
        adopted_now = False
        if document["plan"]["stale"] and not document["plan"]["missing"] \
                and not document["plan"]["failed"] and not owed_now:
            try:
                from graph_scale_dynamics.calibration import adopt as ADOPT
                verdict = ADOPT.verify_and_adopt(
                    document,
                    reason="suite startup: source digest moved, cells re-verified")
                for line in verdict["notices"]:
                    notice(f"adoption: {line}")
                if verdict["adopted"]:
                    stale_before = int(document["plan"]["stale"])
                    T.restamp_header(document, fams, seeds=seeds, max_nodes=max_nodes)
                    T.refresh(document, fams, seeds=seeds, max_nodes=max_nodes, waivers=waivers)
                    T.write(document, path)
                    status["adopted"] = verdict["sampled"]
                    left = int(document["plan"]["stale"]) + int(document["plan"]["missing"])
                    if left:
                        log(f"calibration: re-stamped what reproduced after re-measuring {verdict['sampled']}; "
                            f"{left} cell(s) were stale before it and are measured now")
                    else:
                        log(f"calibration: adopted {stale_before} stale cell(s) after "
                            f"re-measuring {verdict['sampled']}; worst deviation "
                            f"{verdict['worst_deviation']:.2e}, host spread "
                            f"{verdict['worst_host_spread']:.2e}. No recalibration needed.")
                        adopted_now = True
                for refusal in verdict["refused"]:
                    notice(f"adoption refused at {refusal['cell']}: "
                           + "; ".join(refusal["problems"]))
            except Exception as exc:
                notice(f"adoption check skipped: {type(exc).__name__}: {exc}")

        if not adopted_now:
            try:
                recoverable = T.history_recovery_candidates(
                    C.history_dir(var), T.plan_cells(fams, seeds=seeds, max_nodes=max_nodes),
                    int(document["plan"]["current"]))
            except Exception as exc:
                recoverable = []
                notice(f"history scan skipped: {type(exc).__name__}: {exc}")
            if T.durable_table_is_git_tracked(root):
                notice(
                    "the durable calibration table is a TRACKED git path. Every build "
                    "that does not contain it will delete it on deploy and force a full "
                    "recalibration, and every build that does contain it will overwrite "
                    "yours with the packager's. It is host state and must be ignored:")
                notice(f"    git rm --cached {C.DURABLE_DIR}/{C.DURABLE_NAME}")
                notice(f"    echo '{C.DURABLE_DIR}/{C.DURABLE_NAME}' >> .gitignore")
            if recoverable:
                best = recoverable[0]
                notice(
                    f"RECOVERABLE: {best['path']} holds {best['usable_cells']} cells that are "
                    f"current under this build, {best['gain']} more than the table about to be "
                    f"computed. Stop now and restore it to skip this run:")
                notice(f"    cp {best['path']} {path}")
                notice("A build archive carrying calibration/probe_calibration.json is the usual "
                       "cause; that file is host state and no release should contain it.")
            run = run_suite(document, path, fams, seeds=seeds, max_nodes=max_nodes, workers=workers,
                            log=log, waivers=waivers)
            status["computed"] = int(run.get("cells_computed") or 0)
            status["run"] = run
            T.history_copy(document, C.history_dir(var), "table")
            if recoverable:
                notice("this run recomputed cells that were already present in a history "
                       f"copy: {status['computed']} cell(s), against "
                       f"{recoverable[0]['path']}. If the durable table is git-tracked "
                       "(see the notice above) this will repeat on every deploy.")

    deviation = document.get("deviation") or {}
    verdict = deviation.get("verdict")
    for w in deviation.get("waivers_applied") or []:
        log(f"calibration: WAIVED {w['family']}:{w['channel']} at N={w['n']} "
            f"until {w['expires_utc']} -- {w['reason']}")
    for w in deviation.get("waivers_expired") or []:
        log(f"calibration: EXPIRED waiver {w['family']}:{w['channel']} ({w['expires_utc']}); "
            "it no longer applies")
    status.update({"path": str(path), "authoritative": bool(authoritative), "verdict": verdict,
                   "seeds": seeds, "max_nodes": max_nodes, "summary": deviation.get("summary_line"),
                   "suite_fingerprint": document.get("suite_fingerprint"),
                   "adopted": bool((document.get("origin") or {}).get("adopted")),
                   "cells": dict(document.get("plan") or {})})
    log(f"calibration: {deviation.get('summary_line', verdict)}")
    if verdict != "PASS":
        message = (f"calibration {verdict}: {deviation.get('summary_line')}. A runtime whose "
                   "instruments cannot read known targets must not collect data.")
        if not dev_mode:
            raise CalibrationGateError(message)
        log(f"calibration: {message}")
        log("calibration: GSD_DEV_MODE=1 downgrades this refusal to a warning; nothing "
            "collected under it is certifiable")
    if not authoritative:
        log("calibration: the table in force is NOT authoritative (reduced profile); nothing "
            "collected under it is certifiable")
    return status
