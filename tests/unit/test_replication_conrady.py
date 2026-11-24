from __future__ import annotations

import collections
import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import replication_conrady as C  # noqa: E402

OCTAHEDRON = [(0, 1), (0, 2), (0, 3), (0, 4), (5, 1), (5, 2), (5, 3), (5, 4), (1, 2), (2, 3), (3, 4), (4, 1)]


def torus(rows: int, cols: int) -> list[tuple[int, int]]:
    index = lambda i, j: (i % rows) * cols + (j % cols)  # noqa: E731
    edges = set()
    for i in range(rows):
        for j in range(cols):
            for di, dj in ((1, 0), (0, 1), (1, 1)):
                a, b = index(i, j), index(i + di, j + dj)
                edges.add((min(a, b), max(a, b)))
    return sorted(edges)


def band(n: int) -> list[tuple[int, int]]:
    return sorted({(min(i, (i + d) % n), max(i, (i + d) % n)) for i in range(n) for d in (1, 2)})


def test_the_paper_s_couplings_temperatures_and_equilibration():
    assert C.COUPLINGS == {"c_v": 1, "c_e": 10, "c_t": 7, "c_tau": 500}, "equation (3)"
    temps = C.SCHEDULE["temperatures"]
    assert {0.5, 0.625, 1.125, 1.375, 1.875, 2.0, 4.0, 6.75} <= set(temps), "table II's and the peaks' temperatures"
    assert C.paper_equilibration(180, 1.0) == 20_000_000 and C.paper_equilibration(90, 2.25) == 1_000_000, "table I"
    assert C.scan_steps(180, 1.5) == (2_000_000, 10_000_000)
    assert set(C.MODELS) == {"conrady", "conrady_p"}


@pytest.mark.parametrize("model", ["conrady", "conrady_p"])
def test_every_count_the_chain_keeps_is_the_graph_s(model):
    rng = random.Random(5)
    for ne, temperatures in ((12, (6.0, 2.0)), (60, (6.0, 1.5, 0.5))):
        graph = C.ConradyGraph(ne, pair_orders=C.MODELS[model]["pair_orders"])
        graph.check()
        for t in temperatures:
            for i in range(3000):
                graph.step(rng, t)
                if i % 250 == 0:
                    graph.check()
        graph.check()
        assert len(graph.edges) == ne


