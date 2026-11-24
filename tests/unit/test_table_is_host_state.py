from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import plan_cells, suite_families
from graph_scale_dynamics.calibration.contract import (
    AUTHORITATIVE_SEEDS, DURABLE_DIR, DURABLE_NAME, SUITE_VERSION)

ROOT = Path(__file__).resolve().parents[2]

HOST_STATE = (
    f"{DURABLE_DIR}/{DURABLE_NAME}",
)


@pytest.mark.parametrize("relative", HOST_STATE)
def test_no_host_state_is_shipped_in_a_build_archive(relative):
    from tools import package_release

    path = ROOT / relative
    if not path.exists():
        assert relative not in package_release.REQUIRED_RELEASE_PATHS
        assert "probe_calibration.json" in package_release.EXCLUDED_NAMES
        pytest.skip("no durable calibration table on this host")
    assert not package_release.include_in_release(path), (
        f"{relative} is host state produced by running the suite, not source. "
        "Shipping it in a build overwrites the target's own table with whatever "
        "the packager happened to have. A fresh host computes its own; an "
        "existing host keeps the one it earned. If a starter table is genuinely "
        "wanted, it goes through tools/adopt_calibration.py, which announces "
        "itself and re-verifies, rather than through a silent file copy.")
    shipped = {p.relative_to(ROOT).as_posix() for p in package_release.release_paths()
               if package_release.include_in_release(p)}
    assert relative not in shipped
    assert relative not in package_release.REQUIRED_RELEASE_PATHS, (
        "the packager must not demand a file it must not carry")


def test_the_durable_table_path_is_outside_var_and_that_is_why_this_matters():
    from graph_scale_dynamics.calibration.contract import durable_artifact_path

    path = durable_artifact_path(ROOT)
    assert path.parent == ROOT / DURABLE_DIR
    assert "var" not in path.relative_to(ROOT).parts


def _document():
    families = suite_families()
    document = T.new_table(families, seeds=AUTHORITATIVE_SEEDS, max_nodes=None,
                           authoritative=True, profile="full")
    document["suite_version"] = 1
    document["build_number"] = 244
    document["families"] = {"periodic_ring": document["families"]["periodic_ring"]}
    return document, families


def test_a_resumed_table_stops_claiming_the_suite_it_was_created_under():
    document, families = _document()
    T.restamp_header(document, families, seeds=AUTHORITATIVE_SEEDS, max_nodes=None)

    assert document["suite_version"] == SUITE_VERSION
    assert document["build_number"] != 244
    assert set(document["families"]) == set(f["name"] for f in families), (
        "the families header describes the table's shape and must be re-derived")


def test_restamping_preserves_creation_provenance_rather_than_erasing_it():
    document, families = _document()
    T.restamp_header(document, families, seeds=AUTHORITATIVE_SEEDS, max_nodes=None)

    created = document["created_under"]
    assert created["suite_version"] == 1
    assert created["build_number"] == 244

    T.restamp_header(document, families, seeds=AUTHORITATIVE_SEEDS, max_nodes=None)
    assert document["created_under"] == created


def test_a_history_copy_holding_more_cells_is_found_before_the_run(tmp_path):
    families = suite_families()[:1]
    plan = plan_cells(families, seeds=1, max_nodes=300)
    assert plan, "the fixture needs at least one planned cell"

    from graph_scale_dynamics.calibration import fingerprint as FP
    history = tmp_path / "history"
    history.mkdir()
    good = {
        task["key"]: {"family": task["family"], "status": "ok",
                      "cell_fingerprint": FP.cell_fingerprint(task["family"])}
        for task in plan
    }
    (history / "table_20260908T223707Z.json").write_text(
        json.dumps({"cells": good, "written_utc": "2026-09-08T22:37:07Z"}), encoding="utf-8")

    found = T.history_recovery_candidates(history, plan, durable_current=0)
    assert found, "a history copy covering the plan must be offered"
    assert found[0]["usable_cells"] == len(plan)
    assert found[0]["gain"] == len(plan)


def test_a_stale_history_copy_is_not_offered_as_a_recovery(tmp_path):
    families = suite_families()[:1]
    plan = plan_cells(families, seeds=1, max_nodes=300)
    history = tmp_path / "history"
    history.mkdir()
    stale = {
        task["key"]: {"family": task["family"], "status": "ok",
                      "cell_fingerprint": "0000000000000000"}
        for task in plan
    }
    (history / "table_old.json").write_text(
        json.dumps({"cells": stale, "written_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")

    assert T.history_recovery_candidates(history, plan, durable_current=0) == []


def test_nothing_is_offered_when_the_durable_table_is_already_better(tmp_path):
    families = suite_families()[:1]
    plan = plan_cells(families, seeds=1, max_nodes=300)
    history = tmp_path / "history"
    history.mkdir()
    (history / "table_old.json").write_text(
        json.dumps({"cells": {}, "written_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")

    assert T.history_recovery_candidates(history, plan, durable_current=len(plan)) == []


def test_a_missing_or_unreadable_history_directory_is_not_an_error(tmp_path):
    families = suite_families()[:1]
    plan = plan_cells(families, seeds=1, max_nodes=300)
    assert T.history_recovery_candidates(tmp_path / "absent", plan, 0) == []

    history = tmp_path / "history"
    history.mkdir()
    (history / "not_json.json").write_text("{{{", encoding="utf-8")
    assert T.history_recovery_candidates(history, plan, 0) == []
