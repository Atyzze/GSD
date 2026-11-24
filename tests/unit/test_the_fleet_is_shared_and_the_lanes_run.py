from __future__ import annotations

from graph_scale_dynamics.decisions.decider import QUEUE_ORDER, decide_pass
from graph_scale_dynamics.domain import model
from graph_scale_dynamics.observability.child_diagnostics import same_reason_exhausted
from graph_scale_dynamics.operations.failure_repair import analysis_is_the_fleets, seed_is_the_fleets
from graph_scale_dynamics.services.worker import main as worker
from graph_scale_dynamics.services.worker.main import allowed_campaigns
from tests.unit.test_decider import LAW, POLICY, FakeStore, entry


def row(campaign_id, target=None, leased=0, queued=10):
    return {"campaign_id": campaign_id, "workers_target": target, "leased": leased, "queued": queued}


def test_with_no_share_declared_the_campaigns_left_behind_are_offered_first():
    fleet = [row("1", leased=7), row("2", leased=6), row("3", leased=0), row("4", leased=0)]
    assert set(allowed_campaigns(fleet)) == {"3", "4"}, "14 slots among four with work: 3 each, and 3 and 4 have 0"


def test_a_campaign_below_its_equal_part_is_offered_until_it_has_it():
    fleet = [row("1", leased=7), row("2", leased=6), row("3", leased=3), row("4", leased=1)]
    assert allowed_campaigns(fleet) == ("4",)


def test_when_every_campaign_has_its_equal_part_the_claim_is_free():
    assert allowed_campaigns([row("1", leased=4), row("2", leased=4), row("3", leased=3), row("4", leased=3)]) is None


def test_a_campaign_with_no_work_is_owed_nothing_and_one_alone_claims_freely():
    assert allowed_campaigns([row("1", leased=9, queued=0), row("2", leased=0, queued=0), row("3", leased=0)]) is None
    assert allowed_campaigns([row("1", leased=0), row("2", leased=0, queued=0)]) is None


def test_a_declared_share_still_comes_before_an_equal_part():
    assert allowed_campaigns([row("1", None, leased=0), row("2", 8, leased=0)]) == ("2",)


def test_a_paused_campaign_is_not_counted_among_those_with_work():
    fleet = [row("1", 0, leased=0, queued=500), row("2", None, leased=5), row("3", None, leased=0)]
    assert allowed_campaigns(fleet) == ("3",), "the six slots go three and three between 2 and 3; 1 is paused"


def test_a_rung_of_the_base_block_run_again_keeps_the_base_blocks_rank_and_a_bought_rung_its_own():
    cells = {n: dict(entry(2.5), d_s_bucket=("REFUSED_NEVER_EQUILIBRATED" if n >= 1024 else None))
             for n in (64, 256, 1024, 4096)}
    again = FakeStore([LAW], entries={LAW: cells})
    again.enqueue_seeds = lambda *a, queue_order, longer=False, **k: again.jobs.append((a[2], queue_order)) or 3
    decide_pass(again, "1")
    assert again.jobs == [(4096, QUEUE_ORDER["base"])] and again.decisions[0]["priority"] == 2
    bought = FakeStore([LAW], entries={LAW: {64: entry(2.5), 256: entry(2.5), 1024: entry(2.50, d_s=1.50),
                                             4096: entry(2.51, d_s=1.52)}})
    decide_pass(bought, "1")
    assert bought.jobs == [(LAW, 16384, 3, int(POLICY.work_budget(16384) * POLICY.merit_budget_scale), QUEUE_ORDER[1])], \
        "above the base block the decision's priority ranks it, as before"


class _Fleet:
    conn = None

    def __init__(self, leased=None):
        self.leased = leased or {}
        self.claims = []

    def worker_allocation(self, **_):
        return []

    def leased_count(self, *, min_n=None, max_n=None):
        return int(self.leased.get((min_n, max_n), 0))

    def claim_job(self, owner, kinds, **kwargs):
        self.claims.append(kwargs)
        return None


def test_the_lanes_have_their_own_reserve_first_in_extensions_half():
    fleet = _Fleet({(None, None): 1})
    worker.claim_simulation_for_owner(fleet, "w")
    order = [(c.get("min_n"), c.get("max_n"), c.get("order")) for c in fleet.claims]
    assert order[:3] == [(worker.LANE_MIN_N, None, "deepest"), (worker.EXTENSION_MIN_N, None, "deepest"),
                         (worker.EXTENSION_FROM_N, worker.LANE_MIN_N - 1, "oldest")], order


def test_three_lane_seeds_fill_the_lanes_reserve():
    fleet = _Fleet({(worker.LANE_MIN_N, None): 3, (worker.EXTENSION_MIN_N, None): 3,
                    (worker.EXTENSION_FROM_N, None): 3, (None, None): 11})
    worker.claim_simulation_for_owner(fleet, "w")
    reserve = [c for c in fleet.claims if c.get("min_n") == worker.LANE_MIN_N and c.get("order") == "deepest"]
    assert not reserve, "three lane seeds run: the reserve is full"
    rest = [c for c in fleet.claims if c.get("order") == "oldest"]
    assert rest and rest[0]["max_n"] == worker.LANE_MIN_N - 1


def test_the_seed_memory_is_held_for_is_the_first_claim(monkeypatch):
    fleet = _Fleet()
    monkeypatch.setattr(worker.memory_hold, "active", lambda conn: {"job_id": "deep-4m-0"})
    worker.claim_simulation_for_owner(fleet, "w")
    assert fleet.claims[0] == {"lease_seconds": worker.SIM_LEASE_SECONDS, "job_id": "deep-4m-0"}


def _reserves(claims, campaigns):
    return [(c.get("min_n"), c.get("max_n"), c.get("order")) for c in claims if c.get("campaigns") == campaigns]


