from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.scheduling import fleet_halves as H
from graph_scale_dynamics.services.analyzer import main as analyzer
from graph_scale_dynamics.services.worker import main as worker

ROOT = Path(__file__).resolve().parents[2]


def test_extension_holds_half_rounded_down_and_base_exploration_the_rest():
    assert H.extension_first(5, 11) and not H.extension_first(6, 11)
    assert H.extension_first(4, 10) and not H.extension_first(5, 10)
    assert not H.extension_first(0, 0), "a lone worker serves base exploration first"
    assert H.extension_first(0, 1), "of two, one each"
    assert [H.extension_places(n) for n in range(1, 8)] == [0, 1, 1, 2, 2, 3, 3]


def test_the_boundary_is_where_a_designed_study_leaves_its_base_block():
    ladder = json.loads((ROOT / "tests" / "fixtures" / "a_design.json").read_text())["ladder"]
    assert max(ladder["base"]) < H.EXTENSION_FROM_N == min(ladder["deep"]) == 16384
    assert H.EXTENSION_SHARE == 0.5 and worker.EXTENSION_FROM_N == H.EXTENSION_FROM_N


class _Fleet:
    conn = None

    def __init__(self, leased=None, takes=None):
        self.leased = leased or {}
        self.takes = takes
        self.claims = []

    def worker_allocation(self, **_):
        return []

    def leased_count(self, *, min_n=None, max_n=None):
        return int(self.leased.get((min_n, max_n), 0))

    def claim_job(self, owner, kinds, **kwargs):
        self.claims.append(kwargs)
        found = (kwargs.get("min_n"), kwargs.get("max_n"), kwargs.get("order")) == self.takes
        return {"job_id": "found"} if found else None


EXTENSION = [(worker.LANE_MIN_N, None, "deepest"), (worker.EXTENSION_MIN_N, None, "deepest"),
             (H.EXTENSION_FROM_N, worker.LANE_MIN_N - 1, "oldest")]
BASE = [(None, worker.SMALL_RUNG_MAX_N, None), (None, H.EXTENSION_FROM_N - 1, "priority_random")]
REST = [(worker.LANE_MIN_N, None, "priority_random")]


def _order(fleet):
    return [(c.get("min_n"), c.get("max_n"), c.get("order")) for c in fleet.claims]


def test_extension_short_of_its_half_is_tried_first_in_its_own_order():
    fleet = _Fleet({(H.EXTENSION_FROM_N, None): 5, (None, None): 11})
    worker.claim_simulation_for_owner(fleet, "w")
    assert _order(fleet) == EXTENSION + BASE + REST


def test_extension_at_its_half_leaves_the_worker_to_base_exploration_first():
    fleet = _Fleet({(H.EXTENSION_FROM_N, None): 6, (None, None): 11})
    worker.claim_simulation_for_owner(fleet, "w")
    assert _order(fleet) == BASE + EXTENSION + REST


def test_the_lanes_count_in_extensions_half():
    fleet = _Fleet({(worker.LANE_MIN_N, None): 3, (worker.EXTENSION_MIN_N, None): 3,
                    (H.EXTENSION_FROM_N, None): 6, (None, None): 11})
    worker.claim_simulation_for_owner(fleet, "w")
    assert _order(fleet) == BASE + EXTENSION[2:] + REST, "both reserves full: extension's rungs oldest first"


def test_a_half_with_nothing_to_take_hands_the_worker_to_the_other():
    owed_extension = _Fleet({(None, None): 11, (None, worker.SMALL_RUNG_MAX_N): 2}, takes=BASE[1])
    assert worker._claim_by_reserve(owed_extension, "w", None) == {"job_id": "found"}
    assert _order(owed_extension) == EXTENSION + BASE[1:], "the small rungs' two are running: straight to the block"
    owed_base = _Fleet({(H.EXTENSION_FROM_N, None): 6, (None, None): 11}, takes=EXTENSION[2])
    assert worker._claim_by_reserve(owed_base, "w", None) == {"job_id": "found"}
    assert _order(owed_base) == BASE + EXTENSION


def test_the_halves_are_tried_for_the_campaigns_owed_a_worker_then_for_every_campaign():
    fleet = _Fleet()
    fleet.worker_allocation = lambda **_: [{"campaign_id": "1", "workers_target": None, "leased": 0, "queued": 5},
                                           {"campaign_id": "2", "workers_target": None, "leased": 6, "queued": 5}]
    worker.claim_simulation_for_owner(fleet, "w")
    one_pass = BASE + EXTENSION + REST
    assert [c.get("campaigns") for c in fleet.claims] == [("1",)] * len(one_pass) + [None] * len(one_pass)
    assert _order(fleet) == one_pass * 2


class _Analyses:
    def __init__(self, leased=None, queued=(), zone=()):
        self.leased = leased or {}
        self.queued = list(queued)
        self.zone = list(zone)
        self.claims = []

    def analysis_leased_count(self, *, min_n=None, max_n=None):
        return int(self.leased.get((min_n, max_n), 0))

    def claim_analysis_job(self, owner, version, lease_seconds=120, **bounds):
        if "tier_at_most" in bounds:
            return next(({"n": n, "zone": True} for n in self.zone), None)
        self.claims.append(bounds)
        low, high = bounds.get("min_n", 0), bounds.get("max_n", float("inf"))
        return next(({"n": n} for n in self.queued if low <= n <= high), None)


def test_the_zone_s_and_the_depth_worker_s_probes_come_before_either_half():
    both = _Analyses({(H.EXTENSION_FROM_N, None): 2, (None, None): 3}, queued=[4096], zone=[16384])
    assert analyzer.claim_analysis_for_owner(both, "w") == {"n": 16384, "zone": True} and both.claims == []


def test_the_analyses_are_divided_as_the_simulations_are():
    owed = _Analyses({(H.EXTENSION_FROM_N, None): 1, (None, None): 3}, queued=[4096, 65536])
    assert analyzer.claim_analysis_for_owner(owed, "w") == {"n": 65536}
    assert owed.claims == [{"min_n": H.EXTENSION_FROM_N, "order": "oldest"}]
    held = _Analyses({(H.EXTENSION_FROM_N, None): 2, (None, None): 3}, queued=[4096, 65536])
    assert analyzer.claim_analysis_for_owner(held, "w") == {"n": 4096}
    assert held.claims == [{"max_n": H.EXTENSION_FROM_N - 1}], "base exploration's by rank, as before"


def test_an_analysis_half_with_nothing_to_read_hands_the_worker_to_the_other():
    base_only = _Analyses({(None, None): 3}, queued=[1024])
    assert analyzer.claim_analysis_for_owner(base_only, "w") == {"n": 1024}
    assert base_only.claims == [{"min_n": H.EXTENSION_FROM_N, "order": "oldest"}, {"max_n": H.EXTENSION_FROM_N - 1}]
    nothing = _Analyses()
    assert analyzer.claim_analysis_for_owner(nothing, "w") is None and len(nothing.claims) == 2
