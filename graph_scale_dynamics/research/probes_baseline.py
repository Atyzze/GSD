from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from graph_scale_dynamics.domain.randomness import derive_seed
from graph_scale_dynamics.measurements import benchmarks, estimators, known_answers

CONTRACT = "gsd-probes-baseline-1"
DRAWN = 320
DRAWN_SIZES = (12, 20, 32, 48, 96, 200, 400, 800, 1500, 3000)
START_SIZES = (64, 256, 1024, 4096, 16384, 65536)
STARTS = (known_answers.SQUARE_TORUS, known_answers.CUBIC_QUOTIENT, known_answers.TESSERACT_QUOTIENT,
          known_answers.HONEYCOMB_TORUS, known_answers.TRIANGULAR_TORUS, known_answers.BODY_CENTRED_CUBIC,
          known_answers.FACE_CENTRED_CUBIC)
VALUE = {"d_s": "d_s", "d_V": "d_V_window", "d_B": "d_B", "d_w": "d_w"}
A_DIMENSION, NONE = "a dimension", "none"


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items() if key != "probe_seconds"}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return repr(number) if math.isfinite(number) else str(number)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _geometric_plane(n: int, mean_degree: float, rng) -> list:
    from scipy.spatial import cKDTree
    points = rng.random((n, 2))
    radius = math.sqrt(mean_degree / (math.pi * n))
    return sorted(tuple(int(x) for x in pair) for pair in cKDTree(points).query_pairs(radius))


def _recursive_tree(n: int, rng) -> list:
    return [(int(rng.integers(0, v)), v) for v in range(1, n)]


def _ring_rewired(n: int, share: float, rng) -> list:
    edges = set()
    for v in range(n):
        for step in (1, 2):
            w = (v + step) % n
            if rng.random() < share:
                w = int(rng.integers(0, n))
            if w != v:
                edges.add((min(v, w), max(v, w)))
    return sorted(edges)


def _preferential(n: int, links: int, rng) -> list:
    edges = {(w, v) for v in range(links + 1) for w in range(v)}
    ends = [x for edge in edges for x in edge]
    for v in range(links + 1, n):
        chosen = set()
        while len(chosen) < links:
            chosen.add(int(ends[int(rng.integers(0, len(ends)))]))
        for w in chosen:
            edges.add((w, v))
            ends += [w, v]
    return sorted(edges)


def drawn(seed: int) -> dict:
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.choice(DRAWN_SIZES))
    which = seed % 8
    if which == 0:
        mean_degree = float(rng.choice([1.5, 2.5, 4.0, 6.0]))
        _, edges = benchmarks.erdos_renyi(n, mean_degree, seed=seed)
        name, kind, has = f"er_{n}_{mean_degree}", f"random graph of mean degree {mean_degree:g}", NONE
    elif which == 1:
        degree = int(rng.choice([3, 4, 6]))
        n = max(48, n if (n * degree) % 2 == 0 else n + 1)
        _, edges = benchmarks.random_regular(n, degree, seed=seed)
        name, kind, has = f"rrg_{n}_{degree}", f"random {degree}-regular graph", NONE
    elif which == 2:
        edges = _geometric_plane(n, float(rng.choice([6.0, 10.0])), rng)
        name, kind, has = f"rgg2_{n}", "random geometric graph in the plane", A_DIMENSION
    elif which == 3:
        edges = _recursive_tree(n, rng)
        name, kind, has = f"tree_{n}", "random recursive tree", NONE
    elif which == 4:
        share = float(rng.choice([0.0, 0.02, 0.2]))
        edges = _ring_rewired(n, share, rng)
        name, kind, has = f"ws_{n}", f"ring with {share:g} of its edges rewired", A_DIMENSION if share == 0 else NONE
    elif which == 5:
        links = int(rng.choice([1, 2, 3]))
        edges = _preferential(n, links, rng)
        name, kind, has = f"ba_{n}", f"preferential attachment, {links} links a node", NONE
    elif which == 6:
        side = int(round(math.sqrt(n)))
        n = side * side
        _, edges = benchmarks.lattice(2, side, periodic=bool(seed % 2))
        kept = rng.random(len(edges))
        removed = float(rng.choice([0.0, 0.1, 0.3]))
        edges = [edge for edge, share in zip(edges, kept, strict=True) if share > removed]
        name, kind, has = f"diluted_square_{n}", f"square lattice with {removed:g} of its bonds removed", A_DIMENSION
    else:
        dimension = int(rng.choice([1, 3, 4]))
        side = max(3, int(round(n ** (1 / dimension))))
        n, edges = benchmarks.lattice(dimension, side, periodic=bool(seed % 2))
        name, kind, has = f"lattice{dimension}_{n}", f"lattice of {dimension} dimensions", A_DIMENSION
    return {"name": f"{name}_s{seed}", "kind": kind, "has": has, "n": int(n),
            "edges": [tuple(int(x) for x in edge) for edge in edges], "seed": seed}


