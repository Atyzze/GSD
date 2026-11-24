from __future__ import annotations

import pytest

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.services.controller import main as controller


class _Conn:
    def __init__(self):
        self.rollbacks = 0

    def rollback_if_open(self):
        self.rollbacks += 1


class _Repo:
    def __init__(self, error):
        self.error, self.conn, self.passes, self.released = error, _Conn(), 0, False
        self.backend = "postgresql"

    def acquire_service_lock(self, name):
        return True

    def release_service_lock(self, name):
        self.released = True

    def close(self):
        pass

    def get_flag(self, key, default=None):
        if key != "paused":
            return default
        self.passes += 1
        if self.passes == 1:
            raise self.error
        return "0"

    def heartbeat(self, *args):
        pass

    def wait_for_work(self, *args):
        return False

    def active_campaigns(self):
        return []

    def fleet_has_work(self, *args):
        return False


def _run(monkeypatch, tmp_path, error):
    repo = _Repo(error)
    monkeypatch.setattr(controller, "Repo", lambda db: repo)
    code = controller.main(["--db", "x", "--campaign", "1", "--var", str(tmp_path), "--poll", "0.01"])
    return repo, code


def test_a_transient_error_is_a_pass_run_again(monkeypatch, tmp_path):
    repo, code = _run(monkeypatch, tmp_path, DatabaseOperationalError("lock timeout", transient=True,
                                                                      sqlstate="55P03"))
    assert code == 0 and repo.passes == 2 and repo.conn.rollbacks == 1 and repo.released


def test_any_other_error_still_ends_it(monkeypatch, tmp_path):
    with pytest.raises(DatabaseOperationalError):
        _run(monkeypatch, tmp_path, DatabaseOperationalError("syntax", transient=False, sqlstate="42601"))
