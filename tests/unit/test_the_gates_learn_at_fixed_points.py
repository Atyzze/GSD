from __future__ import annotations

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.decider import decide_pass, learned_for
from graph_scale_dynamics.decisions.engine import Policy

POLICY = Policy(let_through_rule=G.LET_THROUGH_RULE, let_through_from=256, confirm_after=2, learn_in_batches_of=2,
                known_result_after=0)
GATE = "empty"


def _law(number: int) -> str:
    return f"law{number:02d}".ljust(64, "0")


def _let_through_then(number: int, clean: bool) -> list:
    law = _law(number)
    return [{"campaign_id": "c", "candidate_id": law, "decision_id": f"{number:04d}-1", "at_n": 256,
             "action": "run_next", "rule": "base_block", "salted": [GATE], "signature": None},
            {"campaign_id": "c", "candidate_id": law, "decision_id": f"{number:04d}-2", "at_n": 1024,
             "action": "stop" if clean else "run_next", "rule": GATE if clean else "base_block", "salted": [],
             "signature": None}]


class World:
    def __init__(self, laws: dict):
        self.laws = laws
        self.decided: dict = {}
        self.read = 0

    def finish(self, number: int, clean: bool) -> None:
        self.decided[number] = _let_through_then(number, clean)

    def rows_of(self, keys: list) -> list:
        self.read += 1
        numbers = {_law(number): number for number in self.laws}
        return [row for _c, law in keys for row in self.decided.get(numbers[law], [])]

    def learning_laws(self) -> list:
        return [{"campaign_id": "c", "candidate_id": _law(number), "number": number, "campaign_order": 0,
                 "ended": False, "verdict_past": 1024 if number in self.decided else None}
                for number in self.laws]

    def points(self, points=None):
        return (points or LT.FixedPoints()).refresh(self.learning_laws(), POLICY)


def test_a_law_waits_until_every_law_numbered_before_its_batch_is_past_its_size():
    world = World(range(1, 7))
    for number in (1, 2, 4):
        world.finish(number, clean=True)
    points = world.points()
    assert points.ledger(LT.batch_of(5, POLICY), 256, world.rows_of) is None, "law 3 is not past 256 yet"
    assert points.ledger(LT.batch_of(2, POLICY), 256, world.rows_of).rows == 0, "the first batch learns from none"
    world.finish(3, clean=True)
    ledger = world.points(points).ledger(LT.batch_of(5, POLICY), 256, world.rows_of)
    assert ledger is not None and ledger.rows == 8, "laws 1 to 4, each its two decisions"
    assert ledger.counters[(GATE, 256)].clean_since_last_miss == 4


def test_what_a_law_learns_is_the_same_whatever_order_the_laws_finished_in():
    found = []
    for order in ((1, 2, 3, 4, 6, 5), (6, 4, 3, 2, 1, 5), (2, 6, 1, 4, 3, 5)):
        world = World(range(1, 9))
        points = world.points()
        for number in order:
            world.finish(number, clean=number != 3)
            points = world.points(points)
            points.ledger(LT.batch_of(5, POLICY), 256, world.rows_of)
        ledger = points.ledger(LT.batch_of(5, POLICY), 256, world.rows_of)
        found.append((ledger.rows, LT.learned_policy(POLICY, ledger, 256).salt_shares,
                      ledger.counters[(GATE, 256)].as_dict()))
    assert found[0] == found[1] == found[2], found
    assert found[0][2]["missed"] == 1 and found[0][2]["clean_since_last_miss"] == 1, (
        "law 3's miss is counted in the laws' own order; laws 5 and 6 of the same batch and 7 and 8 after it are not")


def test_a_gate_confirms_only_when_a_whole_batch_has_been_decided():
    world = World(range(1, 7))
    for number in (1, 2, 3):
        world.finish(number, clean=True)
    points = world.points()
    assert dict(((g, n), s) for g, n, s in LT.learned_policy(
        POLICY, points.ledger(1, 256, world.rows_of), 256).salt_shares)[(GATE, 256)] == G.CONFIRMED_SHARE, (
        "two clean of the first batch confirm the gate for the second")
    assert points.ledger(2, 256, world.rows_of) is None, "law 4 is not past 256: the third batch waits"


def test_a_law_decided_again_after_later_batches_learns_what_it_learned_the_first_time():
    world = World(range(1, 9))
    for number in range(1, 7):
        world.finish(number, clean=number % 2 == 0)
    points = world.points()
    first = points.ledger(1, 256, world.rows_of).counters[(GATE, 256)].as_dict()
    points.ledger(3, 256, world.rows_of)
    again = points.ledger(1, 256, world.rows_of)
    assert again.counters[(GATE, 256)].as_dict() == first
    assert world.points().ledger(1, 256, world.rows_of).counters[(GATE, 256)].as_dict() == first


class LearningStore:
    def __init__(self, world: World, awaiting: list):
        self.world, self.awaiting = world, awaiting
        self.pending: list = []
        self.decisions: list = []

    def fixed_points(self, campaign_id):
        return self.world.points()

    def learning_rows(self, keys):
        return self.world.rows_of(keys)

    def laws_awaiting_decision(self, campaign_id):
        return [_law(number) for number in self.awaiting]

    def law_evidence(self, campaign_id, law):
        return {"entries": {256: {"mean_degree": 4.0, "connected_fraction": 1.0, "measurement_seed_count": 3,
                                  "d_s": None, "d_s_bucket": None, "probes": {}}}}

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


def test_the_decider_holds_a_law_until_its_batch_can_learn_and_records_what_it_learned_from():
    world = World(range(1, 7))
    for number in (1, 2, 4):
        world.finish(number, clean=True)
    store = LearningStore(world, [5])
    tally = decide_pass(store, "c", POLICY)
    assert store.pending == [(_law(5), ("learning",))] and tally[("pending", "learning")] == 1
    assert store.decisions == []
    world.finish(3, clean=True)
    decide_pass(store, "c", POLICY)
    assert len(store.decisions) == 1
    learned = store.decisions[0]["inputs"]["learned"]
    assert learned["contract"] == LT.LEARNING_CONTRACT
    assert (learned["number"], learned["batch"], learned["at_n"], learned["laws_learned_from"]) == (5, 2, 256, 4)
    policy, again = learned_for(store, world.points(), POLICY, _law(5), 256)
    assert again == learned and policy.salt_shares == ((GATE, 256, G.CONFIRMED_SHARE),)
