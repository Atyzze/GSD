from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import contract as C  # noqa: E402


def _tree(base: Path, number: int, *, table: dict | None = None) -> Path:
    tree = base / f"graph_scale_dynamics_build_{number}"
    (tree / C.DURABLE_DIR).mkdir(parents=True, exist_ok=True)
    if table is not None:
        (tree / C.DURABLE_DIR / C.DURABLE_NAME).write_text(json.dumps(table), encoding="utf-8")
    return tree


def _study(base: Path, name: str, *, table: dict | None = None) -> Path:
    tree = base / name / "main"
    (tree / C.DURABLE_DIR).mkdir(parents=True, exist_ok=True)
    if table is not None:
        (tree / C.DURABLE_DIR / C.DURABLE_NAME).write_text(json.dumps(table), encoding="utf-8")
    return tree


def test_a_lone_tree_offers_only_the_table_its_archive_ships(tmp_path):
    here = _tree(tmp_path, 416)
    assert C.candidate_table_paths(here) == [here / C.DURABLE_DIR / C.SEED_TABLE_NAME]


def test_sibling_build_trees_are_never_candidates(tmp_path):
    for n in (399, 415, 631):
        _tree(tmp_path, n, table={"cells": {}})
    here = _tree(tmp_path, 633)
    assert C.candidate_table_paths(here) == [here / C.DURABLE_DIR / C.SEED_TABLE_NAME]


def test_the_other_studies_tables_are_never_candidates(tmp_path):
    _study(tmp_path, "255", table={"cells": {}})
    _study(tmp_path, "257", table={"cells": {}})
    here = _study(tmp_path, "256")
    assert C.candidate_table_paths(here) == [here / C.DURABLE_DIR / C.SEED_TABLE_NAME]


def test_no_environment_variable_points_a_tree_elsewhere(tmp_path, monkeypatch):
    host = tmp_path / "host-state"
    host.mkdir()
    (host / C.DURABLE_NAME).write_text(json.dumps({"cells": {}}), encoding="utf-8")
    monkeypatch.setenv("GSD_CALIBRATION_DIR", str(host))
    here = _tree(tmp_path, 633)
    assert C.candidate_table_paths(here) == [here / C.DURABLE_DIR / C.SEED_TABLE_NAME]


@pytest.mark.parametrize("name", ["probe_calibration.json"])
def test_the_table_is_still_excluded_from_every_archive(name):
    import subprocess

    from tools import package_release as packager
    assert packager.include_in_release(packager.ROOT / C.DURABLE_DIR / name) is False
    assert packager.include_in_release(packager.ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME) is True, "the seed travels"
    ignored = subprocess.run(["git", "check-ignore", "-q", f"{C.DURABLE_DIR}/{name}"], cwd=ROOT)
    if ignored.returncode == 128:
        pytest.skip("not a git checkout")
    assert ignored.returncode == 0, "git ignores the live table"


SHIPPED = ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME


def _no_computing(monkeypatch):
    from graph_scale_dynamics.calibration import adopt, suite

    def refuse(*_, **__):
        raise AssertionError("a calibration cell was computed")

    monkeypatch.setattr(suite, "run_suite", refuse)
    monkeypatch.setattr(adopt, "verify_and_adopt", refuse)