def test_with_nothing_to_take_for_the_campaigns_owed_a_worker_every_reserve_is_tried_for_every_campaign():
    fleet = _Fleet()
    fleet.worker_allocation = lambda **_: [row("1", leased=0, queued=5), row("2", leased=6, queued=5)]
    worker.claim_simulation_for_owner(fleet, "w")
    every = [(None, worker.SMALL_RUNG_MAX_N, None), (None, worker.EXTENSION_FROM_N - 1, "priority_random"),
             (worker.LANE_MIN_N, None, "deepest"), (worker.EXTENSION_MIN_N, None, "deepest"),
             (worker.EXTENSION_FROM_N, worker.LANE_MIN_N - 1, "oldest"), (worker.LANE_MIN_N, None, "priority_random")]
    assert _reserves(fleet.claims, ("1",)) == every, "first for the campaign owed a worker"
    assert _reserves(fleet.claims, None) == every, "then, with nothing there, for every campaign"
    assert [c.get("campaigns") for c in fleet.claims] == [("1",)] * 6 + [None] * 6


def test_an_empty_allow_list_is_one_pass_for_every_campaign():
    fleet = _Fleet()
    worker.claim_simulation_for_owner(fleet, "w")
    assert [c.get("campaigns") for c in fleet.claims] == [None] * 6


def test_only_a_refusal_for_the_room_holds_it(monkeypatch):
    lane = {"job_id": "deep-1m-0", "campaign_id": "1", "candidate_id": "law", "n": worker.LANE_MIN_N, "spec": {},
            "lease_generation": 1}

    class Repo(_Fleet):
        def claim_job(self, owner, kinds, **kwargs):
            self.claims.append(kwargs)
            return dict(lane)

        def emit(self, *a, **k):
            pass

        def release_job(self, *a, **k):
            return True

    started = []
    monkeypatch.setattr(worker, "predicted_claim_peak_bytes", lambda *a, **k: 9 << 30)
    monkeypatch.setattr(worker, "hard_process_limit_bytes", lambda *a, **k: None)
    monkeypatch.setattr(worker.memory_hold, "start", lambda conn, **kw: started.append(kw["job_id"]))
    for refusal, held in (("transient_memory_floor", True), ("transient_host_pressure", True),
                          ("transient_launch_ramp", False), (None, False)):
        started.clear()
        verdict = {"within_budget": False, "requested": 9 << 30, **({"refusal": refusal} if refusal else {})}
        monkeypatch.setattr(worker, "locked_admission", lambda repo, **kw: verdict)
        assert worker.claim_simulation_for_owner(Repo(), "w") is None
        assert started == (["deep-1m-0"] if held else []), refusal


def test_the_fleets_own_endings_are_interruptions_and_named_once():
    from graph_scale_dynamics.db import repo
    assert {model.ATTEMPT_CLASS_WORKER_CAP, model.ATTEMPT_CLASS_LEASE_LOST} <= set(model.INTERRUPTED_ATTEMPT_CLASSES)
    assert repo.Repo.PREEMPT_WORKER_CAP == model.ATTEMPT_CLASS_WORKER_CAP
    assert repo.ATTEMPT_CLASS_LEASE_LOST == model.ATTEMPT_CLASS_LEASE_LOST
    assert not set(model.STORAGE_ATTEMPT_CLASSES) & set(model.INTERRUPTED_ATTEMPT_CLASSES), \
        "the storage's failures still count toward a job's three"


def test_three_interruptions_and_one_real_failure_no_longer_stop_a_job():
    for interruption in model.INTERRUPTED_ATTEMPT_CLASSES:
        assert same_reason_exhausted([interruption] * 3 + ["no_result"]) is None, interruption
    assert same_reason_exhausted(["supervisor_interrupted"] * 5 + ["exception:ValueError"] * 3) == "exception:ValueError"


def test_which_seeds_the_fleet_failed():
    stopped = "child failed [stopped: 4 attempts, third failure with reason 'supervisor_interrupted']"
    assert seed_is_the_fleets("failed", stopped, ["supervisor_interrupted"] * 3 + ["exception:ValueError"])
    assert seed_is_the_fleets("failed", "x [stopped: 3 attempts, third failure with reason 'no_result']",
                              ["no_result"] * 3)
    assert seed_is_the_fleets("failed", "x", ["preempted_fleet_shutdown", "exception:OSError"])
    assert seed_is_the_fleets("lost", "lost after 3 expired leases", ["supervisor_interrupted"] * 3)
    assert seed_is_the_fleets("lost", "lost after 3 expired leases", ["signal:SIGSEGV", "supervisor_interrupted"])
    assert not seed_is_the_fleets("failed", "x [stopped: 3 attempts, third failure with reason 'exception:ValueError']",
                                  ["exception:ValueError"] * 3)
    assert not seed_is_the_fleets("failed", "memory hard stop", ["memory_hard_stop"]), "its own memory, at once"
    assert not seed_is_the_fleets("failed", "memory admission refused permanently (permanent_over_budget)", []), \
        "refused memory for good, with nothing behind it"
    assert not seed_is_the_fleets("failed", "x", []), "nothing recorded, nothing to say it was the fleet"


def test_which_analyses_the_fleet_failed():
    for cls in ("staging_io:OSError", "child_process:missing_success_receipt", "child_process:no_space_left",
                "exception:OSError", "child_process:invalid_terminal_receipt", "lease_expired"):
        assert analysis_is_the_fleets(cls), cls
    for cls in ("memory_hard_cap", "timeout", "analysis:ValueError", "artifact_integrity:ValueError", None,
                "analysis_exception:OSError", "payload_contract:OSError"):
        assert not analysis_is_the_fleets(cls), cls
