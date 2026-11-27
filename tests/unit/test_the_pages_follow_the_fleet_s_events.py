from __future__ import annotations

import io
import json

from graph_scale_dynamics.services.api import events as E


class _Handler:
    def __init__(self, broken_after: int | None = None):
        self.wfile, self.status, self.headers, self.writes, self.broken_after = io.BytesIO(), None, {}, 0, broken_after
        self.close_connection = False

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


class _Wfile(io.BytesIO):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def write(self, data):
        self.owner.writes += 1
        if self.owner.broken_after is not None and self.owner.writes > self.owner.broken_after:
            raise BrokenPipeError
        return super().write(data)


class _Repo:
    def __init__(self):
        self.listening, self.closed = False, False
        self.conn = self
        self.raw = object()

    def listen_for_work(self):
        self.listening = True

    def close(self):
        self.closed = True


def _note(table, status):
    return json.dumps({"table": table, "op": "UPDATE", "status": status})


def test_a_page_hears_each_change_of_the_work_gathered_and_said_what_it_was():
    said = E.gathered([_note("jobs", "done"), _note("jobs", "queued"), _note("analysis_queue", "done"), "not json"])
    assert said["tables"] == ["analysis_queue", "jobs"] and said["statuses"] == ["done", "queued"]
    assert said["readings"] and said["runs"], "a probe done is a new reading; a run done or queued is the fleet's work"
    assert not E.gathered([_note("jobs", "queued")])["readings"]
    assert E.gathered([_note("candidate_evidence_rebuilds", "done")])["readings"], "a rung summary rebuilt is a reading"
    assert E.frame("work", {"a": 1}) == b'event: work\ndata: {"a": 1}\n\n'
    assert E.frame(comment="ping") == b": ping\n\n" and E.frame("hello", {}, retry=5000).startswith(b"retry: 5000\n")


def test_the_stream_says_hello_then_each_change_and_pings_while_nothing_moves_and_drops_the_caches_on_readings():
    handler, repo, forgot = _Handler(), _Repo(), []
    handler.wfile = _Wfile(handler)
    batches = iter([[_note("jobs", "done")], [], [_note("analysis_queue", "done")]])
    sent = E.stream(handler, lambda: repo, on_readings=lambda: forgot.append(1), rounds=3,
                    notes=lambda raw, timeout: next(batches))
    text = handler.wfile.getvalue().decode()
    assert handler.status == 200 and handler.headers["Content-Type"].startswith("text/event-stream")
    assert handler.headers["Cache-Control"] == "no-store" and handler.close_connection
    assert text.startswith("retry: 5000\nevent: hello\n") and text.count("event: work") == 2 and ": ping" in text
    assert sent == 2 and forgot == [1], "the curves' answers are dropped once, on the probe done"
    assert repo.listening and repo.closed


def test_a_page_that_leaves_ends_its_stream_and_a_page_past_the_most_polls_instead(monkeypatch):
    handler, repo = _Handler(broken_after=1), _Repo()
    handler.wfile = _Wfile(handler)
    assert E.stream(handler, lambda: repo, rounds=5, notes=lambda raw, timeout: [_note("jobs", "done")]) == 0
    assert repo.closed, "the browser gone, its connection closed"
    import threading
    monkeypatch.setattr(E, "_OPEN", threading.BoundedSemaphore(1))
    E._OPEN.acquire()
    full = _Handler()
    assert E.stream(full, lambda: _Repo(), rounds=1, notes=lambda raw, timeout: []) == 0
    assert full.status == 503 and b"polls instead" in full.wfile.getvalue()
    E._OPEN.release()
