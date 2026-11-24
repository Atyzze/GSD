from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ("graph_scale_dynamics", "tools", "main.py")

ALLOWLIST = {
    "graph_scale_dynamics/engine/engine.py: local variable 'p_swap' is assigned to but never used",
}


def _findings() -> set[str]:
    pytest.importorskip("pyflakes")
    done = subprocess.run([sys.executable, "-m", "pyflakes", *TARGETS],
                          cwd=ROOT, capture_output=True, text=True)
    out: set[str] = set()
    for line in (done.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split(":", 3)
        if len(parts) < 4:
            out.add(line.strip())
            continue
        out.add(f"{parts[0]}:{parts[3]}")
    return out


def test_no_new_pyflakes_finding_joins_the_list():
    joined = sorted(_findings() - ALLOWLIST)
    assert not joined, (
        "pyflakes reports these and they are not on the allowlist:\n  "
        + "\n  ".join(joined)
        + "\nFix the finding rather than adding it to ALLOWLIST; the list only shrinks.")


def test_the_allowlist_has_not_gone_stale():
    stale = sorted(ALLOWLIST - _findings())
    assert not stale, (
        "these allowlist entries no longer fire and must be deleted:\n  " + "\n  ".join(stale))
