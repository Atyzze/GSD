from __future__ import annotations

import pytest

from graph_scale_dynamics.decisions import nothing_read as NR
from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import Policy, Rung, decide
from graph_scale_dynamics.decisions.replay import policy_from_inputs, replay_matches
from graph_scale_dynamics.observability import law_score

LAW = "5" * 64
TODAY = Policy(every_chain=True, nothing_read_gate=True)


def _rungs(valid_at=(), connected=1.0) -> list:
    out = []
    for index, n in enumerate((64, 256, 1024, 4096)):
        valid = {"d_V": 1.0, "d_B": 0.67} if n in valid_at else {}
        out.append(Rung(n=n, mean_degree=3.0 + 0.2 * index, connected_fraction=connected if n == 4096 else 1.0, probes={},
                        seeds_measured=3, valid_fractions=valid))
    return out


def test_the_gate_reads_a_piece_as_the_score_does():
    assert NR.PIECE_AT_LEAST == law_score.PIECE_AT_LEAST and NR.PIECE_FROM_N == law_score.RELIED_FROM


def test_a_probe_the_analysis_refused_but_the_score_reads_keeps_the_law_going():
    today = decide(LAW, _rungs(valid_at=(4096,)), TODAY)
    assert today.rule != NR.GATE and "nothing_read" not in (today.facts or {})


@pytest.mark.parametrize("valid_at,connected", [((1024,), 1.0), ((4096,), 0.5), ((), 1.0)])
def test_what_the_score_does_not_read_is_still_nothing_read(valid_at, connected):
    decision = decide(LAW, _rungs(valid_at=valid_at, connected=connected), TODAY)
    assert decision.rule == NR.GATE
    assert decision.facts["nothing_read"]["contract"] == NR.CONTRACT_PIECES
    assert "nor on a piece of 4,096 nodes or more" in decision.reason
