from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.services.web.main import SPA_SHELL_PATHS

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests" / "ui" / "dashboard_smoke.js"
UI_DIR = ROOT / "graph_scale_dynamics" / "resources" / "ui"

node = shutil.which("node")
requires_node = pytest.mark.skipif(node is None, reason="node is not installed")


def _run(ui_dir: Path, boot_path: str | None = None) -> subprocess.CompletedProcess:
    command = [node, str(HARNESS), str(ui_dir)]
    if boot_path is not None:
        command.append(boot_path)
    return subprocess.run(command, capture_output=True, text=True, timeout=180)


@requires_node
@pytest.mark.parametrize("boot_path", sorted(SPA_SHELL_PATHS - {"/"}))
def test_the_app_boots_at_every_path_a_browser_can_land_on(boot_path: str):
    result = _run(UI_DIR, boot_path)
    assert result.returncode == 0, (
        f"the dashboard does not survive a direct load of {boot_path}:\n"
        + result.stdout + result.stderr)


@requires_node
def test_dashboard_boots_and_renders_without_crashing():
    result = _run(UI_DIR)
    assert result.returncode == 0, (
        "dashboard smoke test failed:\n" + result.stdout + result.stderr
    )
    assert result.stdout.strip().endswith("OK")


@requires_node
def test_the_harness_catches_a_redraw_that_calls_itself(tmp_path):
    scratch = tmp_path / "ui"
    shutil.copytree(UI_DIR, scratch)

    system = scratch / "system.js"
    source = system.read_text(encoding="utf-8")
    fixed = ("    if(force||!element||!element.dataset.hovering){ if(element) element._deferredRedraw=null;"
             " return false; }")
    assert fixed in source
    system.write_text(
        source.replace(
            fixed,
            "    if(force||!element||!element.dataset.hovering){ redraw(); return false; }",
        ),
        encoding="utf-8",
    )

    result = _run(scratch)
    assert result.returncode != 0, "harness did not catch the reintroduced recursion"
    assert "Maximum call stack size exceeded" in result.stdout


def test_the_release_lane_runs_the_dashboard_smoke_test():
    from tools import test_suite

    assert "tests/unit/test_dashboard_smoke.py" in test_suite.LANES["release"]
