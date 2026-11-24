from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.decider import decide_pass, learned_for
from graph_scale_dynamics.decisions.engine import Policy

GATE = "empty"
STUDY_171 = Policy(let_through_rule=G.LET_THROUGH_RULE, let_through_from=256, confirm_after=100, learn_in_batches_of=4,
                   known_result_after=100, known_result_from=256, gate_shares=((LT.KNOWN_RESULT, 1.0),))


def _law(number: int) -> str:
    return f"law{number:02d}".ljust(64, "0")


class World:
    def __init__(self, numbers):
        self.numbers = list(numbers)
        self.rows: dict = {}
        self.state: dict = {}

    def decide(self, number: int, n: int, action: str = "run_next", rule: str = "base_block", salted=(),
               signature=None, held: bool = False, ended: bool = False) -> None:
        rows = self.rows.setdefault(number, [])
        rows.append({"campaign_id": "c", "candidate_id": _law(number), "decision_id": f"{number:04d}-{len(rows)}",
                     "at_n": n, "action": action, "rule": rule, "salted": list(salted), "signature": signature})
        self.state[number] = {"verdict_past": n, "held": held, "ended": ended}

    def rows_of(self, keys: list) -> list:
        by_law = {_law(number): number for number in self.numbers}
        return [row for _c, law in keys for row in self.rows.get(by_law[law], [])]

    def points(self, policy: Policy) -> LT.FixedPoints:
        laws = [{"campaign_id": "c", "candidate_id": _law(number), "number": number, "campaign_order": 0,
                 **self.state.get(number, {"verdict_past": None, "held": False, "ended": False})}
                for number in self.numbers]
        return LT.FixedPoints().refresh(laws, policy)


class Store:
    def __init__(self, world: World, policy: Policy, asking: int, mean_degree: float):
        self.world, self.policy, self.asking, self.mean_degree = world, policy, asking, mean_degree
        self.pending, self.decisions = [], []

    def fixed_points(self, campaign_id):
        return self.world.points(self.policy)

    def learning_rows(self, keys):
        return self.world.rows_of(keys)

    def laws_awaiting_decision(self, campaign_id):
        return [_law(self.asking)]

    def law_evidence(self, campaign_id, law):
        return {"entries": {256: {"mean_degree": self.mean_degree, "connected_fraction": 1.0,
                                  "measurement_seed_count": 3, "d_s": None, "d_s_bucket": None, "probes": {}}}}

    def record_pending(self, campaign_id, law, reasons):
        self.pending.append((law, tuple(reasons)))

    def seed_rows(self, campaign_id, law):
        return {}

    def enqueue_seeds(self, campaign_id, law, n, **kwargs):
        return kwargs.get("seeds", 0)

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return 0

    def held_laws(self, campaign_id, limit=None):
        return []


def _first_group_at_256(world: World, *, salted=(GATE,)) -> None:
    for number in range(1, 5):
        world.decide(number, 256, rule="salted" if salted else "base_block", salted=salted)


def test_a_law_decides_at_once_when_no_earlier_law_could_confirm_a_gate():
    world = World(range(1, 9))
    _first_group_at_256(world)
    points = world.points(STUDY_171)
    assert points.ledger(1, 256, world.rows_of) is None, "laws 1 to 4 are not past 256: the whole ledger waits"
    policy, learned = learned_for(Store(world, STUDY_171, 5, 4.0), points, STUDY_171, _law(5), 256)
    assert policy is not None and policy.salt_shares == () and policy.known_results == ()
    assert learned["determined"] == {"undecided": 0, "let_through_most": 4}
    assert learned["laws_learned_from"] == 4 and "decisions_read" not in learned


def test_its_decision_is_the_one_the_whole_ledger_gives():
    for mean_degree in (0.0, 4.0):
        found = []
        for whole in (False, True):
            world = World(range(1, 9))
            _first_group_at_256(world)
            if whole:
                for number in range(1, 5):
                    world.decide(number, 1024, action="stop", rule=GATE)
            store = Store(world, STUDY_171, 5, mean_degree)
            decide_pass(store, "c", STUDY_171)
            assert store.pending == [] and len(store.decisions) == 1
            row = store.decisions[0]
            assert ("determined" in row["inputs"]["learned"]) is not whole
            found.append({key: row.get(key) for key in ("action", "rule", "next_n", "facts", "reason")})
        assert found[0] == found[1], (mean_degree, found)


