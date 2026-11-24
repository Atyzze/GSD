from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.reporting import study_explorer as E
from tests.support.explorer_study import write_study

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests" / "ui" / "explorer_check.js"
sys.path.insert(0, str(ROOT / "tools"))

node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_explorer_draws_filters_selects_and_lists_in_a_browser(tmp_path):
    import study_explorer as tool
    page = tmp_path / "explorer.html"
    page.write_text(E.render(tool.read(write_study(tmp_path, laws=120, seed=7))), encoding="utf-8")
    result = subprocess.run([node, str(CHECK), str(page)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0 and result.stdout.startswith("OK"), result.stdout[-4000:] + result.stderr[-2000:]


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_check_fails_a_page_that_breaks(tmp_path):
    import study_explorer as tool
    page = tmp_path / "explorer.html"
    text = E.render(tool.read(write_study(tmp_path, laws=30, seed=3)))
    assert "function pageCurves() {" in text, "the page changed; update this test"
    page.write_text(text.replace("function pageCurves() {", "function pageCurves() { throw new Error('broken');"),
                    encoding="utf-8")
    result = subprocess.run([node, str(CHECK), str(page)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode != 0 and "an error in the page: broken" in result.stdout, result.stdout[-3000:]
