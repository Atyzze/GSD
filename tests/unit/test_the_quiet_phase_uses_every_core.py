from __future__ import annotations

import os
from pathlib import Path

import pytest

from graph_scale_dynamics.services.reporter import main as R


def _fake_build(code, snapshot):
    if code == "03":
        raise ValueError("a report that fails fails the same way in a child")
    if code == "04" and snapshot.get("kill_in_child") and os.getpid() != snapshot["parent"]:
        os._exit(9)
    return {"code": code, "rows": len(snapshot["rows"]), "pid": os.getpid()}


@pytest.mark.skipif(os.name != "posix", reason="the pool forks")
def test_a_forked_child_per_report_builds_what_the_serial_loop_builds(monkeypatch):
    monkeypatch.setattr(R, "build_report", _fake_build)
    snapshot = {"rows": list(range(1000)), "parent": os.getpid()}
    codes = ["01", "02", "03"]
    pool, futures = R.start_report_pool(snapshot, codes, 3)
    try:
        for code in ("01", "02"):
            payload, seconds = R.report_payload(futures, code, snapshot)
            assert payload["rows"] == 1000 and payload["pid"] != os.getpid() and seconds is not None
        with pytest.raises(ValueError):
            R.report_payload(futures, "03", snapshot)
    finally:
        R.end_report_pool(pool)
    import gc
    assert gc.get_freeze_count() == 0
    if Path("/proc/self/smaps_rollup").exists():
        assert R.CHILD_PRIVATE_PEAK["bytes"] > 0
    assert R.start_report_pool(snapshot, codes, 1) == (None, {})
    payload, seconds = R.report_payload({}, "01", snapshot)
    assert payload["pid"] == os.getpid() and seconds is None


@pytest.mark.skipif(os.name != "posix", reason="the pool forks")
def test_a_child_that_dies_costs_the_cycle_nothing_but_time(monkeypatch):
    monkeypatch.setattr(R, "build_report", _fake_build)
    snapshot = {"rows": [1], "parent": os.getpid(), "kill_in_child": True}
    pool, futures = R.start_report_pool(snapshot, ["04"], 2)
    try:
        payload, seconds = R.report_payload(futures, "04", snapshot)
        assert payload["pid"] == os.getpid() and seconds is None
    finally:
        R.end_report_pool(pool)


def test_the_numbered_reports_are_built_in_their_number_order():
    ordered = [int(d.number) for d in R.reports_in_catalog_order()]
    assert ordered == sorted(int(d.number) for d in R.REPORTS)


def test_the_reports_that_read_every_measurement_are_built_before_the_children(monkeypatch):
    def build(code, snapshot):
        if code == "23":
            raise ValueError("fails where it is published, as a child's report does")
        return {"code": code, "pid": os.getpid()}
    monkeypatch.setattr(R, "build_report", build)
    noted = []
    early = R.build_before_the_children({}, ["01", "04", "14", "16", "05", "23", "28"], noted.append)
    assert noted == ["04", "14", "16", "23", "28"] and set(early) == set(R.BUILT_BEFORE_THE_CHILDREN)
    payload, seconds = R.report_payload({}, "28", {}, early)
    assert payload == {"code": "28", "pid": os.getpid()} and seconds is not None
    with pytest.raises(ValueError):
        R.report_payload({}, "23", {}, early)
    payload, seconds = R.report_payload({}, "01", {}, early)
    assert payload["code"] == "01" and seconds is None, "the rest as before: the pool's, or built here"


def test_the_reports_built_before_the_children_are_the_ones_that_read_the_measurements():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import report_audit
    readers = {r["code"] for r in report_audit.audit()["reports"]
               if "measurements" in r["reads"]["parts"].get("primary", [])}
    assert set(R.BUILT_BEFORE_THE_CHILDREN) == readers, readers
