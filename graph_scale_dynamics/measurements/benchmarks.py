from __future__ import annotations
import itertools, os, random
from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements.analysis import analyze_envelope
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION


def lattice(dims: int, length: int, periodic: bool = True):
    coords = list(itertools.product(range(length), repeat=dims))
    index = {c: i for i, c in enumerate(coords)}
    edges = []
    for coordinate in coords:
        for axis in range(dims):
            nxt = list(coordinate)
            nxt[axis] += 1
            if nxt[axis] >= length:
                if not periodic:
                    continue
                nxt[axis] = 0
            edges.append((index[coordinate], index[tuple(nxt)]))
    return len(coords), edges


def erdos_renyi(n: int, mean_degree: float, seed: int):
    rng = random.Random(seed)
    p = mean_degree / (n - 1)
    edges = [(u, v) for u in range(n) for v in range(u + 1, n) if rng.random() < p]
    return n, edges


def random_regular(n: int, degree: int, seed: int):
    if n <= 0 or degree < 0 or degree >= n or (n * degree) % 2:
        raise ValueError("a simple regular graph requires n>0, 0<=degree<n, and even n*degree")
    if degree == 0:
        return n, []

    rng = random.Random(seed)
    edges: set[tuple[int, int]] = set()
    for u in range(n):
        for offset in range(1, degree // 2 + 1):
            v = (u + offset) % n
            edges.add((min(u, v), max(u, v)))
    if degree % 2:
        if n % 2:
            raise ValueError("odd regular degree requires an even vertex count")
        for u in range(n // 2):
            edges.add((u, u + n // 2))

    labels = list(range(n))
    rng.shuffle(labels)
    edges = {(min(labels[u], labels[v]), max(labels[u], labels[v])) for u, v in edges}
    edge_list = list(edges)

    target_swaps = 10 * len(edge_list)
    successful = 0
    for _ in range(max(1, 50 * len(edge_list))):
        if successful >= target_swaps:
            break
        i, j = rng.sample(range(len(edge_list)), 2)
        a, b = edge_list[i]
        c, d = edge_list[j]
        if len({a, b, c, d}) < 4:
            continue
        if rng.random() < 0.5:
            first, second = (min(a, c), max(a, c)), (min(b, d), max(b, d))
        else:
            first, second = (min(a, d), max(a, d)), (min(b, c), max(b, c))
        if first == second or first in edges or second in edges:
            continue
        edges.remove(edge_list[i])
        edges.remove(edge_list[j])
        edges.add(first)
        edges.add(second)
        edge_list[i], edge_list[j] = first, second
        successful += 1
    if successful < target_swaps:
        raise RuntimeError(
            f"regular-graph randomization stalled after {successful}/{target_swaps} swaps"
        )

    degrees = [0] * n
    for u, v in edges:
        degrees[u] += 1
        degrees[v] += 1
    expected_edges = n * degree // 2
    if len(edges) != expected_edges or any(value != degree for value in degrees):
        raise RuntimeError("random-regular control construction violated its degree invariant")
    return n, sorted(edges)


def balanced_tree(branching: int, height: int):
    edges = []
    count = 1
    frontier = [0]
    for _ in range(height):
        nxt = []
        for parent in frontier:
            for _ in range(branching):
                edges.append((parent, count))
                nxt.append(count)
                count += 1
        frontier = nxt
    return count, edges


def _envelope(n, edges):
    degs = [0] * n
    for u, v in edges:
        degs[u] += 1
        degs[v] += 1
    final = {"edge_count": len(edges), "mean_degree": 2 * len(edges) / max(1, n),
             "max_degree": max(degs, default=0), "isolated_vertices": degs.count(0), "energy": 0.0}
    return {"n": n,
            "chains": [{"start": CL.FROM_EMPTY, "final": final, "acceptance": {"rate": {"add": 0.5, "delete": 0.5}}}],
            "sampling_checkpoint": {"chains": [{"start": CL.FROM_EMPTY, "edge_list": edges, "trajectory": []}]}}


CALIBRATION_SEED_OFFSETS = (0, 101, 202)

LATTICES_OF_THE_TABLE = (("periodic_ring", 4096), ("periodic_square_lattice", 64), ("periodic_cubic_lattice", 20),
                         ("periodic_hypercubic_lattice_4d", 12))


BENCHMARK_WORKERS_ENV = "GSD_BENCHMARK_WORKERS"


def _battery_unit(task):
    from graph_scale_dynamics import calibration
    family, parameter, calibration_seed = task
    n, edges = calibration.graph_of_a_cell(family, parameter)
    metrics, _ = analyze_envelope(_envelope(n, edges), seed=calibration_seed)
    return task, n, metrics


def _measure_all(tasks: list, workers: int) -> dict:
    if workers <= 1 or len(tasks) <= 1:
        return {task: (n, metrics) for task, n, metrics in map(_battery_unit, tasks)}
    import concurrent.futures
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            return {task: (n, metrics)
                    for task, n, metrics in pool.map(_battery_unit, tasks)}
    except Exception:
        return {task: (n, metrics) for task, n, metrics in map(_battery_unit, tasks)}


def benchmark_workers(requested: int | None = None) -> int:
    if requested is not None:
        return max(1, int(requested))
    raw = os.environ.get(BENCHMARK_WORKERS_ENV, "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, os.cpu_count() or 1)


def held_as_the_table_holds(family: str, parameter, n: int, readings: dict) -> list[dict]:
    from graph_scale_dynamics import calibration
    judged = calibration.readings_judged_as_the_gate_judges(family, parameter, n, readings)
    return [{"probe": probe, "theory": row["theory"], "tolerance": row["tolerance"], "per_seed": row["per_seed"],
             "measured": row["measured"], "status": row["status"], "passed": row["status"] == "WITHIN_TOLERANCE"}
            for probe, row in sorted(judged.items()) if probe in readings and row["tolerance"] is not None]


def run_battery(seed: int = 1, *, workers: int | None = None) -> dict:
    checks = []

    def analyze(envelope, *, seed):
        return analyze_envelope(envelope, seed=seed)

    def check(name, ok, detail, *, status: str | None = None):
        if status == "skipped":
            checks.append({"name": name, "passed": None, "status": "skipped", "detail": detail})
        else:
            checks.append({"name": name, "passed": bool(ok),
                           "status": "passed" if bool(ok) else "failed", "detail": detail})

    from graph_scale_dynamics import calibration
    calibration_seeds = [seed + offset for offset in CALIBRATION_SEED_OFFSETS]
    tasks = [(family, parameter, calibration_seed) for family, parameter in LATTICES_OF_THE_TABLE
             for calibration_seed in calibration_seeds]
    measured = _measure_all(tasks, benchmark_workers(workers))
    for family, parameter in LATTICES_OF_THE_TABLE:
        n = measured[(family, parameter, calibration_seeds[0])][0]
        readings = {probe: [(metrics.get(probe) or {}).get(key) if (metrics.get(probe) or {}).get("valid") else None
                            for _n, metrics in (measured[(family, parameter, s)] for s in calibration_seeds)]
                    for probe, key in calibration.CHANNEL_VALUE_KEYS.items()}
        held = held_as_the_table_holds(family, parameter, n, readings)
        check(f"{family}_{n}_is_held_by_the_table_s_rule", bool(held),
              {"probes_held": [row["probe"] for row in held], "seeds": calibration_seeds})
        for row in held:
            check(f"{family}_{n}_{row['probe']}_in_the_table_s_band", row["passed"],
                  {key: row[key] for key in ("measured", "theory", "tolerance", "per_seed", "status")})

    n, edges = erdos_renyi(2048, 6.0, seed)
    metrics, _ = analyze(_envelope(n, edges), seed=seed)
    check("erdos_renyi_flagged",
          bool(metrics.get("log_diameter_flag")) or not metrics["d_V"]["valid"],
          {"log_diameter_flag": metrics.get("log_diameter_flag"), "d_V": metrics["d_V"]})
    n, edges = random_regular(2048, 4, seed)
    metrics, _ = analyze(_envelope(n, edges), seed=seed)
    check("random_regular_flagged",
          bool(metrics.get("log_diameter_flag")) or metrics["d_V"].get("refusal") == "EXPONENTIAL_GROWTH",
          {"log_diameter_flag": metrics.get("log_diameter_flag"),
           "volume_growth": metrics["d_V"].get("volume_growth")})

    n, edges = balanced_tree(2, 10)
    metrics, _ = analyze(_envelope(n, edges), seed=seed)
    check("tree_flagged", bool(metrics.get("log_diameter_flag")) or not metrics["d_V"]["valid"],
          {"d_V": metrics["d_V"], "flag": metrics.get("log_diameter_flag")})

    metrics, _ = analyze(_envelope(64, []), seed=seed)
    check("empty_graph_health", metrics["health"]["connected_fraction"] <= 1 / 64 + 1e-9
          and not metrics["d_V"]["valid"], metrics["health"])
    n = 48
    edges = [(u, v) for u in range(n) for v in range(u + 1, n)]
    metrics, _ = analyze(_envelope(n, edges), seed=seed)
    check("near_complete_density", metrics["health"]["density"] > 0.9, {"density": metrics["health"]["density"]})
    half = [(u, v) for u in range(24) for v in range(u + 1, 24)] + \
           [(24 + u, 24 + v) for u in range(24) for v in range(u + 1, 24)]
    metrics, _ = analyze(_envelope(48, half), seed=seed)
    check("disconnected_detected", metrics["health"]["connected_fraction"] < 0.6,
          {"connected_fraction": metrics["health"]["connected_fraction"]})

    passed = all(c["passed"] is not False for c in checks)
    return {"analysis_version": ANALYSIS_VERSION, "passed": passed, "checks": checks}
