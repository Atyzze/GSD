#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import shlex
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

REPLICATION_CONTRACT = "gsd-replication-1"
KTB_MODELS = {
    "ktb1": {"dimension": 1, "degree": 3, "space": "cubic", "girth": 4, "paper": "arXiv:2008.11779"},
    "ktb1t": {"dimension": 1, "degree": 3, "space": "cubic", "girth": 3, "paper": "arXiv:2008.11779"},
    "ktb1c": {"dimension": 1, "degree": 3, "space": "cubic", "girth": 4, "connected": True, "paper": "arXiv:2008.11779"},
    "ktb2": {"dimension": 2, "degree": 4, "space": "bipartite", "paper": "arXiv:1901.09870"},
    "ktb3": {"dimension": 3, "degree": 6, "space": "bipartite", "paper": "arXiv:1901.09870"},
}
SCHEDULES = {
    "cubic": {"beta_from": 0.05, "fine_from": 1.0, "fine_to": 3.0, "fine_step": 0.1, "beta_to": 20.0, "coarse": 7,
              "sweeps": "3N/2"},
    "bipartite": {"beta_from": 0.02, "beta_to": 100.0, "steps": 31, "sweeps": 160},
}
SHUFFLE_PER_EDGE = 20


def _e(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def edge_action(d: int, squares: int) -> int:
    return 4 * max(0, d - 2 - squares)


def cubic_edge_action3(t: int, s: int, p: int) -> int:
    return -(t - max(0, 1 - t - s) - max(0, 1 - t - s - p))


class _Switching:
    def _add(self, a: int, b: int) -> None:
        key = _e(a, b)
        self.adj[a].add(b)
        self.adj[b].add(a)
        self.index[key] = len(self.edges)
        self.edges.append(key)

    def _replace(self, old: tuple[int, int], new: tuple[int, int]) -> None:
        a, b = old
        self.adj[a].discard(b)
        self.adj[b].discard(a)
        i = self.index.pop(old)
        self.edges[i] = new
        self.index[new] = i
        c, d = new
        self.adj[c].add(d)
        self.adj[d].add(c)

    def _switch(self, move) -> None:
        self._replace(move[1], move[3])
        self._replace(move[2], move[4])

    def _unswitch(self, move) -> None:
        self._replace(move[3], move[1])
        self._replace(move[4], move[2])

    def _shuffle(self, rng: random.Random, moves: int) -> None:
        for _ in range(moves):
            move = self._propose(rng)
            if move is not None:
                self._switch(move)

    def _clear_violations(self, rng: random.Random, limit: int = 2_000_000) -> None:
        m, tries = len(self.edges), 0
        while self.violations():
            for _ in range(20 * m):
                tries += 1
                if tries > limit:
                    raise RuntimeError(f"could not clear the violations at n={self.n}, d={self.d}")
                move = self._propose(rng)
                if move is None:
                    continue
                before = self._local_violations(move[0])
                self._switch(move)
                if self._local_violations(move[0]) > before:
                    self._unswitch(move)

    @property
    def action(self) -> float:
        return self._action / self.unit

    def summary(self) -> dict:
        return {"action_per_node": round(self.action / self.n, 5), **self.observables()}


class BipartiteGraph(_Switching):
    unit = 1

    def __init__(self, n: int, d: int, rng: random.Random):
        if n % 2 or n < 2 * (d + 1):
            raise ValueError(f"a {d}-regular bipartite graph needs an even n of at least {2 * (d + 1)}; {n} given")
        self.n, self.d, self.half = n, d, n // 2
        self.adj: list[set[int]] = [set() for _ in range(n)]
        self.edges: list[tuple[int, int]] = []
        self.index: dict[tuple[int, int], int] = {}
        for left in range(self.half):
            for k in range(d):
                self._add(left, self.half + (left + k) % self.half)
        self._shuffle(rng, SHUFFLE_PER_EDGE * len(self.edges))
        self._clear_violations(rng)
        self.squares: dict[tuple[int, int], int] = {e: self._squares_on(*e) for e in self.edges}
        self._action = sum(edge_action(d, s) for s in self.squares.values())

    def _squares_on(self, u: int, v: int) -> int:
        nu = self.adj[u]
        return sum(len((nu & self.adj[x]) - {v}) for x in self.adj[v] if x != u)

    def _square_sets(self, u: int, v: int) -> set[frozenset]:
        nu = self.adj[u]
        return {frozenset((u, v, x, y)) for x in self.adj[v] if x != u for y in (nu & self.adj[x]) - {v}}

    def _propose(self, rng: random.Random):
        m = len(self.edges)
        i, j = rng.randrange(m), rng.randrange(m)
        if i == j:
            return None
        (a, b), (c, d) = self.edges[i], self.edges[j]
        if a == c or b == d or d in self.adj[a] or b in self.adj[c]:
            return None
        return (a, b, c, d), (a, b), (c, d), (a, d), (c, b)

    def _gained_violation(self, new1: tuple[int, int], new2: tuple[int, int]) -> bool:
        adj = self.adj
        for (u, v) in (new1, new2):
            for x, y in ((u, v), (v, u)):
                nx = adj[x]
                for w in adj[y]:
                    if w != x and len(nx & adj[w]) > 2:
                        return True
        return False

    def _pair_violations(self, nodes) -> set[tuple[int, int]]:
        out = set()
        for x in nodes:
            nx = self.adj[x]
            for w in {w for y in nx for w in self.adj[y] if w != x}:
                if len(nx & self.adj[w]) > 2:
                    out.add(_e(x, w))
        return out

    def _local_violations(self, nodes) -> int:
        region = set(nodes).union(*(self.adj[x] for x in nodes))
        near = {_e(x, y) for x in region for y in self.adj[x]}
        return len(self._pair_violations(nodes)) + sum(1 for e in near if self._squares_on(*e) > self.d - 2)

    def violations(self) -> int:
        count = 0
        for x in range(self.n):
            for w in {w for y in self.adj[x] for w in self.adj[y] if w > x}:
                count += len(self.adj[x] & self.adj[w]) > 2
        return count + sum(1 for e in self.edges if self._squares_on(*e) > self.d - 2)

    def step(self, rng: random.Random, beta: float) -> bool:
        move = self._propose(rng)
        if move is None:
            return False
        _, old1, old2, new1, new2 = move
        lost = self._square_sets(*old1) | self._square_sets(*old2)
        self._switch(move)
        if self._gained_violation(new1, new2):
            self._unswitch(move)
            return False
        gained = self._square_sets(*new1) | self._square_sets(*new2)
        change = collections.Counter()
        for square in lost:
            for e in _square_edges(square, self.half):
                change[e] -= 1
        for square in gained:
            for e in _square_edges(square, self.half):
                change[e] += 1
        d, cap = self.d, self.d - 2
        delta = -edge_action(d, self.squares[old1]) - edge_action(d, self.squares[old2])
        for e, k in change.items():
            if e == old1 or e == old2:
                continue
            fresh = e == new1 or e == new2
            before = 0 if fresh else self.squares[e]
            if before + k > cap:
                self._unswitch(move)
                return False
            delta += edge_action(d, before + k) - (0 if fresh else edge_action(d, before))
        for e in (new1, new2):
            if e not in change:
                delta += edge_action(d, 0)
        if delta > 0 and rng.random() >= math.exp(-beta * delta):
            self._unswitch(move)
            return False
        del self.squares[old1], self.squares[old2]
        for e in (new1, new2):
            self.squares[e] = 0
        for e, k in change.items():
            if e in self.squares:
                self.squares[e] += k
        self._action += delta
        return True

    def phi(self) -> float:
        return (sum(self.squares.values()) // 4) / (self.n * self.d * (self.d - 2) / 8)

    def observables(self) -> dict:
        flat = sum(1 for s in self.squares.values() if s >= self.d - 2) / len(self.edges)
        return {"phi": round(self.phi(), 5), "flat_share": round(flat, 5)}

    def classical(self) -> dict:
        return {"classical": self._action == 0}

    def check(self) -> None:
        assert all(len(a) == self.d for a in self.adj), "every node at degree d"
        assert all(u < self.half <= v for u, v in self.edges) and len(self.index) == len(self.edges)
        assert self.violations() == 0, "the hard core condition, and no edge above d - 2 squares"
        assert {e: self._squares_on(*e) for e in self.edges} == self.squares, "each edge's squares"
        assert self._action == sum(edge_action(self.d, s) for s in self.squares.values())


def _square_edges(square: frozenset, half: int) -> tuple:
    left = sorted(x for x in square if x < half)
    right = sorted(x for x in square if x >= half)
    return tuple((u, v) for u in left for v in right)


class CubicGraph(_Switching):
    unit = 3

    def __init__(self, n: int, rng: random.Random, *, girth4: bool = False, connected: bool = False):
        if n % 2 or n < 10:
            raise ValueError(f"a cubic graph here needs an even n of at least 10; {n} given")
        self._load(n, ladder_edges(n, True), girth4, connected)
        for _ in range(50):
            self._shuffle(rng, SHUFFLE_PER_EDGE * len(self.edges))
            self._clear_violations(rng)
            if not connected or _components(n, self.edges) == 1:
                break
        else:
            raise RuntimeError(f"no connected start at n={n}")
        self._count()

    @classmethod
    def from_edges(cls, n: int, edges, *, girth4: bool = False, connected: bool = False) -> "CubicGraph":
        graph = cls.__new__(cls)
        graph._load(n, edges, girth4, connected)
        graph._count()
        return graph

    def _load(self, n: int, edges, girth4: bool, connected: bool = False) -> None:
        self.n, self.d, self.girth4, self.connected = n, 3, girth4, connected
        self.adj: list[set[int]] = [set() for _ in range(n)]
        self.edges: list[tuple[int, int]] = []
        self.index: dict[tuple[int, int], int] = {}
        for a, b in edges:
            self._add(a, b)

    def _count(self) -> None:
        self.counts: dict[tuple[int, int], tuple[int, int, int]] = {e: self._counts(*e) for e in self.edges}
        self._action = sum(cubic_edge_action3(*c) for c in self.counts.values())

    def _cycles(self, u: int, v: int, longest: int = 5):
        adj, nu, uv = self.adj, self.adj[u], _e(u, v)
        c3, c4, c5 = [], [], []
        for a in adj[v]:
            if a == u:
                continue
            va = _e(v, a)
            if a in nu:
                c3.append(frozenset((uv, va, _e(a, u))))
            for b in adj[a]:
                if b == v or b == u:
                    continue
                ab = _e(a, b)
                if b in nu:
                    c4.append(frozenset((uv, va, ab, _e(b, u))))
                if longest > 4:
                    for c in adj[b]:
                        if c != a and c != v and c in nu:
                            c5.append(frozenset((uv, va, ab, _e(b, c), _e(c, u))))
        return c3, c4, c5

    def _counts(self, u: int, v: int) -> tuple[int, int, int]:
        c3, c4, c5 = self._cycles(u, v)
        return len(c3), len(c4), len(c5)

    def _reaches(self, a: int, b: int) -> bool:
        seen, stack = {a}, [a]
        while stack:
            for y in self.adj[stack.pop()]:
                if y == b:
                    return True
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False

    def _propose(self, rng: random.Random):
        m = len(self.edges)
        i, j = rng.randrange(m), rng.randrange(m)
        if i == j:
            return None
        (u, v), (x, y) = self.edges[i], self.edges[j]
        if rng.random() < 0.5:
            x, y = y, x
        if u == x or u == y or v == x or v == y or x in self.adj[u] or y in self.adj[v]:
            return None
        return (u, v, x, y), self.edges[i], self.edges[j], _e(u, x), _e(v, y)

    def _short_cycles_at(self, nodes) -> set[frozenset]:
        out = set()
        for x in nodes:
            for w in self.adj[x]:
                c3, c4, _ = self._cycles(x, w, longest=4)
                out.update(c3)
                out.update(c4)
        return out

    def _bad(self, cycles) -> int:
        cycles = list(cycles)
        pairs = sum(1 for i, c in enumerate(cycles) for o in cycles[i + 1:] if len(c & o) > 1)
        return pairs + (sum(1 for c in cycles if len(c) == 3) if self.girth4 else 0)

    def _local_violations(self, nodes) -> int:
        return self._bad(self._short_cycles_at(nodes))

    def violations(self) -> int:
        return self._bad(self._short_cycles_at(range(self.n)))

    def _breaks_independence(self, cycles) -> bool:
        for c in cycles:
            for e in c:
                c3, c4, _ = self._cycles(*e, longest=4)
                if any(o != c and len(o & c) > 1 for o in c3 + c4):
                    return True
        return False

    def step(self, rng: random.Random, beta: float) -> bool:
        move = self._propose(rng)
        if move is None:
            return False
        _, old1, old2, new1, new2 = move
        lost = set()
        for e in (old1, old2):
            for group in self._cycles(*e):
                lost.update(group)
        self._switch(move)
        gained = set()
        for e in (new1, new2):
            for group in self._cycles(*e):
                gained.update(group)
        if ((self.girth4 and any(len(c) == 3 for c in gained))
                or self._breaks_independence([c for c in gained if len(c) < 5])):
            self._unswitch(move)
            return False
        change = collections.defaultdict(lambda: [0, 0, 0])
        for c in lost:
            for e in c:
                change[e][len(c) - 3] -= 1
        for c in gained:
            for e in c:
                change[e][len(c) - 3] += 1
        delta = -cubic_edge_action3(*self.counts[old1]) - cubic_edge_action3(*self.counts[old2])
        for e, (dt, ds, dp) in change.items():
            if e == old1 or e == old2:
                continue
            if e == new1 or e == new2:
                delta += cubic_edge_action3(dt, ds, dp)
            else:
                t, s, p = self.counts[e]
                delta += cubic_edge_action3(t + dt, s + ds, p + dp) - cubic_edge_action3(t, s, p)
        for e in (new1, new2):
            if e not in change:
                delta += cubic_edge_action3(0, 0, 0)
        if delta > 0 and rng.random() >= math.exp(-beta * delta / 3.0):
            self._unswitch(move)
            return False
        if self.connected and not self._reaches(move[0][0], move[0][1]):
            self._unswitch(move)
            return False
        del self.counts[old1], self.counts[old2]
        for e in (new1, new2):
            self.counts[e] = (0, 0, 0)
        for e, (dt, ds, dp) in change.items():
            if e in self.counts:
                t, s, p = self.counts[e]
                self.counts[e] = (t + dt, s + ds, p + dp)
        self._action += delta
        return True

    def observables(self) -> dict:
        totals = [sum(c[k] for c in self.counts.values()) // (k + 3) for k in range(3)]
        flat = sum(1 for c in self.counts.values() if cubic_edge_action3(*c) == 0) / len(self.edges)
        return {"flat_share": round(flat, 5), "triangles": totals[0], "squares": totals[1], "pentagons": totals[2]}

    def ladder(self) -> str | None:
        if self._action != 0 or any(c[0] for c in self.counts.values()):
            return None
        rungs = [e for e, c in self.counts.items() if c[1] == 2]
        rails = [e for e, c in self.counts.items() if c[1] == 1]
        if len(rungs) != self.n // 2 or len(rails) != self.n or len({x for e in rungs for x in e}) != self.n:
            return None
        rail_adj = collections.defaultdict(list)
        for a, b in rails:
            rail_adj[a].append(b)
            rail_adj[b].append(a)
        rings, seen = 0, set()
        for start in range(self.n):
            if start in seen:
                continue
            rings += 1
            stack = [start]
            seen.add(start)
            while stack:
                for y in rail_adj[stack.pop()]:
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
        components = _components(self.n, self.edges)
        if components > 1:
            return "ladders"
        return {2: "prism", 1: "moebius"}.get(rings)

    def classical(self) -> dict:
        return {"classical": self._action == 0, "ladder": self.ladder()}

    def check(self) -> None:
        assert all(len(a) == 3 for a in self.adj), "every node at degree 3"
        assert len(set(self.edges)) == len(self.edges) == len(self.index) and all(u != v for u, v in self.edges)
        assert self.violations() == 0, "independent short cycles"
        assert {e: self._counts(*e) for e in self.edges} == self.counts, "each edge's cycles"
        assert self._action == sum(cubic_edge_action3(*c) for c in self.counts.values())


def _components(n: int, edges) -> int:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for u, v in edges:
        parent[find(u)] = find(v)
    return len({find(x) for x in range(n)})


def make_graph(model: str, n: int, rng: random.Random):
    spec = KTB_MODELS[model]
    if spec["space"] == "cubic":
        return CubicGraph(n, rng, girth4=spec["girth"] == 4, connected=bool(spec.get("connected")))
    return BipartiteGraph(n, spec["degree"], rng)


def ladder_edges(n: int, twisted: bool) -> list[tuple[int, int]]:
    m = n // 2
    if twisted:
        return [_e(i, (i + 1) % n) for i in range(n)] + [(i, i + m) for i in range(m)]
    return ([_e(i, (i + 1) % m) for i in range(m)] + [_e(m + i, m + (i + 1) % m) for i in range(m)]
            + [(i, m + i) for i in range(m)])


def torus_edges(dim: int, n: int) -> list[tuple[int, int]] | None:
    side = round(n ** (1 / dim))
    if side ** dim != n or side % 2 or side < 6:
        return None
    from itertools import product
    edges = []
    for point in product(range(side), repeat=dim):
        index = sum(c * side ** k for k, c in enumerate(point))
        for axis in range(dim):
            nxt = list(point)
            nxt[axis] = (nxt[axis] + 1) % side
            edges.append(_e(index, sum(c * side ** k for k, c in enumerate(nxt))))
    return edges


def classical_configurations(model: str, n: int) -> dict[str, list]:
    spec = KTB_MODELS[model]
    if spec["space"] == "cubic":
        return {"prism": ladder_edges(n, False), "moebius": ladder_edges(n, True)}
    torus = torus_edges(spec["dimension"], n)
    return {"torus": torus} if torus else {}


def configuration_action(model: str, n: int, edges) -> float:
    from graph_scale_dynamics.measurements.curvature_probe import cycle_counts_python
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    spec = KTB_MODELS[model]
    if spec["space"] == "cubic":
        return sum(cubic_edge_action3(*cycle_counts_python(adj, u, v)) for u, v in edges) / 3
    return sum(edge_action(spec["degree"], cycle_counts_python(adj, u, v)[1]) for u, v in edges)


def shape_reading(n: int, edges) -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements import estimators as M
    matrix = M.build_adjacency(n, [(int(u), int(v)) for u, v in edges])
    component = M.largest_component(n, matrix)
    out = {"giant_share": round(len(component) / n, 4)}
    if len(component) >= 16:
        rng = np.random.default_rng(0)
        out["half_volume_radius"] = M.volume_growth(matrix, component, rng).get("half_volume_radius")
        fit = M.fit_ds(M.return_probability(matrix, component, rng), len(component))
        out["d_s"] = round(fit["d_s"], 3) if fit.get("valid") else None
    return out


def instrument(n: int, edges) -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements.curvature_probe import read as curvature
    from graph_scale_dynamics.measurements.estimators import _measure_graph
    edges = [(int(u), int(v)) for u, v in edges]
    out = shape_reading(n, edges)
    kappa = curvature(n, edges)
    out["curvature"] = round(float(kappa["mean"]), 4) if kappa.get("measured") else None
    probes, _ = _measure_graph(n, edges, np.random.default_rng(0), measure_geometry=True)
    for name, key in (("d_V", "d_V_window"), ("d_B", "d_B"), ("d_w", "d_w")):
        reading = probes.get(name) or {}
        value = reading.get(key) if reading.get("valid") else None
        out[name] = round(float(value), 3) if value is not None else None
    return out


def betas(schedule: dict) -> list[float]:
    def logspace(lo, hi, k):
        return [math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * i / (k - 1)) for i in range(k)]
    if "fine_from" in schedule:
        lo, f0, f1, hi, k = (schedule[key] for key in ("beta_from", "fine_from", "fine_to", "beta_to", "coarse"))
        fine = [f0 + i * schedule["fine_step"] for i in range(int(round((f1 - f0) / schedule["fine_step"])) + 1)]
        values = logspace(lo, f0, k)[:-1] + fine + logspace(f1, hi, k)[1:]
    else:
        values = logspace(schedule["beta_from"], schedule["beta_to"], int(schedule["steps"]))
    return [round(b, 6) for b in values]


def sweeps_at(schedule: dict, n: int) -> int:
    return int(round(1.5 * n)) if schedule["sweeps"] == "3N/2" else int(schedule["sweeps"])


def anneal(graph, rng: random.Random, schedule: dict, *, reverse: bool = False) -> list[dict]:
    rows = []
    m, sweeps = len(graph.edges), sweeps_at(schedule, graph.n)
    for beta in (betas(schedule)[::-1] if reverse else betas(schedule)):
        actions, taken = [], 0
        for sweep in range(sweeps):
            for _ in range(m):
                taken += graph.step(rng, beta)
            if sweep >= sweeps // 2:
                actions.append(graph.action)
        var = statistics.pvariance(actions) if len(actions) > 1 else 0.0
        rows.append({"beta": beta, "action_per_node": round(statistics.fmean(actions) / graph.n, 5),
                     "specific_heat": round(beta * beta * var / graph.n, 5), **graph.observables(),
                     "acceptance": round(taken / (sweeps * m), 5)})
    return rows


def run_one(task: dict) -> dict:
    model, n, seed = task["model"], int(task["n"]), int(task["seed"])
    spec = KTB_MODELS[model]
    schedule = dict(SCHEDULES[spec["space"]], **(task.get("schedule") or {}))
    started = time.monotonic()
    try:
        rng = random.Random(seed)
        graph = make_graph(model, n, rng)
        start = graph.summary()
        cooling = anneal(graph, rng, schedule)
        end = {**graph.summary(), **graph.classical()}
        reading = instrument(n, graph.edges)
        heating = anneal(graph, rng, schedule, reverse=True) if task.get("hysteresis") else None
        row = {"start": start, "cooling": cooling, "end": end, "reading": reading,
               **({"heating": heating} if heating is not None else {})}
        if task.get("classical", True):
            row["classical_readings"] = {
                name: dict(instrument(n, edges), action_per_node=round(configuration_action(model, n, edges) / n, 5))
                for name, edges in classical_configurations(model, n).items()}
    except Exception as exc:
        row = {"error": f"{type(exc).__name__}: {exc}"}
    return {"model": model, "dimension": spec["dimension"], "degree": spec["degree"], "n": n, "seed": seed,
            "schedule": schedule, "sweeps": sweeps_at(schedule, n), "seconds": round(time.monotonic() - started, 1),
            **row}


def order(row: dict, space: str) -> float:
    return row["phi"] if space == "bipartite" else 1.0 - row["action_per_node"]


def beta_tilde(beta: float, n: int, dimension: int) -> float:
    return beta * n ** (1 - 2 / dimension)


def beta_tilde_as_printed(beta: float, n: int, dimension: int) -> float:
    return beta * n ** (2 / dimension - 1)


def log_g(beta: float | None, n: int, dimension: int, convention=beta_tilde) -> float | None:
    return round(-math.log(convention(beta, n, dimension)), 3) if beta else None


MOVING_AT_LEAST = 0.05


def transition(cooling: list[dict], space: str) -> dict:
    moving = [r for r in cooling if r["acceptance"] >= MOVING_AT_LEAST] or cooling
    peak = max(moving, key=lambda r: r["specific_heat"])
    half = next((r["beta"] for r in cooling if order(r, space) >= 0.5), None)
    rises = [((order(b, space) - order(a, space)) / math.log(b["beta"] / a["beta"]), math.sqrt(a["beta"] * b["beta"]))
             for a, b in zip(cooling, cooling[1:], strict=False)]
    steepest = max(rises)[1] if rises else None
    return {"beta_at_peak_heat": peak["beta"], "peak_heat": peak["specific_heat"], "beta_at_half_order": half,
            "beta_at_steepest": round(steepest, 4) if steepest else None}


def summarize(rows: list[dict]) -> list[dict]:
    groups = collections.defaultdict(list)
    for r in rows:
        if "error" not in r:
            groups[(r["model"], r["n"], r.get("sweeps"))].append(r)
    cells = []
    for (model, n, sweeps), group in sorted(groups.items(), key=lambda kv: (KTB_MODELS[kv[0][0]]["dimension"],
                                                                           kv[0][1], kv[0][2] or 0)):
        spec = KTB_MODELS[model]
        space = spec["space"]

        def median(values):
            values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            return round(statistics.median(values), 4) if values else None
        marks = [transition(r["cooling"], space) for r in group]
        curve, moving = collections.defaultdict(list), collections.defaultdict(list)
        for r in group:
            for c in r["cooling"]:
                curve[c["beta"]].append(c["specific_heat"])
                moving[c["beta"]].append(c["acceptance"] >= MOVING_AT_LEAST)
        betas_moving = [b for b in curve if all(moving[b])] or list(curve)
        mean_peak = max(betas_moving, key=lambda b: statistics.fmean(curve[b]))
        cell = {"model": model, "dimension": spec["dimension"], "n": n, "sweeps": sweeps, "seeds": len(group),
                "classical_seeds": sum(1 for r in group if r["end"]["classical"]),
                "end_order": median([order(r["end"], space) for r in group]),
                "end_action_per_node": median([r["end"]["action_per_node"] for r in group]),
                "beta_at_peak_heat": median([m["beta_at_peak_heat"] for m in marks]),
                "beta_at_mean_peak_heat": mean_peak,
                "mean_peak_heat": round(statistics.fmean(curve[mean_peak]), 4),
                "beta_at_half_order": median([m["beta_at_half_order"] for m in marks]),
                "beta_at_steepest": median([m["beta_at_steepest"] for m in marks]),
                "d_s": median([r["reading"].get("d_s") for r in group]),
                "curvature": median([r["reading"].get("curvature") for r in group]),
                "half_volume_radius": median([r["reading"].get("half_volume_radius") for r in group]),
                "giant_share": median([r["reading"].get("giant_share") for r in group]),
                **{probe: median([r["reading"].get(probe) for r in group]) for probe in ("d_V", "d_B", "d_w")}}
        if space == "cubic":
            cell["ladders"] = dict(collections.Counter(str(r["end"].get("ladder")) for r in group))
            cell["end_triangles"] = median([r["end"].get("triangles") for r in group])
            cell["end_triangles_per_node"] = round(cell["end_triangles"] / n, 4)
        else:
            half, dimension = cell["beta_at_half_order"], spec["dimension"]
            cell["end_phi"] = cell["end_order"]
            cell["log_g_at_half_order"] = log_g(half, n, dimension)
            cell["log_g_at_mean_peak_heat"] = log_g(mean_peak, n, dimension)
            cell["log_g_at_steepest"] = log_g(cell["beta_at_steepest"], n, dimension)
            cell["log_g_as_printed_at_half_order"] = log_g(half, n, dimension, beta_tilde_as_printed)
        cell["classical_share"] = round(cell["classical_seeds"] / len(group), 4)
        if space == "cubic":
            single = cell["ladders"].get("prism", 0) + cell["ladders"].get("moebius", 0)
            cell["single_ladder_share"] = round(single / len(group), 4)
            cell["prism_share"] = round(cell["ladders"].get("prism", 0) / single, 4) if single else None
        classical = next((r.get("classical_readings") for r in group if r.get("classical_readings")), None) or {}
        for name, reading in classical.items():
            cell[f"{name}_d_s"] = reading.get("d_s")
            cell[f"{name}_radius"] = reading.get("half_volume_radius")
        reference = [reading.get("d_s") for reading in classical.values() if isinstance(reading.get("d_s"), float)]
        if reference and isinstance(cell["d_s"], float):
            cell["d_s_minus_classical"] = round(cell["d_s"] - statistics.fmean(reference), 4)
        heated = [r for r in group if r.get("heating")]
        if heated:
            loops = []
            for r in heated:
                back = {h["beta"]: order(h, space) for h in r["heating"]}
                loops.append(max(abs(back[c["beta"]] - order(c, space)) for c in r["cooling"]))
            cell["largest_loop"] = median(loops)
        cells.append(cell)
    return cells


def render(cells: list[dict]) -> str:
    lines = [f"{'model':6} {'D':>2} {'N':>6} {'sweeps':>6} {'seeds':>5} {'zero A':>6} {'order':>6} {'beta1/2':>7} {'betaC':>6} "
             f"{'logG':>6} {'d_s':>5} {'(classical)':>13} {'giant':>5} {'loop':>5}  ends"]
    for c in cells:
        def f(key, form, width, c=c):
            v = c.get(key)
            return (format(v, form) if isinstance(v, (int, float)) and not isinstance(v, bool) else "-").rjust(width)
        classical = "/".join(format(c[k], ".2f") for k in ("torus_d_s", "prism_d_s", "moebius_d_s")
                             if isinstance(c.get(k), (int, float)))
        ends = ", ".join(f"{k} {v}" for k, v in sorted(c.get("ladders", {}).items()))
        lines.append(f"{c['model']:6} {c['dimension']:>2} {c['n']:>6,} {f('sweeps', 'd', 6)} {c['seeds']:>5} "
                     f"{str(c['classical_seeds']) + '/' + str(c['seeds']):>6} {f('end_order', '.3f', 6)} "
                     f"{f('beta_at_half_order', '.3f', 7)} {f('beta_at_mean_peak_heat', '.2f', 6)} "
                     f"{f('log_g_at_half_order', '.2f', 6)} {f('d_s', '.2f', 5)} {(classical or '-'):>13} "
                     f"{f('giant_share', '.2f', 5)} {f('largest_loop', '.3f', 5)}  {ends}")
    lines.append("  zero A: seeds that reached zero action; order: phi (2019) or 1 - A/N (2021) at the cold end; "
                 "beta1/2: where the order passed one half; betaC: the peak of the seeds' mean specific heat; logG: "
                 "the 2019 paper's log G at beta1/2, G = 1/(beta N^(1 - 2/D)); d_s beside the classical configurations' (torus, or prism/"
                 "Moebius); giant: the largest component's share; loop: the largest gap in order between cooling and "
                 "heating back; ends: the 2021 model's classical ends")
    return "\n".join(lines)


def judge(cells: list[dict], criterion: dict) -> list[dict]:
    by = {(c["model"], c["n"], c.get("sweeps")): c for c in cells}
    plain = {(c["model"], c["n"]): c for c in cells}

    def cell(model: str, n: int, sweeps) -> dict:
        return (by.get((model, n, sweeps)) if sweeps is not None else plain.get((model, n))) or {}

    verdicts = []
    for p in criterion["predictions"]:
        values = {n: cell(p["model"], n, p.get("sweeps")).get(p["reading"]) for n in p["sizes"]}
        rule = p["rule"]
        if "above" in rule:
            below = {n: cell(p["model"], n, rule["above"]["sweeps"]).get(p["reading"]) for n in p["sizes"]}
            values = {n: values[n] for n in p["sizes"]}
            numbers = list(values.values()) + list(below.values())
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in numbers):
                verdict = "unread"
            else:
                verdict = "held" if all(values[n] > below[n] for n in p["sizes"]) else "missed"
            verdicts.append({"id": p["id"], "verdict": verdict, "expected": p.get("expect", "held"),
                             "as_expected": verdict == p.get("expect", "held"), "values": values, "against": below})
            continue
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values.values()):
            verdict = "unread"
        elif rule.get("alternates"):
            seq = [values[n] for n in p["sizes"]]
            verdict = "held" if all((a - 0.5) * (b - 0.5) < 0 for a, b in zip(seq, seq[1:], strict=False)) else "missed"
        else:
            verdict = "held" if all(_meets(v, rule) for v in values.values()) else "missed"
        verdicts.append({"id": p["id"], "verdict": verdict, "expected": p.get("expect", "held"),
                         "as_expected": verdict == p.get("expect", "held"), "values": values})
    return verdicts


