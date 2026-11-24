import itertools, math, random, collections
import pytest
from graph_scale_dynamics.engine.engine import GraphState


def test_analyzer_benchmark_battery_passes():
    from graph_scale_dynamics.measurements.benchmarks import run_battery
    report = run_battery(seed=1)
    failed = [check["name"] for check in report["checks"] if check["passed"] is False]
    assert report["passed"], f"battery failures: {failed}"


def test_detailed_balance_on_tiny_graphs():
    n = 4
    pairs = list(itertools.combinations(range(n), 2))
    max_edges = len(pairs)
    index = {p: i for i, p in enumerate(pairs)}

    def energy_of(mask):
        adj = [set() for _ in range(n)]
        for bit, (u, v) in enumerate(pairs):
            if mask >> bit & 1:
                adj[u].add(v)
                adj[v].add(u)
        edges = bin(mask).count("1")
        triangles = sum(1 for a, b, c in itertools.combinations(range(n), 3)
                        if b in adj[a] and c in adj[a] and c in adj[b])
        return 0.5 * edges - 0.7 * triangles

    Z = sum(math.exp(-energy_of(s)) for s in range(1 << max_edges))
    target = {s: math.exp(-energy_of(s)) / Z for s in range(1 << max_edges)}
    rng = random.Random(11)
    state = GraphState(n)
    counts = collections.Counter()
    mask = 0
    for _ in range(300_000):
        edges = len(state.edges)
        adding = rng.random() < 0.5
        if (adding and edges >= max_edges) or (not adding and edges == 0):
            counts[mask] += 1
            continue
        if adding:
            while True:
                u = rng.randrange(n)
                v = rng.randrange(n)
                if u != v and v not in state.adj[u]:
                    break
            log_ratio = math.log(0.5 * (max_edges - edges)) - math.log(0.5 * (edges + 1))
        else:
            u, v = state.edge_list[rng.randrange(edges)]
            log_ratio = math.log(0.5 * edges) - math.log(0.5 * (max_edges - edges + 1))
        deltas = state.op_deltas(u, v, adding)
        delta_h = 0.5 * deltas["edge_count"] - 0.7 * deltas["triangle_count"]
        if math.log(rng.random() + 1e-300) < -delta_h + log_ratio:
            state.apply(u, v, adding, deltas)
            mask ^= 1 << index[(min(u, v), max(u, v))]
        counts[mask] += 1
    total = sum(counts.values())
    err = max(abs(counts.get(s, 0) / total - target[s]) for s in target)
    assert err < 0.012, f"empirical distribution deviates from Boltzmann by {err:.4f}"


def test_integrated_autocorrelation_time_calibration():
    import numpy as np
    from graph_scale_dynamics.measurements.certificate import integrated_autocorrelation_time as iat
    rng = np.random.default_rng(4)
    assert 0.5 < iat(rng.normal(size=4000)) < 2.0
    rho, ar = 0.8, np.zeros(4000)
    for i in range(1, 4000):
        ar[i] = rho * ar[i - 1] + rng.normal()
    assert 5.0 < iat(ar) < 15.0


def test_fast_mixing_law_passes_thermalization_screen():
    from graph_scale_dynamics.scaleflow.engine_door import run_simulation
    from graph_scale_dynamics.measurements.certificate import equilibration_certificate
    spec = {"dsl_version": 1, "init": "empty",
            "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "log_N"}},
                      {"op": "degree_anchor", "params": {"k": 8}, "coeff": {"c0": 0.3, "scale": "one"}}],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 60}}
    import statistics
    certificates = [equilibration_certificate(run_simulation(spec, 256, seed)) for seed in range(1, 6)]
    assert statistics.median(c["effective_samples"] for c in certificates) > 8
    certificate = certificates[0]
    assert max(certificate["split"].values()) < 3.0
    assert certificate["decide"] == ["empty", "given"] and set(certificate["pairs"]) == {"empty|given"}


def _adjacency_from_edges(n, edges):
    import numpy as np
    rows = [[] for _ in range(n)]
    for u, v in edges:
        rows[u].append(v)
        rows[v].append(u)
    return [np.asarray(row, dtype=np.int32) for row in rows]


def test_half_volume_radius_extends_censored_sources_instead_of_dropping_them():
    import numpy as np
    from graph_scale_dynamics.measurements.estimators import volume_growth

    n = 150
    edges = [(i, i + 1) for i in range(n - 1)]
    adj = _adjacency_from_edges(n, edges)
    component = np.arange(n, dtype=np.int32)
    seed = 123
    sources = 20
    result = volume_growth(adj, component, np.random.default_rng(seed),
                           sources=sources, r_max=20)

    picks = np.random.default_rng(seed).choice(component, size=sources, replace=False)
    target = math.ceil(n / 2)
    exact = []
    for source in picks:
        radius = 0
        while min(n - 1, int(source) + radius) - max(0, int(source) - radius) + 1 < target:
            radius += 1
        exact.append(radius)

    assert result["half_volume_radius_extended_sources"] > 0
    assert result["half_volume_radius_source_fraction"] == 1.0
    assert result["half_volume_radius"] == pytest.approx(sum(exact) / len(exact))


def test_sampled_eccentricity_lower_bound_cannot_certify_logarithmic_diameter():
    import numpy as np
    from graph_scale_dynamics.measurements.estimators import volume_growth

    n = 10_000
    edges = []
    tail_start = n - 36
    for v in range(1, tail_start):
        edges.append((0, v))
    next_v = tail_start
    for _ in range(2):
        prev = 0
        for _ in range(18):
            edges.append((prev, next_v))
            prev = next_v
            next_v += 1
    assert next_v == n
    adj = _adjacency_from_edges(n, edges)
    component = np.arange(n, dtype=np.int32)
    result = volume_growth(adj, component, np.random.default_rng(0))
    threshold = 1.6 * math.log2(n)

    assert result["eccentricity_lower_bound"] <= threshold
    assert result["diameter_upper_bound"] is None or result["diameter_upper_bound"] > threshold


def test_spectral_hutchinson_probes_are_memory_blocked(monkeypatch):
    import numpy as np
    from graph_scale_dynamics.measurements.estimators import return_probability

    n = 64
    edges = [(i, (i + 1) % n) for i in range(n)]
    adj = _adjacency_from_edges(n, edges)
    component = np.arange(n, dtype=np.int32)
    monkeypatch.setenv("GSD_SPECTRAL_PROBE_BLOCK", "4")
    result = return_probability(adj, component, np.random.default_rng(7), probes=12, t_max=20)

    assert result["probe_block_size"] == 4
    assert result["method"] == "hutchinson_trace_lazy_walk_blocked"
    assert len(result["p0"]) == 20
    assert all(math.isfinite(value) for value in result["p0"])
