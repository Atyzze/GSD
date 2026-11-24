from __future__ import annotations

import errno
import io
import re
import sys
import time

from graph_scale_dynamics.observability import console_log
from graph_scale_dynamics.observability.evidence_sources import TeeStdout, supervisor_log_path

STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z"


class Terminal(io.StringIO):
    def __init__(self):
        super().__init__()
        self.buffer = io.BytesIO()


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_a_services_stdout_and_stderr_and_the_supervisors_lines_land_on_disk_timed_and_named(tmp_path):
    var = tmp_path / "var"
    scratch = tmp_path / "scratch"
    scratch.write_text("")
    service = ("import sys, pathlib\n"
               "try:\n"
               f"    pathlib.Path({str(scratch / 'executor.log')!r}).write_text('x')\n"
               "except OSError as exc:\n"
               "    print(f'log write failed: {exc.strerror}', file=sys.stderr)\n"
               "print('claimed a seed at N=4096')\n")
    terminal = Terminal()
    proc = console_log.popen_logged([sys.executable, "-c", service], source="executor-3", var=var, terminal=terminal)
    assert proc.wait(timeout=30) == 0
    tee = TeeStdout(io.StringIO(), supervisor_log_path(var))
    print("fleet: 14 simulation slots", file=tee)
    for _ in range(100):
        if len(_lines(supervisor_log_path(var))) >= 3:
            break
        time.sleep(0.05)
    lines = _lines(supervisor_log_path(var))
    assert any(re.fullmatch(STAMP + r" \[executor-3\] log write failed: .+", line) for line in lines), lines
    assert any(re.fullmatch(STAMP + r" \[executor-3\] claimed a seed at N=4096", line) for line in lines), lines
    assert any(re.fullmatch(STAMP + r" \[supervisor\] fleet: 14 simulation slots", line) for line in lines), lines
    shown = terminal.buffer.getvalue().decode()
    assert "claimed a seed at N=4096" in shown and "log write failed" in shown, "the terminal shows them as before"


def test_a_log_that_cannot_be_written_costs_the_log_and_not_the_line(tmp_path, monkeypatch):
    terminal = Terminal()
    log = console_log.ConsoleLog(tmp_path / "log" / "supervisor.log", terminal=terminal)

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("builtins.open", full)
    assert log.line("executor-1", "a line") is False and log.line("executor-1", "another") is False
    monkeypatch.undo()
    assert log.failed_writes == 2, "counted, never raised"
    warned = terminal.buffer.getvalue().decode()
    assert warned.count("[console-log]") == 1 and "No space left on device" in warned, "said once a minute"
    assert log.line("executor-1", "room again") is True, "it opens again once the disk has room"


def test_the_log_rotates_by_size_and_keeps_its_generations(tmp_path):
    path = tmp_path / "supervisor.log"
    log = console_log.ConsoleLog(path, max_bytes=200, generations=3)
    for i in range(60):
        log.line("supervisor", f"line {i:03d} " + "x" * 40)
    kept = sorted(p.name for p in tmp_path.iterdir())
    assert kept == ["supervisor.log", "supervisor.log.1", "supervisor.log.2", "supervisor.log.3"], kept
    assert "line 059" in path.read_text() + (tmp_path / "supervisor.log.1").read_text()
