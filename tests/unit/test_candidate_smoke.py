from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests" / "ui" / "candidate_smoke.js"
UI_DIR = ROOT / "graph_scale_dynamics" / "resources" / "ui"

node = shutil.which("node")
requires_node = pytest.mark.skipif(node is None, reason="node is not installed")


def _run(ui_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [node, str(HARNESS), str(ui_dir)],
        capture_output=True, text=True, timeout=180,
    )


@requires_node
def test_the_candidate_page_paints_a_realistic_rung_payload():
    result = _run(UI_DIR)
    assert result.returncode == 0, (
        "candidate smoke test failed:\n" + result.stdout + result.stderr
    )
    assert result.stdout.strip().endswith("OK")


def test_the_release_lane_names_files_that_exist():
    from tools import test_suite

    missing = [target for paths in test_suite.LANES.values() for target in paths
               if not (ROOT / target.split("::", 1)[0]).exists()]
    assert not missing, f"test lanes name paths that are not in the tree: {missing}"

    release = " ".join(test_suite.LANES["release"])
    assert "test_candidate_smoke.py" in release, (
        "the candidate page's only executing test is not in the release lane"
    )
