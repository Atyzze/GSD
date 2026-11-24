from __future__ import annotations
import math
import os
import time

from graph_scale_dynamics.domain.randomness import STREAM_VERSION, stream_id
from graph_scale_dynamics.dsl.dsl import (
    COOLING_SHAPE, LOCAL_MOVES, coefficient, cooling_schedule, dynamics_regime, dynamics_settings, fingerprint,
    local_move_problem)
from graph_scale_dynamics.engine.summaries import trajectory_diagnostics

ENGINE_VERSION = "engine-3.3.0"
COMPATIBLE_ENGINE_VERSIONS = frozenset({"engine-2.7.0", "engine-2.7.1", "engine-2.8.0", "engine-3.0.0",
                                        "engine-3.1.0", "engine-3.2.0", ENGINE_VERSION})

EXACT_ZERO_SHARE = 1e-12


def exact_zero(change: float, magnitude: float) -> float:
    return 0.0 if abs(change) <= EXACT_ZERO_SHARE * magnitude else change


def swap_terms(ctx) -> list:
    return [(term["op"], coefficient(term, ctx.n)) for term in ctx.candidate_spec["terms"] if term["op"] not in NODE_OPS]


def swap_change(terms: list, moved: list) -> float:
    change = magnitude = 0.0
    for op, coeff in terms:
        part = coeff * (((moved[0][op] + moved[1][op]) + moved[2][op]) + moved[3][op])
        change += part
        magnitude += abs(part)
    return exact_zero(change, magnitude)


class _Fenwick:

    def __init__(self, values: list[int]):
        self.n = len(values)
        self.tree = [0] * (self.n + 1)
        for index, value in enumerate(values, 1):
            self.tree[index] += int(value)
            parent = index + (index & -index)
            if parent <= self.n:
                self.tree[parent] += self.tree[index]

    def add(self, index: int, delta: int) -> None:
        cursor = index + 1
        while cursor <= self.n:
            self.tree[cursor] += int(delta)
            cursor += cursor & -cursor

    def total(self) -> int:
        total = 0
        cursor = self.n
        while cursor:
            total += self.tree[cursor]
            cursor -= cursor & -cursor
        return total

    def find_by_order(self, order: int) -> int:
        if order < 0 or order >= self.total():
            raise IndexError("weighted order outside Fenwick total")
        index = 0
        bit = 1 << (self.n.bit_length() - 1) if self.n else 0
        remaining = order
        while bit:
            nxt = index + bit
            if nxt <= self.n and self.tree[nxt] <= remaining:
                index = nxt
                remaining -= self.tree[nxt]
            bit >>= 1
        return index


