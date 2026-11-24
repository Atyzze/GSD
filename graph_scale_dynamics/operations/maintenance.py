from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from graph_scale_dynamics.db.repo import Repo

MAINTENANCE_LOCK = "gsd:maintenance-exclusive-v1"


@contextmanager
def exclusive_maintenance(repo: Repo) -> Iterator[None]:
    repo.wait_for_advisory_lock(MAINTENANCE_LOCK)
    try:
        yield
    finally:
        repo.release_advisory_lock(MAINTENANCE_LOCK)


@contextmanager
def unless_maintenance(repo: Repo) -> Iterator[bool]:
    key = repo._advisory_key(MAINTENANCE_LOCK)
    taken = bool(repo.conn.execute("SELECT pg_try_advisory_lock(?) AS taken", (key,)).fetchone()["taken"])
    try:
        yield taken
    finally:
        if taken:
            repo.release_advisory_lock(MAINTENANCE_LOCK)
