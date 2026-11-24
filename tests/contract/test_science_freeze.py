from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "fixtures" / "science_freeze.json"


def test_science_sensitive_sources_match_the_current_freeze():
    baseline = json.loads(MANIFEST.read_text(encoding="utf-8"))
    build = int((ROOT / "BUILD_NUMBER").read_text().strip())
    assert baseline["baseline_build"] <= build, (
        f"the freeze is anchored at build {baseline['baseline_build']} but the tree "
        f"is at {build}; a freeze from the future means a rolled-back release left "
        "the manifest ahead of the tree, and its hashes describe a different tree"
    )
    assert baseline["contract"] == "gsd-science-freeze-1"

    drift = []
    for relative, expected in baseline["files"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            drift.append(relative)
    if drift:
        from graph_scale_dynamics.operations import dev_mode
        if dev_mode.relaxation_active("science_freeze_advisory"):
            print("DEVELOPMENT MODE: science freeze drift (advisory):")
            for relative in drift:
                print(f"  CHANGED {relative}")
        else:
            raise AssertionError(
                "science-sensitive sources changed since the freeze; re-run "
                "`python tools/science_freeze.py --write` if intended, or set "
                "GSD_DEV_MODE=1 to make this advisory while iterating"
            )


def test_science_freeze_manifest_covers_the_intended_boundaries():
    baseline = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    required_prefixes = (
        "graph_scale_dynamics/scaleflow/",
        "graph_scale_dynamics/dsl/",
        "graph_scale_dynamics/measurements/",
        "graph_scale_dynamics/engine/",
        "graph_scale_dynamics/resources/configs/",
        "graph_scale_dynamics/resources/calibration/",
    )
    for prefix in required_prefixes:
        assert any(path.startswith(prefix) for path in baseline), prefix
    assert any(path.startswith("graph_scale_dynamics/decisions/") for path in baseline)
    assert "graph_scale_dynamics/domain/randomness.py" in baseline


def test_freeze_covers_every_current_science_source():
    import tools.science_freeze as freeze

    stored = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["files"])
    assert set(freeze.frozen_paths()) == stored, (
        "science sources were added or removed without re-freezing; "
        "re-run `python tools/science_freeze.py --write`"
    )
