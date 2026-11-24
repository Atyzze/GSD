#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import replication as R  # noqa: E402

PAPER = "conrady"
COUPLINGS = {"c_v": 1, "c_e": 10, "c_t": 7, "c_tau": 500}
MODELS = {
    "conrady": {"dimension": 2, "pair_orders": 2, "paper": "arXiv:1009.3195",
                "reading": "equation (4) sampled exactly"},
    "conrady_p": {"dimension": 2, "pair_orders": 1, "paper": "arXiv:1009.3195",
                  "reading": "equation (13) as printed: 1/(N_v N_v) for the 3_1 move"},
}
OPEN_CHOICES = {
    "P_m": "an edge or a triangle chosen uniformly among the N_e + N_t of them: m = 1 for an edge, m = 2 for a triangle, "
           "whose two edges at one of its three vertices (1/3) leave",
    "P_n_prime": "the addition's types equally likely: 1_1, 2_1, 3_1, 4_1 a quarter each; 2_2, 3_2 a half each",
    "3_1": "two vertices drawn independently; a draw of one vertex twice or of a linked pair proposes nothing",
    "4_1": "a centre drawn among the vertices, then a pair of its unlinked neighbours among its N_vc",
    "labels": "conrady counts edge-labelled graphs (equation (4)): x2 for each one-edge component, x1/2 for an edge "
              "made with two new ends; conrady_p as conrady but for 3_1's 1/(N_v N_v)",
    "start": "N_e disconnected edges (figure 3's)",
    "reduction": "table II's surface: an edge on three triangles or more leaves with its triangles, the edges left in no "
                 "triangle leave, each conical singularity is split into one vertex a fan; R from equations (20) "
                 "and (21) with V_v the vertex's edges on the surface",
}
PAPER_EQUILIBRATION = {45: ((2.0, 7_000_000), (99.0, 1_000_000)),
                       90: ((2.0, 7_000_000), (99.0, 1_000_000)),
                       180: ((1.5, 20_000_000), (2.5, 7_000_000), (99.0, 1_000_000))}
SCHEDULE = {
    "temperatures": [round(0.5 + 0.125 * i, 3) for i in range(17)] + [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 6.75],
    "equilibrate": "a tenth of the paper's dt_eq at that N_e and T (table I)",
    "measure": "half of the paper's dt_eq",
    "every": 200,
    "anneal_from": 4.0,
    "anneal_steps_per_edge": 40_000,
    "settle_steps_per_edge": 40_000,
    "instrument_below": 1.0,
}
PEAK_FROM, FINE_TO = 0.875, 2.5
PAPER_FIGURES = {
    "eps": {45: {1.5: -4.381, 2.0: -3.850, 3.0: -2.871, 4.0: -2.135, 5.0: -1.561, 6.0: -1.17},
            90: {1.5: -3.920, 2.0: -3.410, 3.0: -2.613, 4.0: -1.967, 5.0: -1.452, 6.0: -1.097},
            180: {1.5: -3.518, 2.0: -3.050, 3.0: -2.26, 4.0: -1.615, 5.0: -1.165, 6.0: -0.851}},
    "m": {45: {1.5: 0.989, 2.0: 0.896, 3.0: 0.727, 4.0: 0.607, 5.0: 0.515, 6.0: 0.455},
          90: {1.5: 0.903, 2.0: 0.803, 3.0: 0.654, 4.0: 0.538, 5.0: 0.448, 6.0: 0.388},
          180: {1.5: 0.844, 2.0: 0.747, 3.0: 0.584, 4.0: 0.458, 5.0: 0.371, 6.0: 0.313}},
    "c": {45: {1.5: 0.571, 2.0: 1.266, 3.0: 0.829, 4.0: 0.684, 5.0: 0.513, 6.0: 0.405},
          90: {1.5: 1.347, 2.0: 0.944, 3.0: 0.74, 4.0: 0.584, 5.0: 0.453, 6.0: 0.346},
          180: {1.5: 1.080, 2.0: 0.909, 3.0: 0.761, 4.0: 0.557, 5.0: 0.415, 6.0: 0.298}},
    "chi": {45: {1.5: 0.026, 2.0: 0.089, 3.0: 0.074, 4.0: 0.078, 5.0: 0.069, 6.0: 0.065},
            90: {1.5: 0.090, 2.0: 0.075, 3.0: 0.080, 4.0: 0.080, 5.0: 0.074, 6.0: 0.065},
            180: {1.5: 0.077, 2.0: 0.084, 3.0: 0.098, 4.0: 0.092, 5.0: 0.082, 6.0: 0.069}},
    "peak": {45: (1.875, 1.347), 90: (1.375, 1.442), 180: (1.125, 1.701)},
    "valence_90_at_2": {"v2": 0.66, "v1": 0.28, "v0": 0.05},
    "table_ii_180": {0.625: {"zero_valence_share": 0.00, "conical_share": 0.08, "components": 1.2, "mean_valence": 6.7,
                             "mean_ricci": -0.8, "largest_boundary_share": 0.00, "orientable_share": 0.00,
                             "largest_euler": -6.1},
                     2.0: {"zero_valence_share": 0.09, "conical_share": 0.40, "components": 2.6, "mean_valence": 5.3,
                           "mean_ricci": 3.0, "largest_boundary_share": 0.36, "orientable_share": 0.07,
                           "largest_euler": -4.8}},
    "acceptance": {0.5: 1e-4, 2.0: 0.02},
}


