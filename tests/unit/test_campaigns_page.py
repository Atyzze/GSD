from __future__ import annotations

def test_the_ladder_is_reported_deepest_first_and_three_deep():
    from graph_scale_dynamics.services.api.campaign_manager import TOP_RUNGS, _rung_rows
    rungs = _rung_rows({4096: 40, 65536: 9, 262144: 3, 1048576: 1}, {4096: 38})
    top = list(reversed(rungs[-TOP_RUNGS:]))
    assert [row["n"] for row in top] == [1048576, 262144, 65536]
    assert top[0]["laws"] == 1 and rungs[0]["measured"] == 38, (
        "laws and measured are different readings of a rung and must stay apart")


def test_a_surveyed_campaign_still_offers_its_controls():
    from graph_scale_dynamics.services.api.campaign_manager import _controls

    class NoLinks:
        def campaign_link(self, campaign_id):
            return None

        def dependent_campaigns(self, campaign_id):
            return []

    import graph_scale_dynamics.services.api.campaign_manager as manager
    manager_chains = manager.campaign_chains_running
    manager.campaign_chains_running = lambda repo, campaign_id: 0

    surveyed = _controls(NoLinks(), {"campaign_id": "2", "status": "active",
                                     "workers_target": None}, 1)
    assert surveyed["pause"] is True and surveyed["workers"] is True
    paused = _controls(NoLinks(), {"campaign_id": "1", "status": "active",
                                   "workers_target": 0}, 1)
    assert paused["resume"] is True and paused["pause"] is False
    manager.campaign_chains_running = manager_chains


def test_the_page_divides_the_fleet_and_deletes_but_never_archives():
    from graph_scale_dynamics.services.api.campaign_manager import ACTIONS
    assert {"workers", "allocate", "delete"} <= set(ACTIONS) and "archive" not in ACTIONS
    assert set(ACTIONS) <= {"pause", "resume", "reopen", "preflight", "clone", "create",
                            "workers", "allocate", "fleet_pause", "fleet_resume", "delete", "budget",
                            "auto_extend", "fleet_workers"}
