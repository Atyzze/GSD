from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.operations import standing_controls as SC

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class Log:
    def write(self, *args, **kwargs):
        pass


def test_the_fleet_start_creates_the_standing_controls_once_and_every_given_chain_starts_at_its_answer(
        isolated_postgres_schema):
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study
    from graph_scale_dynamics.services.api import campaign_manager
    from graph_scale_dynamics.services.controller.engine_campaign import run_engine_campaign

    criterion = SC.load_criterion()
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        assert SC.repair(repo)["why"] == "not a study's folder", "a folder with no quadrant gets no controls"
        study.start_study(repo, control.shipped_spec(), search_seed=7, log=lambda *_: None)
        created = SC.repair(repo)
        campaign_id = created["created"]
        assert campaign_id and created["laws"] == len(criterion["laws"]) == 5
        again = SC.repair(repo)
        assert again["created"] is None and again["campaign_id"] == campaign_id, "one standing controls a folder"
        assert again["added"] == 0
        row = repo.campaign(campaign_id)
        spec = row["spec"]
        assert spec["name"] == SC.NAME and spec["controls_criterion"] == "gsd-controls-criterion-2"
        assert spec["engine"]["policy"]["base_sizes"] == [n for n in criterion["rungs"] if n <= 1048576]
        assert campaign_id == "5", "beside the study's four quadrants"
        passed = run_engine_campaign(repo, Log(), {"campaign_id": campaign_id, "spec": spec})
        assert passed["admitted"] == 5 and passed["decisions"].get("run_next:start") == 5, passed
        starts = {}
        for job in repo.conn.execute("SELECT candidate_id,n,spec_json FROM jobs WHERE campaign_id=? "
                                     "AND kind='simulate'", (campaign_id,)).fetchall():
            one_shot = json.loads(job["spec_json"])["execution"]["one_shot"]
            starts[str(job["candidate_id"])] = one_shot.get("given_start")
            assert int(job["n"]) == 64
        by_label = {law["label"]: law["candidate_id"] for law in SC.laws(criterion)}
        assert starts[by_label["C1"]] == {"family": "periodic_cubic_quotient", "n": 64}
        assert starts[by_label["P1"]] == {"family": "periodic_square_lattice", "n": 64}
        shown = {c["campaign_id"]: c for c in campaign_manager.overview(repo)["campaigns"]}[campaign_id]
        assert shown["hand_fed"] and "ollivier_curvature" in shown["terms"]
        assert shown["laws_total"] == 5 and shown["graphs_total"] == 0
        assert shown["control_verdict"]["overall"] == "incomplete", "nothing read yet"


def test_a_control_campaign_the_operator_deletes_stays_deleted(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study

    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        study.start_study(repo, control.shipped_spec(), search_seed=7, log=lambda *_: None)
        standing = SC.repair(repo, var=tmp_path)["created"]
        assert standing and SC.made(tmp_path) == {SC.NAME: standing}
        repo.set_campaign_status(standing, "closed")
        repo.delete_campaign(standing)
        again = SC.repair(repo, var=tmp_path)
        assert again["created"] is None and again["deleted"] == standing
        assert SC.render(again) == [f"controls: Campaign {standing}, the standing controls, was deleted in this "
                                    f"folder; not made again"]
        assert standing not in {c["campaign_id"] for c in repo.all_campaigns()}
        fresh = tmp_path / "another_folder_s_var"
        assert SC.repair(repo, var=fresh)["created"], "a folder with no record of one gets it, as before"