def test_a_gate_that_could_still_confirm_makes_it_wait():
    world = World(range(1, 9))
    for number in (1, 2, 4):
        world.decide(number, 256, rule="salted", salted=(GATE,))
    for confirm_after, decides in ((4, False), (5, True)):
        policy = replace(STUDY_171, confirm_after=confirm_after)
        got = learned_for(Store(world, policy, 5, 4.0), world.points(policy), policy, _law(5), 256)
        assert (got[0] is not None) is decides, (confirm_after, "three let through and law 3 not decided: four")
    store = Store(world, replace(STUDY_171, confirm_after=4), 5, 4.0)
    decide_pass(store, "c", store.policy)
    assert store.pending == [(_law(5), ("learning",))] and store.decisions == []


def test_a_held_law_is_not_settled_at_its_size_and_a_gate_the_design_fixes_counts_nothing():
    world = World(range(1, 9))
    _first_group_at_256(world)
    world.decide(3, 256, action="hold", rule="deep_lane_full", salted=(GATE,), held=True)
    found = world.points(STUDY_171).determined(1, 256, STUDY_171, world.rows_of)
    assert found["undecided"] == 1 and found["let_through_most"] == 4
    fixed = replace(STUDY_171, gate_shares=STUDY_171.gate_shares + ((GATE, 1.0),))
    assert world.points(fixed).determined(1, 256, fixed, world.rows_of)["let_through_most"] == 0


def test_signatures_that_could_still_be_seen_make_a_law_wait_where_known_result_acts():
    acting = replace(STUDY_171, gate_shares=(), known_result_after=4)
    for signatures, decides in ((("ring",) * 4, False), (("ring", "ring", "dust", "dense"), True)):
        world = World(range(1, 9))
        for number, signature in zip(range(1, 5), signatures, strict=True):
            world.decide(number, 256, signature=signature)
        got = world.points(acting).determined(1, 256, acting, world.rows_of)
        assert (got is not None) is decides, signatures
    world = World(range(1, 9))
    for number in range(1, 5):
        world.decide(number, 256, signature="ring")
    assert world.points(STUDY_171).determined(1, 256, STUDY_171, world.rows_of) is not None, (
        "a known_result that only records holds no law back for its signatures")


def test_a_known_result_that_only_records_learns_no_signatures():
    ledger = LT.ledger_from_rows([
        {"campaign_id": "c", "candidate_id": _law(1), "decision_id": "1", "at_n": 256, "action": "run_next",
         "rule": "base_block", "salted": [], "signature": "ring"},
        {"campaign_id": "c", "candidate_id": _law(1), "decision_id": "2", "at_n": 1024, "action": "run_next",
         "rule": "base_block", "salted": [], "signature": "ring"}])
    acting = replace(STUDY_171, gate_shares=(), known_result_after=1)
    assert LT.learned_policy(acting, ledger, 256).known_results == ((256, "ring"),)
    assert LT.learned_policy(replace(acting, gate_shares=STUDY_171.gate_shares), ledger, 256).known_results == ()


def test_a_group_not_yet_drawn_in_every_batch_is_never_bounded():
    world = World(range(1, 9))
    _first_group_at_256(world)
    points = world.points(STUDY_171)
    points.drawing = {"other": {"top": 2, "finished": False}}
    assert points.determined(1, 256, STUDY_171, world.rows_of) is None


def test_laws_waiting_to_learn_are_not_called_stranded():
    from graph_scale_dynamics.operations.lifecycle_recovery import decision_backlog_alerts, stranded_work_alerts
    rows = [{"candidate_id": f"law{i}", "state": "BASE_BLOCK_RUNNING", "updated_utc": "x", "held": False,
             "held_total": 0} for i in range(48)]
    alert = stranded_work_alerts(rows, {}, lambda _since: 60.0, 48)[0]
    assert alert["stranded"] == 0 and alert["learning"] == 48 and alert["severity"] == "info"
    assert "48 waiting for earlier laws to be decided" in alert["headline"] and "STRANDED" not in alert["headline"]
    assert stranded_work_alerts(rows, {}, lambda _since: 60.0, 40)[0]["stranded"] == 8
    behind = decision_backlog_alerts({"awaiting": 48, "oldest_since_utc": "x"}, paused=False,
                                     age_seconds=lambda _since: 3600.0, learning=48)[0]
    assert behind["severity"] == "info" and "wait for earlier laws" in behind["headline"]
    assert decision_backlog_alerts({"awaiting": 48, "oldest_since_utc": "x"}, paused=False,
                                   age_seconds=lambda _since: 3600.0)[0]["severity"] == "warning"
