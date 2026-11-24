from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "graph_scale_dynamics" / "resources" / "ui"
SMOKE = ROOT / "tests" / "ui" / "dashboard_smoke.js"
HERO = ROOT / "tests" / "ui" / "hero_check.js"

node = shutil.which("node")
requires_node = pytest.mark.skipif(node is None, reason="node is not installed")


def _dump(ui_dir: Path, tmp_path: Path) -> Path:
    dump = tmp_path / "drawn.json"
    smoke = subprocess.run([node, str(SMOKE), str(ui_dir)], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, GSD_LAYOUT_DUMP=str(dump)))
    assert smoke.returncode == 0 and dump.is_file(), smoke.stdout[-2000:] + smoke.stderr[-2000:]
    return dump


def _check(ui_dir: Path, dump: Path) -> subprocess.CompletedProcess:
    result = subprocess.run([node, str(HERO), str(ui_dir), str(dump)], capture_output=True, text=True, timeout=300)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    return result


@requires_node
def test_the_landscape_holds_its_whole_plot_above_the_filters_beside_the_top_100(tmp_path):
    result = _check(UI_DIR, _dump(UI_DIR, tmp_path))
    assert result.returncode == 0 and result.stdout.startswith("OK"), result.stdout[-4000:] + result.stderr[-2000:]


@requires_node
def test_the_check_finds_the_plot_857_cut_off(tmp_path):
    dump = _dump(UI_DIR, tmp_path)
    scratch = tmp_path / "ui"
    shutil.copytree(UI_DIR, scratch)
    css = scratch / "system.css"
    source = css.read_text(encoding="utf-8")
    row = "--gsd-hero-h:calc(var(--gsd-land-h) + var(--gsd-filter-h) + var(--gsd-hero-gap))"
    assert row in source, "the row's height changed; update this test"
    css.write_text(source.replace(row, "--gsd-hero-h:var(--gsd-land-h)"), encoding="utf-8")
    result = _check(scratch, dump)
    assert result.returncode == 1 and "cuts off" in result.stdout, result.stdout[-2000:]
