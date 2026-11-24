from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_a_reading_setting_off_its_default_is_recorded(monkeypatch):
    from graph_scale_dynamics.domain import version as V
    monkeypatch.delenv("GSD_SPECTRAL_PROBE_BLOCK", raising=False)
    monkeypatch.setenv("GSD_SPECTRAL_PROBE_BLOCK", "8")
    assert V.reading_settings() == {}, "the defaults leave the environment's record as it was"
    monkeypatch.setenv("GSD_SPECTRAL_PROBE_BLOCK", "4")
    assert V.reading_settings() == {"GSD_SPECTRAL_PROBE_BLOCK": "4"}


def _tree(tmp_path: Path, table: dict) -> Path:
    from graph_scale_dynamics.calibration import contract as C
    here = tmp_path / "main"
    (here / C.DURABLE_DIR).mkdir(parents=True)
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_bytes((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_bytes())
    (here / C.DURABLE_DIR / C.DURABLE_NAME).write_text(json.dumps(table))
    return here


def _quick(monkeypatch, checked: list):
    from graph_scale_dynamics.calibration import adopt, suite

    def spot(document, **kw):
        checked.append(True)
        return {"sampled": 1, "worst_deviation": 0.0, "worst_host_spread": 0.0, "moved": []}

    def refuse(*_, **__):
        raise AssertionError("a calibration cell was computed")

    monkeypatch.setattr(adopt, "spot_check", spot)
    monkeypatch.setattr(suite, "run_suite", refuse)


def test_a_table_is_held_by_its_fingerprints_not_a_host_s_or_folder_s_name(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import contract as C
    from graph_scale_dynamics.calibration import suite
    seed = json.loads((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_text())
    seed.setdefault("origin", {})["computed_on"] = "another host entirely"
    seed["origin"].pop("adopted_on", None)
    here, checked = _tree(tmp_path, seed), []
    _quick(monkeypatch, checked)
    status = suite.ensure_calibration(root=here, var=here / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert not checked and status["verdict"] == "PASS" and status["computed"] == 0, status.get("summary")


def test_the_archive_s_seed_is_spot_checked_once_as_it_is_adopted(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import contract as C
    from graph_scale_dynamics.calibration import suite
    here, checked = tmp_path / "main", []
    (here / C.DURABLE_DIR).mkdir(parents=True)
    (here / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_bytes((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_bytes())
    _quick(monkeypatch, checked)
    status = suite.ensure_calibration(root=here, var=here / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert checked and status["verdict"] == "PASS", status.get("summary")
    checked.clear()
    suite.ensure_calibration(root=here, var=here / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert not checked, "the table adopted is not checked again"


def test_an_unusable_table_falls_through_to_the_seed(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import contract as C
    from graph_scale_dynamics.calibration import suite
    here, checked = _tree(tmp_path, {"contract": "some-other-contract", "cells": {}}), []
    _quick(monkeypatch, checked)
    status = suite.ensure_calibration(root=here, var=here / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert status["table_source"] == "shipped_seed"
    assert status["computed"] == 0 and status["verdict"] == "PASS"


def test_the_instrument_check_judges_only_current_cells(monkeypatch):
    from graph_scale_dynamics.calibration import fingerprint as FP
    from graph_scale_dynamics.calibration.instrument_check import instrument_check
    monkeypatch.setattr(FP, "cell_fingerprint", lambda family, root=None: "now")
    cell = {"family": "periodic_ring", "n": 64, "seed": 0, "status": "ok", "parameter": None,
            "channels": {"d_s": {"value": 1.0, "se": 0.01, "valid": True}}}
    table = {"profile": {"seeds": 1}, "cells": {"a": dict(cell, cell_fingerprint="now"),
                                                 "b": dict(cell, seed=1, cell_fingerprint="pre-627")}}
    found = instrument_check(table)
    assert (found["cells_judged"], found["stale_cells_left_out"]) == (1, 1)


def test_a_suite_version_mismatch_says_what_happens():
    from graph_scale_dynamics.calibration import table as T
    from graph_scale_dynamics.calibration.contract import CONTRACT
    report = T.verify({"contract": CONTRACT, "suite_version": -5, "cells": {}}, [], seeds=1, max_nodes=None)
    notice = next(n for n in report["notices"] if "suite version" in n)
    assert "is not resumed from" in notice and "measured as a new one" in notice and not report["usable"], notice


def test_a_cell_paused_after_its_record_is_continued_before_the_join(monkeypatch):
    from graph_scale_dynamics.calibration import suite
    sent = []
    monkeypatch.setattr(suite.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    class Process:
        pid = 4321

        def join(self, timeout=None):
            sent.append("join")

        def is_alive(self):
            return False

    class Pipe:
        def close(self):
            pass

    cell = suite._LargeCell.__new__(suite._LargeCell)
    cell.process, cell.receive, cell.result = Process(), Pipe(), {"elapsed_seconds": 5.0}
    cell.paused_at, cell.paused_seconds, cell.trace = time.monotonic(), 0.0, []
    assert cell.collect()["elapsed_seconds"] == 5.0
    assert sent[:2] == [(4321, signal.SIGCONT), "join"]


def test_a_budget_refusal_alone_gives_a_rung_no_classification():
    from graph_scale_dynamics.readmodel import rung_classification as R
    summary = {"mean_degree": {"mean": 3.0}, "probe_refusals": {"d_s": {"REFUSED_COMPUTE_BUDGET": 2}}}
    assert R.classification_from_summary(summary, {"mean_degree_window": {"min": 0.0, "max": 16.0}}) is None


def test_the_certificate_s_overrides_reach_the_child():
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    plain = one_shot_policy(spec, n=256)
    assert "zero_temperature_rest_late_descent_share" not in plain, "a spec that sets none is what it was"
    spec["policy"] = dict(spec.get("policy") or {}, zero_temperature_rest_late_descent_share=0.02,
                          equilibration_connected_delta_floor=0.05)
    policy = one_shot_policy(spec, n=256)
    assert policy["zero_temperature_rest_late_descent_share"] == 0.02
    assert policy["equilibration_connected_delta_floor"] == 0.05


def test_a_killed_writer_s_temp_files_are_found_once_they_are_old(tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    store = BlobStore(tmp_path)
    folder = tmp_path / "blobs" / "ab" / "cd"
    folder.mkdir(parents=True)
    old, new = folder / ".abcd.123.spill", folder / ".abcd.x.tmp"
    for path in (old, new):
        path.write_text("x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    assert store.stale_temporaries() == [old]


def test_a_lost_session_s_blocking_lock_fails_the_statement_in_flight(monkeypatch):
    from graph_scale_dynamics.db import connection as DB
    conn = DB.PostgresConnection.__new__(DB.PostgresConnection)

    class Lost(Exception):
        sqlstate = "57P01"

    class Raw:
        def execute(self, *a):
            raise Lost("terminating connection due to administrator command")

    conn.raw, conn._held_locks, conn._session_locks = Raw(), {}, {}
    monkeypatch.setattr(conn, "_session_lost", lambda exc: True, raising=False)
    monkeypatch.setattr(conn, "_reconnect", lambda: True, raising=False)
    monkeypatch.setattr(conn, "_map_error", lambda exc, transient=None: DB.DatabaseOperationalError(str(exc)),
                        raising=False)
    conn._psycopg = type("P", (), {"Error": Lost})
    monkeypatch.setattr(DB.PostgresConnection, "in_transaction", property(lambda self: False), raising=False)
    conn.hold_lock(7, "gsd:memory-claim")
    try:
        conn.execute("SELECT 1")
    except DB.DatabaseOperationalError as exc:
        assert "gsd:memory-claim" in str(exc) and not exc.transient
    else:
        raise AssertionError("the statement ran on a new session without the lock")
    assert conn._held_locks == {}