def paper_equilibration(ne: int, temperature: float) -> int:
    sizes = sorted(PAPER_EQUILIBRATION)
    table = PAPER_EQUILIBRATION[next((s for s in sizes if s >= ne), sizes[-1])]
    return next(steps for upto, steps in table if temperature <= upto + 1e-9)


def scan_steps(ne: int, temperature: float) -> tuple[int, int]:
    dt = paper_equilibration(ne, temperature)
    return dt // 10, dt // 2


_VT = [0] + [abs(d - 6) for d in range(1, 8192)]
_F = [v * v if v > 2 else 0 for v in range(8192)]


class ConradyGraph:
    def __init__(self, ne: int, *, pair_orders: int = 2, couplings: dict | None = None, edges=None):
        if edges is not None:
            edges = [(int(a), int(b)) for a, b in edges]
            ne = len(edges)
        if ne < 3:
            raise ValueError("N_e must be at least 3")
        c = dict(COUPLINGS, **(couplings or {}))
        self.cv, self.ce, self.ct, self.ctau = c["c_v"], c["c_e"], c["c_t"], c["c_tau"]
        self.ne = ne
        self.pair_orders = pair_orders
        self.adj: dict[int, set[int]] = {}
        self.verts: list[int] = []
        self.vpos: dict[int, int] = {}
        self.edges: list[tuple[int, int]] = []
        self.epos: dict[tuple[int, int], int] = {}
        self.tris: list[tuple[int, int, int]] = []
        self.tpos: dict[tuple[int, int, int], int] = {}
        self.tc: dict[tuple[int, int], int] = {}
        self.hist = [0, 0, 0, 0]
        self.vterm = 0
        self.eterm = 0
        self.ntau = 0
        self.k2 = 0
        self.next_id = 0
        self.w1 = (0.25, 0.25, 0.25, 0.25)
        self.w2 = (0.5, 0.5)
        if edges is None:
            edges = [(2 * i, 2 * i + 1) for i in range(ne)]
        for a, b in edges:
            if a == b or (a in self.adj and b in self.adj[a]):
                raise ValueError(f"not a simple graph: {a}-{b}")
            self._add(a, b)
        self.next_id = max(max(a, b) for a, b in edges) + 1

    @property
    def energy(self) -> int:
        return self.cv * self.vterm + self.ce * self.eterm - self.ct * len(self.tris) + self.ctau * self.ntau

    @property
    def m(self) -> float:
        return (self.hist[2] + 0.5 * self.hist[1]) / self.ne

    def full_energy(self) -> int:
        adj = self.adj
        vterm = sum(_VT[len(n)] for n in adj.values())
        eterm = nt = ntau = 0
        for a, b in self.edges:
            eterm += _F[len(adj[a] & adj[b])]
        for a in adj:
            for b in adj[a]:
                if b > a:
                    for c in adj[a] & adj[b]:
                        if c > b:
                            nt += 1
                            ntau += sum(1 for d in adj[a] & adj[b] & adj[c] if d > c)
        return self.cv * vterm + self.ce * eterm - self.ct * nt + self.ctau * ntau

    def relabelled(self) -> tuple[int, list[tuple[int, int]]]:
        index = {v: i for i, v in enumerate(sorted(self.adj))}
        return len(index), sorted((index[a], index[b]) for a, b in self.edges)

    def _add(self, a: int, b: int) -> None:
        adj = self.adj
        if a not in adj:
            adj[a] = set()
            self.vpos[a] = len(self.verts)
            self.verts.append(a)
        if b not in adj:
            adj[b] = set()
            self.vpos[b] = len(self.verts)
            self.verts.append(b)
        na, nb = adj[a], adj[b]
        da, db = len(na), len(nb)
        if da == 1:
            if len(adj[next(iter(na))]) == 1:
                self.k2 -= 1
        elif da == 0 and db == 0:
            self.k2 += 1
        if db == 1 and len(adj[next(iter(nb))]) == 1:
            self.k2 -= 1
        self.vterm += _VT[da + 1] - _VT[da] + _VT[db + 1] - _VT[db]
        common = na & nb
        k = len(common)
        hist = self.hist
        if k:
            tc, tris, tpos, de = self.tc, self.tris, self.tpos, 0
            for c in common:
                if a < b:
                    t = (c, a, b) if c < a else (a, c, b) if c < b else (a, b, c)
                else:
                    t = (c, b, a) if c < b else (b, c, a) if c < a else (b, a, c)
                tpos[t] = len(tris)
                tris.append(t)
                for e in ((a, c) if a < c else (c, a), (b, c) if b < c else (c, b)):
                    old = tc[e]
                    tc[e] = old + 1
                    de += _F[old + 1] - _F[old]
                    hist[old if old < 3 else 3] -= 1
                    hist[old + 1 if old < 2 else 3] += 1
            if k > 1:
                self.ntau += sum([len(adj[c] & common) for c in common]) // 2
            self.eterm += de + _F[k]
        hist[k if k < 3 else 3] += 1
        e = (a, b) if a < b else (b, a)
        self.tc[e] = k
        self.epos[e] = len(self.edges)
        self.edges.append(e)
        na.add(b)
        nb.add(a)

    def _remove(self, a: int, b: int) -> list[int]:
        adj = self.adj
        na, nb = adj[a], adj[b]
        if len(na) == 1 and len(nb) == 1:
            self.k2 -= 1
        na.discard(b)
        nb.discard(a)
        da, db = len(na), len(nb)
        if da == 1 and len(adj[next(iter(na))]) == 1:
            self.k2 += 1
        if db == 1 and len(adj[next(iter(nb))]) == 1:
            self.k2 += 1
        self.vterm += _VT[da] - _VT[da + 1] + _VT[db] - _VT[db + 1]
        e = (a, b) if a < b else (b, a)
        tc, hist = self.tc, self.hist
        k = tc.pop(e)
        hist[k if k < 3 else 3] -= 1
        de = -_F[k]
        if k:
            tris, tpos = self.tris, self.tpos
            common = na & nb
            for c in common:
                if a < b:
                    t = (c, a, b) if c < a else (a, c, b) if c < b else (a, b, c)
                else:
                    t = (c, b, a) if c < b else (b, c, a) if c < a else (b, a, c)
                i = tpos.pop(t)
                last = tris.pop()
                if last != t:
                    tris[i] = last
                    tpos[last] = i
                for f in ((a, c) if a < c else (c, a), (b, c) if b < c else (c, b)):
                    old = tc[f]
                    tc[f] = old - 1
                    de += _F[old - 1] - _F[old]
                    hist[old if old < 3 else 3] -= 1
                    hist[old - 1 if old < 4 else 3] += 1
            if k > 1:
                self.ntau -= sum([len(adj[c] & common) for c in common]) // 2
        self.eterm += de
        i = self.epos.pop(e)
        last = self.edges.pop()
        if last != e:
            self.edges[i] = last
            self.epos[last] = i
        gone = []
        for v, d in ((a, da), (b, db)):
            if not d:
                del adj[v]
                i = self.vpos.pop(v)
                last = self.verts.pop()
                if last != v:
                    self.verts[i] = last
                    self.vpos[last] = i
                gone.append(v)
        return gone

    def _pairs_at(self, c: int) -> int:
        n = self.adj[c]
        d = len(n)
        return d * (d - 1) // 2 - sum([len(self.adj[u] & n) for u in n]) // 2

    def _p_between(self, a: int, b: int) -> float:
        nv = len(self.verts)
        p = self.w1[2] * self.pair_orders / (nv * nv)
        common = self.adj[a] & self.adj[b]
        if common:
            p += self.w1[3] * sum(1.0 / self._pairs_at(c) for c in common) / nv
        return p

    def step(self, rng: random.Random, temperature: float) -> bool:
        ne = self.ne
        s = ne + len(self.tris)
        r = rng.randrange(s)
        e0, k0 = self.energy, self.k2
        if r < ne:
            return self._step1(rng, temperature, r, s, e0, k0)
        return self._step2(rng, temperature, r - ne, s, e0, k0)

    def _accept(self, rng, temperature, q: float, e0: int) -> bool:
        lr = math.log(q) - (self.energy - e0) / temperature
        return lr >= 0 or rng.random() < math.exp(lr)

    def _step1(self, rng, temperature, r, s, e0, k0) -> bool:
        a, b = self.edges[r]
        gone = self._remove(a, b)
        if len(gone) == 2:
            kind, p_back = 1, self.w1[0]
        elif gone:
            if gone[0] == a:
                a, b = b, a
            kind, p_back = 2, self.w1[1] / len(self.verts)
        else:
            kind, p_back = 3, self._p_between(a, b)
        nv, u, w = len(self.verts), rng.random(), self.w1
        new = 0
        if u < w[0]:
            x, y, new, p_add = self.next_id, self.next_id + 1, 2, w[0]
        elif u < w[0] + w[1]:
            x, y, new = self.verts[rng.randrange(nv)], self.next_id, 1
            p_add = w[1] / nv
        else:
            if u < w[0] + w[1] + w[2]:
                x, y = self.verts[rng.randrange(nv)], self.verts[rng.randrange(nv)]
                if x == y or y in self.adj[x]:
                    self._add(a, b)
                    return False
            else:
                n = self.adj[self.verts[rng.randrange(nv)]]
                pairs = [(p, q) for p in n for q in n if p < q and q not in self.adj[p]]
                if not pairs:
                    self._add(a, b)
                    return False
                x, y = pairs[rng.randrange(len(pairs))]
            p_add = self._p_between(x, y)
        self.next_id += new
        self._add(x, y)
        q = (s * p_back) / ((self.ne + len(self.tris)) * p_add) * _label_factor(self.k2 - k0, kind == 1, new == 2)
        if self._accept(rng, temperature, q, e0):
            return True
        self._remove(x, y)
        self.next_id -= new
        self._add(a, b)
        return False

    def _step2(self, rng, temperature, r, s, e0, k0) -> bool:
        t = self.tris[r]
        k = rng.randrange(3)
        w = t[k]
        u1, u2 = (t[1], t[2]) if k == 0 else (t[0], t[2]) if k == 1 else (t[0], t[1])
        alone = len(self.adj[w]) == 2
        self._remove(w, u1)
        self._remove(w, u2)
        ne2, nv = self.ne - 2, len(self.verts)
        p_back = self.w2[0] / ne2 if alone else self.w2[1] / (ne2 * nv)
        cx, cy = self.edges[rng.randrange(ne2)]
        if rng.random() < self.w2[0]:
            z, new, p_add = self.next_id, 1, self.w2[0] / ne2
        else:
            z, new = self.verts[rng.randrange(nv)], 0
            if z == cx or z == cy or z in self.adj[cx] or z in self.adj[cy]:
                self._add(w, u1)
                self._add(w, u2)
                return False
            p_add = self.w2[1] / (ne2 * nv)
        self.next_id += new
        self._add(z, cx)
        self._add(z, cy)
        q = (s * p_back) / ((self.ne + len(self.tris)) * p_add) * _label_factor(self.k2 - k0, False, False)
        if self._accept(rng, temperature, q, e0):
            return True
        self._remove(z, cx)
        self._remove(z, cy)
        self.next_id -= new
        self._add(w, u1)
        self._add(w, u2)
        return False

    def check(self) -> None:
        adj = self.adj
        assert len(self.edges) == self.ne and all(adj[v] for v in adj), "N_e edges, no vertex without one"
        assert set(self.verts) == set(adj) == set(self.vpos) and len(self.verts) == len(adj)
        es = {(a, b) for a in adj for b in adj[a] if a < b}
        assert es == set(self.edges) == set(self.epos), "the edges"
        ts = {tuple(sorted((a, b, c))) for a, b in es for c in adj[a] & adj[b]}
        assert ts == set(self.tris) == set(self.tpos), "the triangles"
        assert all(self.tc[e] == len(adj[e[0]] & adj[e[1]]) for e in es), "an edge's triangles"
        hist = [0, 0, 0, 0]
        for e in es:
            hist[min(self.tc[e], 3)] += 1
        assert hist == self.hist, (hist, self.hist)
        assert self.energy == self.full_energy(), (self.energy, self.full_energy())
        assert self.k2 == sum(1 for a, b in es if len(adj[a]) == 1 and len(adj[b]) == 1), "the one-edge components"


