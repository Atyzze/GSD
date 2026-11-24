from __future__ import annotations

import pytest

from graph_scale_dynamics.db.connection import connect_database
from graph_scale_dynamics.domain.cadence import ticks


@pytest.fixture
def conn(folder_postgres_base):
    connection = connect_database(folder_postgres_base)
    try:
        yield connection
    finally:
        connection.close()


def _show(conn, name: str) -> str:
    row = conn.execute(f"SHOW {name}").fetchone()
    return str(list(dict(row).values())[0] if hasattr(row, "keys") or isinstance(row, dict) else row[0])


def test_commits_do_not_wait_for_the_disk(conn):
    assert _show(conn, "synchronous_commit") == "off"


def test_the_wal_writer_flushes_once_a_tick(conn):
    assert _show(conn, "wal_writer_delay") == f"{int(ticks(1))}s"


def test_fsync_and_full_page_writes_are_untouched(conn):
    assert _show(conn, "fsync") == "on"
    assert _show(conn, "full_page_writes") == "on"
