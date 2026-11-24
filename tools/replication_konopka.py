#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
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

CONTRACT = "gsd-replication-konopka-1"
PAPER = "konopka2008"
CUTOFF = 20
R_FIGURE = 7.3
R_BOUND = 7.1
FLAT = (60, 60)
LINE_LEVELS = 400
HEPT_RADIUS = CUTOFF // 2 + 2
TUBES = {"zigzag": (4, 6, 8, 10, 12), "armchair": (4, 6, 8, 10, 12)}
OPEN_CHOICES = {
    "p_a_l": "closed paths at a that use no edge twice, each direction counted (normal ordering, equations (11) to (14))",
    "g_b": 1.0,
    "braided_line": "figure 2(b): two rails, every other cell crossed by an X, no rungs",
    "braided_tree": "figure 2(c) is drawn, not defined: not built; its claims reported unread",
    "heptagonal": "the {7,3} tiling, three regular heptagons at a vertex",
    "tube": "the brick-wall honeycomb with one short period: zigzag (a column closes after c edges) or armchair (a row "
            "after c columns), closed far along it",
    "defects": "type I moves a neighbour of a to b across the edge ab where no hexagon holds both, type II where one "
               "does (figure 1(a)); the change summed over every vertex within CUTOFF / 2 + 1 of the four",
    "chain": "3-regular graphs from a random start (configuration model), equation (27)'s exchanges, Metropolis on H_B "
             "to the chain's cutoff, beta from 1/100 of its end over 80% of the moves, then downhill only; the end "
             "beta 10 over the median |dE| of a move at the start",
}
FIGURE_3 = {
    "hex": {6: 81, 10: 313, 12: 388, 14: 541, 16: 599, 18: 643, 20: 655},
    "line": {4: 15, 6: 180, 10: 490, 14: 593, 18: 603},
    "hept": {7: 86, 12: 200, 15: 212, 17: 231},
    "tree": {6: 126, 8: 200, 10: 351, 12: 469, 14: 520, 16: 546, 18: 551, 20: 553},
}


def _graph():
    return collections.defaultdict(list)


def _add(adj, a, b) -> None:
    adj[a].append(b)
    adj[b].append(a)


def honeycomb(w: int, h: int):
    adj = _graph()
    for i in range(w):
        for j in range(h):
            _add(adj, (i, j), (i, (j + 1) % h))
            if (i + j) % 2 == 0:
                _add(adj, (i, j), ((i + 1) % w, j))
    return adj


def hex_tube(circumference: int, length: int = 60, kind: str = "zigzag"):
    return honeycomb(length, circumference) if kind == "zigzag" else honeycomb(circumference, length)


def braided_line(levels: int = LINE_LEVELS):
    adj = _graph()
    for i in range(levels):
        _add(adj, ("L", i), ("L", (i + 1) % levels))
        _add(adj, ("R", i), ("R", (i + 1) % levels))
        if i % 2 == 0:
            _add(adj, ("L", i), ("R", (i + 1) % levels))
            _add(adj, ("R", i), ("L", (i + 1) % levels))
    return adj


