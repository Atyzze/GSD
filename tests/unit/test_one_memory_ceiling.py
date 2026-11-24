from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.scheduling import memory  # noqa: E402
from graph_scale_dynamics.scheduling.memory import (  # noqa: E402
    GIB, GIVEN_BACK_CEILING_FRACTION, RUNAWAY_MIN_BYTES, RUNAWAY_RESERVATION_MULTIPLE,
    SINGLE_JOB_CEILING_FRACTION, MemorySnapshot, process_stop_bytes,
)

HOST = MemorySnapshot(total=92 * GIB, available=60 * GIB)
SURVEY = {"resource_limits": {"deep_from_n": 262144, "deep_single_job_fraction_total": 0.55,
                              "hard_single_job_fraction_total": 0.08}}
CEILING = int(92 * GIB * SINGLE_JOB_CEILING_FRACTION)
GIVEN_BACK = int(92 * GIB * GIVEN_BACK_CEILING_FRACTION)


def test_the_ceiling_is_a_quarter_of_the_host_at_every_rung():
    for n in (64, 16384, 262144, 1048576, 4194304):
        assert memory.hard_process_limit_bytes(SURVEY, snapshot=HOST, n=n) == CEILING
    assert memory.given_back_limit_bytes(snapshot=HOST) == GIVEN_BACK
    assert GIVEN_BACK / GIB > 32, "an analysis given back may use up to 32 GiB on the operator's host"


def test_a_child_is_stopped_at_four_times_its_opening_reservation_as_a_runaway():
    limit, kind = process_stop_bytes(SURVEY, 65536, 1 * GIB, snapshot=HOST)
    assert (limit, kind) == (int(RUNAWAY_RESERVATION_MULTIPLE * GIB), "runaway")


def test_a_small_child_gets_at_least_the_runaway_floor():
    limit, kind = process_stop_bytes(SURVEY, 64, 40 * 1024 ** 2, snapshot=HOST)
    assert (limit, kind) == (RUNAWAY_MIN_BYTES, "runaway")


def test_a_large_child_is_stopped_at_the_ceiling_not_past_it():
    limit, kind = process_stop_bytes(SURVEY, 1048576, 18 * GIB, snapshot=HOST)
    assert (limit, kind) == (CEILING, "ceiling")
    assert process_stop_bytes(SURVEY, 1048576, None, snapshot=HOST) == (CEILING, "ceiling")
    assert process_stop_bytes(SURVEY, 4194304, 18 * GIB, snapshot=HOST) == (CEILING, "ceiling"), "no deeper ceiling"


class _Rows:
    def __init__(self, row=None):
        self.row, self.rowcount = row, 1

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.updates = []

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append(params)
            return _Rows()
        return _Rows({"sim_bytes": 0, "ana_bytes": 0, "sim_count": 0, "ana_count": 0, "total": 0,
                      "simulation": 0, "analysis": 0, "c": 0})


def test_a_claim_predicted_above_the_ceiling_reserves_the_ceiling_instead_of_being_refused(monkeypatch):
    monkeypatch.setattr(memory, "recorded_lease_reservations", lambda conn: {"total": 0})
    monkeypatch.setattr(memory, "host_memory_launch_guard",
                        lambda snapshot=None: {"allowed": True, "total_bytes": HOST.total,
                                               "min_available_bytes": 10 * GIB})
    monkeypatch.setattr(memory, "launch_ramp_state", lambda conn, snapshot=None: {"allowed": True})
    conn = _Conn()
    verdict = memory.admit_recorded_claim(
        conn, kind="analysis", reservation_bytes=30 * GIB, budget_bytes=60 * GIB,
        hard_single_job_bytes=CEILING, campaign_id="c", artifact="a", analysis_version="v",
        owner="o", claim_token="t", snapshot=HOST)
    assert verdict.get("refusal") is None and verdict["within_budget"] is True
    assert verdict["requested"] == CEILING and verdict["clamped_to_ceiling"] is True
    assert verdict["predicted"] == 30 * GIB
    assert conn.updates and conn.updates[0][0] == CEILING, "the ceiling is what is reserved"