def test_a_fresh_folder_with_only_the_shipped_table_adopts_it_without_computing_a_cell(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration.suite import ensure_calibration
    _no_computing(monkeypatch)
    here = _tree(tmp_path, 457)
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_bytes(SHIPPED.read_bytes())
    lines: list[str] = []
    status = ensure_calibration(root=here, var=here / "var", log=lines.append, profile=C.PROFILE_FULL)
    assert status["table_source"] == "shipped_seed", status["table_source"]
    assert status["computed"] == 0 and status["verdict"] == "PASS", status.get("summary")
    assert status["candidates_examined"] == [f"{here / C.DURABLE_DIR / C.SEED_TABLE_NAME}: used"]
    assert (here / C.DURABLE_DIR / C.DURABLE_NAME).is_file(), "the adopted table becomes this tree's own"
    spot = status["spot_check"]
    assert spot["sampled"] >= 10 and spot["moved"] == []
    assert any(line.startswith("calibration: spot check:") and "none moved" in line for line in lines), lines
    assert any("Candidates:" in line and "seed_table.json: used" in line for line in lines), lines


def test_a_new_study_beside_a_stale_table_starts_from_its_own_seed(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration.suite import ensure_calibration
    _no_computing(monkeypatch)
    stale = json.loads(SHIPPED.read_text(encoding="utf-8"))
    stale["cells"] = dict(list(stale["cells"].items())[:3])
    _study(tmp_path, "255", table=stale)
    here = _study(tmp_path, "256")
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_bytes(SHIPPED.read_bytes())
    lines: list[str] = []
    status = ensure_calibration(root=here, var=here / "var", log=lines.append, profile=C.PROFILE_FULL)
    assert status["table_source"] == "shipped_seed" and status["computed"] == 0, status.get("summary")
    assert status["candidates_examined"] == [f"{here / C.DURABLE_DIR / C.SEED_TABLE_NAME}: used"]
    assert not any("255" in line for line in lines), "the other study's table is never named, so never read"


def test_a_seed_that_cannot_be_resumed_from_says_why(tmp_path, monkeypatch):
    from graph_scale_dynamics.calibration import suite
    here = _tree(tmp_path, 633)
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_text(json.dumps({"contract": "not-a-calibration-table"}),
                                                            encoding="utf-8")

    class Measured(Exception):
        pass

    def stop(*_, **__):
        raise Measured

    monkeypatch.setattr(suite, "run_suite", stop)
    lines: list[str] = []
    with pytest.raises(Measured):
        suite.ensure_calibration(root=here, var=here / "var", log=lines.append, profile=C.PROFILE_FULL)
    assert any("no usable seed in this tree" in line for line in lines), lines


def test_a_seed_whose_value_moved_is_caught_by_the_spot_check_and_its_family_measured_again(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import adopt as ADOPT
    seed = json.loads(SHIPPED.read_text(encoding="utf-8"))
    picked = dict(ADOPT.sample_cells(seed, 1, deep_to=None))
    key = next(k for k, c in picked.items() if (c["channels"].get("d_s") or {}).get("valid"))
    seed["cells"][key]["channels"]["d_s"]["value"] += 0.25
    spot = ADOPT.spot_check({"cells": {key: seed["cells"][key]}})
    assert [m["cell"] for m in spot["moved"]] == [key] and "d_s: value" in spot["moved"][0]["problems"][0]
    family = seed["cells"][key]["family"]
    here = _tree(tmp_path, 636)
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_text(json.dumps(seed), encoding="utf-8")
    from graph_scale_dynamics.calibration import suite

    class Measured(Exception):
        pass

    def stop(*_, **__):
        raise Measured

    monkeypatch.setattr(suite, "run_suite", stop)
    monkeypatch.setattr(ADOPT, "verify_and_adopt", lambda *a, **k: {"adopted": False, "refused": [], "notices": []})
    lines: list[str] = []
    with pytest.raises(Measured):
        suite.ensure_calibration(root=here, var=here / "var", log=lines.append, profile=C.PROFILE_FULL)
    said = next(line for line in lines if "spot check:" in line)
    assert "1 moved" in said and family in said, said


def test_the_adoption_sample_reaches_each_family_s_largest_cell_to_4096():
    from graph_scale_dynamics.calibration import adopt as ADOPT
    seed = json.loads(SHIPPED.read_text(encoding="utf-8"))
    picked = ADOPT.sample_cells(seed, 2)
    by_family: dict = {}
    for _key, cell in picked:
        by_family.setdefault(cell["family"], []).append(cell["n"])
    for family, sizes in by_family.items():
        ladder = sorted({c["n"] for c in seed["cells"].values() if c["family"] == family and c["status"] == "ok"})
        assert max(sizes) == max(n for n in ladder if n <= ADOPT.DEEP_SAMPLE_TO), (family, sizes)