def _label_factor(k2_change: int, removed_alone: bool, made_alone: bool) -> float:
    return 2.0 ** k2_change * (2.0 if removed_alone else 1.0) * (0.5 if made_alone else 1.0)


def flat_torus(ne: int) -> list[tuple[int, int]] | None:
    if ne % 3:
        return None
    nv = ne // 3
    pairs = [(r, nv // r) for r in range(4, int(math.isqrt(nv)) + 1) if nv % r == 0 and nv // r >= 4]
    if not pairs:
        return None
    rows, cols = min(pairs, key=lambda rc: rc[1] - rc[0])
    edges = set()
    for i in range(rows):
        for j in range(cols):
            for di, dj in ((1, 0), (0, 1), (1, 1)):
                a, b = i * cols + j, ((i + di) % rows) * cols + (j + dj) % cols
                edges.add((min(a, b), max(a, b)))
    return sorted(edges)


_TORUS_READINGS: dict[int, dict] = {}


def torus_reading(ne: int) -> dict:
    if ne not in _TORUS_READINGS:
        edges = flat_torus(ne)
        if edges is None:
            _TORUS_READINGS[ne] = {}
        else:
            graph = ConradyGraph(0, edges=edges)
            _TORUS_READINGS[ne] = {"vertices": len(graph.verts), "eps": round(graph.energy / graph.ne, 4),
                                   **R.instrument(*graph.relabelled())}
    return _TORUS_READINGS[ne]


def _components(nodes, links) -> list[list]:
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in links:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = collections.defaultdict(list)
    for n in nodes:
        groups[find(n)].append(n)
    return list(groups.values())


def _fans(triangles) -> dict:
    link, nodes = collections.defaultdict(list), collections.defaultdict(set)
    for a, b, c in triangles:
        for v, u, w in ((a, b, c), (b, a, c), (c, a, b)):
            link[v].append((u, w))
            nodes[v].update((u, w))
    return {v: _components(nodes[v], link[v]) for v in link}


def surface_reading(adj: dict, triangles) -> dict:
    edges = {(a, b) for a in adj for b in adj[a] if a < b}
    nv, ne = len(adj), len(edges)
    tris = [tuple(sorted(t)) for t in triangles]
    tc = collections.Counter()
    for a, b, c in tris:
        tc[(a, b)] += 1
        tc[(a, c)] += 1
        tc[(b, c)] += 1
    out = {"vertices": nv, "edges": ne, "zero_valence_share": round(sum(tc[e] == 0 for e in edges) / ne, 4),
           "branched_edges": sum(1 for e in edges if tc[e] > 2),
           "conical_share": round(sum(len(f) > 1 for f in _fans(tris).values()) / nv, 4)}
    keep = [t for t in tris if max(tc[(t[0], t[1])], tc[(t[0], t[2])], tc[(t[1], t[2])]) <= 2]
    fan_of = {}
    for v, comps in _fans(keep).items():
        for i, comp in enumerate(comps):
            for u in comp:
                fan_of[(v, u)] = (v, i)
    faces = [(fan_of[(a, b)], fan_of[(b, a)], fan_of[(c, a)]) for a, b, c in keep]
    on = collections.Counter()
    for x, y, z in faces:
        for e in ((x, y), (x, z), (y, z)):
            on[tuple(sorted(e))] += 1
    verts = {v for f in faces for v in f}
    degree = collections.Counter()
    for x, y in on:
        degree[x] += 1
        degree[y] += 1
    comps = _components(verts, list(on))
    out.update({"surface_vertices": len(verts), "surface_edges": len(on), "surface_triangles": len(faces),
                "components": len(comps)})
    if not faces:
        return out
    area = math.sqrt(3) / 4
    ricci = [2 * (2 * math.pi - degree[v] * math.pi / 3) / (degree[v] * area / 3) for v in verts]
    out["mean_valence"] = round(sum(degree[v] for v in verts) / len(verts), 4)
    out["mean_ricci"] = round(statistics.fmean(ricci), 4)
    comp_of = {v: i for i, comp in enumerate(comps) for v in comp}
    size = collections.Counter(comp_of[e[0]] for e in on)
    big = max(sorted(size), key=lambda i: size[i])
    big_edges = [e for e in on if comp_of[e[0]] == big]
    big_faces = [f for f in faces if comp_of[f[0]] == big]
    out["largest_edges"] = len(big_edges)
    out["largest_boundary_share"] = round(sum(1 for e in big_edges if on[e] == 1) / len(big_edges), 4)
    out["largest_euler"] = len(comps[big]) - len(big_edges) + len(big_faces)
    out["largest_orientable"] = orientable(big_faces)
    return out


def orientable(faces) -> bool:
    by_edge = collections.defaultdict(list)
    for i, (a, b, c) in enumerate(faces):
        for x, y in ((a, b), (b, c), (c, a)):
            by_edge[frozenset((x, y))].append(i)

    def runs(t):
        return {(t[0], t[1]), (t[1], t[2]), (t[2], t[0])}
    orient: list = [None] * len(faces)
    for start in range(len(faces)):
        if orient[start] is not None:
            continue
        orient[start] = faces[start]
        stack = [start]
        while stack:
            i = stack.pop()
            for x, y in runs(orient[i]):
                for j in by_edge[frozenset((x, y))]:
                    if j == i:
                        continue
                    if orient[j] is None:
                        p, q, r = faces[j]
                        orient[j] = (p, q, r) if (y, x) in runs((p, q, r)) else (r, q, p)
                        stack.append(j)
                    elif (y, x) not in runs(orient[j]):
                        return False
    return True


def _rng(task: dict) -> random.Random:
    return random.Random(f"{task['model']}:{task['kind']}:{task['ne']}:{task['T']}:{task['seed']}:{task.get('sample', 0)}")


def _graph(task: dict) -> ConradyGraph:
    return ConradyGraph(int(task["ne"]), pair_orders=MODELS[task["model"]]["pair_orders"])


def _read(graph: ConradyGraph, *, instrument: bool) -> dict:
    out = {"eps": round(graph.energy / graph.ne, 4), "m": round(graph.m, 4), "vertices": len(graph.verts),
           "triangles": len(graph.tris), "tetrahedra": graph.ntau,
           "mean_degree": round(2 * graph.ne / len(graph.verts), 4),
           "surface": surface_reading(graph.adj, graph.tris)}
    if instrument:
        out["reading"] = R.instrument(*graph.relabelled())
    return out


def run_scan(task: dict) -> dict:
    ne, temperature = int(task["ne"]), float(task["T"])
    equilibrate, measure = task.get("steps") or scan_steps(ne, temperature)
    every = SCHEDULE["every"]
    rng, graph = _rng(task), _graph(task)
    started = time.monotonic()
    step = graph.step
    for _ in range(equilibrate):
        step(rng, temperature)
    eps, ms, shares, verts = [], [], [0.0, 0.0, 0.0, 0.0], 0
    taken = 0
    for i in range(measure):
        taken += step(rng, temperature)
        if i % every == 0:
            eps.append(graph.energy / ne)
            ms.append(graph.m)
            for k in range(4):
                shares[k] += graph.hist[k]
            verts += len(graph.verts)
    n = len(eps)
    beta = 1.0 / temperature
    blocks = [statistics.fmean(eps[i * n // 10:(i + 1) * n // 10]) for i in range(10)] if n >= 10 else []
    row = {"eps": round(statistics.fmean(eps), 5), "m": round(statistics.fmean(ms), 5),
           "c": round(beta * beta * ne * statistics.pvariance(eps), 5),
           "chi": round(beta * ne * statistics.pvariance(ms), 6),
           "valence_shares": [round(s / (n * ne), 5) for s in shares], "vertices": round(verts / n, 3),
           "acceptance": round(taken / measure, 6), "eps_blocks": [round(b, 4) for b in blocks],
           "end": _read(graph, instrument=temperature < SCHEDULE["instrument_below"])}
    return {**_task_fields(task), "equilibrate": equilibrate, "measure": measure, "every": every,
            "seconds": round(time.monotonic() - started, 1), **row}


def run_anneal(task: dict) -> dict:
    ne, temperature = int(task["ne"]), float(task["T"])
    anneal = task.get("anneal") or SCHEDULE["anneal_steps_per_edge"] * ne
    settle = task.get("settle") or SCHEDULE["settle_steps_per_edge"] * ne
    hot = SCHEDULE["anneal_from"]
    rng, graph = _rng(task), _graph(task)
    started = time.monotonic()
    step = graph.step
    for i in range(anneal):
        step(rng, hot + (temperature - hot) * i / anneal)
    taken = 0
    for _ in range(settle):
        taken += step(rng, temperature)
    return {**_task_fields(task), "anneal": anneal, "settle": settle, "acceptance": round(taken / settle, 6),
            "seconds": round(time.monotonic() - started, 1),
            **_read(graph, instrument=temperature < SCHEDULE["instrument_below"])}


def _task_fields(task: dict) -> dict:
    return {"kind": task["kind"], "model": task["model"], "ne": int(task["ne"]), "T": float(task["T"]),
            "seed": int(task["seed"]), **({"sample": task["sample"]} if "sample" in task else {})}


def run_one(task: dict) -> dict:
    try:
        return run_scan(task) if task["kind"] == "scan" else run_anneal(task)
    except Exception as exc:
        return {**_task_fields(task), "error": f"{type(exc).__name__}: {exc}"}


def cost(task: dict) -> float:
    if task["kind"] == "scan":
        return float(sum(task.get("steps") or scan_steps(int(task["ne"]), float(task["T"]))))
    return float((SCHEDULE["anneal_steps_per_edge"] + SCHEDULE["settle_steps_per_edge"]) * int(task["ne"]))


def _median(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(statistics.median(values), 4) if values else None


def _mean(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(statistics.fmean(values), 4) if values else None


def _key(name: str, temperature: float) -> str:
    return f"{name}_{temperature:g}"


def transition(curve: dict[float, dict]) -> dict:
    fine = sorted(t for t in curve if PEAK_FROM - 1e-9 <= t <= FINE_TO + 1e-9)
    out = {}
    if not fine:
        return out
    peak = max(fine, key=lambda t: curve[t]["c"])
    out.update({"T_peak_c": peak, "c_peak": curve[peak]["c"]})
    steps = list(zip(fine, fine[1:], strict=False))
    if steps:
        dm = max(steps, key=lambda p: (curve[p[0]]["m"] - curve[p[1]]["m"]) / (p[1] - p[0]))
        de = max(steps, key=lambda p: (curve[p[1]]["eps"] - curve[p[0]]["eps"]) / (p[1] - p[0]))
        out.update({"T_peak_dm": dm[0], "dm_peak": round((curve[dm[0]]["m"] - curve[dm[1]]["m"]) / (dm[1] - dm[0]), 4),
                    "T_peak_deps": de[0],
                    "deps_peak": round((curve[de[1]]["eps"] - curve[de[0]]["eps"]) / (de[1] - de[0]), 4)})
    return out


CELL_FIELDS = ("eps", "m", "c", "chi", "acceptance", "vertices")
SURFACE_FIELDS = ("zero_valence_share", "conical_share", "components", "mean_valence", "mean_ricci",
                  "largest_boundary_share", "largest_euler", "branched_edges")


def summarize(rows: list[dict]) -> list[dict]:
    groups = collections.defaultdict(list)
    for r in rows:
        if "error" not in r:
            groups[(r["model"], r["ne"])].append(r)
    cells = []
    for (model, ne), group in sorted(groups.items()):
        cell = {"model": model, "dimension": MODELS[model]["dimension"], "n": ne, "edges": ne}
        scans = [r for r in group if r["kind"] == "scan"]
        if scans:
            by_t = collections.defaultdict(list)
            for r in scans:
                by_t[r["T"]].append(r)
            curve = {}
            for t, runs in sorted(by_t.items()):
                point = {f: statistics.fmean(r[f] for r in runs) for f in CELL_FIELDS}
                shares = [statistics.fmean(r["valence_shares"][k] for r in runs) for k in range(4)]
                curve[t] = point
                for f in CELL_FIELDS:
                    cell[_key(f, t)] = round(point[f], 6 if f == "acceptance" else 4)
                for k, name in enumerate(("v0", "v1", "v2", "v3")):
                    cell[_key(f"share_{name}", t)] = round(shares[k], 4)
            cell["scan_seeds"] = len({r["seed"] for r in scans})
            cell.update(transition(curve))
            for name in ("eps", "m", "c", "chi"):
                for t, value in PAPER_FIGURES[name].get(ne, {}).items():
                    if t in curve:
                        cell[_key(f"{name}_gap", t)] = round(curve[t][name] - value, 4)
            if ne in PAPER_FIGURES["peak"] and "T_peak_c" in cell:
                t_peak, c_peak = PAPER_FIGURES["peak"][ne]
                cell["T_peak_c_gap"] = round(cell["T_peak_c"] - t_peak, 4)
                cell["c_peak_ratio"] = round(cell["c_peak"] / c_peak, 4)
        anneals = [r for r in group if r["kind"] == "anneal"]
        by_t = collections.defaultdict(list)
        for r in anneals:
            by_t[r["T"]].append(r)
        for t, runs in sorted(by_t.items()):
            prefix = f"s{t:g}_"
            cell[prefix + "runs"] = len(runs)
            cell[prefix + "eps"] = _mean([r["eps"] for r in runs])
            cell[prefix + "m"] = _mean([r["m"] for r in runs])
            cell[prefix + "vertices"] = _mean([r["vertices"] for r in runs])
            for f in SURFACE_FIELDS:
                cell[prefix + f] = _mean([r["surface"].get(f) for r in runs])
            cell[prefix + "orientable_share"] = _mean([1.0 if r["surface"].get("largest_orientable") else 0.0
                                                      for r in runs if "largest_orientable" in r["surface"]])
        cold = []
        if by_t:
            cold = [r["reading"] for r in by_t[min(by_t)] if r.get("reading")]
            cell["read_at"] = f"annealed to {min(by_t):g}"
            ends = by_t[min(by_t)]
        if not cold and scans:
            t0 = min(r["T"] for r in scans)
            ends = [r["end"] for r in scans if r["T"] == t0]
            cold = [e["reading"] for e in ends if e.get("reading")]
            cell["read_at"] = f"the scan's end at {t0:g}"
        if cold:
            for probe in ("d_s", "d_V", "d_B", "d_w", "curvature", "half_volume_radius", "giant_share"):
                cell[probe] = _median([c.get(probe) for c in cold])
            cell["d_s_readable"] = round(sum(c.get("d_s") is not None for c in cold) / len(cold), 4)
            cell["vertices"] = _median([e.get("vertices") for e in ends])
            cell["mean_degree"] = _median([e.get("mean_degree") for e in ends])
        torus = torus_reading(ne)
        if torus:
            cell["torus_vertices"] = torus["vertices"]
            cell["torus_eps"] = torus["eps"]
            for probe in ("d_s", "d_V", "d_w", "half_volume_radius"):
                cell[f"torus_{probe}"] = torus.get(probe)
            if isinstance(cell.get("half_volume_radius"), (int, float)) and torus.get("half_volume_radius"):
                cell["radius_over_torus"] = round(cell["half_volume_radius"] / torus["half_volume_radius"], 4)
        cell["seeds"] = len({r["seed"] for r in group})
        cells.append(cell)
    return cells


def render(cells: list[dict]) -> str:
    def f(c, key, form):
        v = c.get(key)
        return format(v, form) if isinstance(v, (int, float)) and not isinstance(v, bool) else "-"
    lines = [f"{'model':10} {'N_e':>4} {'m(0.5)':>6} {'eps(0.5)':>8} {'Tc':>6} {'c_max':>6} {'T|dm|':>6} "
             f"{'eps(4)':>7} {'m(4)':>6} {'chi(4)':>6} {'acc(0.5)':>9} {'conical':>7} {'euler':>6} {'orient':>6} "
             f"{'N_v':>5} {'d_s':>5}"]
    for c in cells:
        lines.append(f"{c['model']:10} {c['n']:>4} {f(c, 'm_0.5', '.3f'):>6} {f(c, 'eps_0.5', '.3f'):>8} "
                     f"{f(c, 'T_peak_c', '.3f'):>6} {f(c, 'c_peak', '.2f'):>6} {f(c, 'T_peak_dm', '.3f'):>6} "
                     f"{f(c, 'eps_4', '.3f'):>7} {f(c, 'm_4', '.3f'):>6} {f(c, 'chi_4', '.3f'):>6} "
                     f"{f(c, 'acceptance_0.5', '.1e'):>9} {f(c, 's0.625_conical_share', '.3f'):>7} "
                     f"{f(c, 's0.625_largest_euler', '.1f'):>6} {f(c, 's0.625_orientable_share', '.2f'):>6} "
                     f"{f(c, 'vertices', '.0f'):>5} {f(c, 'd_s', '.2f'):>5}")
    lines.append("  m, eps at T = 0.5 and 4; Tc and c_max: the specific heat's peak; T|dm|: figure 7's largest |dm/dT|; "
                 "acc: the acceptance; conical, euler, orient: table II's at 0.625 (annealed); N_v and d_s: the coldest "
                 "graphs' vertices and the instrument's d_s")
    return "\n".join(lines)


def judge(cells: list[dict], criterion: dict) -> list[dict]:
    by = {(c["model"], c["n"]): c for c in cells}
    verdicts = []
    for p in criterion["predictions"]:
        values = {n: (by.get((p["model"], n)) or {}).get(p["reading"]) for n in p["sizes"]}
        rule = p["rule"]
        seq = [values[n] for n in p["sizes"]]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in seq):
            verdict = "unread"
        elif rule.get("decreasing") or rule.get("increasing"):
            ok = all((a > b) if rule.get("decreasing") else (a < b) for a, b in zip(seq, seq[1:], strict=False))
            verdict = "held" if ok else "missed"
        elif rule.get("alternates"):
            verdict = "held" if all((a - 0.5) * (b - 0.5) < 0 for a, b in zip(seq, seq[1:], strict=False)) else "missed"
        else:
            verdict = "held" if all(R._meets(v, rule) for v in seq) else "missed"
        verdicts.append({"id": p["id"], "verdict": verdict, "expected": p.get("expect", "held"),
                         "as_expected": verdict == p.get("expect", "held"), "values": values})
    return verdicts


def parse_anneal(text: str, models: list[str]) -> dict[str, list[tuple[int, float, int | None]]]:
    plan = {m: [] for m in models}
    for part in text.split(";"):
        if not part.strip():
            continue
        name, _, values = part.partition(":")
        if name.strip() not in plan:
            continue
        for token in values.split(","):
            if token.strip():
                size, _, rest = token.strip().partition("@")
                t, _, k = rest.partition("x")
                plan[name.strip()].append((int(size), float(t), int(k) if k else None))
    return plan


def plan_tasks(models, scan_plan, anneal_plan, seeds: int, first_seed: int) -> list[dict]:
    tasks = []
    for m in models:
        for ne, k in scan_plan.get(m, []):
            for seed in range(first_seed, first_seed + (k or seeds)):
                for t in SCHEDULE["temperatures"]:
                    tasks.append({"kind": "scan", "model": m, "ne": ne, "T": t, "seed": seed})
        for ne, t, k in anneal_plan.get(m, []):
            for seed in range(first_seed, first_seed + seeds):
                for sample in range(k or 1):
                    tasks.append({"kind": "anneal", "model": m, "ne": ne, "T": t, "seed": seed, "sample": sample})
    return sorted(tasks, key=lambda t: (-cost(t), t["model"], t["ne"], t["T"], t["seed"], t.get("sample", 0)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/replication_conrady.py: see docs/TOOLS.md")
    parser.add_argument("--models", default=",".join(MODELS), help=f"of {', '.join(MODELS)}")
    parser.add_argument("--scan", default="conrady:45,90,180;conrady_p:45,90,180",
                        help="the temperature scans: N_e for every model given, or model:N_e,N_e;model:N_e; "
                             "N_exK scans K seeds at N_e")
    parser.add_argument("--anneal", default="conrady:180@0.625x2,180@2x2",
                        help="the annealed runs, model:N_e@T[xK],...; K samples a seed")
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--output", help="default var/readings/replication_conrady_<utc>.json")
    parser.add_argument("--judge", help="a committed criterion: each prediction judged against the run's cells")
    parser.add_argument("--read", help="judge runs already written (their documents, comma-separated) instead")
    args = parser.parse_args(argv)
    if args.read:
        rows = [r for path in args.read.split(",") if path
                for r in json.loads(Path(path).read_text(encoding="utf-8"))["rows"]]
        cells = summarize(rows)
        print(render(cells))
        if args.judge:
            criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
            print(R.render_verdicts(judge(cells, criterion), criterion))
        return 0
    models = [m for m in args.models.split(",") if m]
    unknown = [m for m in models if m not in MODELS]
    if unknown:
        parser.error(f"unknown model(s) {unknown}; the models are {', '.join(MODELS)}")
    scan_plan = R.parse_sizes(args.scan, models)
    anneal_plan = parse_anneal(args.anneal, models)
    tasks = plan_tasks(models, scan_plan, anneal_plan, args.seeds, args.first_seed)
    print(f"replication (Conrady): {len(tasks)} runs, {sum(map(cost, tasks)) / 1e9:.2f} billion steps, "
          f"seeds from {args.first_seed}, on {args.workers} worker(s)", flush=True)
    started, rows = time.monotonic(), []
    try:
        from partial_rows import kept_on_failure, partial_path
    except ImportError:
        from tools.partial_rows import kept_on_failure, partial_path
    with kept_on_failure(rows, partial_path(args.output, "replication_conrady")):
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for done, future in enumerate(as_completed([pool.submit(run_one, t) for t in tasks]), start=1):
                row = future.result()
                rows.append(row)
                print(f"  {done}/{len(tasks)} {row['model']} {row['kind']} N_e={row['ne']} T={row['T']:g} "
                      f"seed {row['seed']}: "
                      + (row["error"] if "error" in row else f"eps {row['eps']}, m {row['m']}, {row['seconds']} s"),
                      flush=True)
    cells = summarize(rows)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    document = {"contract": R.REPLICATION_CONTRACT, "paper": PAPER, "run_utc": stamp,
                "seconds": round(time.monotonic() - started, 1), "models": {m: MODELS[m] for m in models},
                "couplings": COUPLINGS, "open_choices": OPEN_CHOICES, "schedule": SCHEDULE,
                "paper_equilibration": {str(k): v for k, v in PAPER_EQUILIBRATION.items()},
                "scan": {m: scan_plan[m] for m in models}, "anneal": {m: anneal_plan[m] for m in models},
                "first_seed": args.first_seed, "seeds": args.seeds, "cells": cells,
                "rows": sorted(rows, key=lambda r: (r["model"], r["kind"], r["ne"], r["T"], r["seed"],
                                                    r.get("sample", 0)))}
    if args.judge:
        criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
        document["criterion"] = {"path": args.judge, "verdicts": judge(cells, criterion)}
    output = Path(args.output) if args.output else ROOT / "var" / "readings" / f"replication_conrady_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(render(cells))
    if args.judge:
        print(R.render_verdicts(document["criterion"]["verdicts"], criterion))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
