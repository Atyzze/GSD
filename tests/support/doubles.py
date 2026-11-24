from __future__ import annotations

class NullLog:
    def write(self, *args, **kwargs) -> None:
        pass


class Cursor:
    def __init__(self, row=None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


def bare_repo(connection):
    from graph_scale_dynamics.db.repo import Repo

    repo = object.__new__(Repo)
    repo.conn = connection
    repo.backend = "postgresql"
    repo._closed = False
    return repo


class RollbackCapable:
    def rollback_if_open(self) -> bool:
        if not getattr(self, "in_transaction", False):
            return False
        try:
            self.execute("ROLLBACK")
            return True
        except Exception:
            return False
