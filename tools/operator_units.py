#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.dsl.dsl import OPERATORS  # noqa: E402
from graph_scale_dynamics.engine import engine as eng  # noqa: E402

OUT = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "operator_units.json"
VERSION = "operator-units-1"
N, EDGES, ANCHOR_K = 4096, 8192, 4
MOVES = 100000
MIX = {"global_add": 0.5, "local_add": 0.25, "delete": 0.25}
GRAPH_SEED, MOVE_SEED = 4096, 631
SIGNIFICANT = 6


def reference_graph() -> eng.GraphState:
    rng = random.Random(GRAPH_SEED)
    state = eng.GraphState(N)
    while len(state.edges) < EDGES:
        u, v = rng.randrange(N), rng.randrange(N)
        if u == v or (min(u, v), max(u, v)) in state.edges:
            continue
        state.apply(u, v, True, state.op_deltas(u, v, True))
    return state


def _move(state: eng.GraphState, rng: random.Random) -> tuple[int, int, bool]:
    u = rng.random()
    if u < MIX["global_add"]:
        a, b = state.sample_non_edge(rng)
        return a, b, True
    if u < MIX["global_add"] + MIX["local_add"]:
        while True:
            w = rng.randrange(N)
            neighbours = sorted(state.adj[w])
            if len(neighbours) < 2:
                continue
            a, b = rng.sample(neighbours, 2)
            if b not in state.adj[a]:
                return a, b, True
    a, b = state.edge_list[rng.randrange(len(state.edge_list))]
    return a, b, False


def _node_change(op: str, du: int, dv: int, adding: bool) -> float:
    f = eng._NODE_FUNCTIONALS[op]
    sign = 1 if adding else -1
    return sign * (f(du + 1, ANCHOR_K) - f(du, ANCHOR_K) + f(dv + 1, ANCHOR_K) - f(dv, ANCHOR_K))


def measure(moves: int = MOVES) -> dict:
    state = reference_graph()
    rng = random.Random(MOVE_SEED)
    squares = {op: 0.0 for op in OPERATORS}
    zero = {op: 0 for op in OPERATORS}
    for _ in range(moves):
        a, b, adding = _move(state, rng)
        deltas = state.op_deltas(a, b, adding)
        du = state.degree(a) - (0 if adding else 1)
        dv = state.degree(b) - (0 if adding else 1)
        for op in OPERATORS:
            change = _node_change(op, du, dv, adding) if op in eng.NODE_OPS else float(deltas[op])
            squares[op] += change * change
            zero[op] += change == 0
    units = {op: float(f"{math.sqrt(squares[op] / moves):.{SIGNIFICANT}g}") for op in OPERATORS}
    return {
        "version": VERSION,
        "made_by": "tools/operator_units.py",
        "reading": ("each operator's root-mean-square change of its own value a move on the reference graph; a grid "
                    "with units natural divides a drawn magnitude by it, so a coefficient of 1 is one unit of energy "
                    "on a typical move of that operator"),
        "reference": {"graph": "uniform random edges", "n": N, "edges": EDGES, "mean_degree": 2 * EDGES / N,
                      "graph_seed": GRAPH_SEED, "anchor_k": ANCHOR_K, "moves": moves, "move_seed": MOVE_SEED,
                      "move_mix": dict(MIX),
                      "local_add": "a uniform node with two neighbours not joined, and the edge between them"},
        "units": units,
        "share_of_moves_unchanged": {op: round(zero[op] / moves, 4) for op in OPERATORS},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/operator_units.py: see docs/TOOLS.md")
    parser.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(ROOT)}")
    args = parser.parse_args(argv)
    table = measure()
    text = json.dumps(table, indent=2, sort_keys=True) + "\n"
    if args.write:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
