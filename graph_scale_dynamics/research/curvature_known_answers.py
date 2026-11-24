from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

from graph_scale_dynamics.measurements import curvature_probe
from graph_scale_dynamics.research import look_alikes
from graph_scale_dynamics.research import planted_geometries as planted

CURVATURE_KNOWN_ANSWERS_CONTRACT = "gsd-curvature-known-answers-1"
AGREES_WITHIN = 1e-6


def complete(n: int):
    return n, [(a, b) for a in range(n) for b in range(a + 1, n)]


FAMILIES = {
    "square_torus": lambda seed: look_alikes.torus(400, 2),
    "cubic_torus": lambda seed: look_alikes.torus(729, 3),
    "tesseract_torus": lambda seed: look_alikes.torus(1296, 4),
    "ring": lambda seed: planted.ring(200),
    "honeycomb_torus": lambda seed: look_alikes._honeycomb(1024),
    "complete_6": lambda seed: complete(6),
    "triangular_torus": lambda seed: look_alikes.triangular_torus(400),
    "random_geometric_2d": lambda seed: planted.random_geometric(1000, 2, 8.0, seed),
    "random_regular_3": lambda seed: planted.random_regular(2000, 3, seed),
    "erdos_renyi_4": lambda seed: planted.erdos_renyi(1000, 4.0, seed),
}


def adjacency(n: int, edges) -> list[list[int]]:
    adj: list[set] = [set() for _ in range(n)]
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    return [sorted(row) for row in adj]


def distances_within(adj, source: int, radius: int) -> dict[int, int]:
    seen = {source: 0}
    frontier = [source]
    for step in range(1, radius + 1):
        nxt = []
        for node in frontier:
            for other in adj[node]:
                if other not in seen:
                    seen[other] = step
                    nxt.append(other)
        frontier = nxt
    return seen


def ollivier(adj, u: int, v: int) -> float:
    from_u, from_v = adj[u], adj[v]
    cost = np.array([[distances_within(adj, a, 3).get(b, 3) for b in from_v] for a in from_u], dtype=float)
    rows, cols = cost.shape
    equal = np.zeros((rows + cols, rows * cols))
    for i in range(rows):
        equal[i, i * cols:(i + 1) * cols] = 1.0
    for j in range(cols):
        equal[rows + j, j::cols] = 1.0
    mass = np.concatenate([np.full(rows, 1.0 / rows), np.full(cols, 1.0 / cols)])
    solved = linprog(cost.ravel(), A_eq=equal[:-1], b_eq=mass[:-1], bounds=(0, None), method="highs")
    if not solved.success:
        raise RuntimeError(f"transport on edge ({u}, {v}) did not solve: {solved.message}")
    return 1.0 - float(solved.fun)


def probe_curvature(n: int, edges, adj) -> np.ndarray:
    scaled, _ = curvature_probe.curvature_per_edge(n, edges)
    degrees = np.array([len(adj[a]) * len(adj[b]) for a, b in edges], dtype=float)
    return scaled / degrees


def measure_family(family: str, seed: int, edges_at_most: int) -> dict:
    n, edges = FAMILIES[family](seed)
    edges = [(int(a), int(b)) for a, b in edges]
    adj = adjacency(n, edges)
    probe = probe_curvature(n, edges, adj)
    rng = np.random.default_rng(seed)
    picked = sorted(rng.choice(len(edges), size=min(edges_at_most, len(edges)), replace=False).tolist())
    exact = np.array([ollivier(adj, *edges[i]) for i in picked])
    read = probe[picked]
    apart = read - exact
    return {"family": family, "seed": seed, "n": n, "edges": len(edges), "edges_read": len(picked),
            "mean_degree": round(2.0 * len(edges) / n, 4),
            "exact_mean": round(float(exact.mean()), 6), "probe_mean": round(float(read.mean()), 6),
            "apart_worst": round(float(np.abs(apart).max()), 6), "apart_mean": round(float(apart.mean()), 6),
            "apart_least": round(float(apart.min()), 6), "apart_most": round(float(apart.max()), 6),
            "edges_agreeing": int((np.abs(apart) <= AGREES_WITHIN).sum())}


def measure(criterion: dict) -> list[dict]:
    return [measure_family(case["family"], criterion["seed"], criterion["edges_at_most"])
            for case in criterion["cases"]]


def judge(criterion: dict, rows: list[dict]) -> dict:
    by_family = {row["family"]: row for row in rows}
    cases = []
    for case in criterion["cases"]:
        row = by_family[case["family"]]
        exact = row["edges_agreeing"] == row["edges_read"]
        expected = case.get("expected")
        right = None if expected is None else (exact if expected == "exact" else not exact)
        if expected == "not_exact" and case.get("apart") is not None:
            right = right and abs(row["apart_least"] - case["apart"]) <= AGREES_WITHIN and abs(
                row["apart_most"] - case["apart"]) <= AGREES_WITHIN
        cases.append({**row, "expected": expected, "exact": exact, "right": right})
    judged = [case for case in cases if case["right"] is not None]
    return {"contract": CURVATURE_KNOWN_ANSWERS_CONTRACT, "agrees_within": AGREES_WITHIN, "cases": cases,
            "predictions_right": sum(bool(case["right"]) for case in judged), "predictions": len(judged),
            "passes": bool(judged) and all(case["right"] for case in judged),
            "exact_on": [case["family"] for case in cases if case["exact"]],
            "not_exact_on": [case["family"] for case in cases if not case["exact"]]}


def render(judged: dict) -> str:
    lines = ["# The curvature probe against Ollivier's curvature, edge by edge", "",
             f"{judged['contract']}: the probe is Kelly, Trugenberger and Biancalana's formula from the triangles, "
             "squares and pentagons on an edge (`engine.scaled_curvature` over the two degrees); the known answer is "
             "Ollivier's curvature of the same edge, 1 less the cost of moving one end's neighbours onto the other's, "
             "solved exactly. A family is exact when every edge read agrees.", "",
             f"Predictions right: **{judged['predictions_right']} of {judged['predictions']}**.", "",
             "| family | nodes | mean degree | edges read | agreeing | Ollivier, mean | the probe, mean | "
             "the probe less Ollivier (least, most) | expected | exact |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for case in judged["cases"]:
        lines.append(f"| `{case['family']}` | {case['n']:,} | {case['mean_degree']:g} | {case['edges_read']} | "
                     f"{case['edges_agreeing']} | {case['exact_mean']:.4f} | {case['probe_mean']:.4f} | "
                     f"{case['apart_least']:+.4f}, {case['apart_most']:+.4f} | {case['expected'] or 'not committed'} | "
                     f"{'yes' if case['exact'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)