def _meets(value: float, rule: dict) -> bool:
    if "between" in rule:
        return rule["between"][0] <= value <= rule["between"][1]
    if "at_least" in rule:
        return value >= rule["at_least"]
    if "at_most" in rule:
        return value <= rule["at_most"]
    if "equals" in rule:
        return value == rule["equals"]
    raise ValueError(f"a rule this harness cannot read: {rule}")


def render_verdicts(verdicts: list[dict], criterion: dict) -> str:
    claims = {p["id"]: p for p in criterion["predictions"]}
    lines = [f"{sum(v['as_expected'] for v in verdicts)} of {len(verdicts)} as the criterion expected; "
             f"{sum(v['verdict'] == 'held' for v in verdicts)} rules held"]
    for v in verdicts:
        p = claims[v["id"]]
        shown = ", ".join(f"{n}: {x}" for n, x in v["values"].items())
        mark = "  " if v["as_expected"] else "! "
        at = f" at {p['sweeps']} sweeps" if p.get("sweeps") else ""
        lines.append(f"{mark}{v['id']:4} {v['verdict']:6} (expected {v['expected']}) {p['model']}{at} {p['reading']} "
                     f"{json.dumps(p['rule'])} ({shown})")
    return "\n".join(lines)


def _run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--models", default=",".join(KTB_MODELS), help=f"of {', '.join(KTB_MODELS)}")
    parser.add_argument("--sizes", default="200,1024",
                        help="N for every model given, or model:N,N;model:N; NxK runs K seeds at N")
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--hysteresis", action="store_true", help="heat each run back after cooling it")
    parser.add_argument("--hysteresis-at", default="", help="heat back only the runs at these N")
    parser.add_argument("--sweeps", type=int, help="sweeps at each temperature step, for every run (the schedule's own "
                        "by default)")


