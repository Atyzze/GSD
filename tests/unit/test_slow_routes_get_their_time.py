from __future__ import annotations

from graph_scale_dynamics.services.web import main as W


def test_the_memory_ledger_is_given_its_time():
    assert dict(W.SLOW_ROUTES)["/api/memory-ledger"] >= 10.0


def test_a_law_s_page_is_given_its_time():
    for route in ("/api/campaign/1/candidate/" + "9f" * 32, "/api/candidate/" + "9f" * 32):
        assert next(t for prefix, t in W.SLOW_ROUTES if route.startswith(prefix)) >= 5.0
    assert not any("/api/campaigns".startswith(prefix) for prefix, _ in W.SLOW_ROUTES if prefix == "/api/campaign/")


def test_home_s_study_now_is_given_its_time_where_the_campaigns_overview_reads_every_campaign():
    assert next(t for prefix, t in W.SLOW_ROUTES if "/api/campaigns/overview".startswith(prefix)) >= 20.0
    assert next(t for prefix, t in W.SLOW_ROUTES if "/api/study-hours/study".startswith(prefix)) >= 5.0