def test_the_ground_state_of_an_edge_count_is_its_flat_torus():
    for ne, vertices in ((90, 30), (180, 60), (720, 240)):
        graph = C.ConradyGraph(0, edges=C.flat_torus(ne))
        assert (graph.ne, len(graph.verts), graph.energy, graph.m) == (ne, vertices, -14 * ne // 3, 1.0)
        assert all(len(n) == 6 for n in graph.adj.values()) and graph.ntau == 0
    assert C.flat_torus(45) is None and C.flat_torus(100) is None, "15 vertices close a triangle round the torus"


def test_the_hamiltonian_of_graphs_whose_energy_is_known():
    flat = C.ConradyGraph(0, edges=torus(6, 10))
    flat.check()
    assert (flat.ne, len(flat.verts), len(flat.tris)) == (180, 60, 120)
    assert flat.energy == -7 * 120 and flat.m == 1.0, "a flat torus: no vertex term, every edge on two triangles"
    octahedron = C.ConradyGraph(0, edges=OCTAHEDRON)
    assert octahedron.energy == 6 * 2 - 7 * 8, "six vertices of valence 4, eight triangles"
    k4 = C.ConradyGraph(0, edges=list(itertools.combinations(range(4), 2)))
    assert k4.energy == 4 * 3 - 7 * 4 + 500, "a tetrahedron costs c_tau"
    fan = C.ConradyGraph(0, edges=[(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (0, 4), (1, 4)])
    assert fan.tc[(0, 1)] == 3 and fan.energy == fan.full_energy() and fan.eterm == 9, "c_e V_e^2 above valence 2"
    with pytest.raises(ValueError):
        C.ConradyGraph(0, edges=[(0, 1), (1, 0), (1, 2)])


def _invariant(adj) -> tuple:
    seen, out = set(), []
    for v in adj:
        if v in seen:
            continue
        stack, comp = [v], []
        seen.add(v)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        tri = sum(len(adj[a] & adj[b]) for a in comp for b in adj[a]) // 6
        out.append((len(comp), tuple(sorted(len(adj[x]) for x in comp)), tri))
    return tuple(sorted(out))


def _exact(ne: int, temperature: float) -> dict:
    classes = {}
    for edges in itertools.combinations(itertools.combinations(range(2 * ne), 2), ne):
        adj = collections.defaultdict(set)
        for a, b in edges:
            adj[a].add(b)
            adj[b].add(a)
        key = _invariant(adj)
        if key in classes:
            continue
        verts = sorted(adj)
        es = {frozenset(e) for e in edges}
        aut = 0
        for perm in itertools.permutations(verts):
            image = dict(zip(verts, perm, strict=True))
            aut += all(frozenset((image[a], image[b])) in es for a, b in edges)
        graph = C.ConradyGraph(0, edges=edges)
        classes[key] = math.factorial(ne) * 2 ** graph.k2 / aut * math.exp(-graph.energy / temperature)
    total = sum(classes.values())
    return {k: w / total for k, w in classes.items()}


def _chain(ne: int, temperature: float, steps: int, pair_orders: int = 2) -> dict:
    rng = random.Random(11)
    graph = C.ConradyGraph(ne, pair_orders=pair_orders)
    counts = collections.Counter()
    for i in range(steps):
        graph.step(rng, temperature)
        if i % 5 == 0:
            counts[_invariant(graph.adj)] += 1
    total = sum(counts.values())
    return {k: n / total for k, n in counts.items()}


@pytest.mark.parametrize("ne,temperature", [(3, 30.0), (4, 12.0), (4, 2.5)])
def test_the_chain_samples_equation_4_exactly(ne, temperature):
    exact = _exact(ne, temperature)
    seen = _chain(ne, temperature, 250_000)
    assert set(seen) <= set(exact), "every graph the chain visits is a configuration"
    for key, p in exact.items():
        if p > 0.02:
            assert abs(seen.get(key, 0.0) - p) < 0.06 * p + 0.004, (key, p, seen.get(key))


def test_the_printed_3_1_count_is_another_measure():
    exact = _exact(3, 30.0)
    printed = _chain(3, 30.0, 250_000, pair_orders=1)
    triangle, loose = ((3, (2, 2, 2), 1),), ((2, (1, 1), 0),) * 3
    assert printed[triangle] > 1.15 * exact[triangle] and printed[loose] < 0.85 * exact[loose], (printed, exact)


def _reference(ne: int, temperature: float, steps: int, seed: int) -> float:
    pool = 2 * ne + 2
    rng = random.Random(seed)
    graph = C.ConradyGraph(ne)

    def logw():
        return -graph.energy / temperature + graph.k2 * math.log(2) + math.lgamma(pool - len(graph.verts) + 1)
    lw, eps = logw(), []
    for i in range(steps):
        a, b = graph.edges[rng.randrange(ne)]
        x, y = rng.randrange(pool), rng.randrange(pool)
        if x != y and not (x in graph.adj and y in graph.adj[x]):
            graph._remove(a, b)
            graph._add(x, y)
            lw2 = logw()
            if lw2 >= lw or rng.random() < math.exp(lw2 - lw):
                lw = lw2
            else:
                graph._remove(x, y)
                graph._add(a, b)
        if i > steps // 5 and i % 20 == 0:
            eps.append(graph.energy / ne)
    return statistics.fmean(eps)


def test_the_chain_agrees_with_an_independent_sampler_where_enumeration_cannot_go():
    rng = random.Random(3)
    graph = C.ConradyGraph(9)
    eps = []
    for i in range(300_000):
        graph.step(rng, 3.0)
        if i > 60_000 and i % 20 == 0:
            eps.append(graph.energy / 9)
    reference = statistics.fmean([_reference(9, 3.0, 300_000, seed) for seed in (1, 2)])
    assert abs(statistics.fmean(eps) - reference) < 0.08, (statistics.fmean(eps), reference)


def test_table_ii_s_reading_of_surfaces_whose_answers_are_known():
    flat = C.surface_reading(C.ConradyGraph(0, edges=torus(7, 7)).adj, C.ConradyGraph(0, edges=torus(7, 7)).tris)
    assert (flat["largest_euler"], flat["largest_orientable"], flat["mean_valence"], flat["mean_ricci"]) == (
        0, True, 6.0, 0.0)
    assert flat["conical_share"] == 0 and flat["components"] == 1 and flat["largest_boundary_share"] == 0
    for n, orientable in ((9, False), (10, True)):
        g = C.ConradyGraph(0, edges=band(n))
        strip = C.surface_reading(g.adj, g.tris)
        assert strip["largest_orientable"] is orientable, n
        assert strip["largest_euler"] == 0 and strip["largest_boundary_share"] == 0.5, "a band: half its edges bound it"
    g = C.ConradyGraph(0, edges=OCTAHEDRON)
    assert C.surface_reading(g.adj, g.tris)["largest_euler"] == 2
    two = C.ConradyGraph(0, edges=OCTAHEDRON + [(a + 5, b + 5) for a, b in OCTAHEDRON])
    reading = C.surface_reading(two.adj, two.tris)
    assert reading["conical_share"] == round(1 / 11, 4), "one vertex of eleven joins two surfaces"
    assert (reading["components"], reading["surface_vertices"], reading["largest_euler"]) == (2, 12, 2), (
        "split at its conical singularity, two spheres")
    loose = C.ConradyGraph(0, edges=OCTAHEDRON + [(20, 21), (0, 22)])
    reading = C.surface_reading(loose.adj, loose.tris)
    assert reading["zero_valence_share"] == round(2 / 14, 4) and reading["largest_euler"] == 2, (
        "edges on no triangle are counted and are not on the surface")


def test_a_scan_and_an_anneal_read_what_the_paper_reads():
    scan = C.run_one({"kind": "scan", "model": "conrady", "ne": 30, "T": 1.0, "seed": 1, "steps": (3000, 6000)})
    assert "error" not in scan, scan
    assert scan["measure"] == 6000 and len(scan["eps_blocks"]) == 10 and abs(sum(scan["valence_shares"]) - 1) < 1e-6
    assert scan["c"] >= 0 and scan["chi"] >= 0 and 0 <= scan["m"] <= 1 and "reading" not in scan["end"]
    cold = C.run_one({"kind": "anneal", "model": "conrady", "ne": 30, "T": 0.625, "seed": 1, "sample": 0,
                      "anneal": 3000, "settle": 3000})
    assert "error" not in cold and "surface" in cold and "giant_share" in cold["reading"], (
        "the instrument reads a cold end")
    again = C.run_one({"kind": "anneal", "model": "conrady", "ne": 30, "T": 0.625, "seed": 1, "sample": 0,
                       "anneal": 3000, "settle": 3000})
    assert (again["eps"], again["m"]) == (cold["eps"], cold["m"]), "a run is its model, size, temperature and seed"


def test_the_readings_of_a_scan():
    rows = []
    for t, m, eps, c in ((1.0, 1.0, -4.4, 0.2), (1.125, 0.99, -4.3, 0.6), (1.25, 0.9, -4.0, 1.5), (1.375, 0.85, -3.8,
                                                                                                     1.1)):
        rows.append({"kind": "scan", "model": "conrady", "ne": 90, "T": t, "seed": 1, "eps": eps, "m": m, "c": c,
                     "chi": 0.05, "acceptance": 0.01, "vertices": 30.0, "valence_shares": [0, 0, 1, 0],
                     "end": {"eps": eps, "m": m, "vertices": 30, "mean_degree": 6.0}})
    cold = dict(rows[0], T=0.5, c=3.0)
    cell = C.summarize([cold] + rows)[0]
    assert (cell["T_peak_c"], cell["c_peak"], cell["c_0.5"]) == (1.25, 1.5, 3.0)
    assert cell["T_peak_dm"] == 1.125 and cell["m_1.25"] == 0.9 and cell["eps_1.375"] == -3.8
    assert cell["torus_vertices"] == 30 and cell["torus_eps"] == round(-14 / 3, 4), "the ground state beside it"
    criterion = {"predictions": [
        {"id": "A", "model": "conrady", "sizes": [90], "reading": "T_peak_c", "rule": {"between": [1.2, 1.3]}},
        {"id": "B", "model": "conrady", "sizes": [45, 90], "reading": "T_peak_c", "rule": {"decreasing": True}},
        {"id": "C", "model": "conrady", "sizes": [90], "reading": "m_1.25", "rule": {"at_least": 0.95},
         "expect": "missed"}]}
    verdicts = {v["id"]: v for v in C.judge([cell, {**cell, "n": 45, "T_peak_c": 1.5}], criterion)}
    assert verdicts["A"]["verdict"] == "held" and verdicts["B"]["verdict"] == "held"
    assert verdicts["C"]["verdict"] == "missed" and verdicts["C"]["as_expected"]
    assert C.parse_anneal("conrady:180@0.625x3,720@0.625;conrady_p:180@2", ["conrady", "conrady_p"]) == {
        "conrady": [(180, 0.625, 3), (720, 0.625, None)], "conrady_p": [(180, 2.0, None)]}


def test_the_command_writes_a_document_the_explorer_reads(tmp_path, monkeypatch):
    monkeypatch.setitem(C.SCHEDULE, "temperatures", [0.75, 3.0])
    monkeypatch.setitem(C.SCHEDULE, "anneal_steps_per_edge", 100)
    monkeypatch.setitem(C.SCHEDULE, "settle_steps_per_edge", 100)
    monkeypatch.setattr(C, "scan_steps", lambda ne, t: (500, 1000))
    out = tmp_path / "graph_scale_dynamics" / "resources" / "readings" / "replication_conrady_test.json"
    assert C.main(["--models", "conrady", "--scan", "24", "--anneal", "conrady:24@0.75", "--seeds", "1",
                   "--workers", "1", "--output", str(out)]) == 0
    document = json.loads(out.read_text())
    assert document["paper"] == "conrady" and document["open_choices"] == C.OPEN_CHOICES
    cell = document["cells"][0]
    assert (cell["model"], cell["n"], cell["read_at"]) == ("conrady", 24, "annealed to 0.75")
    assert cell["vertices"] and cell["mean_degree"]
    from graph_scale_dynamics.reporting import study_explorer as E
    papers = [p for p in E.papers(tmp_path) if p["model"] == "conrady"]
    assert papers and papers[0]["n"] == cell["vertices"] and papers[0]["k"] == cell["mean_degree"], (
        "a paper whose size is its edges is drawn at its vertices and its mean degree")
