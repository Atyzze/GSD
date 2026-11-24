from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.operations import study_record

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _stop_at(monkeypatch, made_before_stop: int):
    real, calls = control.create_campaign, []

    def create(repo, spec, **kwargs):
        if len(calls) == made_before_stop:
            raise KeyboardInterrupt("the first start was stopped here")
        calls.append(1)
        return real(repo, spec, **kwargs)

    monkeypatch.setattr(control, "create_campaign", create)
    return lambda: monkeypatch.setattr(control, "create_campaign", real)


def _quiet(*_):
    return None


def test_a_named_spec_s_start_does_not_finish_the_study_s(isolated_postgres_schema, tmp_path, monkeypatch):
    var = tmp_path / "var"
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        restore = _stop_at(monkeypatch, 2)
        with pytest.raises(KeyboardInterrupt):
            S.start_study(repo, control.shipped_spec(), search_seed=7, var=var, log=_quiet)
        restore()
        S.start_study(repo, control.shipped_spec(), default=False, var=var, log=_quiet)
        assert not study_record.complete(study_record.read(var))
        out = S.repair(repo, var=var)
        assert len(out["made"]) == 2
        seeds = sorted(int(repo.campaign(c)["search_seed"]) for c in out["made"])
        assert seeds == [9, 10]


def test_a_named_spec_stopped_before_its_campaign_leaves_plain_starts_alone(
        isolated_postgres_schema, tmp_path, monkeypatch):
    var = tmp_path / "var"
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        restore = _stop_at(monkeypatch, 0)
        with pytest.raises(KeyboardInterrupt):
            S.start_study(repo, control.shipped_spec(), default=False, var=var, log=_quiet)
        restore()
        assert study_record.read(var)["kind"] == study_record.NAMED_SPEC
        first = S.start_study(repo, control.shipped_spec(), search_seed=7, var=var, log=_quiet)
        assert first and len(repo.all_campaigns()) == 4
        record = study_record.read(var)
        assert record["kind"] == study_record.DEFAULT and study_record.complete(record)


def test_a_study_s_rest_is_not_made_from_another_base_spec(isolated_postgres_schema, tmp_path, monkeypatch):
    var = tmp_path / "var"
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        restore = _stop_at(monkeypatch, 2)
        with pytest.raises(KeyboardInterrupt):
            S.start_study(repo, control.shipped_spec(), search_seed=7, var=var, log=_quiet)
        restore()
        document = json.loads(study_record.path(var).read_text())
        study_record.path(var).write_text(json.dumps(dict(document, spec_sha256="0" * 64)))
        out = S.repair(repo, var=var)
        assert out["made"] is None and "another base spec" in S.render(out)[1]
        assert len(repo.all_campaigns()) == 2
