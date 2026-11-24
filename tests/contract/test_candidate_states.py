from __future__ import annotations

import ast
from pathlib import Path

from graph_scale_dynamics.domain.model import (
    ENGINE_RUNNING_STATES, RUNNING_CANDIDATE_STATES, TERMINAL_CANDIDATE_STATES, CandidateState)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "graph_scale_dynamics"
HOME = PACKAGE / "domain" / "model.py"
RUNNING_NAMES = {"BASE_BLOCK_RUNNING", "EXTENDING", "HELD", "DISCOVERY_ACTIVE", "PILOT_RUNNING"}


def test_the_two_sets_do_not_overlap_and_cover_the_engine():
    assert not (RUNNING_CANDIDATE_STATES & TERMINAL_CANDIDATE_STATES), \
        "a state cannot be both alive and finished"
    assert ENGINE_RUNNING_STATES <= RUNNING_CANDIDATE_STATES
    assert CandidateState.PARKED.value in TERMINAL_CANDIDATE_STATES, \
        "parking is terminal: the law is finished for now, with its measurements kept"
    for name in RUNNING_NAMES:
        assert name in RUNNING_CANDIDATE_STATES, f"{name} is a running state and is not in the set"


def test_no_module_types_a_list_of_running_states():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == HOME:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                continue
            names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            found = names & RUNNING_NAMES
            if len(found) >= 2:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} types {sorted(found)}")
    assert not offenders, (
        "these type their own list of running states instead of importing "
        "RUNNING_CANDIDATE_STATES:\n  " + "\n  ".join(offenders))


def test_the_deciders_own_query_filters_on_every_running_state():
    from graph_scale_dynamics.db import decision_store
    assert set(decision_store._LIVE_STATES) == set(RUNNING_CANDIDATE_STATES), (
        "the decider's filter and the set have drifted; a law in the difference waits for a "
        "decision that cannot come")


def test_a_hold_and_an_extension_are_states_the_store_will_write():
    from graph_scale_dynamics.decisions.decider import STATE_BY_ACTION
    from graph_scale_dynamics.decisions.engine import HOLD
    assert STATE_BY_ACTION[HOLD] == CandidateState.HELD.value
    assert CandidateState.HELD.value in RUNNING_CANDIDATE_STATES, \
        "a held law is alive; making it terminal would strand every hold"
