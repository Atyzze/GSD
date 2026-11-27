from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


def test_a_run_queued_and_a_probe_done_reach_a_listening_page_within_a_second(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.services.api import events as E
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as listening, Repo(isolated_postgres_schema.dsn) as fleet:
        listening.conn.listen_for_work()
        campaign = str(fleet.create_campaign({"name": "events"}, search_seed=1)["campaign_id"])
        law = "e" * 64
        fleet.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        fleet.insert_job(job_id="ev-1", campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=64,
                         seed=0, spec={}, priority=1)
        said = E.gathered(E._notes(listening.conn.raw, 5.0))
        assert "jobs" in said["tables"] and said["runs"] and not said["readings"]
        assert E._notes(listening.conn.raw, 0.2) == [], "nothing more: the page waits and pings"


def test_the_stream_relayed_by_the_web_service_arrives_as_it_is_written():
    import http.client
    from graph_scale_dynamics.services.web import streaming

    class Upstream:
        status = 200

        def __init__(self):
            self.parts = [b"retry: 5000\nevent: hello\ndata: {}\n\n", b"event: work\ndata: {}\n\n"]

        def getheader(self, key, default=None):
            return {"Content-Type": "text/event-stream; charset=utf-8"}.get(key, default)

        def read1(self, n):
            return self.parts.pop(0) if self.parts else b""

    class Conn:
        def request(self, method, path, headers=None):
            assert (method, path) == ("GET", "/api/events")

        def getresponse(self):
            return Upstream()

        def close(self):
            pass

    class Handler:
        def __init__(self):
            self.wfile, self.sent, self.close_connection, self.status = io.BytesIO(), {}, False, None

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            self.sent[key] = value

        def end_headers(self):
            pass

    handler = Handler()
    assert streaming.relay_events(handler, Conn, {"Host": "api"}) is True
    assert handler.status == 200 and handler.sent["Content-Type"].startswith("text/event-stream")
    assert handler.wfile.getvalue().count(b"event: ") == 2 and handler.close_connection
    assert http.client.HTTPResponse.read1, "the relay reads what has come, not a whole chunk"
