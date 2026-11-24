from __future__ import annotations

import io
import re
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from graph_scale_dynamics.observability import incidents

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean():
    incidents.clear()
    yield
    incidents.clear()


def _raise(kind=NameError, message="name 'rung_standings' is not defined"):
    def inner():
        raise kind(message)
    try:
        inner()
    except Exception as exc:
        return exc
    raise AssertionError("unreachable")


def test_the_record_carries_the_line_that_failed():
    record = incidents.record("api", "overview refresh", _raise())
    assert record["error"] == "NameError: name 'rung_standings' is not defined"
    assert record["origin"] and re.match(r".+\.py:\d+ in \w+", record["origin"])
    assert "Traceback" in record["traceback"]


def test_it_reaches_stderr_where_a_supervisor_log_can_see_it():
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        incidents.record("api", "overview refresh", _raise())
    written = buffer.getvalue()
    assert "ERROR" in written
    assert "overview refresh failed" in written
    assert "rung_standings" in written
    assert "Traceback" in written, "the first occurrence carries the full stack"


def test_a_repeating_fault_is_reported_once_then_counted():
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        for _ in range(50):
            record = incidents.record("api", "overview refresh", _raise())
    assert record["count"] == 50
    assert buffer.getvalue().count("overview refresh failed") == 1


def test_distinct_faults_are_not_collapsed_into_one():
    incidents.record("api", "overview refresh", _raise(NameError, "a"))
    incidents.record("api", "overview refresh", _raise(TypeError, "b"))
    assert len({r["error"] for r in incidents.recent()}) == 2


def test_a_recovered_lane_stops_warning():
    incidents.record("api", "overview refresh", _raise())
    assert incidents.recent()
    assert incidents.clear("api", "overview refresh") == 1
    assert incidents.recent() == []


def test_the_store_is_bounded():
    for i in range(incidents.MAX_INCIDENTS * 2):
        incidents.record("api", "overview refresh", _raise(NameError, f"n{i}"))
    assert len(incidents.recent(limit=1000)) <= incidents.MAX_INCIDENTS
