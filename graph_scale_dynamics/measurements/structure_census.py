from __future__ import annotations

import time

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.sparse.linalg import ArpackError, ArpackNoConvergence, LinearOperator, eigsh

CENSUS_CONTRACT = "structure-census-3"
CLIQUE_COUNT_BUDGET = 2_000_000
LARGEST_CLIQUE_BUDGET = 2_000_000
CLIQUE_MAX_N = 262144
SQUARE_MAX_N = 262144
SQUARE_WORK_BUDGET = 200_000_000
SQUARE_CHUNK = 4_000_000
GAP_MAX_N = 65536
DIAMETER_SWEEPS = 4
GAP_LANCZOS_ITERATIONS = 60
GAP_LANCZOS_VECTORS = 96
GAP_TOLERANCE = 1e-7
GAP_SHIFT_INVERT_MIN_DIAMETER_LOGS = 4.0
GAP_SHIFT_INVERT_MIN_HALF_RADIUS_LOGS = 2.0
GAP_BULK_SOURCES = 3
GAP_CORE_MIN_FRACTION = 0.5
GAP_SHIFT = 1e-12

LIMITS = {"clique_max_n": CLIQUE_MAX_N, "square_max_n": SQUARE_MAX_N, "gap_max_n": GAP_MAX_N,
          "diameter_sweeps": DIAMETER_SWEEPS, "clique_count_budget": CLIQUE_COUNT_BUDGET,
          "largest_clique_budget": LARGEST_CLIQUE_BUDGET, "square_work_budget": SQUARE_WORK_BUDGET}


def _adjacency(n: int, edges) -> sparse.csr_matrix:
    pairs = np.asarray(list(edges) if not isinstance(edges, np.ndarray) else edges, dtype=np.int64)
    if pairs.size == 0:
        return sparse.csr_matrix((n, n), dtype=np.int8)
    pairs = pairs.reshape(-1, 2)
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    data = np.ones(len(rows), dtype=np.int8)
    return sparse.csr_matrix((data, (rows, cols)), shape=(n, n))


def _histogram(values) -> dict:
    counts = np.bincount(np.asarray(values, dtype=np.int64)) if len(values) else np.zeros(0, dtype=np.int64)
    return {str(k): int(c) for k, c in enumerate(counts) if c}


def _assortativity(adj: sparse.csr_matrix, degree: np.ndarray) -> float | None:
    coo = adj.tocoo()
    if coo.nnz < 2:
        return None
    x = degree[coo.row].astype(float)
    y = degree[coo.col].astype(float)
    if float(np.std(x)) == 0.0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _eccentricity_sweep(sub: sparse.csr_matrix) -> dict:
    size = sub.shape[0]
    if size <= 1:
        return {"lower_bound": 0, "upper_bound": 0, "sweeps": 0, "exact": True}
    source = 0
    eccentricities = []
    lower = 0
    for _ in range(DIAMETER_SWEEPS):
        dist = csgraph.shortest_path(sub, method="D", unweighted=True, directed=False, indices=source)
        ecc = int(np.max(dist))
        eccentricities.append(ecc)
        far = int(np.argmax(dist))
        if ecc <= lower and len(eccentricities) > 1:
            break
        lower = max(lower, ecc)
        source = far
    upper = min(size - 1, 2 * min(eccentricities))
    return {"lower_bound": int(lower), "upper_bound": int(upper), "sweeps": len(eccentricities),
            "exact": bool(lower == upper)}


