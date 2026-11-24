from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration.contract import DURABLE_DIR, DURABLE_NAME, SUITE_VERSION

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "calibration" / "seed_table.json"
PREPARE = (ROOT / "tools" / "prepare_environment.sh").read_text(encoding="utf-8")


def test_the_seed_is_the_table_the_host_measured_whole_and_is_this_suite_s():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import table as T
    from graph_scale_dynamics.calibration.cells import suite_families
    from graph_scale_dynamics.calibration.contract import AUTHORITATIVE_SEEDS
    assert SEED.exists(), "the archive holds no record of what the host measured"
    table = T.load(SEED)
    assert table["contract"] == "gsd-calibration-table-1"
    assert len(table["cells"]) > 1000
    for key in ("science_fingerprint", "suite_fingerprint", "estimator_fingerprint"):
        assert table.get(key), f"the seed says the {key} it was measured under"
    report = T.verify(table, suite_families(), seeds=AUTHORITATIVE_SEEDS, max_nodes=None)
    assert int(table["suite_version"]) == SUITE_VERSION and report["usable"] and report["complete"], (
        "measured whole by this suite on the host: a first start adopts it and measures no table")
    assert report["cells"]["stale"] == report["cells"]["missing"] == 0 and table["deviation"]["verdict"] == "PASS"


def test_the_packager_ships_the_seed_and_still_refuses_the_live_table():
    from tools import package_release as PR
    assert "calibration/seed_table.json" in PR.REQUIRED_RELEASE_PATHS, "the seed is not a required path"
    assert PR.included(Path("calibration/seed_table.json"))
    assert not PR.included(Path("calibration/probe_calibration.json")), (
        "an archive that carries the live table overwrites a better table on arrival")


def _seed_step() -> str:
    step = PREPARE[PREPARE.index('step "6  The calibration table"'):]
    return step[:step.index('step "7 ')]


def test_bring_up_seeds_only_a_host_with_no_table():
    step = _seed_step()
    guard = f'if [ -f "$TREE/{DURABLE_DIR}/{DURABLE_NAME}" ]; then'
    assert guard in step, "the existing-table branch is not the first test"
    seed_branch = step.index('elif [ -f "$TREE/calibration/seed_table.json" ]; then')
    assert seed_branch > step.index(guard), "the seed branch must sit after the guard"
    copy_line = f'cp "$TREE/calibration/seed_table.json" "$TREE/{DURABLE_DIR}/{DURABLE_NAME}"'
    assert copy_line in step[seed_branch:], "the seed branch does not install the seed"
    assert copy_line not in step[:seed_branch], (
        "a copy outside the elif would run on a host that already has a table, "
        "which is the build 353 failure exactly")


@pytest.mark.parametrize("claim", ["unverified", "re-check"])
def test_the_seed_is_not_presented_as_authoritative(claim):
    assert claim in _seed_step()
