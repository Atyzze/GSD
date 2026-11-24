from __future__ import annotations

import os
import time

import numpy as np

CONTRACT = "gsd-curvature-probe-1"
WORK_BUDGET = 10_000_000_000
PYTHON_WORK_BUDGET = 20_000_000


def _engine():
    if os.environ.get("GSD_ENGINE", "rust").lower() == "python":
        return None
    try:
        import gsd_engine_rs
    except ImportError:
        return None
    return gsd_engine_rs if hasattr(gsd_engine_rs, "curvature_per_edge") else None


def scaled_curvature_python(t: int, s: int, p: int, da: int, db: int) -> int:
    from graph_scale_dynamics.engine.engine import scaled_curvature
    return int(scaled_curvature(int(t), int(s), int(p), int(da), int(db)))


def cycle_counts_python(adj: list[set], u: int, v: int) -> tuple[int, int, int]:
    nv = adj[v] - {u}
    t = s = p = 0
    for x in adj[u]:
        if x == v:
            continue
        if x in nv:
            t += 1
        for z in adj[x]:
            if z in nv:
                s += 1
            if z == u or z == v:
                continue
            for y in adj[z]:
                if y != x and y in nv:
                    p += 1
    return t, s, p


def curvature_per_edge_python(n: int, edges) -> np.ndarray:
    adj = [set() for _ in range(int(n))]
    for u, v in edges:
        u, v = int(u), int(v)
        if u == v or v in adj[u]:
            raise ValueError(f"edge ({u}, {v}) is a loop or repeated")
        adj[u].add(v)
        adj[v].add(u)
    out = np.empty(len(edges), dtype=np.int64)
    for i, (u, v) in enumerate(edges):
        t, s, p = cycle_counts_python(adj, int(u), int(v))
        out[i] = scaled_curvature_python(t, s, p, len(adj[int(u)]), len(adj[int(v)]))
    return out


def curvature_per_edge(n: int, edges, *, engine=None, incremental: bool = False) -> tuple[np.ndarray, str]:
    engine = _engine() if engine is None else engine
    pairs = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    if engine is not None and engine is not False:
        if len(pairs) and (pairs.min() < 0 or pairs.max() >= int(n)):
            raise ValueError(f"an edge is outside 0..{int(n)}")
        raw = engine.curvature_per_edge(int(n), pairs.astype(np.uint32).tobytes(), incremental=incremental)
        return np.frombuffer(raw, dtype=np.int64).copy(), "rust"
    return curvature_per_edge_python(n, pairs.tolist()), "python"


def _giant(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from scipy import sparse
    from scipy.sparse import csgraph
    if not len(a):
        return np.zeros(0, dtype=bool)
    graph = sparse.coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)).tocsr()
    _, labels = csgraph.connected_components(graph, directed=False)
    sizes = np.bincount(labels)
    return labels[a] == int(np.argmax(sizes))


def walk_cost(n: int, a: np.ndarray, b: np.ndarray) -> tuple[int, np.ndarray]:
    from scipy import sparse
    degree = np.bincount(np.concatenate([a, b]), minlength=n).astype(np.float64)
    adjacency = sparse.coo_matrix((np.ones(2 * len(a)), (np.concatenate([a, b]), np.concatenate([b, a]))),
                                  shape=(n, n)).tocsr()
    second = adjacency @ (adjacency @ degree)
    flip = second[b] < second[a]
    return int(np.minimum(second[a], second[b]).sum()), flip


def _summary(kappa: np.ndarray, weight: np.ndarray) -> dict:
    q1, median, q3 = (float(x) for x in np.quantile(kappa, [0.25, 0.5, 0.75]))
    edges = len(kappa)
    return {"mean": round(float(kappa.mean()), 6), "median": round(median, 6), "q1": round(q1, 6), "q3": round(q3, 6),
            "positive_share": round(float((kappa > 0).sum()) / edges, 6),
            "zero_share": round(float((kappa == 0).sum()) / edges, 6),
            "negative_share": round(float((kappa < 0).sum()) / edges, 6),
            "degree_weighted_mean": round(float((weight * kappa).sum() / weight.sum()), 6)}


def read(n: int, edges, *, engine=None, budget: int | None = None) -> dict:
    started = time.monotonic()
    out = {"contract": CONTRACT, "measured": False}
    try:
        n = int(n)
        pairs = np.asarray(edges if edges is not None and len(edges) else [], dtype=np.int64).reshape(-1, 2)
        if not len(pairs):
            return dict(out, reason="no edges", seconds=round(time.monotonic() - started, 4))
        keep = _giant(n, pairs[:, 0], pairs[:, 1])
        a, b = pairs[keep, 0], pairs[keep, 1]
        cost, flip = walk_cost(n, a, b)
        chosen = _engine() if engine is None else engine
        limit = budget if budget is not None else (WORK_BUDGET if chosen not in (None, False) else PYTHON_WORK_BUDGET)
        out.update({"component_edges": int(len(a)), "component_nodes": int(len(np.unique(np.concatenate([a, b])))),
                    "walk_steps": cost})
        if cost > limit:
            return dict(out, reason=f"not measured: its pentagon walk is {cost:,} steps, over the {limit:,} one "
                                    "graph is allowed", seconds=round(time.monotonic() - started, 4))
        del pairs, keep
        ordered = np.where(flip[:, None], np.stack([b, a], axis=1), np.stack([a, b], axis=1))
        scaled, used = curvature_per_edge(n, ordered, engine=chosen if chosen is not None else False)
        del ordered, flip
        degree = np.bincount(np.concatenate([a, b]), minlength=n)
        da, db = degree[a].astype(np.float64), degree[b].astype(np.float64)
        kappa = scaled.astype(np.float64) / (da * db)
        out.update(_summary(kappa, da + db), measured=True, engine=used)
    except Exception as exc:  # noqa: BLE001
        out.update(reason=f"failed: {type(exc).__name__}: {exc}")
    out["seconds"] = round(time.monotonic() - started, 4)
    return out