class GraphState:

    def __init__(self, n: int):
        if n < 1:
            raise ValueError("graph size must be positive")
        self.n = n
        self.adj: list[set[int]] = [set() for _ in range(n)]
        self.edges: set[tuple[int, int]] = set()
        self.edge_list: list[tuple[int, int]] = []
        self.edge_index: dict[tuple[int, int], int] = {}
        self.non_degree = [n - 1 for _ in range(n)]
        self._non_degree_tree = _Fenwick(self.non_degree)
        self.non_edge_fast_path_hits = 0
        self.non_edge_exact_fallbacks = 0
        self.ledgers = {"edge_count": 0.0, "degree_square_sum": 0.0, "wedge_count": 0.0,
                        "triangle_count": 0.0, "triangle_edge_overlap": 0.0,
                        "square_count": 0.0, "square_edge_overlap": 0.0,
                        "induced_square_count": 0.0, "degree_neighbor_gradient": 0.0,
                        "ollivier_curvature": 0.0}
        self.edge_cycles: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._last_curvature: tuple | None = None
        self.edge_square_counts: dict[tuple[int, int], int] = {}
        self._last_square_key: tuple[int, int, bool] | None = None
        self._last_square_paths: list[tuple[int, int]] | None = None
        self._last_square_multiplicity: dict[tuple[int, int], int] | None = None
        self.late: tuple[set, set] | None = None
        self.required_ops = frozenset(self.ledgers)
        self.work = 0
        self.parts = [0, 0, 0, 0, 0]

    def require_ops(self, ops) -> None:
        wanted = {op for op in ops if op in self.ledgers}
        self.required_ops = frozenset(wanted)

    def degree(self, v: int) -> int:
        return len(self.adj[v])

    def _read(self, lists: int, entries: int) -> None:
        self.work += entries
        self.parts[2] += lists
        self.parts[3] += entries

    def _scan(self, entries: int) -> None:
        self.work += entries
        self.parts[3] += entries

    def _units(self, count: int) -> None:
        self.work += count
        self.parts[4] += count

    def tests_edge(self, u: int, v: int) -> bool:
        self.parts[4] += 1
        return v in self.adj[u]

    def counted(self) -> list[int]:
        return [self.work, *self.parts]

    def sample_non_edge(self, rng) -> tuple[int, int]:
        oriented_missing = self._non_degree_tree.total()
        if oriented_missing <= 0:
            raise LookupError("complete graph has no non-edge")
        for _ in range(16):
            self._units(1)
            u = rng.randrange(self.n)
            v = rng.randrange(self.n - 1) if self.n > 1 else 0
            if v >= u:
                v += 1
            if v != u and v not in self.adj[u]:
                self.non_edge_fast_path_hits += 1
                return (u, v) if u < v else (v, u)
        self.non_edge_exact_fallbacks += 1
        u = self._non_degree_tree.find_by_order(rng.randrange(oriented_missing))
        missing = self.non_degree[u]
        if missing <= 0:
            raise RuntimeError("complement-degree sampler selected a saturated vertex")
        for _ in range(64):
            self._units(1)
            v = rng.randrange(self.n)
            if v != u and v not in self.adj[u]:
                return (u, v) if u < v else (v, u)
        rank = rng.randrange(missing)
        for v in range(self.n):
            self._units(1)
            if v == u or v in self.adj[u]:
                continue
            if rank == 0:
                return (u, v) if u < v else (v, u)
            rank -= 1
        raise RuntimeError("complement-degree ledger disagrees with adjacency")

    @staticmethod
    def _edge(u: int, v: int) -> tuple[int, int]:
        return (u, v) if u < v else (v, u)

    def _square_paths(self, u: int, v: int) -> list[tuple[int, int]]:
        nu = self.adj[u] - {v}
        nv = self.adj[v] - {u}
        self._read(2 + len(nu), len(self.adj[u]) + len(self.adj[v]) + sum(len(self.adj[x]) for x in nu))
        paths: list[tuple[int, int]] = []
        for x in nu:
            for y in self.adj[x] & nv:
                paths.append((x, y))
        return paths

    def _square_multiplicity(self, u: int, v: int,
                             paths: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
        multiplicity: dict[tuple[int, int], int] = {}
        get = multiplicity.get
        for x, y in paths:
            edge = (u, x) if u < x else (x, u)
            multiplicity[edge] = get(edge, 0) + 1
            edge = (x, y) if x < y else (y, x)
            multiplicity[edge] = get(edge, 0) + 1
            edge = (y, v) if y < v else (v, y)
            multiplicity[edge] = get(edge, 0) + 1
        return multiplicity

    def _square_overlap_delta(self, u: int, v: int, adding: bool,
                              paths: list[tuple[int, int]],
                              multiplicity: dict[tuple[int, int], int] | None = None) -> float:
        if multiplicity is None:
            multiplicity = self._square_multiplicity(u, v, paths)
        s = len(paths)
        counts = self.edge_square_counts
        if adding:
            delta = s * (s - 1) / 2
            for edge, m in multiplicity.items():
                q = counts.get(edge, 0)
                delta += m * q + m * (m - 1) / 2
            return float(delta)
        delta = -s * (s - 1) / 2
        for edge, m in multiplicity.items():
            q = counts.get(edge, 0)
            delta += -m * q + m * (m + 1) / 2
        return float(delta)

    def _update_square_edge_counts(self, u: int, v: int, adding: bool,
                                   paths: list[tuple[int, int]],
                                   multiplicity: dict[tuple[int, int], int] | None = None) -> None:
        if multiplicity is None:
            multiplicity = self._square_multiplicity(u, v, paths)
        toggled = self._edge(u, v)
        if adding:
            for edge, m in multiplicity.items():
                self.edge_square_counts[edge] = self.edge_square_counts.get(edge, 0) + m
            if paths:
                self.edge_square_counts[toggled] = len(paths)
            else:
                self.edge_square_counts.pop(toggled, None)
            return
        for edge, m in multiplicity.items():
            value = self.edge_square_counts.get(edge, 0) - m
            if value > 0:
                self.edge_square_counts[edge] = value
            else:
                self.edge_square_counts.pop(edge, None)
        self.edge_square_counts.pop(toggled, None)

    def op_deltas(self, u: int, v: int, adding: bool) -> dict[str, float]:
        self.work += 1
        self.parts[0] += 1
        sign = 1.0 if adding else -1.0
        du, dv = len(self.adj[u]), len(self.adj[v])
        if not adding:
            du -= 1
            dv -= 1
        required = self.required_ops
        deltas = {"edge_count": sign,
                  "degree_square_sum": sign * (2 * du + 1 + 2 * dv + 1),
                  "wedge_count": sign * (du + dv),
                  "triangle_count": 0.0,
                  "triangle_edge_overlap": 0.0,
                  "square_count": 0.0,
                  "square_edge_overlap": 0.0,
                  "induced_square_count": 0.0,
                  "degree_neighbor_gradient": 0.0,
                  "ollivier_curvature": 0.0}

        if "ollivier_curvature" in required:
            delta, changes, own = self._curvature_delta(u, v, adding)
            deltas["ollivier_curvature"] = float(delta)
            self._last_curvature = ((u, v, adding), changes, own)
        else:
            self._last_curvature = None

        if "degree_neighbor_gradient" in required:
            read = len(self.adj[u]) + len(self.adj[v])
            self._read(2, read)
            self.parts[2] += read
            gradient = sign * (du - dv) ** 2
            for x in self.adj[u] - {v}:
                gradient += sign * (2 * (du - len(self.adj[x])) + 1)
            for y in self.adj[v] - {u}:
                gradient += sign * (2 * (dv - len(self.adj[y])) + 1)
            deltas["degree_neighbor_gradient"] = float(gradient)

        if not (required & _NEIGHBOURHOOD_OPS):
            self._last_square_key = None
            self._last_square_paths = None
            self._last_square_multiplicity = None
            return deltas

        self._read(2, len(self.adj[u]) + len(self.adj[v]))
        common_nodes = self.adj[u] & self.adj[v]
        common = len(common_nodes)
        deltas["triangle_count"] = sign * common

        square_required = bool(required & _SQUARE_PATH_OPS)
        square_paths = self._square_paths(u, v) if square_required else []
        if square_required:
            self._last_square_key = (u, v, adding)
            self._last_square_paths = square_paths
            self._last_square_multiplicity = None
        else:
            self._last_square_key = None
            self._last_square_paths = None
            self._last_square_multiplicity = None

        if "square_count" in required:
            deltas["square_count"] = sign * len(square_paths)

        if "induced_square_count" in required:
            self._units(2 * len(square_paths) + common * (common - 1) // 2)
            boundary = sum(1 for x, y in square_paths
                           if y not in self.adj[u] and x not in self.adj[v])
            common_list = list(common_nodes)
            diagonal = 0
            for i, x in enumerate(common_list):
                for y in common_list[i + 1:]:
                    if y not in self.adj[x]:
                        diagonal += 1
            deltas["induced_square_count"] = sign * (boundary - diagonal)

        if "square_edge_overlap" in required:
            multiplicity = self._square_multiplicity(u, v, square_paths)
            self._units(3 * len(square_paths) + len(multiplicity))
            self._last_square_multiplicity = multiplicity
            deltas["square_edge_overlap"] = self._square_overlap_delta(
                u, v, adding, square_paths, multiplicity)

        if "triangle_edge_overlap" in required:
            self._read(4 * common, sum(len(self.adj[u]) + len(self.adj[v]) + 2 * len(self.adj[w]) for w in common_nodes))
            if adding:
                triangle_overlap = common * (common - 1) / 2
                for w in common_nodes:
                    triangle_overlap += len(self.adj[u] & self.adj[w])
                    triangle_overlap += len(self.adj[v] & self.adj[w])
            else:
                triangle_overlap = -common * (common - 1) / 2
                for w in common_nodes:
                    triangle_overlap -= max(0, len(self.adj[u] & self.adj[w]) - 1)
                    triangle_overlap -= max(0, len(self.adj[v] & self.adj[w]) - 1)
            deltas["triangle_edge_overlap"] = triangle_overlap
        return deltas

    def _cycle_paths(self, u: int, v: int):
        nu = self.adj[u] - {v}
        nv = self.adj[v] - {u}
        entries, lists = len(self.adj[u]) + len(self.adj[v]), 2
        for x in nu:
            entries += 2 * len(self.adj[x])
            lists += 2
            for z in self.adj[x]:
                if z != u and z != v:
                    entries += len(self.adj[z])
                    lists += 1
        self._read(lists, entries)
        triangles = list(nu & nv)
        squares = [(x, y) for x in nu for y in self.adj[x] & nv]
        pentagons = [(x, z, y) for x in nu for z in self.adj[x] - {u, v} for y in self.adj[z] & nv if y != x]
        return triangles, squares, pentagons

    def _curvature_delta(self, u: int, v: int, adding: bool):
        sign = 1 if adding else -1
        triangles, squares, pentagons = self._cycle_paths(u, v)
        changes: dict[tuple[int, int], list[int]] = {}

        def bump(a: int, b: int, index: int) -> None:
            edge = (a, b) if a < b else (b, a)
            entry = changes.get(edge)
            if entry is None:
                entry = changes[edge] = [0, 0, 0]
            entry[index] += sign

        for w in triangles:
            bump(u, w, 0)
            bump(w, v, 0)
        for x, y in squares:
            bump(u, x, 1)
            bump(x, y, 1)
            bump(y, v, 1)
        for x, z, y in pentagons:
            bump(u, x, 2)
            bump(x, z, 2)
            bump(z, y, 2)
            bump(y, v, 2)
        affected = set(changes)
        affected.update((u, x) if u < x else (x, u) for x in self.adj[u] if x != v)
        affected.update((v, y) if v < y else (y, v) for y in self.adj[v] if y != u)
        self._read(2, len(self.adj[u]) + len(self.adj[v]))
        self._units(len(affected))

        def after(node: int) -> int:
            return len(self.adj[node]) + (sign if node in (u, v) else 0)

        delta = 0
        for edge in affected:
            a, b = edge
            before = self.edge_cycles.get(edge, (0, 0, 0))
            moved = changes.get(edge, (0, 0, 0))
            delta += scaled_curvature(before[0] + moved[0], before[1] + moved[1], before[2] + moved[2],
                                      after(a), after(b))
            delta -= scaled_curvature(*before, len(self.adj[a]), len(self.adj[b]))
        own = (len(triangles), len(squares), len(pentagons))
        if adding:
            delta += scaled_curvature(*own, after(u), after(v))
        else:
            delta -= scaled_curvature(*own, len(self.adj[u]), len(self.adj[v]))
        return delta, changes, own

    def _update_edge_cycles(self, u: int, v: int, adding: bool, changes, own) -> None:
        for edge, moved in changes.items():
            before = self.edge_cycles.get(edge, (0, 0, 0))
            now = (before[0] + moved[0], before[1] + moved[1], before[2] + moved[2])
            if any(now):
                self.edge_cycles[edge] = now
            else:
                self.edge_cycles.pop(edge, None)
        toggled = self._edge(u, v)
        if adding and any(own):
            self.edge_cycles[toggled] = tuple(own)
        else:
            self.edge_cycles.pop(toggled, None)

    def apply(self, u: int, v: int, adding: bool, deltas: dict[str, float]) -> None:
        self.work += 1
        self.parts[1] += 1
        if "ollivier_curvature" in self.required_ops:
            cached = self._last_curvature
            if cached is not None and cached[0] == (u, v, adding):
                _, changes, own = cached
            else:
                _, changes, own = self._curvature_delta(u, v, adding)
            self._update_edge_cycles(u, v, adding, changes, own)
        self._last_curvature = None
        if "square_edge_overlap" in self.required_ops:
            if self._last_square_key == (u, v, adding) and self._last_square_paths is not None:
                paths = self._last_square_paths
                multiplicity = self._last_square_multiplicity
            else:
                paths = self._square_paths(u, v)
                multiplicity = None
            self._update_square_edge_counts(u, v, adding, paths, multiplicity)
        self._last_square_key = None
        self._last_square_paths = None
        self._last_square_multiplicity = None
        if adding:
            self.adj[u].add(v)
            self.adj[v].add(u)
            self.non_degree[u] -= 1
            self.non_degree[v] -= 1
            self._non_degree_tree.add(u, -1)
            self._non_degree_tree.add(v, -1)
            edge = (u, v) if u < v else (v, u)
            self.edges.add(edge)
            self.edge_index[edge] = len(self.edge_list)
            self.edge_list.append(edge)
            if self.late is not None:
                added, removed = self.late
                if edge in removed:
                    removed.discard(edge)
                else:
                    added.add(edge)
        else:
            self.adj[u].discard(v)
            self.adj[v].discard(u)
            self.non_degree[u] += 1
            self.non_degree[v] += 1
            self._non_degree_tree.add(u, 1)
            self._non_degree_tree.add(v, 1)
            edge = (u, v) if u < v else (v, u)
            self.edges.discard(edge)
            index = self.edge_index.pop(edge)
            last = self.edge_list[-1]
            if index != len(self.edge_list) - 1:
                self.edge_list[index] = last
                self.edge_index[last] = index
            self.edge_list.pop()
            if self.late is not None:
                added, removed = self.late
                if edge in added:
                    added.discard(edge)
                else:
                    removed.add(edge)
        for key, delta in deltas.items():
            self.ledgers[key] += delta


def scaled_curvature(triangles: int, squares: int, pentagons: int, da: int, db: int) -> int:
    low, high = (da, db) if da <= db else (db, da)
    t, s, p = int(triangles), int(squares), int(pentagons)
    return (t * high
            - max(0, low * high - (1 + t + s) * low - high)
            - max(t * high - t * low, low * high - (1 + t + s + p) * low - high))


NODE_OPS = ("degree_anchor", "degree_anchor_abs", "degree_cube_sum", "degree_fourth_sum")
_SQUARE_PATH_OPS = frozenset({"square_count", "square_edge_overlap", "induced_square_count"})
_NEIGHBOURHOOD_OPS = frozenset({
    "triangle_count", "triangle_edge_overlap", "square_count", "square_edge_overlap",
    "induced_square_count", "degree_neighbor_gradient",
})


def _term_delta_energy(spec: dict, n: int, deltas: dict[str, float], node_energy_delta: float,
                       node_magnitude: float = 0.0) -> float:
    energy = node_energy_delta
    magnitude = node_magnitude
    for term in spec["terms"]:
        op = term["op"]
        if op in NODE_OPS:
            continue
        part = coefficient(term, n) * deltas[op]
        energy += part
        magnitude += abs(part)
    return exact_zero(energy, magnitude)


GIVEN_START_MEAN_DEGREE = 8

LOCAL_WALK = "local_walk"
START_KERNELS = (LOCAL_WALK,)
LOCAL_WALK_DELETE, LOCAL_WALK_SWAP_BELOW, LOCAL_WALK_ADD = 0.2, 0.6, 0.4
LOCAL_WALK_STEPS = (2, 3)


def given_start_kernel(start) -> str | None:
    kernel = start.get("kernel") if isinstance(start, dict) else None
    if kernel is None:
        return None
    if str(kernel) not in START_KERNELS:
        raise ValueError(f"given_start kernel {kernel!r} is not one this engine has ({', '.join(START_KERNELS)})")
    return str(kernel)


def given_start_name(start) -> str:
    name = start.get("family") if isinstance(start, dict) else None
    return f"family_{name}" if name else f"erdos_renyi_mean_degree_{GIVEN_START_MEAN_DEGREE}"


def declared_given(ctx, runner, edges, state, energy, apply_edge):
    init_declared = getattr(runner, "init_declared", None)
    if init_declared is not None:
        return init_declared(ctx, edges, state, energy)
    for u, v in edges:
        if v in state.adj[u]:
            continue
        deltas, delta_h = apply_edge(state, u, v, True, energy)
        state.apply(u, v, True, deltas)
        energy += delta_h
    return state, energy


def given_start_edges(start, n: int):
    if not isinstance(start, dict):
        return None
    edges = start.get("edges")
    if edges is None:
        if start.get("family"):
            raise ValueError(
                f"given_start names family {start['family']!r} and carries no "
                f"edges. The caller resolves a family to an edge list before the "
                f"chain starts; an engine that silently fell back to Erdos-Renyi "
                f"here would run the wrong experiment and report the right one.")
        return None
    resolved = (edges if isinstance(edges, list) and (not edges or type(edges[0]) is tuple)
                else [(int(u), int(v)) for u, v in edges])
    highest = max((max(u, v) for u, v in resolved), default=-1)
    if highest >= int(n):
        raise ValueError(
            f"given_start edges reference node {highest} at N={n}: a given chain is the size of the chain from "
            f"empty")
    return resolved


LATE_FROM_FRACTION = 0.85
LATE_CHANGE_CONTRACT = "late-change-1"


def late_change_of(state, from_move: int) -> dict:
    added, removed = state.late
    return {"contract": LATE_CHANGE_CONTRACT, "from_move": int(from_move),
            "added": sorted(added), "removed": sorted(removed)}


def arm_late_change(state, late_change: dict | None) -> None:
    if late_change:
        state.late = ({(int(u), int(v)) for u, v in late_change.get("added") or []},
                      {(int(u), int(v)) for u, v in late_change.get("removed") or []})
    else:
        state.late = None


def late_edge_overlap(late_change: dict | None, final_edges: int) -> float | None:
    if not late_change:
        return None
    added, removed = len(late_change.get("added") or []), len(late_change.get("removed") or [])
    union = int(final_edges) + removed
    return ((int(final_edges) - added) / union) if union else 1.0

STOP_CHECK_SECONDS = 4.0
WORK_CHECK_MOVES = 64
STOPPED_INSIDE_A_SEGMENT = ("stop_requested", "work_budget")

CLOCK_STRIDE_START_MOVES = 1
CLOCK_STRIDE_MAX_MOVES = 1 << 22


def cooled_beta(final: float, start: float, moves: int, move: int) -> float:
    if move >= moves:
        return final
    return start + (final - start) * (move / moves)


def next_clock_stride(stride: int, elapsed: float, tick: float | None = None) -> int:
    tick = STOP_CHECK_SECONDS if tick is None else float(tick)
    if elapsed < 0.5 * tick:
        return min(CLOCK_STRIDE_MAX_MOVES, max(1, int(stride)) * 2)
    if elapsed > tick:
        return max(1, int(int(stride) * 0.5 * tick / elapsed))
    return max(1, int(stride))


REBUILD_CLOCK_EDGES = 64


class RestoreInterrupted(Exception):

    def __init__(self, reason: str, edges_rebuilt: int = 0):
        super().__init__(f"graph rebuild stopped ({reason}) after {int(edges_rebuilt)} edges")
        self.reason, self.edges_rebuilt = str(reason), int(edges_rebuilt)


def _counter(value=None):
    return {key: int((value or {}).get(key, 0)) for key in ("add", "delete", "swap")}


ACCOUNTING_CONTRACT = "move-accounting-1"
ACCOUNTING_KINDS = ("add", "delete", "swap")
ACCOUNTING_SCOPES = ("local", "global")
ACCOUNTING_SIGNS = ("neg", "zero", "pos")
ACCOUNTING_OUTCOMES = ("accepted", "rejected")
ACCOUNTING_KEYS = tuple(f"{kind}.{scope}.{sign}.{outcome}" for kind in ACCOUNTING_KINDS
                        for scope in ACCOUNTING_SCOPES for sign in ACCOUNTING_SIGNS
                        for outcome in ACCOUNTING_OUTCOMES)
DELTA_H_BIN_LIMIT = 40
ACCOUNTING_LATE_QUARTERS = 3


def delta_h_bin(delta_h: float) -> str:
    if delta_h == 0.0:
        return "0"
    exponent = max(-DELTA_H_BIN_LIMIT, min(DELTA_H_BIN_LIMIT, math.frexp(abs(delta_h))[1]))
    return f"{'+' if delta_h > 0 else '-'}2^{exponent}"


WORK_PARTS = ("moves", "evaluations", "changes", "lists", "entries", "tests")


def units_spent(weights, moves: int, before: list[int], now: list[int]) -> int:
    return int(weights[0]) * int(moves) + sum(int(weight) * (is_ - was) for weight, was, is_ in zip(
        weights[1:], before[1:], now[1:], strict=True))


def units_of_an_accounting(accounting: dict | None, weights) -> int:
    parts = (accounting or {}).get("parts") or {}
    return sum(int(weight) * int(parts.get(name) or 0) for weight, name in zip(weights, WORK_PARTS, strict=True))


def _count(block: dict, before: list[int], now: list[int], moves: int) -> None:
    block["work"] += now[0] - before[0]
    parts = block["parts"]
    parts["moves"] += moves
    for name, was, is_ in zip(WORK_PARTS[1:], before[1:], now[1:]):
        parts[name] += is_ - was


def _accounting_block(value=None) -> dict:
    value = value or {}
    counts = value.get("counts") or {}
    hist = value.get("delta_h_log2") or {}
    parts = value.get("parts") or {}
    return {"work": int(value.get("work") or 0), "parts": {name: int(parts.get(name) or 0) for name in WORK_PARTS},
            "counts": {key: int(counts.get(key, 0)) for key in ACCOUNTING_KEYS},
            "delta_h_log2": {side: {str(b): int(c) for b, c in (hist.get(side) or {}).items()}
                             for side in ("proposed", "accepted")}}


def new_accounting(value=None) -> dict:
    value = value or {}
    late = value.get("late") or {}
    last = value.get("last_decrease_move")
    return {"contract": ACCOUNTING_CONTRACT, **_accounting_block(value),
            "late": {"from_move": (None if late.get("from_move") is None else int(late["from_move"])),
                     **_accounting_block(late)},
            "last_decrease_move": None if last is None else int(last)}


STRUCTURE_POINT_STRIDE = 20


def structure_point_stride(n: int) -> int:
    return STRUCTURE_POINT_STRIDE


def trajectory_structure(adj, n: int) -> dict:
    seen = bytearray(n)
    components = largest = 0
    for start in range(n):
        if seen[start]:
            continue
        components += 1
        seen[start] = 1
        stack = [start]
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            for other in adj[node]:
                if not seen[other]:
                    seen[other] = 1
                    stack.append(other)
        largest = max(largest, size)
    triangles = 0
    for u in range(n):
        au = adj[u]
        for v in au:
            if v > u:
                for w in au & adj[v]:
                    if w > v:
                        triangles += 1
    return {"components": components, "largest_component": largest, "triangles": triangles}


class ChainContext:

    def __init__(self, **fields):
        self.__dict__.update(fields)


class _LocalWalk:

    def __init__(self, ctx, state, rng, counters, tally):
        self.state, self.rng, self.n, self.apply_edge = state, rng, ctx.n, ctx.apply_edge
        self.zero_temperature = bool(getattr(ctx, "zero_temperature", False))
        self.swap_terms = swap_terms(ctx)
        self.attempted, self.proposed, self.accepted = counters
        self.tally = tally
        self.energy, self.beta = 0.0, ctx.beta

    def move(self, move, energy, beta):
        self.energy, self.beta = energy, beta
        rng = self.rng
        a = rng.randrange(self.n)
        draw = rng.random()
        if draw < LOCAL_WALK_DELETE:
            self.attempted["delete"] += 1
            first = sorted(self.state.adj[a])
            self.state._read(1, len(first))
            if first:
                self.toggle(move, a, first[rng.randrange(len(first))], False)
        elif draw < LOCAL_WALK_SWAP_BELOW:
            self.attempted["swap"] += 1
            self.swap(move, a)
        else:
            self.attempted["add"] += 1
            self.walk_add(move, a)
        return self.energy

    def neighbours(self, w, without=None):
        found = sorted(self.state.adj[w])
        self.state._read(1, len(found))
        if without is not None and w in without:
            found.remove(without[1] if w == without[0] else without[0])
        return found

    def walk_ends(self, u, x, steps, without=None):
        first = self.neighbours(u, without)
        du = len(first)
        total = 0.0
        for b in first:
            second = self.neighbours(b, without)
            db = len(second)
            if steps == 2:
                self.state._scan(db)
                if x in second:
                    total += 1.0 / (du * db)
                continue
            for c in second:
                third = self.neighbours(c, without)
                self.state._scan(len(third))
                if x in third:
                    total += 1.0 / (du * db * len(third))
        return total

    def walk_add_chance(self, u, x, without=None):
        ends = ((self.walk_ends(u, x, 2, without) + self.walk_ends(x, u, 2, without))
                + (self.walk_ends(u, x, 3, without) + self.walk_ends(x, u, 3, without)))
        return LOCAL_WALK_ADD * ends / (2 * self.n)

    def delete_chance(self, du, dv):
        return LOCAL_WALK_DELETE * (1.0 / du + 1.0 / dv) / self.n

    def toggle(self, move, u, v, adding):
        state, kind = self.state, "add" if adding else "delete"
        self.proposed[kind] += 1
        deltas, delta_h = self.apply_edge(state, u, v, adding, self.energy)
        if not math.isfinite(delta_h):
            raise FloatingPointError(f"non-finite energy delta at move {move}; refusing to sample")
        du, dv = len(state.adj[u]), len(state.adj[v])
        if adding:
            forward, reverse = self.walk_add_chance(u, v), self.delete_chance(du + 1, dv + 1)
        else:
            forward, reverse = self.delete_chance(du, dv), self.walk_add_chance(u, v, without=(u, v))
        if reverse <= 0.0 or forward <= 0.0:
            took = False
        elif self.zero_temperature:
            took = delta_h <= 0.0
        else:
            took = math.log(self.rng.random() + 1e-300) < -self.beta * delta_h + math.log(reverse / forward)
        if took:
            state.apply(u, v, adding, deltas)
            self.energy += delta_h
            self.accepted[kind] += 1
        self.tally(move, kind, "local", delta_h, took)

    def force(self, edge, adding):
        u, v = edge
        deltas, delta_h = self.apply_edge(self.state, u, v, adding, self.energy)
        if not math.isfinite(delta_h):
            raise FloatingPointError("non-finite energy delta during edge swap")
        self.state.apply(u, v, adding, deltas)
        self.energy += delta_h
        return deltas

    def swap(self, move, a):
        state, rng = self.state, self.rng
        first = sorted(state.adj[a])
        state._read(1, len(first))
        if not first:
            return
        b = first[rng.randrange(len(first))]
        state._read(1, len(state.adj[b]))
        second = [w for w in sorted(state.adj[b]) if w != a]
        if not second:
            return
        c = second[rng.randrange(len(second))]
        state._read(1, len(state.adj[c]))
        third = [w for w in sorted(state.adj[c]) if w != b]
        if not third:
            return
        d = third[rng.randrange(len(third))]
        if d == a or state.tests_edge(a, c) or state.tests_edge(b, d):
            return
        self.proposed["swap"] += 1
        old_energy = self.energy
        e1, e2, n1, n2 = state._edge(a, b), state._edge(c, d), state._edge(a, c), state._edge(b, d)
        moved = [self.force(edge, adding) for edge, adding in ((e1, False), (e2, False), (n1, True), (n2, True))]
        delta_h = swap_change(self.swap_terms, moved)
        self.energy = old_energy + delta_h
        took = (delta_h <= 0.0 if self.zero_temperature
                else math.log(rng.random() + 1e-300) < -self.beta * delta_h)
        if took:
            self.accepted["swap"] += 1
        else:
            for edge, adding in ((n2, False), (n1, False), (e2, True), (e1, True)):
                self.force(edge, adding)
            self.energy = old_energy
        self.tally(move, "swap", "local", delta_h, took)

    def walk_add(self, move, a):
        rng, adj = self.rng, self.state.adj
        steps = LOCAL_WALK_STEPS[rng.randrange(len(LOCAL_WALK_STEPS))]
        x = a
        for _ in range(steps):
            onward = sorted(adj[x])
            self.state._read(1, len(onward))
            if not onward:
                return
            x = onward[rng.randrange(len(onward))]
        if x == a or self.state.tests_edge(a, x):
            return
        self.toggle(move, a, x, True)


def run_chain(ctx, rng, state, energy, points, *, start_move=0,
              attempted=None, proposed=None, accepted=None, trajectory=None,
              late_change=None, peak_edge_count=None, late_from_move=None,
              enforce_limits=False, segment_start=None, stop_file=None,
              accounting=None, work_room=None, work_weights=None):
    segment_start = start_move if segment_start is None else int(segment_start)
    last_stop_check = time.monotonic()
    last_clock_read = last_stop_check
    clock_stride = CLOCK_STRIDE_START_MOVES
    next_clock_move = start_move + clock_stride
    n = ctx.n
    total_moves = ctx.total_moves
    mean_degree_cap = ctx.mean_degree_cap
    proposal_locality = ctx.proposal_locality
    locality = float(getattr(ctx, "locality", 0.0))
    zero_temperature = bool(getattr(ctx, "zero_temperature", False))
    exact_swaps = swap_terms(ctx)
    apply_edge = ctx.apply_edge
    p_add, p_del, p_swap = ctx.p_add, ctx.p_del, ctx.p_swap
    beta = ctx.beta
    beta_final, cooling_from_beta = beta, getattr(ctx, "cooling_from_beta", None)
    cooling_moves = getattr(ctx, "cooling_moves", None)
    max_edges = ctx.max_edges
    candidate_spec = ctx.candidate_spec
    termination = None
    cap_edges = None
    if enforce_limits and mean_degree_cap is not None:
        cap_edges = int(math.floor(float(mean_degree_cap) * n / 2.0))
    attempted = _counter(attempted)
    proposed = _counter(proposed)
    accepted = _counter(accepted)
    trajectory = list(trajectory or [])
    arm_late_change(state, late_change)
    late_change_from = int((late_change or {}).get("from_move", -1))
    peak_edge_count = max(len(state.edges), int(peak_edge_count or 0))
    arm_at = int(late_from_move) if late_from_move is not None and int(late_from_move) >= start_move else None
    segment_moves = max(0, total_moves - segment_start)
    record_every = max(1, segment_moves // max(1, points))
    structure_stride = structure_point_stride(n)
    acc = accounting if accounting is not None else new_accounting()
    late_from = segment_start + (ACCOUNTING_LATE_QUARTERS * segment_moves) // 4
    if start_move == segment_start or acc["late"].get("from_move") != late_from:
        acc["late"] = {"from_move": late_from, **_accounting_block()}
    counts, histograms = acc["counts"], acc["delta_h_log2"]
    late_counts, late_histograms = acc["late"]["counts"], acc["late"]["delta_h_log2"]

    def tally(move, kind, scope, delta_h, took):
        sign = "neg" if delta_h < 0 else ("pos" if delta_h > 0 else "zero")
        key = f"{kind}.{scope}.{sign}.{'accepted' if took else 'rejected'}"
        bin_ = delta_h_bin(delta_h)
        counts[key] += 1
        histograms["proposed"][bin_] = histograms["proposed"].get(bin_, 0) + 1
        if took:
            histograms["accepted"][bin_] = histograms["accepted"].get(bin_, 0) + 1
            if delta_h < 0:
                acc["last_decrease_move"] = int(move)
        if move >= late_from:
            late_counts[key] += 1
            late_histograms["proposed"][bin_] = late_histograms["proposed"].get(bin_, 0) + 1
            if took:
                late_histograms["accepted"][bin_] = late_histograms["accepted"].get(bin_, 0) + 1

    def swap_proposal():
        e_count = len(state.edge_list)
        if e_count < 2:
            return None
        i = rng.randrange(e_count)
        j = rng.randrange(e_count - 1)
        if j >= i:
            j += 1
        e1 = state.edge_list[i]
        e2 = state.edge_list[j]
        a, b = e1
        c, d = e2
        if len({a, b, c, d}) != 4:
            return None
        if rng.random() < 0.5:
            n1, n2 = state._edge(a, c), state._edge(b, d)
        else:
            n1, n2 = state._edge(a, d), state._edge(b, c)
        if n1 == n2 or state.tests_edge(*n1) or state.tests_edge(*n2):
            return None
        return e1, e2, n1, n2

    def force_toggle(edge, adding):
        nonlocal energy
        u, v = edge
        deltas, delta_h = apply_edge(state, u, v, adding, energy)
        if not math.isfinite(delta_h):
            raise FloatingPointError("non-finite energy delta during edge swap")
        state.apply(u, v, adding, deltas)
        energy += delta_h
        return deltas

    def symmetric_audit_pair():
        if n < 2:
            return None
        if rng.random() < proposal_locality:
            radius = max(1, min(int(math.sqrt(n)), max(1, (n - 1) // 2)))
            u = rng.randrange(n)
            distance = 1 + rng.randrange(radius)
            if rng.random() < 0.5:
                v = (u + distance) % n
            else:
                v = (u - distance) % n
            if v == u:
                v = (u + 1) % n
        else:
            u = rng.randrange(n)
            v = rng.randrange(n - 1)
            if v >= u:
                v += 1
        return state._edge(u, v)

    def local_pair():
        u = rng.randrange(n)
        nbrs = sorted(state.adj[u])
        state._read(1, len(nbrs))
        d = len(nbrs)
        if d < 2:
            return None
        i = rng.randrange(d)
        j = rng.randrange(d - 1)
        if j >= i:
            j += 1
        return state._edge(nbrs[i], nbrs[j])

    walker = getattr(ctx, "local_walk", False) and _LocalWalk(ctx, state, rng, (attempted, proposed, accepted), tally)

    counted_from = state.counted()
    late_counted_from = None
    moves_run = late_moves_run = 0
    for move in range(start_move, total_moves):
        moves_run += 1
        if move >= late_from:
            late_moves_run += 1
            if late_counted_from is None:
                late_counted_from = state.counted()
        if cooling_moves is not None:
            beta = cooled_beta(beta_final, cooling_from_beta, cooling_moves, move)
        if move == arm_at:
            state.late = (set(), set())
            late_change_from = move
        e_count = len(state.edges)

        if walker:
            energy = walker.move(move, energy, beta)
            peak_edge_count = max(peak_edge_count, len(state.edges))
        elif locality > 0.0 and rng.random() < locality:
            edge = local_pair()
            if edge is None:
                attempted["add"] += 1
            else:
                adding = not state.tests_edge(*edge)
                kind = "add" if adding else "delete"
                attempted[kind] += 1
                proposed[kind] += 1
                u, v = edge
                deltas, delta_h = apply_edge(state, u, v, adding, energy)
                if not math.isfinite(delta_h):
                    raise FloatingPointError(
                        f"non-finite energy delta at move {move}; refusing to sample"
                    )
                took = (delta_h <= 0.0 if zero_temperature
                        else math.log(rng.random() + 1e-300) < -beta * delta_h)
                if took:
                    state.apply(u, v, adding, deltas)
                    energy += delta_h
                    peak_edge_count = max(peak_edge_count, len(state.edges))
                    accepted[kind] += 1
                tally(move, kind, "local", delta_h, took)
        elif proposal_locality > 0.0:
            edge = symmetric_audit_pair()
            if edge is None:
                attempted["add"] += 1
            else:
                adding = not state.tests_edge(*edge)
                kind = "add" if adding else "delete"
                attempted[kind] += 1
                proposed[kind] += 1
                u, v = edge
                deltas, delta_h = apply_edge(state, u, v, adding, energy)
                if not math.isfinite(delta_h):
                    raise FloatingPointError(
                        f"non-finite energy delta at move {move}; refusing to sample"
                    )
                took = (delta_h <= 0.0 if zero_temperature
                        else math.log(rng.random() + 1e-300) < -beta * delta_h)
                if took:
                    state.apply(u, v, adding, deltas)
                    energy += delta_h
                    peak_edge_count = max(peak_edge_count, len(state.edges))
                    accepted[kind] += 1
                tally(move, kind, "global", delta_h, took)
        else:
            draw = rng.random()
            if draw < p_add:
                kind = "add"
            elif draw < p_add + p_del:
                kind = "delete"
            else:
                kind = "swap"
            attempted[kind] += 1

            if kind == "swap":
                proposal = swap_proposal()
                if proposal is not None:
                    proposed["swap"] += 1
                    old_energy = energy
                    e1, e2, n1, n2 = proposal
                    moved = [force_toggle(e1, False), force_toggle(e2, False),
                             force_toggle(n1, True), force_toggle(n2, True)]
                    delta_h = swap_change(exact_swaps, moved)
                    energy = old_energy + delta_h
                    took = (delta_h <= 0.0 if zero_temperature
                            else math.log(rng.random() + 1e-300) < -beta * delta_h)
                    if took:
                        accepted["swap"] += 1
                    else:
                        force_toggle(n2, False)
                        force_toggle(n1, False)
                        force_toggle(e2, True)
                        force_toggle(e1, True)
                        energy = old_energy
                    tally(move, "swap", "global", delta_h, took)
            else:
                adding = kind == "add"
                feasible = not ((adding and e_count >= max_edges) or
                                (not adding and e_count == 0))
                if feasible:
                    if adding:
                        u, v = state.sample_non_edge(rng)
                        proposed["add"] += 1
                        log_ratio = math.log(p_del * (max_edges - e_count)) - math.log(
                            p_add * (e_count + 1))
                    else:
                        u, v = state.edge_list[rng.randrange(e_count)]
                        proposed["delete"] += 1
                        log_ratio = math.log(p_add * e_count) - math.log(
                            p_del * (max_edges - e_count + 1))
                    deltas, delta_h = apply_edge(state, u, v, adding, energy)
                    if not math.isfinite(delta_h):
                        raise FloatingPointError(
                            f"non-finite energy delta at move {move}; refusing to sample")
                    took = (delta_h <= 0.0 if zero_temperature
                            else math.log(rng.random() + 1e-300) < -beta * delta_h + log_ratio)
                    if took:
                        state.apply(u, v, adding, deltas)
                        energy += delta_h
                        peak_edge_count = max(peak_edge_count, len(state.edges))
                        accepted[kind] += 1
                    tally(move, kind, "global", delta_h, took)

        if cap_edges is not None and len(state.edges) > cap_edges:
            termination = {"reason": "mean_degree_cap", "at_move": int(move),
                           "at_sweep": int(move // max(1, n)),
                           "mean_degree_at_stop": 2.0 * len(state.edges) / n,
                           "cap": float(mean_degree_cap)}
        at_record = ((move - segment_start) % record_every == 0 or move == total_moves - 1)
        at_stride = move >= next_clock_move
        at_clock = at_record or at_stride
        now = time.monotonic() if at_clock else 0.0
        if at_stride:
            clock_stride = next_clock_stride(clock_stride, now - last_clock_read)
            last_clock_read = now
            next_clock_move = move + clock_stride
        if termination is None and stop_file is not None and at_clock and move + 1 < total_moves:
            if now - last_stop_check >= 0.5 * STOP_CHECK_SECONDS:
                last_stop_check = now
                if os.path.exists(stop_file):
                    termination = {"reason": "stop_requested", "at_move": int(move)}
        if (termination is None and work_room is not None and move + 1 < total_moves
                and (move - segment_start) % WORK_CHECK_MOVES == WORK_CHECK_MOVES - 1):
            spent = units_spent(work_weights, moves_run, counted_from, state.counted())
            if spent >= work_room:
                termination = {"reason": "work_budget", "at_move": int(move), "units": int(spent)}
        stopping = termination is not None and termination["reason"] in STOPPED_INSIDE_A_SEGMENT
        if stopping and not at_record:
            break
        if at_record or termination is not None:
            degs = [len(a) for a in state.adj]
            degree_sum = float(sum(degs))
            degree_square_sum = float(sum(d * d for d in degs))
            degree_cube_sum = float(sum(d * d * d for d in degs))
            degree_fourth_sum = float(sum((d * d) * (d * d) for d in degs))
            mean_degree = degree_sum / max(1, n)
            degree_variance = max(0.0, degree_square_sum / max(1, n) - mean_degree * mean_degree)

            term_components = []
            component_sum = 0.0
            for term_index, term in enumerate(candidate_spec["terms"]):
                op = term["op"]
                params = dict(term.get("params") or {})
                if op == "edge_count":
                    observable = float(len(state.edges))
                elif op == "degree_square_sum":
                    observable = degree_square_sum
                elif op == "wedge_count":
                    observable = float(sum(d * (d - 1) / 2 for d in degs))
                elif op == "degree_cube_sum":
                    observable = degree_cube_sum
                elif op == "degree_fourth_sum":
                    observable = degree_fourth_sum
                elif op in ("degree_anchor", "degree_anchor_abs"):
                    k = int(params.get("k", 0))
                    if op == "degree_anchor":
                        observable = float(sum((d - k) ** 2 for d in degs))
                    else:
                        observable = float(sum(abs(d - k) for d in degs))
                else:
                    observable = float(state.ledgers.get(op, 0.0))
                coeff = float(coefficient(term, n))
                energy_component = coeff * observable
                component_sum += energy_component
                term_components.append({
                    "term_index": term_index, "op": op, "params": params,
                    "scale": (term.get("coeff") or {}).get("scale", "one"),
                    "coefficient": coeff, "observable": observable,
                    "energy_component": energy_component,
                })

            point = {"move": move, "energy": energy, "edges": len(state.edges),
                     "mean_degree": mean_degree,
                     "max_degree": max(degs) if degs else 0,
                     "isolated_fraction": (sum(1 for d in degs if d == 0) / max(1, n)),
                     "degree_variance": degree_variance,
                     "degree_second_moment": degree_square_sum / max(1, n),
                     "degree_third_moment": degree_cube_sum / max(1, n),
                     "degree_fourth_moment": degree_fourth_sum / max(1, n),
                     "active_term_components": term_components,
                     "term_energy_sum": component_sum,
                     "term_energy_residual": float(energy - component_sum),
                     "attempted_add": attempted["add"],
                     "attempted_delete": attempted["delete"],
                     "attempted_swap": attempted["swap"],
                     "proposed_add": proposed["add"],
                     "proposed_delete": proposed["delete"],
                     "proposed_swap": proposed["swap"],
                     "accepted_add": accepted["add"],
                     "accepted_delete": accepted["delete"],
                     "accepted_swap": accepted["swap"]}
            if len(trajectory) % structure_stride == 0:
                point.update(trajectory_structure(state.adj, n))
            trajectory.append(point)
            if termination is not None:
                termination["trajectory_points"] = len(trajectory)
                break
    counted_now = state.counted()
    _count(acc, counted_from, counted_now, moves_run)
    if late_counted_from is not None:
        _count(acc["late"], late_counted_from, counted_now, late_moves_run)
    late_out = late_change_of(state, late_change_from) if state.late is not None else None
    state.late = None
    return (state, energy, trajectory, attempted, proposed, accepted,
            late_out, peak_edge_count, termination)


def _rebuild_in_python(chain: dict, *, n: int, spec_ops, apply_edge, energy,
                       stop_file) -> tuple["GraphState", float]:
    from graph_scale_dynamics.engine.checkpoint import check_edges
    check_edges(n, chain.get("edge_list") or [])
    state = GraphState(n)
    state.require_ops(spec_ops)
    last_stop = time.monotonic()
    for index, raw in enumerate(chain.get("edge_list") or []):
        if index and not index % REBUILD_CLOCK_EDGES:
            now = time.monotonic()
            if stop_file is not None and now - last_stop >= 0.5 * STOP_CHECK_SECONDS:
                last_stop = now
                if os.path.exists(stop_file):
                    raise RestoreInterrupted("stop_requested", index)
        u, v = int(raw[0]), int(raw[1])
        deltas, delta_h = apply_edge(state, u, v, True, energy)
        state.apply(u, v, True, deltas)
        energy += delta_h
    if "energy" in chain:
        energy = float(chain["energy"])
    state.non_edge_fast_path_hits = int(chain.get("non_edge_fast_path_hits", 0))
    state.non_edge_exact_fallbacks = int(chain.get("non_edge_exact_fallbacks", 0))
    return state, energy


def _law_dynamics(candidate_spec: dict, proposal_locality: float) -> dict:
    settings = dynamics_settings(candidate_spec)
    locality = settings["locality"]
    if not 0.0 <= locality < 1.0:
        raise ValueError("dynamics.locality must lie in [0,1)")
    if locality > 0.0 and proposal_locality > 0.0:
        raise ValueError("a law with its own locality is not audited with another proposal locality")
    if settings["local_move"] not in LOCAL_MOVES:
        raise ValueError(local_move_problem(settings["local_move"]))
    cooling = cooling_schedule(candidate_spec)
    if cooling is not None and (settings["zero_temperature"] or cooling["over_sweeps"] < 1
                                or not 0.0 < cooling["from_beta"] < float(candidate_spec["dynamics"]["beta"])):
        raise ValueError("dynamics.cooling must start hotter than the law's beta, over at least one sweep, "
                         "and never at zero temperature")
    return settings


def _proposal_model(candidate_spec: dict, n: int, proposal_locality: float, mix: tuple) -> dict:
    p_add, p_del, p_swap = mix
    settings = dynamics_settings(candidate_spec)
    locality, zero_temperature = settings["locality"], settings["zero_temperature"]
    if proposal_locality > 0.0:
        proposal_model = {
            "kernel": "symmetric_fixed_label_local_toggle_with_global_fallback",
            "proposal_locality": proposal_locality,
            "local_radius": max(1, min(int(math.sqrt(n)), max(1, (n - 1) // 2))) if n > 1 else 0,
            "acceptance_rule": "metropolis_symmetric_toggle",
            "detailed_balance_note": "pair proposal is graph-state independent and symmetric; q reverse equals q forward",
        }
    else:
        proposal_model = {
            "kernel": "canonical_global_add_delete_swap",
            "move_mix": {"add": p_add, "delete": p_del, "swap": p_swap},
            "add_selection": "uniform_non_edge_hybrid_complement_degree",
            "delete_selection": "uniform_edge",
            "swap_selection": "uniform_distinct_edge_pair_plus_uniform_cross_rewire",
            "acceptance_rule": "metropolis_hastings_add_delete_plus_symmetric_swap",
        }
    if locality > 0.0:
        proposal_model |= {
            "kernel": "neighbour_pair_toggle_with_global_fallback",
            "locality": locality, "local_move": settings["local_move"],
            "local_selection": "uniform_node_then_uniform_pair_of_its_neighbours",
        }
    if zero_temperature:
        proposal_model["acceptance_rule"] = "zero_temperature_accept_if_energy_does_not_rise"
    if locality > 0.0 or zero_temperature:
        proposal_model["dynamics_regime"] = dynamics_regime(candidate_spec)
    cooling = cooling_schedule(candidate_spec)
    if cooling is not None:
        proposal_model["beta_schedule"] = {
            "shape": COOLING_SHAPE, "from_beta": cooling["from_beta"],
            "to_beta": float(candidate_spec["dynamics"]["beta"]), "over_sweeps": cooling["over_sweeps"],
            "over_moves": cooling["over_sweeps"] * n, "then": "held at the law's beta"}
    return proposal_model


_NODE_FUNCTIONALS = {
    "degree_anchor": lambda d, k: (d - k) ** 2,
    "degree_anchor_abs": lambda d, k: abs(d - k),
    "degree_cube_sum": lambda d, k: d ** 3,
    "degree_fourth_sum": lambda d, k: d ** 4,
}


def _energy_model(candidate_spec: dict, n: int):
    node_terms = []
    for term in candidate_spec["terms"]:
        if term["op"] not in _NODE_FUNCTIONALS:
            continue
        k = term.get("params", {}).get("k", 0)
        if isinstance(k, bool) or not isinstance(k, int):
            raise ValueError(f"{term['op']} parameter k must be an integer; refusing coercion")
        node_terms.append((term["op"], coefficient(term, n), k))
    empty_energy = sum(c * n * _NODE_FUNCTIONALS[op](0, k) for op, c, k in node_terms)

    def apply_edge(state, u, v, adding, energy):
        deltas = state.op_deltas(u, v, adding)
        node_energy = node_magnitude = 0.0
        if node_terms:
            sign = 1 if adding else -1
            du = state.degree(u) - (0 if adding else 1)
            dv = state.degree(v) - (0 if adding else 1)
            for op, c, k in node_terms:
                f = _NODE_FUNCTIONALS[op]
                part = c * sign * (
                    f(du + 1, k) - f(du, k) + f(dv + 1, k) - f(dv, k)
                )
                node_energy += part
                node_magnitude += abs(part)
        delta_h = _term_delta_energy(candidate_spec, n, deltas, node_energy, node_magnitude)
        return deltas, delta_h

    return node_terms, empty_energy, apply_edge


def configuration_energy(candidate_spec: dict, n: int, edges) -> float:
    _node_terms, energy, apply_edge = _energy_model(candidate_spec, n)
    state = GraphState(n)
    state.require_ops({term["op"] for term in candidate_spec["terms"]})
    for u, v in edges:
        deltas, delta_h = apply_edge(state, int(u), int(v), True, energy)
        state.apply(int(u), int(v), True, deltas)
        energy += delta_h
    return energy


def run_simulation(candidate_spec: dict, n: int, seed: int, *, record_points: int = 240,
                   engine_contract_version: str | None = None,
                   target_sweeps: int | None = None,
                   resume_checkpoint: dict | None = None,
                   proposal_locality: float = 0.0,
                   identity_fingerprint: str | None = None,
                   mean_degree_cap: float | None = None,
                   chain_runner=None, stop_file: str | None = None,
                   given_start: dict | None = None, more_given: list | None = None,
                   work_budget: int | None = None, work_weights=None) -> dict:
    from graph_scale_dynamics.engine import chains as C
    contract_version = engine_contract_version or ENGINE_VERSION
    if contract_version not in COMPATIBLE_ENGINE_VERSIONS:
        raise ValueError(f"unsupported engine contract {contract_version!r}")
    if isinstance(proposal_locality, bool) or not isinstance(proposal_locality, (int, float)):
        raise ValueError("proposal_locality must be numeric")
    proposal_locality = float(proposal_locality)
    if not 0.0 <= proposal_locality < 1.0:
        raise ValueError("proposal_locality must lie in [0,1)")

    dyn = candidate_spec["dynamics"]
    settings = _law_dynamics(candidate_spec, proposal_locality)
    locality = settings["locality"]
    beta = float(dyn["beta"])
    cooling = cooling_schedule(candidate_spec)
    p_add = float(dyn["move_mix"]["add"])
    p_del = float(dyn["move_mix"]["delete"])
    p_swap = float(dyn["move_mix"].get("swap", 0.0))
    base_sweeps = int(dyn["sweeps"])
    if base_sweeps < 1:
        raise ValueError("candidate dynamics.sweeps must be positive")
    sweeps = int(target_sweeps if target_sweeps is not None else base_sweeps)
    if sweeps < 1:
        raise ValueError("target_sweeps must be positive")
    total_moves = sweeps * n
    max_edges = n * (n - 1) // 2

    node_terms, empty_energy, apply_edge = _energy_model(candidate_spec, n)
    spec_ops = {term["op"] for term in candidate_spec["terms"]}
    chains = C.chain_list(given_start, more_given)

    def _restore_graph(chain: dict) -> tuple[GraphState, float]:
        rebuild = getattr(runner, "rebuild", None)
        if rebuild is not None and "energy" in chain:
            state = rebuild(ctx, chain, stop_file=stop_file)
            return state, float(chain["energy"])
        return _rebuild_in_python(chain, n=n, spec_ops=spec_ops, apply_edge=apply_edge, energy=empty_energy,
                                  stop_file=stop_file)

    t0 = time.monotonic()
    execution_fingerprint = (str(identity_fingerprint) if identity_fingerprint is not None
                             else fingerprint(candidate_spec))
    stream_context = (contract_version, execution_fingerprint, int(n), int(seed))

    checkpoint = resume_checkpoint or {}
    if checkpoint:
        if str(checkpoint.get("contract")) != C.CHECKPOINT_CONTRACT:
            raise ValueError(f"unsupported sampling checkpoint contract {checkpoint.get('contract')!r}: a chunk "
                             f"runs on from a checkpoint of {C.CHECKPOINT_CONTRACT}")
        if checkpoint.get("candidate_fingerprint") != execution_fingerprint:
            raise ValueError("sampling checkpoint candidate fingerprint mismatch")
        if int(checkpoint.get("n", -1)) != int(n) or int(checkpoint.get("seed", -1)) != int(seed):
            raise ValueError("sampling checkpoint N/seed mismatch")
        if abs(float(checkpoint.get("proposal_locality", 0.0)) - proposal_locality) > 1e-15:
            raise ValueError("sampling checkpoint proposal locality mismatch")
        start_move = int(checkpoint.get("cumulative_moves", 0))
        if start_move > total_moves:
            raise ValueError("sampling checkpoint already exceeds requested cumulative target")
    else:
        start_move = 0

    late_from_move = int(LATE_FROM_FRACTION * total_moves)

    ctx = ChainContext(
        n=n, total_moves=total_moves, mean_degree_cap=mean_degree_cap,
        proposal_locality=proposal_locality, apply_edge=apply_edge,
        locality=locality, zero_temperature=settings["zero_temperature"],
        p_add=p_add, p_del=p_del, p_swap=p_swap, beta=beta, max_edges=max_edges,
        cooling_from_beta=None if cooling is None else float(cooling["from_beta"]),
        cooling_moves=None if cooling is None else int(cooling["over_sweeps"]) * n,
        candidate_spec=candidate_spec, spec_ops=spec_ops, node_terms=node_terms,
    )
    runner = chain_runner or run_chain
    segment = (checkpoint or {}).get("in_segment") or {}
    identity = {"contract": C.CHECKPOINT_CONTRACT, "engine_version": contract_version,
                "candidate_fingerprint": execution_fingerprint, "n": int(n), "seed": int(seed),
                "proposal_locality": proposal_locality}
    ran = C.run_chains(ctx=ctx, runner=runner, chains=chains, stream_context=stream_context, checkpoint=checkpoint,
                       segment=segment, start_move=start_move, record_points=record_points,
                       late_from_move=late_from_move, sweeps=sweeps, stop_file=stop_file, restore=_restore_graph,
                       empty_energy=empty_energy, identity=identity, work_budget=work_budget,
                       work_weights=work_weights)
    if "stopped" in ran:
        return ran["stopped"]
    termination = ran["termination"]
    actual_moves = (int(termination["at_move"]) + 1) if termination else total_moves
    by_name = {block["start"]: block for block in ran["blocks"]}
    from_empty = by_name[C.FROM_EMPTY]
    first_given = by_name.get(C.GIVEN) or {}
    cumulative_sweeps = sweeps if termination is None else int(actual_moves // max(1, n))
    proposal_model = _proposal_model(candidate_spec, n, proposal_locality, (p_add, p_del, p_swap))
    return {
        "schema": "raw-simulation-envelope-v2",
        "observation_contract": "simulation-observation-ledger-1",
        "engine_version": contract_version,
        "producer_engine_version": ENGINE_VERSION,
        "n": n, "seed": seed, "sweeps": sweeps, "moves": total_moves,
        "executed_moves": actual_moves,
        "sweeps_multiplier": max(1, int(round(sweeps / max(1, base_sweeps)))),
        "cumulative_sweeps": cumulative_sweeps,
        "termination": termination or {"reason": "completed", "at_move": total_moves - 1, "at_sweep": sweeps},
        "limits": {"mean_degree_cap": mean_degree_cap},
        "continued_from_sweeps": int(start_move // max(1, n)),
        "dynamics_declared": dyn["kind"],
        "proposal_model": proposal_model,
        "random_streams": {"version": STREAM_VERSION,
                           "given_initialization": stream_id(C.GIVEN_INITIALISATION_STREAM, *stream_context)},
        "chains": ran["records"],
        "trajectory_diagnostics": trajectory_diagnostics(from_empty.get("trajectory") or [],
                                                         first_given.get("trajectory") or [], n),
        "trajectory_structure_stride": structure_point_stride(n),
        "sampling_checkpoint": dict(identity, cumulative_moves=actual_moves, cumulative_sweeps=cumulative_sweeps,
                                    chains=ran["blocks"]),
        "wall_seconds": time.monotonic() - t0,
    }
