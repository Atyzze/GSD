from __future__ import annotations

import json
from pathlib import Path

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


def test_the_default_study_stopped_after_two_quadrants_is_made_whole_at_the_next_start(
        isolated_postgres_schema, tmp_path, monkeypatch):
    var = tmp_path / "var"
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        restore = _stop_at(monkeypatch, 2)
        with pytest.raises(KeyboardInterrupt):
            S.start_study(repo, control.shipped_spec(), search_seed=7, var=var, log=lambda *_: None)
        restore()
        assert len(repo.all_campaigns()) == 2 and not study_record.complete(study_record.read(var))

        from graph_scale_dynamics.artifact_store.blobstore import BlobStore
        from graph_scale_dynamics.operations.scratch_relief import at_fleet_start
        said: list[str] = []
        out = at_fleet_start(repo, BlobStore(tmp_path / "blobs"), var=var, say=said.append)["study"]
        assert out["made"] == ["3", "4"], out
        assert said[0].startswith("study default: its first start stopped part-way; this start made the rest")
        rows = {str(r["campaign_id"]): r for r in repo.active_campaigns()}
        assert [S.quadrant_label(rows[c]["spec"]) for c in "1234"] == [
            "zero temperature, mean degree to 16", "zero temperature, mean degree to 32",
            "finite temperature, mean degree to 16", "finite temperature, mean degree to 32"]
        assert all(S.law_budget(repo, c) == S.DEFAULT_LAW_BUDGET for c in "1234")
        events = repo.conn.execute("SELECT COUNT(*) AS c FROM campaign_events WHERE "
                                   "event_type='campaign_law_budget_changed'").fetchone()["c"]
        assert events == 4, "each quadrant's budget given once"
        assert study_record.complete(study_record.read(var))
        assert sorted(S.made(repo, None)) == sorted(S.quadrant_label(rows[c]["spec"]) for c in "1234")
        held = len(repo.all_campaigns())
        assert S.repair(repo, var=var) is None and len(repo.all_campaigns()) == held, "whole: the next start makes none"


def _a_tree_with_a_study_of_three_batches(tmp_path) -> tuple[Path, dict]:
    root = Path(__file__).resolve().parents[2]
    readings = root / "graph_scale_dynamics" / "resources" / "readings"
    design = json.loads((root / "tests" / "fixtures" / "a_design.json").read_text())
    seed = int(design["search_seeds"][0])
    design.update(study="261", search_seeds=[seed, seed + 1, seed + 2],
                  campaigns=[dict(design["campaigns"][0], label=f"batch {i + 1}") for i in range(3)])
    tree = tmp_path / "tree"
    (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True)
    (tree / "graph_scale_dynamics" / "resources" / "readings" / "study_261_design.json").write_text(json.dumps(design))
    (tree / "graph_scale_dynamics" / "resources" / "readings" / "studies.json").write_text(json.dumps(
        {"studies": [{"id": "261", "notes": "three batches of a test's draw"}]}))
    return tree, design


def test_a_designed_study_stopped_part_way_is_completed_as_its_first_start_would_have_made_it(
        isolated_postgres_schema, tmp_path, monkeypatch):
    var = tmp_path / "var"
    tree, design = _a_tree_with_a_study_of_three_batches(tmp_path)
    planned = len(design["campaigns"])
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        restore = _stop_at(monkeypatch, 2)
        with pytest.raises(KeyboardInterrupt):
            S.start_study(repo, control.shipped_spec(), var=var, tree=tree, study="261", log=lambda *_: None)
        restore()
        assert len(repo.all_campaigns()) == 2 and not (var / "salt").exists(), "no ledger is carried"

        out = S.repair(repo, var=var, tree=tree)
        assert len(out["made"]) == planned - 2
        assert sorted(S.made(repo, "261")) == list(range(planned)), "each place of the design made once"
        campaigns = sorted(repo.all_campaigns(), key=lambda c: int(c["campaign_id"]))
        assert [int(c["search_seed"]) for c in campaigns] == design["search_seeds"], "each campaign its fixed seed"
        assert S.repair(repo, var=var, tree=tree) is None and len(repo.all_campaigns()) == planned


def test_a_study_made_whole_or_recorded_by_its_campaigns_is_left_as_it_is(isolated_postgres_schema, tmp_path):
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        whole = tmp_path / "whole"
        S.start_study(repo, control.shipped_spec(), search_seed=7, var=whole, log=lambda *_: None)
        assert study_record.complete(study_record.read(whole)) and S.repair(repo, var=whole) is None
        for name, record in (("by_campaigns", {"chosen_by": study_record.BY_CAMPAIGNS}),
                             ("before_648", {"chosen_by": study_record.BY_FLAG})):
            var = tmp_path / name
            study_record.write(var, study="default", kind=study_record.DEFAULT, log=lambda *_: None, **record)
            document = json.loads(study_record.path(var).read_text())
            if name == "before_648":
                document.pop(study_record.COMPLETE)
                study_record.path(var).write_text(json.dumps(document))
            assert S.repair(repo, var=var) is None, name
        other = tmp_path / "other_build"
        study_record.write(other, study="default", kind=study_record.DEFAULT, chosen_by=study_record.BY_DEFAULT,
                           log=lambda *_: None)
        document = json.loads(study_record.path(other).read_text())
        study_record.path(other).write_text(json.dumps(dict(document, build_number=int(document["build_number"]) - 1)))
        out = S.repair(repo, var=other)
        assert out["made"] is None and "start this folder on build" in S.render(out)[1]
        assert len(repo.all_campaigns()) == 4
