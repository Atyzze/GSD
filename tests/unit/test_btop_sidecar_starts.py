from __future__ import annotations

import os
import shutil
import stat
import time

import pytest

from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.services.api import host as api_host

BTOP_HELP = """usage: btop [-h] [-v] [-/+t] [-p <id>] [-u <ms>] [--utf-force] [--debug]

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show version info and exit
  -lc, --low-color      disable truecolor, converts 24-bit colors to 256-color
  -t, --tty_on          force (ON) tty mode, max 16 colors and tty friendly graph symbols
  +t, --tty_off         force (OFF) tty mode
  -p, --preset <id>     start with preset, integer value between 0-9
  -u, --update <ms>     set the program update rate in milliseconds
  --utf-force           force start even if no UTF-8 locale was detected
  --debug               start in DEBUG mode
"""


def _stub_btop(tmp_path, help_text: str):
    path = tmp_path / "btop"
    path.write_text("#!/bin/sh\ncat <<'EOF'\n" + help_text + "EOF\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def test_no_flag_is_passed_that_the_binary_does_not_advertise(tmp_path):
    argv, dropped, error = api_host._btop_argv(_stub_btop(tmp_path, BTOP_HELP))
    assert error is None and not dropped, f"a flag was dropped against btop's real help: {dropped}"
    advertised = {"-h", "--help", "-v", "--version", "-lc", "--low-color", "-t", "--tty_on",
                  "--tty_off", "-p", "--preset", "-u", "--update", "--utf-force", "--debug"}
    passed = [token for token in argv[1:] if token.startswith("-")]
    assert passed, "the sidecar passes no flags at all, so this check proves nothing"
    unknown = sorted(set(passed) - advertised)
    assert not unknown, (
        f"the sidecar passes {unknown}, which btop does not accept. btop exits on an unknown "
        "argument, and a sidecar that exits reads exactly like one that is slow to start.")
    for retired in ("--tty", "--force-utf", "--config"):
        assert retired not in argv, f"{retired} is back; btop has never accepted it"


def test_a_flag_this_btop_does_not_know_is_dropped_and_recorded(tmp_path):
    argv, dropped, error = api_host._btop_argv(_stub_btop(tmp_path, "usage: btop [-h]\n  -h, --help\n"))
    assert error is None
    assert "--utf-force" in dropped and "--utf-force" not in argv
    assert argv[0].endswith("btop"), "the binary itself is still invoked"


def test_the_config_reaches_btop_through_the_environment_not_a_flag():
    from graph_scale_dynamics.operations import power_sidecar
    source = power_sidecar.start.__code__
    names = set(source.co_names) | set(source.co_consts)
    assert "XDG_CONFIG_HOME" in names, "the private config is not pointed at through the environment"


def test_the_parser_reads_temperature_and_watts_independently():
    both = "CPU  " + "■" * 8 + "  42%   57°C   138 W  C0  12%"
    assert api_host._parse_btop_telemetry(both) == (57.0, 138.0)
    assert api_host._parse_btop_telemetry("CPU  " + "■" * 8 + "  42%   57°C  C0 12%") == (57.0, None)
    assert api_host._parse_btop_telemetry("CPU  " + "■" * 8 + "  42%   138 W  C0 12%") == (None, 138.0)
    assert api_host._parse_btop_telemetry("nothing here") == (None, None)
    assert api_host._parse_btop_telemetry("CPU  42%   57°C   0 W")[1] is None


@pytest.mark.skipif(shutil.which("btop") is None,
                    reason="btop is not installed; prepare_environment.sh installs it")
def test_the_sidecar_starts_btop_and_draws_frames():
    try:
        api_host._btop_telemetry_snapshot(start=True, wait_seconds=12.0)
        status = api_host._btop_telemetry_status()
        state = api_host._BTOP_STATE
        assert status["path"], "no btop path was recorded"
        assert not state.get("flags_dropped"), (
            f"this btop does not accept {state.get('flags_dropped')}, which the sidecar still passes")
        assert status["running"], (
            f"btop exited instead of running: {status['last_error']!r}. It exits on an unknown "
            f"argument; the argv was {state.get('argv')}")
        drew = (int(state.get("frames_without_a_reading") or 0) > 0
                or status["watts"] is not None or status["temperature_celsius"] is not None)
        assert drew, (
            "btop ran for 12 s and the parser recognised no CPU line in anything it drew. "
            "Either btop's layout moved or the parser did; `tools/collect_power.py` captures "
            "a raw frame to compare.")
    finally:
        api_main._stop_btop_sidecar()


@pytest.mark.skipif(shutil.which("btop") is None, reason="btop is not installed")
def test_the_sidecar_leaves_no_btop_behind():
    api_host._btop_telemetry_snapshot(start=True, wait_seconds=3.0)
    pid = api_host._btop_telemetry_status()["pid"]
    api_main._stop_btop_sidecar()
    assert api_host._btop_telemetry_status()["running"] is False
    if pid:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.kill(int(pid), 0)
            except OSError:
                return
            time.sleep(0.1)
        pytest.fail(f"btop {pid} is still alive after the sidecar was stopped")
