from __future__ import annotations

def fake_cell_main(task, conn):
    import time
    time.sleep(float(task.get("sleep", 0.2)))
    try:
        conn.send({"family": task["family"], "parameter": task["parameter"], "seed": task["seed"],
                   "n": task["n"], "status": "ok", "channels": {},
                   "elapsed_seconds": float(task.get("sleep", 0.2))})
    finally:
        conn.close()


def fake_climbing_cell(task, conn):
    import os
    import time
    from pathlib import Path

    path = Path(task["report"]) / str(os.getpid())
    plateau, peak = int(task["plateau"]), int(task["peak"])
    steps, step = int(task["steps"]), float(task["step"])
    half = steps // 2

    def report(held: int) -> None:
        part = path.with_name(path.name + ".part")
        part.write_text(str(held))
        os.replace(part, path)

    started = time.monotonic()
    for index in range(steps):
        held = plateau if index < half else plateau + (peak - plateau) * (index - half + 1) // (steps - half)
        report(held)
        time.sleep(step)
    try:
        conn.send({"family": task["family"], "parameter": task["parameter"], "seed": task["seed"],
                   "n": task["n"], "status": "ok", "channels": {}, "peak_rss_bytes": peak,
                   "elapsed_seconds": round(time.monotonic() - started, 3)})
    finally:
        conn.close()
    report(0)


def fake_setup_then_sleep(task, conn):
    import time

    from graph_scale_dynamics.calibration.cells import _cell_process_setup
    _cell_process_setup(task.get("parent_pid"))
    time.sleep(float(task.get("sleep", 30.0)))
    conn.close()


def start_orphaned_cell(report_dir, ready):
    import multiprocessing
    import os
    from pathlib import Path

    from graph_scale_dynamics.calibration.suite import _LargeCell
    task = {"key": "orphan:1:0", "family": "orphan", "parameter": 1, "seed": 0, "n": 1, "sleep": 30.0}
    cell = _LargeCell(multiprocessing.get_context("spawn"), task, dict(task), 1, "a test price",
                      target=fake_setup_then_sleep)
    Path(report_dir, "orphan.pid").write_text(str(cell.process.pid))
    ready.wait(20)
    os._exit(0)