def _spectral_gap(sub: sparse.csr_matrix, diameter_lower_bound: int = 0,
                  shift_invert_below_dimension: float | None = None,
                  half_volume_radius: float | None = None) -> dict:
    size = sub.shape[0]
    if size < 3:
        return {"value": None, "reason": "component under three nodes"}
    started = time.perf_counter()
    degree = np.asarray(sub.sum(axis=1), dtype=float).ravel()
    inv_sqrt = 1.0 / np.sqrt(degree)
    scaled = (sparse.diags(inv_sqrt) @ sub.astype(float) @ sparse.diags(inv_sqrt)).tocsr()
    top = np.sqrt(degree)
    top /= np.linalg.norm(top)

    def matvec(x):
        x = np.asarray(x).ravel()
        return scaled @ x - 2.0 * top * float(top @ x)

    operator = LinearOperator((size, size), matvec=matvec, dtype=float)
    start = np.random.default_rng(0).standard_normal(size)
    stretched = diameter_lower_bound > GAP_SHIFT_INVERT_MIN_DIAMETER_LOGS * np.log2(size) and (
        half_volume_radius is None or half_volume_radius > GAP_SHIFT_INVERT_MIN_HALF_RADIUS_LOGS * np.log2(size))
    if shift_invert_below_dimension is not None:
        stretched = diameter_lower_bound > 1 and (
            np.log(size) / np.log(diameter_lower_bound) < float(shift_invert_below_dimension))
    failures = []

    def lanczos():
        values = eigsh(operator, k=1, which="LA", tol=GAP_TOLERANCE, maxiter=GAP_LANCZOS_ITERATIONS,
                       ncv=min(size - 1, GAP_LANCZOS_VECTORS), v0=start, return_eigenvectors=False)
        return float(1.0 - values[0])

    def shift_invert():
        laplacian = (sparse.identity(size, format="csc") - scaled.tocsc()).tocsc()
        values = eigsh(laplacian, k=2, sigma=-GAP_SHIFT, which="LM", tol=0, v0=start,
                       return_eigenvectors=False)
        return float(np.max(values))

    for name, solve in ((("shift_invert", shift_invert), ("lanczos_deflated", lanczos)) if stretched
                        else (("lanczos_deflated", lanczos),)):
        try:
            return {"value": solve(), "reason": None, "method": name,
                    "seconds": round(time.perf_counter() - started, 3)}
        except (ArpackNoConvergence, ArpackError, RuntimeError, MemoryError) as exc:
            failures.append(f"{name}: {type(exc).__name__}")
    return {"value": None, "method": None, "seconds": round(time.perf_counter() - started, 3),
            "reason": "no solve converged (" + "; ".join(failures) + ")"
            + ("" if stretched else "; too well connected to factorise")}


def _two_core(sub: sparse.csr_matrix) -> np.ndarray:
    size = sub.shape[0]
    indptr, indices = sub.indptr, sub.indices
    degree = np.diff(indptr).astype(np.int64)
    alive = np.ones(size, dtype=bool)
    stack = np.flatnonzero(degree <= 1).tolist()
    alive[stack] = False
    while stack:
        v = stack.pop()
        for u in indices[indptr[v]:indptr[v + 1]].tolist():
            if alive[u]:
                degree[u] -= 1
                if degree[u] <= 1:
                    alive[u] = False
                    stack.append(u)
    return alive


def _half_volume_radius(sub: sparse.csr_matrix) -> float | None:
    size = sub.shape[0]
    if size < 3:
        return None
    sources = np.random.default_rng(0).choice(size, size=min(GAP_BULK_SOURCES, size), replace=False)
    dist = csgraph.shortest_path(sub, method="D", unweighted=True, directed=False, indices=sources)
    half = (size - 1) // 2
    return float(np.median([np.partition(row, half)[half] for row in np.atleast_2d(dist)]))


def _gap_on_the_core(sub: sparse.csr_matrix, shift_invert_below_dimension: float | None = None,
                     component_sweep: dict | None = None) -> dict:
    size = sub.shape[0]
    alive = _two_core(sub) if size >= 3 else np.zeros(size, dtype=bool)
    core_size = int(alive.sum())
    on_core = core_size >= 3 and core_size >= GAP_CORE_MIN_FRACTION * size
    measured = sub[alive][:, alive].tocsr() if on_core and core_size < size else sub
    sweep = component_sweep if measured is sub and component_sweep is not None else _eccentricity_sweep(measured)
    radius = _half_volume_radius(measured)
    gap = _spectral_gap(measured, sweep["lower_bound"], shift_invert_below_dimension, radius)
    gap.update({"on": "2-core" if on_core else "component", "size": int(measured.shape[0]),
                "core_fraction": (core_size / size) if size else None,
                "diameter_lower_bound": int(sweep["lower_bound"]), "half_volume_radius": radius})
    return gap


def _core_numbers(n: int, neighbours: list) -> tuple[np.ndarray, list]:
    degree = [len(a) for a in neighbours]
    max_degree = max(degree) if n else 0
    bins = [0] * (max_degree + 1)
    for d in degree:
        bins[d] += 1
    start = 0
    for d in range(max_degree + 1):
        count = bins[d]
        bins[d] = start
        start += count
    pos = [0] * n
    vert = [0] * n
    for v in range(n):
        pos[v] = bins[degree[v]]
        vert[pos[v]] = v
        bins[degree[v]] += 1
    for d in range(max_degree, 0, -1):
        bins[d] = bins[d - 1]
    if bins:
        bins[0] = 0
    for i in range(n):
        v = vert[i]
        for u in neighbours[v]:
            if degree[u] > degree[v]:
                du, pu = degree[u], pos[u]
                pw = bins[du]
                w = vert[pw]
                if u != w:
                    pos[u], vert[pu] = pw, w
                    pos[w], vert[pw] = pu, u
                bins[du] += 1
                degree[u] -= 1
    return np.asarray(degree, dtype=np.int64), vert


