from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.domain.cadence import TICK_SECONDS
from graph_scale_dynamics.services.api import freshness as F
from graph_scale_dynamics.services.api import study_scope as S

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = (ROOT / "graph_scale_dynamics" / "resources" / "ui" / "system.js").read_text(encoding="utf-8")
node = shutil.which("node")
STEP = 0.05
BUSY = "dashboard database capacity busy"


class _Handler:
    def __init__(self):
        self.sent = None

    def _json(self, payload, status=200):
        self.sent = (status, payload)

    def _access_payload(self):
        return {"admin": False}

    def _privileged(self):
        return True


class _Api:
    def __init__(self, ids, *, build, slots, slot_wait, ttl, shared=False, jitter=0.25, other_reads=0.5, seed=7):
        self.ids, self.build, self.slots, self.slot_wait, self.ttl = ids, build, slots, slot_wait, ttl
        self.shared = shared
        self.jitter, self.other_reads, self.rand = jitter, other_reads, random.Random(seed)
        self.now, self.built, self.errors, self.refreshing = 0.0, {}, {}, set()
        self.waiting, self.running, self.held_until, self.stopped = [], {}, [], False
        self.ms = {}

    def cached(self, key):
        cid = key[0]
        built = self.built.get(cid)
        payload = None if built is None else {"campaign_id": cid, "active": [],
                                              "dashboard_response": {"build_ms": self.ms[cid]}}
        return payload, None if built is None else self.now - built, cid in self.refreshing, self.errors.get(cid)

    def schedule(self, key):
        cid = key[0]
        if cid in self.refreshing:
            return False
        self.refreshing.add(cid)
        self.waiting.append((cid, self.now))
        return True

    def _free(self):
        self.held_until = [t for t in self.held_until if t > self.now]
        return self.slots - len(self.running) - len(self.held_until)

    def advance(self, seconds):
        end = self.now + seconds
        while self.now < end - 1e-9:
            self.now = round(self.now + STEP, 6)
            share = STEP / max(1, len(self.running)) if self.shared else STEP
            for cid, (left, began) in list(self.running.items()):
                if self.stopped:
                    continue
                left -= share
                if left > 1e-9:
                    self.running[cid] = (left, began)
                    continue
                del self.running[cid]
                self.ms[cid] = round((self.now - began) * 1000.0, 1)
                self.built[cid] = self.now
                self.errors.pop(cid, None)
                self.refreshing.discard(cid)
            kept = []
            for cid, asked in self.waiting:
                if self._free() > 0:
                    took = self.build * (1.0 + self.rand.uniform(-self.jitter, self.jitter))
                    self.running[cid] = (took, self.now)
                elif self.now - asked >= self.slot_wait:
                    self.errors[cid] = BUSY
                    self.refreshing.discard(cid)
                else:
                    kept.append((cid, asked))
            self.waiting = kept

    def poll(self, scope):
        if self.other_reads:
            self.held_until.append(self.now + self.other_reads)
        handler = _Handler()
        scope.serve(handler, "overview", {})
        return handler.sent[1]["dashboard_response"]


def _scope(api, slots_known):
    return S.Scope(batches=lambda: list(api.ids), landscape_status=None, schedule_landscape=None, landscape_ttl=16.0,
                   cached_overview=api.cached, schedule_overview=api.schedule, overview_ttl=api.ttl,
                   host_snapshot=lambda: {}, incidents=lambda handler: [], cache_root=ROOT, python="python3", root=ROOT,
                   overview_slots=slots_known)