def graphs(top: int = START_SIZES[-1]) -> list[dict]:
    starts = [{"name": f"{family}_{n}", "kind": "lattice start", "has": A_DIMENSION, "n": n,
               "edges": known_answers.edges(family, n), "seed": 0}
              for family in STARTS for n in START_SIZES if n <= top and known_answers.reaches(family, n)]
    return starts + [drawn(seed) for seed in range(DRAWN)]


def read(graph: dict) -> tuple[str, dict]:
    rng = np.random.default_rng(derive_seed("baseline", graph["name"], graph["seed"]) % (2 ** 63))
    result, _curves = estimators._measure_graph(graph["n"], graph["edges"], rng, measure_geometry=True)
    return graph["name"], {"kind": graph["kind"], "has": graph["has"], "result": plain(result)}


def measure(top: int = START_SIZES[-1], workers: int = 1) -> dict:
    tasks = graphs(top)
    if int(workers) <= 1:
        found = dict(read(task) for task in tasks)
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            found = dict(pool.map(read, tasks))
    return {"contract": CONTRACT, "top": int(top), "graphs": found}


def _state(result: dict, probe: str) -> str:
    block = result.get(probe) or {}
    return "read" if block.get("valid") is True else str(block.get("refusal"))


def _value(result: dict, probe: str) -> float:
    return float(result[probe][VALUE[probe]])


def compare(before: dict, after: dict) -> dict:
    out = {}
    for probe in VALUE:
        both = same = 0
        moved, lost, gained, now = [], defaultdict(list), defaultdict(list), Counter()
        for name, graph in before["graphs"].items():
            if name not in after["graphs"]:
                continue
            was, is_now = graph["result"], after["graphs"][name]["result"]
            a, b = _state(was, probe), _state(is_now, probe)
            now[graph["has"]] += b == "read"
            where = f"{graph['has']}: {graph['kind']}"
            if a == b == "read":
                both += 1
                if was[probe][VALUE[probe]] == is_now[probe][VALUE[probe]]:
                    same += 1
                else:
                    moved.append((name, _value(was, probe), _value(is_now, probe)))
            elif a == "read":
                lost[f"{where}: {b}"].append((int(was["component"]), round(_value(was, probe), 2)))
            elif b == "read":
                gained[where].append((int(is_now["component"]), round(_value(is_now, probe), 2)))
        out[probe] = {"read_in_both": both, "same_to_the_last_digit": same,
                      "moved": sorted(moved, key=lambda row: -abs(row[2] - row[1])),
                      "lost": {key: sorted(rows) for key, rows in sorted(lost.items())},
                      "gained": {key: sorted(rows) for key, rows in sorted(gained.items())},
                      "read_now": dict(sorted(now.items()))}
    return out


def render(found: dict, most: int = 8) -> str:
    lines = []
    for probe, part in found.items():
        lines.append(f"{probe}: read in both {part['read_in_both']}, the same to the last digit "
                     f"{part['same_to_the_last_digit']}; read now on graphs with {A_DIMENSION} "
                     f"{part['read_now'].get(A_DIMENSION, 0)}, on graphs with {NONE} {part['read_now'].get(NONE, 0)}")
        for label in ("lost", "gained"):
            for where, rows in part[label].items():
                lines.append(f"  {label} {len(rows)} ({where}): " + ", ".join(
                    f"{value:g} at {nodes}" for nodes, value in rows[:most]) + (" ..." if len(rows) > most else ""))
        for name, was, now in part["moved"][:most]:
            lines.append(f"  moved {re.sub(r'_s[0-9]+$', '', name)}: {was:.4f} to {now:.4f}")
    return "\n".join(lines) + "\n"
