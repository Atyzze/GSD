from __future__ import annotations

import ast
import re
from pathlib import Path

from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES
from graph_scale_dynamics.services.proposer import main as proposer

ROOT = Path(__file__).resolve().parents[2]


def _laws(n, state, action=None, next_n=None):
    return [{"state": state, "action": action, "next_n": next_n} for _ in range(n)]


def test_the_proposer_uses_the_one_terminal_set():
    assert proposer.TERMINAL is TERMINAL_CANDIDATE_STATES
    assert {"STOPPED", "DONE"} <= proposer.TERMINAL


def test_campaign_1_as_it_stood_is_open_to_new_laws():
    live = (_laws(20, "BASE_BLOCK_RUNNING", "run_next", 1048576) + _laws(6, "BASE_BLOCK_RUNNING", "run_next", 262144)
            + _laws(2, "BASE_BLOCK_RUNNING", "hold"))
    window = proposer.admission(live, pool_min=32, max_active=48, top_base_n=4096)
    assert window["open"] and window["need"] == 32, window
    assert window["counts"] == {"proposed": 0, "base_block": 0, "held": 2, "above_base_block": 26, "finishing": 0}


def test_only_laws_in_their_base_block_take_places():
    window = proposer.admission(_laws(80, "BASE_BLOCK_RUNNING", "run_next", 4096), pool_min=32, max_active=48,
                                top_base_n=4096)
    assert not window["open"] and "base block" in window["reason"]
    undecided = proposer.admission(_laws(79, "VALIDATING"), pool_min=32, max_active=48, top_base_n=4096)
    assert undecided["open"] and undecided["counts"]["base_block"] == 79
    held = proposer.admission(_laws(500, "BASE_BLOCK_RUNNING", "hold"), pool_min=32, max_active=48, top_base_n=4096)
    assert held["open"], "held laws wait for spare capacity; they do not stop the search"


def test_a_full_pool_of_proposed_laws_closes_it():
    window = proposer.admission(_laws(32, "PROPOSED"), pool_min=32, max_active=48, top_base_n=4096)
    assert not window["open"] and window["need"] == 0 and "proposed" in window["reason"]


def test_a_decided_stop_or_finish_is_on_its_way_out():
    assert proposer.admission_slot("BASE_BLOCK_RUNNING", "stop", None, 4096) == "finishing"
    assert proposer.admission_slot("BASE_BLOCK_RUNNING", "done", None, 4096) == "finishing"
    assert proposer.admission_slot("BASE_BLOCK_RUNNING", "run_next", 16384, 4096) == "above_base_block"
    assert proposer.admission_slot("BASE_BLOCK_RUNNING", "run_next", 4096, 4096) == "base_block"


def test_no_module_keeps_its_own_list_of_terminal_states():
    terminal = set(TERMINAL_CANDIDATE_STATES)
    offenders = []
    for path in sorted((ROOT / "graph_scale_dynamics").rglob("*.py")) + [ROOT / "main.py"]:
        if path.name == "model.py" and path.parent.name == "domain":
            continue
        text = path.read_text()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len(names & terminal) >= 3:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        for match in re.finditer(r"state\s+(?:NOT\s+)?IN\s*\(([^)]*)\)", text, re.I):
            if len(set(re.findall(r"'([A-Z_]+)'", match.group(1))) & terminal) >= 3:
                offenders.append(f"{path.relative_to(ROOT)}:{text[:match.start()].count(chr(10)) + 1} (SQL)")
    assert not offenders, offenders