def _clique_census(n: int, neighbours: list, order: list, core: np.ndarray | None = None) -> dict:
    rank = np.empty(n, dtype=np.int64)
    rank[np.asarray(order, dtype=np.int64)] = np.arange(n)
    out = [frozenset(w for w in neighbours[v] if rank[w] > rank[v]) for v in range(n)]
    core_of = core if core is not None else np.zeros(n, dtype=np.int64)
    triangles = k4 = k5 = 0
    work = 0
    k4_done = k5_done = True
    largest = 1 if n else 0
    if any(neighbours):
        largest = 2
    calls = 0
    exact = True

    def grow(candidates, depth):
        nonlocal largest, calls, exact
        calls += 1
        if calls > LARGEST_CLIQUE_BUDGET:
            exact = False
            return
        if depth > largest:
            largest = depth
        if depth + len(candidates) <= largest:
            return
        for w in candidates:
            if not exact:
                return
            if core is not None and core_of[w] + 1 <= largest:
                continue
            grow(candidates & out[w], depth + 1)

    for u in range(n):
        ou = out[u]
        for v in ou:
            common = ou & out[v]
            triangles += len(common)
            if not k4_done:
                continue
            for w in common:
                work += 1
                if work > CLIQUE_COUNT_BUDGET:
                    k4_done = k5_done = False
                    break
                inner = common & out[w]
                k4 += len(inner)
                if k5_done:
                    for x in inner:
                        k5 += len(inner & out[x])
                    work += len(inner)
        if exact:
            grow(ou, 1)
    bound = int(core_of.max()) + 1 if core is not None and n else None
    if bound is not None and largest >= bound:
        exact = True
    return {"triangles": int(triangles), "k4": int(k4), "k5": int(k5), "largest_clique": int(largest),
            "k4_exact": k4_done, "k5_exact": k5_done, "largest_clique_exact": bool(exact),
            "largest_clique_bound": bound,
            "work": {"intersections": int(work), "search_calls": int(calls)}}