def _shown(responses):
    start = SYSTEM.index("  const STALE_AFTER_MS")
    end = SYSTEM.index("  function showFreshness(")
    script = SYSTEM[start:end] + (f"\nconsole.log(JSON.stringify({json.dumps(responses)}"
                                  ".map(r => freshnessOf(r, 0).state)));")
    out = subprocess.run([node], input=script, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _run(*, batches, build, minutes, stop_at=None, slots=4, ttl=TICK_SECONDS, shared=False):
    api = _Api([str(i) for i in range(1, batches + 1)], build=build, slots=slots,
               slot_wait=F.REFRESH_SLOT_WAIT_SECONDS, ttl=ttl, shared=shared)
    scope = _scope(api, slots)
    responses, times = [], []
    while api.now < minutes * 60.0:
        if stop_at is not None and api.now >= stop_at:
            api.stopped = True
        response = api.poll(scope)
        if not response.get("pending"):
            responses.append(response)
            times.append(api.now)
        api.advance(TICK_SECONDS)
    return times, responses


@pytest.mark.skipif(node is None, reason="node is not installed")
@pytest.mark.parametrize("build,shared", [(0.8, False), (2.0, False), (4.0, False),
                                          (0.8, True), (1.2, True), (1.5, True), (2.0, True)])
def test_eleven_batches_refreshing_on_a_busy_host_show_their_age_and_no_banner(build, shared):
    times, responses = _run(batches=11, build=build, minutes=10, shared=shared)
    states = _shown(responses)
    ages = [r["source_age_ms"] / 1000.0 for r in responses]
    assert set(states[3:]) == {"fresh"}, (build, [(t, a, s) for t, a, s in zip(times, ages, states, strict=True) if s != "fresh"])
    assert not any(r.get("last_refresh_error") for r in responses[3:]), "no refresh gave up waiting for a slot"
    if shared and build >= 1.2:
        assert max(ages[3:]) > 3 * TICK_SECONDS, "older than the bound of one campaign: what raised the banner before"


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_a_dashboard_a_minute_behind_says_so_whatever_its_load():
    times, responses = _run(batches=11, build=3.0, minutes=10, shared=True)
    states = _shown(responses)
    late = [(r["source_age_ms"] / 1000.0, bool(r.get("last_refresh_error"))) for r, s in zip(responses, states, strict=True)
            if s == "fresh"]
    assert "stale" in states[3:]
    assert all(age <= F.MOST_STALE_AFTER_SECONDS and not failed for age, failed in late), late
    assert all(r["stale_after_ms"] <= F.MOST_STALE_AFTER_SECONDS * 1000.0 for r in responses)


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_banner_comes_when_the_refreshes_stop_and_says_so_within_its_own_bound():
    times, responses = _run(batches=11, build=2.0, minutes=6, stop_at=120.0)
    states = _shown(responses)
    before = [s for t, s in zip(times, states, strict=True) if 12.0 <= t < 120.0]
    after = [(t, s, r) for t, s, r in zip(times, states, responses, strict=True) if t >= 120.0]
    assert set(before) == {"fresh"}
    first = next(t for t, s, _r in after if s == "stale")
    bound = after[0][2]["stale_after_ms"] / 1000.0
    assert first - 120.0 <= bound + F.REFRESH_SLOT_WAIT_SECONDS + 2 * TICK_SECONDS, (first, bound)
    assert all(s == "stale" for t, s, _r in after if t >= first), "once behind, it stays said until it catches up"


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_a_batch_whose_refresh_failed_is_named_in_the_study_s_answer():
    api = _Api(["1", "2", "3"], build=0.5, slots=4, slot_wait=F.REFRESH_SLOT_WAIT_SECONDS, ttl=TICK_SECONDS)
    scope = _scope(api, 4)
    api.poll(scope)
    api.advance(TICK_SECONDS)
    api.errors["2"] = "OperationalError: the server closed the connection at overview.py:812"
    response = api.poll(scope)
    assert response["last_refresh_error"].startswith("batch 2: OperationalError")
    assert response["refresh_errors"] == {"2": "OperationalError: the server closed the connection at overview.py:812"}
    assert _shown([response]) == ["stale"], "a failing refresh is a fault: the banner says which batch and why"


def test_one_campaign_keeps_its_bound_and_a_paused_one_its_longer_ttl():
    assert F.stale_after_seconds(4.0, [0.8], 1) == pytest.approx(2.0 * (4.0 + TICK_SECONDS + 0.8))
    assert F.stale_after_seconds(4.0, [None], 1) == pytest.approx(16.0), "no build time read: one round of the tick"
    assert F.stale_after_seconds(16.0, [0.8], 1) == pytest.approx(48.0), "paused: three of its own ttl, as before"
    assert F.stale_after_seconds(4.0, [2.0] * 11, 4) == pytest.approx(2.0 * (4.0 + TICK_SECONDS + 3 * 2.0))
    assert F.stale_after_seconds(4.0, [9.0] * 11, 4) == F.MOST_STALE_AFTER_SECONDS == 60.0, "a minute at most"
    assert F.build_seconds({"dashboard_response": {"build_ms": 877.1}}) == pytest.approx(0.8771)
    assert F.build_seconds({"dashboard_response": {}}) is None
    reading = F.reading(4.0, [0.8, 2.0], 4)
    assert reading["slowest_build_seconds"] == 2.0 and reading["stale_after_seconds"] == pytest.approx(20.0)
