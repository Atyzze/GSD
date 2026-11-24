from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _web(path: str):
    from graph_scale_dynamics.services.web import main as web
    Handler = web.build_handler(api_host="127.0.0.1", api_port=1, bind_host="127.0.0.1", allowed_hosts=(),
                                base_path="", report_root=None, access_counter=web.AccessCounter())
    handler = Handler.__new__(Handler)
    handler.path, handler.command = path, "GET"
    handler.headers = {"Host": "127.0.0.1:8765"}
    handler.rfile = io.BytesIO(b"")
    proxied, sent = [], []
    handler._proxy = lambda upstream_override=None: proxied.append(upstream_override)
    handler._send = lambda body, content_type, code=200, **kw: sent.append(code)
    return handler, proxied, sent


def test_the_web_process_bridges_the_structure_reading_to_its_own_api():
    handler, proxied, sent = _web("/structure-data/4/c079aa58")
    handler._dispatch()
    assert proxied == ["/api/structure/4/c079aa58"] and not sent
    handler, proxied, sent = _web("/structure-data/4")
    handler._dispatch()
    assert not proxied and sent == [404]


def test_the_bridge_gets_the_structure_reading_s_time():
    from graph_scale_dynamics.services.web import main as web
    assert any("/api/structure/4/x".startswith(prefix) for prefix, _ in web.SLOW_ROUTES)


class _Repo:
    def __init__(self, memberships):
        self.memberships = memberships
        self.asked = []

    def measurements(self, candidate_id, analysis_version, campaign_id):
        self.asked.append(campaign_id)
        return []

    def candidate(self, candidate_id, campaign_id):
        return {"candidate_id": candidate_id, "campaign_id": campaign_id} if campaign_id in self.memberships else None

    def candidate_campaign_ids(self, candidate_id):
        return list(self.memberships)

    def engine_decisions(self, campaign_id, candidate_id):
        return []

    def campaign(self, campaign_id):
        return {"spec": {}}


def test_a_wrongly_named_campaign_resolves_to_the_law_s_one_campaign():
    from graph_scale_dynamics.services.api import readings_route
    repo = _Repo(["4"])
    payload = readings_route.structure(repo, "study", "law")
    assert payload["campaign_id"] == "4" and repo.asked == ["study", "4"]
    assert readings_route.structure(_Repo(["4"]), "4", "law")["campaign_id"] == "4"


def test_a_law_of_two_campaigns_is_never_guessed():
    from graph_scale_dynamics.services.api import readings_route
    assert readings_route.structure(_Repo(["4", "5"]), "study", "law") is None
    assert readings_route.structure(_Repo([]), "4", "law") is None


def test_the_reading_is_the_campaign_s_own_analysis():
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.services.api import readings_route

    class Versioned(_Repo):
        def __init__(self, version):
            super().__init__(["4"])
            self.version, self.versions = version, []

        def measurements(self, candidate_id, analysis_version, campaign_id):
            self.versions.append(analysis_version)
            return []

        def campaign(self, campaign_id):
            return {"spec": {"analysis_version": self.version} if self.version else {}}

    old = Versioned("analysis-4.0.0")
    readings_route.structure(old, "4", "law")
    assert old.versions == ["analysis-4.0.0"]
    unnamed = Versioned(None)
    readings_route.structure(unnamed, "4", "law")
    assert unnamed.versions == [ANALYSIS_VERSION]