def tasks_of(args) -> tuple[list[dict], dict]:
    models = [m for m in args.models.split(",") if m]
    unknown = [m for m in models if m not in KTB_MODELS]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; the models are {', '.join(KTB_MODELS)}")
    plan = parse_sizes(args.sizes, models)
    heat = {int(n) for n in args.hysteresis_at.split(",") if n}
    override = {"sweeps": int(args.sweeps)} if args.sweeps else {}
    tasks = [{"model": m, "n": n, "seed": seed, "hysteresis": args.hysteresis or n in heat,
              **({"schedule": override} if override else {})}
             for m in models for n, k in plan[m] for seed in range(args.first_seed, args.first_seed + (k or args.seeds))]
    about = {"models": models, "sizes": {m: [n for n, _ in plan[m]] for m in models}, "first_seed": args.first_seed,
             "seeds": args.seeds, "seeds_at": {m: {n: k for n, k in plan[m] if k} for m in models},
             "sweeps": override.get("sweeps"), "hysteresis": args.hysteresis, "hysteresis_at": sorted(heat)}
    return tasks, about


def planned(criterion: dict) -> tuple[list[dict], list[dict]]:
    parser = argparse.ArgumentParser(add_help=False)
    _run_options(parser)
    tasks, abouts = [], []
    for line in criterion.get("run") or []:
        words = shlex.split(line)
        if "tools/replication.py" not in words or "--read" in words:
            continue
        args, _ = parser.parse_known_args(words[words.index("tools/replication.py") + 1:])
        found, about = tasks_of(args)
        tasks += found
        abouts.append(about)
    seen, unique = set(), []
    for task in tasks:
        key = (task["model"], task["n"], task["seed"], (task.get("schedule") or {}).get("sweeps"), task["hysteresis"])
        if key not in seen:
            seen.add(key)
            unique.append(task)
    return unique, abouts


