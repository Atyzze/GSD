from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_a_law_with_no_graph_has_no_code_rather_than_a_wrong_one():
    from graph_scale_dynamics.domain.model import ensemble_code

    assert ensemble_code({}) is None
    assert ensemble_code({64: 917}) == "G-917"
