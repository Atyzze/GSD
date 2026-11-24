from __future__ import annotations

from pathlib import Path

import graph_scale_dynamics.decisions.evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
def test_the_evidence_module_decides_nothing():
    import ast
    tree = ast.parse((ROOT / "graph_scale_dynamics/decisions/evidence.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    forbidden = ("graph_scale_dynamics.decisions.engine", "graph_scale_dynamics.decisions.decider",
                 "graph_scale_dynamics.db")
    assert imported and not {name for name in imported if name.startswith(forbidden)}, sorted(imported)


def test_a_landed_rungs_entry_does_not_change_when_its_block_completes():
    import json
    import random
    from graph_scale_dynamics.scheduling.base_block import base_sizes
    root = Path(__file__).resolve().parents[2]
    spec = json.loads((root / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    rng = random.Random(5)
    node = lambda lo, hi: {"mean": rng.uniform(lo, hi), "se": rng.uniform(0, 0.2)}
    summaries, states = {}, {}
    for n in base_sizes(spec):
        summaries[n] = {"connected_fraction": node(0.5, 1), "mean_degree": node(1, 5), "seeds": 3,
                        "d_s": node(1, 3), "d_s_valid_fraction": 1.0, "probe_refusals": {}}
        states[n] = {"history": [{"health": {"activity": {}, "equilibration": {"split": {"z": 1.0}}}}],
                     "classification": "EQUILIBRATED_ACTIVE", "failures": [], "current_multiplier": 8}
    whole = evidence._build_four_rung_phenotype(spec, summaries, states)
    for n in base_sizes(spec):
        assert evidence._rung_cell(spec, n, summaries[n], states[n]) == whole["per_n"][str(n)]
