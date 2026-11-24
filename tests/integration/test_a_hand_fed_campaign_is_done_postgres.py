from __future__ import annotations

from pathlib import Path

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.resources import committed

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

ROOT = Path(__file__).resolve().parents[2]
CRITERION = committed.read(ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_3.json")


def _state(repo, campaign_id: str) -> str:
    from graph_scale_dynamics.services.api import campaign_manager
    return {c["campaign_id"]: c for c in campaign_manager.overview(repo)["campaigns"]}[campaign_id]["state"]


def test_a_hand_fed_campaign_with_nothing_in_flight_is_done(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import standing_controls as SC

    criterion = dict(CRITERION, laws=CRITERION["laws"][:3:2])
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = SC.campaign_spec(criterion)
        first = str(control.create_campaign(repo, spec, reason="a hand-fed campaign", search_seed=7)["campaign_id"])
        SC._insert_laws(repo, first, spec, criterion, only_missing=False)
        assert _state(repo, first) == "active", "two laws not yet admitted are in flight"
        laws = [c["candidate_id"] for c in repo.candidates(first)]
        repo.set_candidate_state(laws[0], "STOPPED", "a test", campaign_id=first)
        assert _state(repo, first) == "active", "one law still to run keeps it active"
        repo.set_candidate_state(laws[1], "DONE", "a test", campaign_id=first)
        assert _state(repo, first) == "done"