def heptagonal(radius: int = HEPT_RADIUS):
    import numpy as np
    ell = 2 * math.acosh(math.cos(math.pi / 7) / math.sin(math.pi / 3))

    def rot(t):
        c, s = math.cos(t), math.sin(t)
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    def boost(d):
        c, s = math.cosh(d), math.sinh(d)
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [s, 0.0, c]])

    origin = np.array([0.0, 0.0, 1.0])
    step = [rot(2 * math.pi * k / 3) @ boost(ell) @ rot(math.pi) for k in range(3)]
    frames, points, cells = {0: np.eye(3)}, [origin], collections.defaultdict(list)

    def cell(p):
        return (round(p[0] / (1 + p[2]) * 2e4), round(p[1] / (1 + p[2]) * 2e4))

    def find(p):
        kx, ky = cell(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in cells.get((kx + dx, ky + dy), ()):
                    q = points[idx]
                    if p[2] * q[2] - p[0] * q[0] - p[1] * q[1] < 1.0 + 1e-6:
                        return idx
        return None

    cells[cell(origin)].append(0)
    adj, dist, queue = _graph(), {0: 0}, collections.deque([0])
    while queue:
        v = queue.popleft()
        if dist[v] >= radius:
            continue
        for k in range(3):
            frame = frames[v] @ step[k]
            p = frame @ origin
            w = find(p)
            if w is None:
                w = len(points)
                points.append(p)
                frames[w] = frame
                cells[cell(p)].append(w)
                dist[w] = dist[v] + 1
                queue.append(w)
            if w not in adj[v]:
                _add(adj, v, w)
    return adj, 0


def _bfs(adj, root, limit: int) -> dict:
    dist, queue = {root: 0}, collections.deque([root])
    while queue:
        u = queue.popleft()
        if dist[u] >= limit:
            continue
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                queue.append(v)
    return dist


def closed_trails(adj, root, lmax: int = CUTOFF) -> list[int]:
    dist = _bfs(adj, root, lmax // 2 + 1)
    counts = [0] * (lmax + 1)
    used: set = set()

    def go(u, depth):
        for v in adj[u]:
            e = (u, v) if u < v else (v, u)
            if e in used:
                continue
            d = depth + 1
            if v == root:
                counts[d] += 1
            dv = dist.get(v)
            if dv is None or dv > lmax - d or d >= lmax:
                continue
            used.add(e)
            go(v, d)
            used.discard(e)
    go(root, 0)
    return counts


def coupling(r: float, length: int) -> float:
    return r ** length / math.factorial(length)


def loop_energy(counts, r: float, cutoff: int = CUTOFF) -> float:
    return -sum(coupling(r, L) * counts[L] for L in range(min(cutoff, len(counts) - 1) + 1))


def per_vertex(name: str, lmax: int = CUTOFF) -> list[float]:
    if name == "hex":
        return [float(x) for x in closed_trails(honeycomb(*FLAT), (0, 0), lmax)]
    if name == "line":
        adj = braided_line()
        a, b = closed_trails(adj, ("L", 100), lmax), closed_trails(adj, ("L", 101), lmax)
        return [(x + y) / 2 for x, y in zip(a, b, strict=True)]
    if name == "hept":
        adj, root = heptagonal(lmax // 2 + 2)
        return [float(x) for x in closed_trails(adj, root, lmax)]
    kind, _, c = name.partition("_")
    if kind in TUBES:
        adj = hex_tube(int(c), 60, kind)
        roots = [(0, 0)] if kind == "zigzag" else [(0, 0), (1, 0)]
        counts = [closed_trails(adj, v, lmax) for v in roots]
        return [sum(x) / len(x) for x in zip(*counts, strict=True)]
    raise ValueError(f"no graph {name!r}")


def switch(adj, a, b, c, d):
    out = {v: list(ns) for v, ns in adj.items()}
    out[a].remove(c)
    out[c].remove(a)
    out[b].remove(d)
    out[d].remove(b)
    out[a].append(d)
    out[d].append(a)
    out[b].append(c)
    out[c].append(b)
    return out


def _same_hexagon(adj, a, b, c, d) -> bool:
    return any(c in adj[y] for x in adj[d] if x not in (a, b) for y in adj[x] if y not in (a, b, d))


def defect(adj, a, b, kind: str):
    for c in (x for x in adj[a] if x != b):
        for d in (x for x in adj[b] if x != a):
            if _same_hexagon(adj, a, b, c, d) == (kind == "II"):
                return switch(adj, a, b, c, d), (a, b, c, d)
    raise ValueError("no such exchange on this edge")


def defect_energy(kind: str, r: float, cutoff: int = CUTOFF) -> dict:
    adj = honeycomb(*FLAT)
    a, b = (FLAT[0] // 2, FLAT[1] // 2), (FLAT[0] // 2, FLAT[1] // 2 + 1)
    moved, quad = defect(adj, a, b, kind)
    near: set = set()
    for v in quad:
        near |= set(_bfs(adj, v, cutoff // 2 + 1)) | set(_bfs(moved, v, cutoff // 2 + 1))
    changes = [loop_energy(closed_trails(moved, v, cutoff), r, cutoff) - loop_energy(closed_trails(adj, v, cutoff), r,
                                                                                     cutoff) for v in near]
    return {"total": round(sum(changes), 1), "largest": round(max(changes), 1), "smallest": round(min(changes), 1),
            "vertices": len(changes)}


def random_cubic(n: int, rng: random.Random) -> dict:
    while True:
        stubs = [v for v in range(n) for _ in range(3)]
        rng.shuffle(stubs)
        edges, ok = set(), True
        for i in range(0, len(stubs), 2):
            a, b = stubs[i], stubs[i + 1]
            e = (min(a, b), max(a, b))
            if a == b or e in edges:
                ok = False
                break
            edges.add(e)
        if ok:
            adj = {v: set() for v in range(n)}
            for a, b in edges:
                adj[a].add(b)
                adj[b].add(a)
            return adj


def cycle_census(n: int, seeds: int, lmax: int, seed0: int) -> dict:
    totals = collections.Counter()
    for s in range(seeds):
        adj = random_cubic(n, random.Random(seed0 + s))
        g = {v: list(ns) for v, ns in adj.items()}
        for v in g:
            for L, c in enumerate(closed_trails(g, v, lmax)):
                totals[L] += c
    out = {}
    for L in range(3, lmax + 1):
        mean = totals[L] / (2 * L) / seeds
        out[str(L)] = {"mean": round(mean, 3), "expected": round(2 ** L / (2 * L), 3),
                       "ratio": round(mean / (2 ** L / (2 * L)), 3)}
    return out


def _dist_from(adj, src, limit: int) -> dict:
    return _bfs(adj, src, limit)


def cycles_through(adj, u, v, lmax: int, skip=frozenset()) -> list[int]:
    counts = [0] * (lmax + 1)
    dist = _dist_from(adj, u, lmax - 1)
    seen = {v}

    def go(x, depth):
        for y in adj[x]:
            if y == u:
                if depth + 1 >= 3 and x != v:
                    counts[depth + 1] += 1
                continue
            if y in seen or (min(x, y), max(x, y)) in skip:
                continue
            dy = dist.get(y)
            if dy is None or depth + 1 + dy > lmax:
                continue
            seen.add(y)
            go(y, depth + 1)
            seen.discard(y)
    go(v, 1)
    return counts


def _cycle_energy(counts, r: float) -> float:
    return -sum(coupling(r, L) * 2 * L * c for L, c in enumerate(counts))


def _apply(adj, a, b, c, d) -> None:
    adj[a].remove(c)
    adj[c].remove(a)
    adj[b].remove(d)
    adj[d].remove(b)
    adj[a].add(d)
    adj[d].add(a)
    adj[b].add(c)
    adj[c].add(b)


def exchange_delta(adj, move, r: float, lmax: int) -> float:
    a, b, c, d = move
    e1 = (min(a, c), max(a, c))
    old = [x + y for x, y in zip(cycles_through(adj, a, c, lmax), cycles_through(adj, b, d, lmax, frozenset([e1])),
                                 strict=True)]
    _apply(adj, a, b, c, d)
    f1 = (min(a, d), max(a, d))
    new = [x + y for x, y in zip(cycles_through(adj, a, d, lmax), cycles_through(adj, b, c, lmax, frozenset([f1])),
                                 strict=True)]
    return _cycle_energy(new, r) - _cycle_energy(old, r)


def undo(adj, move) -> None:
    a, b, c, d = move
    _apply(adj, a, b, d, c)


def propose(adj, nodes, rng):
    a = rng.choice(nodes)
    b = rng.choice(sorted(adj[a]))
    c = rng.choice(sorted(adj[a] - {b}))
    d = rng.choice(sorted(adj[b] - {a}))
    if c == d or d in adj[a] or c in adj[b]:
        return None
    return a, b, c, d


def run_chain(n: int, r: float, lmax: int, moves_per_node: int, seed: int, *, cool_share: float = 0.8,
              span: float = 100.0, cold_kt: float = 10.0) -> tuple[dict, dict]:
    rng = random.Random(seed)
    adj = random_cubic(n, rng)
    nodes = list(adj)
    changes = []
    while len(changes) < 100:
        move = propose(adj, nodes, rng)
        if move is not None:
            changes.append(abs(exchange_delta(adj, move, r, lmax)))
            undo(adj, move)
    scale = statistics.median([c for c in changes if c > 0] or [1.0])
    beta_end = cold_kt / scale
    beta_start = beta_end / span
    total = moves_per_node * n
    cool = int(cool_share * total)
    taken = 0
    for step in range(total):
        move = propose(adj, nodes, rng)
        if move is None:
            continue
        dh = exchange_delta(adj, move, r, lmax)
        if step < cool:
            beta = beta_start * (beta_end / beta_start) ** (step / cool)
            ok = dh <= 0 or rng.random() < math.exp(-beta * dh)
        else:
            ok = dh <= 0
        if ok:
            taken += 1
        else:
            undo(adj, move)
    return adj, {"beta_start": beta_start, "beta_end": beta_end, "accepted": taken, "proposals": total}


def honeycomb_share(adj) -> float:
    g = {v: list(ns) for v, ns in adj.items()}
    hit = 0
    for v in g:
        c = closed_trails(g, v, 8)
        hit += c[3] == c[4] == c[5] == c[7] == c[8] == 0 and c[6] == 6
    return round(hit / len(g), 4)


NAMED = ("hex", "line", "hept")
R_SCAN = (6.9, 7.0, 7.05, 7.1, 7.2, 7.3, 8.0, -7.1, -7.3)


def crossing_cutoff(hex_counts, line_counts, r: float, lmax: int = CUTOFF) -> int | None:
    for L in range(3, lmax + 1):
        if all(loop_energy(hex_counts, r, k) < loop_energy(line_counts, r, k) for k in range(L, lmax + 1)):
            return L
    return None


def crossing_r(hex_counts, line_counts, lmax: int = CUTOFF, lo: float = 6.0, hi: float = 9.0) -> float:
    def gap(r):
        return loop_energy(hex_counts, r, lmax) - loop_energy(line_counts, r, lmax)
    if gap(lo) * gap(hi) > 0:
        return float("nan")
    for _ in range(60):
        mid = (lo + hi) / 2
        if gap(lo) * gap(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 4)


def winding(tube_counts, flat_counts) -> int | None:
    return next((L for L, (t, f) in enumerate(zip(tube_counts, flat_counts, strict=True)) if t > f + 1e-9), None)


def named_readings() -> dict:
    counts = {name: per_vertex(name) for name in NAMED}
    hex30 = [float(x) for x in closed_trails(honeycomb(80, 80), (0, 0), 30)]
    out = {"counts": {k: v for k, v in counts.items()}}
    unit = abs(loop_energy(counts["hex"], R_FIGURE))
    out["figure_3"] = {name: {str(L): round(loop_energy(counts[name], R_FIGURE, L), 2) for L in range(CUTOFF + 1)}
                       for name in NAMED}
    out["figure_3_share_error"] = {
        name: round(max(abs(abs(loop_energy(counts[name], R_FIGURE, L)) / unit - px / FIGURE_3["hex"][CUTOFF])
                        for L, px in FIGURE_3[name].items()), 4) for name in NAMED}
    out["energy_at_cutoff"] = {str(r): {name: round(loop_energy(counts[name], r), 2) for name in NAMED} for r in R_SCAN}
    out["crossing_cutoff"] = crossing_cutoff(counts["hex"], counts["line"], R_FIGURE)
    out["crossing_r"] = crossing_r(counts["hex"], counts["line"])
    out["convergence_7.1"] = round(loop_energy(hex30, R_BOUND, CUTOFF) / loop_energy(hex30, R_BOUND, 30), 5)
    out["tubes"] = {}
    for kind, sizes in TUBES.items():
        for c in sizes:
            tube = per_vertex(f"{kind}_{c}")
            out["tubes"][f"{kind}_{c}"] = {
                "circumference_edges": winding(tube, counts["hex"]),
                "ratio_7.3": round(loop_energy(tube, R_FIGURE) / loop_energy(counts["hex"], R_FIGURE), 4),
                "ratio_7.1": round(loop_energy(tube, R_BOUND) / loop_energy(counts["hex"], R_BOUND), 4)}
    return out


def flat_readings(named: dict, defects: dict, census: dict, chains: list[dict]) -> dict:
    e = named["energy_at_cutoff"]
    out = {}
    for r in R_SCAN:
        for name in NAMED:
            out[f"E_{name}_{r}"] = e[str(r)][name]
        out[f"hex_below_line_{r}"] = round((e[str(r)]["line"] - e[str(r)]["hex"]) / abs(e[str(r)]["hex"]), 4)
        out[f"hex_below_hept_{r}"] = round((e[str(r)]["hept"] - e[str(r)]["hex"]) / abs(e[str(r)]["hex"]), 4)
    for name in NAMED:
        out[f"figure_3_error_{name}"] = named["figure_3_share_error"][name]
    f3 = named["figure_3"]
    out["line_below_hex_at_10"] = round(f3["hex"]["10"] - f3["line"]["10"], 2)
    out["crossing_cutoff"] = named["crossing_cutoff"]
    out["crossing_r"] = named["crossing_r"]
    out["convergence_7.1"] = named["convergence_7.1"]
    tubes = named["tubes"]
    best = max(tubes, key=lambda k: tubes[k]["ratio_7.3"])
    out["tube_best_ratio_7.3"] = tubes[best]["ratio_7.3"]
    out["tube_best_circumference"] = tubes[best]["circumference_edges"]
    out["tube_ratio_at_circumference_8"] = max(t["ratio_7.3"] for t in tubes.values() if t["circumference_edges"] == 8)
    for key, value in defects.items():
        out[f"defect_{key}_total"] = value["total"]
        out[f"defect_{key}_largest"] = value["largest"]
    for L, row in census.items():
        out[f"census_ratio_{L}"] = row["ratio"]
    groups = collections.defaultdict(list)
    for row in chains:
        if "error" not in row:
            groups[(row["r"], row["n"])].append(row)
    for (r, n), rows in groups.items():
        for key in ("honeycomb_share", "odd_short_share", "d_s", "half_volume_radius", "energy_per_vertex"):
            values = [x[key] for x in rows if x.get(key) is not None]
            if values:
                out[f"chain_{key}_{r}_{n}"] = round(statistics.median(values), 4)
    return out


def odd_short_share(adj, lmax: int = 7) -> float:
    g = {v: list(ns) for v, ns in adj.items()}
    return round(sum(any(closed_trails(g, v, lmax)[L] for L in range(3, lmax + 1, 2)) for v in g) / len(g), 4)


def chain_task(task: dict) -> dict:
    import replication as R
    started = time.monotonic()
    row = {k: task[k] for k in ("r", "n", "seed", "cutoff", "moves_per_node")}
    try:
        adj, schedule = run_chain(task["n"], task["r"], task["cutoff"], task["moves_per_node"], task["seed"])
        edges = sorted({(min(a, b), max(a, b)) for a in adj for b in adj[a]})
        reading = R.instrument(task["n"], edges)
        row.update({"schedule": schedule, "honeycomb_share": honeycomb_share(adj),
                    "odd_short_share": odd_short_share(adj),
                    "d_s": reading.get("d_s"), "half_volume_radius": reading.get("half_volume_radius"),
                    "instrument": reading,
                    "energy_per_vertex": round(sum(loop_energy(closed_trails({v: list(ns) for v, ns in adj.items()},
                                                                             v, task["cutoff"]), task["r"],
                                                               task["cutoff"]) for v in adj) / task["n"], 2)})
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["seconds"] = round(time.monotonic() - started, 1)
    return row


def parse_chains(text: str) -> list[tuple[float, int, int]]:
    out = []
    for token in (t.strip() for t in text.split(",") if t.strip()):
        r, _, rest = token.partition(":")
        n, _, k = rest.partition("x")
        out.append((float(r), int(n), int(k) if k else 1))
    return out


def judge(readings: dict, criterion: dict) -> list[dict]:
    import replication as R
    verdicts = []
    for p in criterion["predictions"]:
        value = readings.get(p["reading"])
        rule = p["rule"]
        if value is None or isinstance(value, bool) or (isinstance(value, float) and math.isnan(value)):
            verdict = "unread"
        elif "below" in rule:
            other = readings.get(rule["below"])
            verdict = "unread" if other is None else ("held" if value < other else "missed")
        else:
            verdict = "held" if R._meets(value, rule) else "missed"
        verdicts.append({"id": p["id"], "verdict": verdict, "expected": p.get("expect", "held"),
                         "as_expected": verdict == p.get("expect", "held"), "values": {p["reading"]: value}})
    return verdicts


def render(verdicts: list[dict], criterion: dict) -> str:
    claims = {p["id"]: p for p in criterion["predictions"]}
    lines = [f"{sum(v['as_expected'] for v in verdicts)} of {len(verdicts)} as the criterion expected; "
             f"{sum(v['verdict'] == 'held' for v in verdicts)} rules held"]
    for v in verdicts:
        p = claims[v["id"]]
        mark = "  " if v["as_expected"] else "! "
        lines.append(f"{mark}{v['id']:4} {v['verdict']:6} (expected {v['expected']}) {p['reading']} "
                     f"{json.dumps(p['rule'])} ({json.dumps(v['values'])})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/replication_konopka.py: see docs/TOOLS.md")
    parser.add_argument("--chains", default="-7.1:256x2,7.3:256x2", help="r:NxK, comma-separated")
    parser.add_argument("--chain-cutoff", type=int, default=CUTOFF)
    parser.add_argument("--moves", type=int, default=30, help="exchanges proposed a vertex, each chain")
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--census", default="2000x4", help="random cubic graphs: NxK")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--judge", help="a committed criterion to judge the run against")
    parser.add_argument("--read", help="judge a run already written instead")
    parser.add_argument("--output", help="default var/readings/replication_konopka_<utc>.json")
    args = parser.parse_args(argv)
    if args.read:
        document = json.loads(Path(args.read).read_text(encoding="utf-8"))
        if args.judge:
            criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
            print(render(judge(document["readings"], criterion), criterion))
        return 0
    started = time.monotonic()
    tasks = [{"r": r, "n": n, "seed": args.first_seed + s, "cutoff": args.chain_cutoff, "moves_per_node": args.moves}
             for r, n, k in parse_chains(args.chains) for s in range(k)]
    print(f"paper 3: the named graphs, the defects, a census and {len(tasks)} chains on {args.workers} worker(s)",
          flush=True)
    census_n, _, census_k = args.census.partition("x")
    chains: list[dict] = []
    try:
        from partial_rows import kept_on_failure, partial_path
    except ImportError:
        from tools.partial_rows import kept_on_failure, partial_path
    with kept_on_failure(chains, partial_path(args.output, "replication_konopka")):
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(chain_task, t): "chain" for t in tasks}
            named_f = pool.submit(named_readings)
            defect_f = {f"{kind}_{r}": pool.submit(defect_energy, kind, r) for kind in ("I", "II") for r in (R_BOUND,
                                                                                                             -R_BOUND)}
            census_f = pool.submit(cycle_census, int(census_n), int(census_k or 1), 10, args.first_seed * 1000)
            for future in as_completed(futures):
                row = future.result()
                chains.append(row)
                print(f"chain r={row['r']} N={row['n']} seed {row['seed']}: honeycomb share {row.get('honeycomb_share')}, "
                      f"odd {row.get('odd_short_share')}, d_s {row.get('d_s')}, {row['seconds']} s "
                      f"{row.get('error', '')}", flush=True)
            named = named_f.result()
            defects = {k: f.result() for k, f in defect_f.items()}
            census = census_f.result()
    chains.sort(key=lambda r: (r["r"], r["n"], r["seed"]))
    readings = flat_readings(named, defects, census, chains)
    document = {"contract": CONTRACT, "paper": PAPER,
                "run_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "seconds": round(time.monotonic() - started, 1), "open_choices": OPEN_CHOICES,
                "command": {"chains": args.chains, "chain_cutoff": args.chain_cutoff, "moves": args.moves,
                            "first_seed": args.first_seed, "census": args.census},
                "named": named, "defects": defects, "census": census, "chains": chains, "readings": readings}
    for key, value in sorted(readings.items()):
        print(f"  {key}: {value}")
    if args.judge:
        criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
        verdicts = judge(readings, criterion)
        document["criterion"] = {"path": args.judge, "verdicts": verdicts}
        print(render(verdicts, criterion))
    out = Path(args.output) if args.output else (
        ROOT / "var" / "readings" / f"replication_konopka_{document['run_utc'].replace(':', '-')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