def _squares(adj: sparse.csr_matrix, degree: np.ndarray, budget: int | None = None) -> int | None:
    budget = SQUARE_WORK_BUDGET if budget is None else int(budget)
    n = adj.shape[0]
    if n == 0 or adj.nnz == 0:
        return 0
    degree = np.asarray(degree, dtype=np.int64)
    rank = np.empty(n, dtype=np.int64)
    rank[np.lexsort((np.arange(n), degree))] = np.arange(n)
    indptr = adj.indptr.astype(np.int64)
    indices = adj.indices.astype(np.int64)
    rows = np.repeat(np.arange(n, dtype=np.int64), np.diff(indptr))
    lower = rank[indices] < rank[rows]
    v_of, u_of = rows[lower], indices[lower]
    lengths = degree[u_of]
    if int(lengths.sum()) > budget:
        return None
    ends = np.cumsum(lengths)
    squares = 0
    start = 0
    while start < len(v_of):
        stop = int(np.searchsorted(ends, (ends[start - 1] if start else 0) + SQUARE_CHUNK, side="right"))
        stop = max(stop, start + 1)
        if stop < len(v_of):
            stop = int(np.searchsorted(v_of, v_of[stop - 1], side="right"))
        v, u, length = v_of[start:stop], u_of[start:stop], lengths[start:stop]
        offsets = np.repeat(indptr[u] - (np.cumsum(length) - length), length)
        w = indices[offsets + np.arange(int(length.sum()), dtype=np.int64)]
        vv = np.repeat(v, length)
        keep = rank[w] < rank[vv]
        if keep.any():
            _, counts = np.unique(vv[keep] * n + w[keep], return_counts=True)
            squares += int(np.sum(counts * (counts - 1) // 2))
        start = stop
    return int(squares)


def census(n: int, edges, *, gap_max_n: int | None = None,
           shift_invert_below_dimension: float | None = None, clique_max_n: int | None = None,
           square_max_n: int | None = None) -> dict:
    started = time.perf_counter()
    n = int(n)
    gap_max_n = GAP_MAX_N if gap_max_n is None else int(gap_max_n)
    clique_max_n = CLIQUE_MAX_N if clique_max_n is None else int(clique_max_n)
    square_max_n = SQUARE_MAX_N if square_max_n is None else int(square_max_n)
    adj = _adjacency(n, edges)
    degree = np.asarray(adj.sum(axis=1), dtype=np.int64).ravel()
    edge_count = int(degree.sum()) // 2
    count, labels = csgraph.connected_components(adj, directed=False)
    sizes = np.bincount(labels, minlength=count)
    giant = int(np.argmax(sizes)) if count else 0
    members = np.flatnonzero(labels == giant)
    sub = adj[members][:, members].tocsr()
    sub_edges = int(sub.nnz) // 2
    result = {
        "contract": CENSUS_CONTRACT, "limits": dict(LIMITS), "n": n, "edges": edge_count,
        "degree_histogram": _histogram(degree),
        "components": {"count": int(count), "size_histogram": _histogram(sizes)},
        "assortativity": _assortativity(adj, degree),
        "largest_component": {
            "size": int(len(members)), "edges": sub_edges,
            "cycle_rank": int(max(0, sub_edges - len(members) + (1 if len(members) else 0))),
            "diameter": _eccentricity_sweep(sub),
        },
    }
    giant = result["largest_component"]
    if n <= int(gap_max_n):
        try:
            giant["spectral_gap"] = _gap_on_the_core(sub, shift_invert_below_dimension, giant["diameter"])
        except Exception as exc:  # noqa: BLE001
            giant["spectral_gap"] = {"value": None, "reason": f"the gap failed: {type(exc).__name__}"}
    else:
        giant["spectral_gap"] = {"value": None, "reason": f"not computed above N={int(gap_max_n)}"}
    if n <= clique_max_n:
        try:
            neighbours = [adj.indices[adj.indptr[v]:adj.indptr[v + 1]].tolist() for v in range(n)]
            core, order = _core_numbers(n, neighbours)
            result["k_core"] = {"degeneracy": int(core.max()) if n else 0, "profile": _histogram(core)}
            result["cliques"] = _clique_census(n, neighbours, order, core)
        except Exception as exc:  # noqa: BLE001
            reason = f"the clique census failed: {type(exc).__name__}"
            result["k_core"] = {"degeneracy": None, "profile": None, "reason": reason}
            result["cliques"] = {"triangles": None, "k4": None, "k5": None, "largest_clique": None,
                                 "reason": reason}
    else:
        reason = f"not computed above N={clique_max_n}"
        result["k_core"] = {"degeneracy": None, "profile": None, "reason": reason}
        result["cliques"] = {"triangles": None, "k4": None, "k5": None, "largest_clique": None,
                             "reason": reason}
    if n > square_max_n:
        result["squares"] = None
        result["squares_reason"] = f"not computed above N={square_max_n}"
    else:
        try:
            result["squares"] = _squares(adj, degree)
            if result["squares"] is None:
                result["squares_reason"] = f"over the work budget of {SQUARE_WORK_BUDGET:,} wedges"
        except Exception as exc:  # noqa: BLE001
            result["squares"] = None
            result["squares_reason"] = f"the square count failed: {type(exc).__name__}"
    result["seconds"] = round(time.perf_counter() - started, 3)
    return result


def log_diameter_state(metrics: dict, census_from_empty: dict | None) -> dict:
    import math

    flag = metrics.get("log_diameter_flag")
    if flag is None:
        return {"flag": None, "basis": "not measured"}
    giant = (census_from_empty or {}).get("largest_component") or {}
    size = giant.get("size") or metrics.get("component")
    threshold = 1.6 * math.log2(max(4, int(size or 4)))
    if flag:
        return {"flag": True, "basis": "certified upper bound", "threshold": threshold}
    lowers = [value for value in (metrics.get("diameter_lower_bound"),
                                  (giant.get("diameter") or {}).get("lower_bound"))
              if isinstance(value, (int, float))]
    if lowers and max(lowers) > threshold:
        return {"flag": False, "basis": "diameter lower bound above the threshold", "threshold": threshold,
                "lower_bound": max(lowers)}
    return {"flag": None, "basis": "no bound decides it", "threshold": threshold,
            "lower_bound": max(lowers) if lowers else None,
            "upper_bound": metrics.get("diameter_upper_bound")}
