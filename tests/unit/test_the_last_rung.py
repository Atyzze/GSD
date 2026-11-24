from __future__ import annotations

from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import DONE, STOP
from graph_scale_dynamics.decisions.every_chain import decide_every_chain
from graph_scale_dynamics.decisions.replay import replay
from tests.unit.test_depth_is_bought_by_promise import CUBIC_HOLDS, EVERY, LAW, reading, rung

LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]
EMPTY = [rung(n, None, md=0.0) for n in LADDER]
LATTICE = [rung(n) for n in LADDER]
HOLDS = reading({n: "holds" for n in LADDER[2:]}, fates=CUBIC_HOLDS)


def test_a_lattice_that_completes_the_ladder_is_the_law_s_end_over_the_empty_chain_s_verdict():
    decision = decide_every_chain(LAW, {"empty": EMPTY, "cubic": LATTICE}, EVERY, starts_reading=HOLDS)
    assert (decision.action, decision.rule, decision.at_n) == (DONE, "ladder_complete", 1048576)
    assert decision.facts["earned_by"] == "cubic"
    assert decision.facts["shape_over_verdict"]["empty"]["rule"] == "empty"
    assert decision.facts["chains"]["empty"]["rule"] == "empty", "the empty chain's own verdict is kept"


def test_without_a_shape_the_chain_from_empty_s_verdict_stands_at_the_top_as_below_it():
    apart = reading({n: "remembers" for n in LADDER[2:]})
    decision = decide_every_chain(LAW, {"empty": EMPTY, "cubic": LATTICE}, EVERY, starts_reading=apart)
    assert (decision.action, decision.rule) == (STOP, "empty")


def test_a_decision_recorded_before_734_replays_as_it_was_made():
    inputs = decision_inputs(LAW, EMPTY, EVERY, chains={"cubic": LATTICE}, starts_reading=HOLDS)
    assert inputs["last_rung_completes"] is True
    assert (replay(inputs).action, replay(inputs).rule) == (DONE, "ladder_complete")
    before = {key: value for key, value in inputs.items() if key != "last_rung_completes"}
    assert (replay(before).action, replay(before).rule) == (STOP, "empty")