def run_key(run: dict) -> tuple:
    if "sweeps" in run:
        sweeps = run["sweeps"]
    else:
        schedule = dict(SCHEDULES[KTB_MODELS[run["model"]]["space"]], **(run.get("schedule") or {}))
        sweeps = sweeps_at(schedule, int(run["n"]))
    return run["model"], int(run["n"]), int(run["seed"]), int(sweeps)


def written(path: Path, document: dict) -> None:
    fresh = path.with_name(path.name + ".writing")
    fresh.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    fresh.replace(path)


def against_rows(criterion: dict) -> list[dict]:
    paths = criterion.get("against") or []
    paths = [paths] if isinstance(paths, str) else paths
    return [r for path in paths for r in json.loads((ROOT / path).read_text(encoding="utf-8"))["rows"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/replication.py: see docs/TOOLS.md")
    _run_options(parser)
    parser.add_argument("--plan", help="a committed criterion: run every one of its run lines in one pool")
    parser.add_argument("--max-n", type=int, help="only the runs at N at most this")
    parser.add_argument("--min-n", type=int, help="only the runs at N at least this")
    parser.add_argument("--largest-first", action="store_true",
                        help="start the longest runs first (the shortest first by default, so results come soonest)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--output", help="default var/readings/replication_ktb_<utc>.json")
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
            print(render_verdicts(judge(cells, criterion), criterion))
        return 0
    criterion = None
    if args.plan:
        criterion = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        tasks, abouts = planned(criterion)
        about = {"plan": args.plan, "runs": abouts}
        args.judge = args.judge or args.plan
    else:
        try:
            tasks, about = tasks_of(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.judge and criterion is None:
        criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
    tasks = [t for t in tasks if (args.max_n is None or t["n"] <= args.max_n)
             and (args.min_n is None or t["n"] >= args.min_n)]
    tasks = sorted(tasks, key=lambda t: ((-1 if args.largest_first else 1) * cost(t), t["model"], t["seed"]))
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    output = Path(args.output) if args.output else ROOT / "var" / "readings" / f"replication_ktb_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    kept, resumed = [], []
    if output.exists():
        earlier = json.loads(output.read_text(encoding="utf-8"))
        if earlier.get("contract") != REPLICATION_CONTRACT or not isinstance(earlier.get("rows"), list):
            parser.error(f"{output} exists and is not a replication file: choose another --output")
        kept = [r for r in earlier["rows"] if "error" not in r]
        done_keys = {run_key(r) for r in kept}
        resumed = list(earlier.get("resumed_utc") or []) + [stamp]
        stamp = str(earlier.get("started_utc") or stamp)
        skipped = [t for t in tasks if run_key(t) in done_keys]
        tasks = [t for t in tasks if run_key(t) not in done_keys]
        print(f"replication: {output} holds {len(kept)} finished run(s); they are kept, {len(skipped)} of this plan's "
              f"are not run again", flush=True)
    print(f"replication: {len(tasks)} runs ("
          + "; ".join(f"{t['model']} N {t['n']:,} seed {t['seed']}"
                      + (f" at {t['schedule']['sweeps']} sweeps" if t.get("schedule") else "") for t in tasks[:4])
          + ("; ..." if len(tasks) > 4 else "") + f") on {args.workers} worker(s)", flush=True)
    started, rows = time.monotonic(), list(kept)
    planned_runs = len(kept) + len(tasks)
    extra = against_rows(criterion) if criterion else []

    def document(complete: bool) -> dict:
        cells = summarize(rows)
        out = {"contract": REPLICATION_CONTRACT, "paper": "ktb", "run_utc": time.strftime("%Y-%m-%dT%H-%M-%SZ",
                                                                                          time.gmtime()),
               "started_utc": stamp, "resumed_utc": resumed, "complete": complete, "runs_done": len(rows),
               "runs_planned": planned_runs,
               "seconds": round(time.monotonic() - started, 1),
               "models": {m: KTB_MODELS[m] for m in sorted({r["model"] for r in rows} | {t["model"] for t in tasks})},
               **about,
               "schedules": {space: dict(SCHEDULES[space], betas=betas(SCHEDULES[space])) for space in SCHEDULES},
               "cells": cells, "rows": sorted(rows, key=lambda r: (r["dimension"], r["n"], r.get("sweeps") or 0,
                                                                   r["seed"]))}
        if criterion is not None:
            out["criterion"] = {"path": args.judge, "verdicts": judge(summarize(rows + extra), criterion)}
        return out

    try:
        from partial_rows import kept_on_failure, partial_path
    except ImportError:
        from tools.partial_rows import kept_on_failure, partial_path
    with kept_on_failure(rows, partial_path(args.output, "replication_ktb")):
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for done, future in enumerate(as_completed([pool.submit(run_one, t) for t in tasks]), start=1):
                row = future.result()
                rows.append(row)
                print(f"  {len(rows)}/{planned_runs} {row['model']} N={row['n']:,} seed {row['seed']}"
                      + (f" at {row.get('sweeps')} sweeps" if row.get("sweeps") else "") + ": "
                      + (row["error"] if "error" in row else
                         f"A/N {row['end']['action_per_node']}, zero action {row['end']['classical']}"
                         + (f" ({row['end']['ladder']})" if "ladder" in row["end"] else "")
                         + f", d_s {row['reading'].get('d_s')}, {row['seconds']} s"), flush=True)
                if done < len(tasks):
                    written(output, document(False))
    final = document(True)
    written(output, final)
    print(render(final["cells"]))
    if criterion is not None:
        print(render_verdicts(final["criterion"]["verdicts"], criterion))
    print(f"wrote {output}")
    return 0


def parse_sizes(text: str, models: list[str]) -> dict[str, list[tuple[int, int | None]]]:
    def sizes(values: str) -> list[tuple[int, int | None]]:
        out = []
        for token in values.split(","):
            if token.strip():
                n, _, k = token.strip().partition("x")
                out.append((int(n), int(k) if k else None))
        return out
    if ":" not in text:
        return {m: sizes(text) for m in models}
    plan = {m: [] for m in models}
    for part in text.split(";"):
        if part.strip():
            name, _, values = part.partition(":")
            if name.strip() in plan:
                plan[name.strip()] = sizes(values)
    return plan


def cost(task: dict) -> float:
    spec = KTB_MODELS[task["model"]]
    schedule = dict(SCHEDULES[spec["space"]], **(task.get("schedule") or {}))
    edges = task["n"] * spec["degree"] / 2
    return edges * sweeps_at(schedule, task["n"]) * len(betas(schedule)) * spec["degree"] ** 2 * (
        2 if task.get("hysteresis") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
