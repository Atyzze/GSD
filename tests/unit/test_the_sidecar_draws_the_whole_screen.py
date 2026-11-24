from __future__ import annotations

import os
import pty
import fcntl
import struct
import subprocess
import select
import shutil
import termios
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def api():
    from graph_scale_dynamics.services.api import host
    return host


def test_the_sidecar_never_forces_tty_mode_on(api):
    assert all(flag != "-t" for flag, _ in api._BTOP_WANTED_FLAGS)
    assert "-t" not in api._BTOP_TTY_OFF_FLAGS


def test_the_flag_detector_can_see_a_plus_flag(api, tmp_path):
    fake = tmp_path / "btop"
    fake.write_text("#!/bin/sh\ncat <<'EOF'\n"
                    "usage: btop [-h] [-v] [-/+t] [-p <id>] [-u <ms>] [--utf-force]\n"
                    "  -t, --tty_on   force (ON) tty mode\n"
                    "  +t, --tty_off  force (OFF) tty mode\n"
                    "EOF\n", encoding="utf-8")
    fake.chmod(0o755)
    found, error = api._btop_supported_flags(str(fake))
    assert error is None
    assert "+t" in found, f"the flag detector still cannot see +t: {sorted(found)}"
    assert "-t" in found and "--tty_off" in found
    argv, _dropped, _ = api._btop_argv(str(fake))
    assert any(flag in argv for flag in api._BTOP_TTY_OFF_FLAGS)
    assert "-t" not in argv


def test_an_unknown_flag_is_dropped_not_passed(api, tmp_path):
    fake = tmp_path / "btop"
    fake.write_text("#!/bin/sh\necho 'usage: btop [-h] [-u <ms>]'\n", encoding="utf-8")
    fake.chmod(0o755)
    argv, dropped, error = api._btop_argv(str(fake))
    assert error is None
    assert not any(flag in argv for flag in api._BTOP_TTY_OFF_FLAGS)
    assert set(api._BTOP_TTY_OFF_FLAGS) <= set(dropped)


def _draw(argv: list[str], seconds: float = 5.0) -> bytes:
    env = dict(os.environ, TERM=os.environ.get("TERM", "xterm-256color"))
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
    process = subprocess.Popen(argv, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                               env=env, close_fds=True)
    os.close(slave_fd)
    chunks: list[bytes] = []
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.25)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            elif process.poll() is not None:
                break
    finally:
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            pass
        os.close(master_fd)
    return b"".join(chunks)


def test_tty_mode_really_does_draw_less(api):
    btop = shutil.which("btop")
    if not btop:
        pytest.skip("btop is not installed on this host; the drawing cannot be measured")
    reduced = _draw([btop, "-t", "--utf-force", "-u", "500"])
    argv, _, _ = api._btop_argv(btop)
    full = _draw(argv)
    if len(reduced) < 4096 or len(full) < 4096:
        pytest.skip("btop drew almost nothing here; this host cannot show the difference")
    assert len(full) > len(reduced) * 1.2, (
        f"the sidecar's argv draws {len(full)} bytes against tty mode's {len(reduced)}; "
        "it is not getting the full screen")
    plain = api._BTOP_ANSI_RE.sub("", full.decode("utf-8", "replace")).replace("\n", " ")
    assert api._BTOP_CPU_LINE_RE.search(plain), "the full drawing has no CPU line to parse"
