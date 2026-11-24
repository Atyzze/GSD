from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

CALIBRATION_CONTRACT = "gsd-calibration-anchor-1"

SIERPINSKI_DF = math.log(3) / math.log(2)
SIERPINSKI_DW = math.log(5) / math.log(2)
SIERPINSKI_DS = 2 * math.log(3) / math.log(5)

LATTICE_DF = 2.0
LATTICE_DW = 2.0
LATTICE_DS = 2.0


def sierpinski_gasket(level: int) -> tuple[int, list[tuple[int, int]]]:
    points = {(0, 0): 0, (1, 0): 1, (0, 1): 2}
    edges: list[tuple[int, int]] = [(0, 1), (0, 2), (1, 2)]
    for _ in range(level):
        span = max(max(x, y) for x, y in points)
        inverse = {index: point for point, index in points.items()}
        fresh: dict[tuple[int, int], int] = {}
        rebuilt: list[tuple[int, int]] = []

        def index_of(point, fresh=fresh):
            if point not in fresh:
                fresh[point] = len(fresh)
            return fresh[point]

        for shift_x, shift_y in ((0, 0), (span, 0), (0, span)):
            for u, v in edges:
                ux, uy = inverse[u]
                vx, vy = inverse[v]
                a = index_of((ux + shift_x, uy + shift_y))
                b = index_of((vx + shift_x, vy + shift_y))
                if a != b:
                    rebuilt.append((min(a, b), max(a, b)))
        points = fresh
        edges = sorted(set(rebuilt))
    return len(points), edges


def periodic_square_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    def index(x: int, y: int) -> int:
        return (y % side) * side + (x % side)

    edges: set[tuple[int, int]] = set()
    for y in range(side):
        for x in range(side):
            here = index(x, y)
            for nx, ny in ((x + 1, y), (x, y + 1)):
                other = index(nx, ny)
                if here != other:
                    edges.add((min(here, other), max(here, other)))
    return side * side, sorted(edges)


ANCHORS: tuple[dict, ...] = (
    {
        "name": "sierpinski_gasket_level_7",
        "build": lambda: sierpinski_gasket(7),
        "expect": {"d_s": SIERPINSKI_DS, "d_B": SIERPINSKI_DF, "d_w": SIERPINSKI_DW},
        "tolerance": {"d_s": 0.25, "d_B": 0.35, "d_w": 0.35},
        "why": ("all three channels differ, so a pipeline that has collapsed or "
                "crossed them is caught rather than merely looking plausible"),
    },
    {
        "name": "periodic_square_lattice_48",
        "build": lambda: periodic_square_lattice(48),
        "expect": {"d_s": LATTICE_DS, "d_w": LATTICE_DW},
        "tolerance": {"d_s": 0.30, "d_w": 0.40},
        "why": ("arrives converged with no boundary, which is the case the flow "
                "ladder's already-flat route exists for"),
    },
)


def periodic_ring(n: int) -> tuple[int, list[tuple[int, int]]]:
    count = int(n)
    return count, sorted((i, (i + 1) % count) if i < (i + 1) % count
                         else ((i + 1) % count, i) for i in range(count))


def periodic_cubic_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    s = int(side)

    def index(x: int, y: int, z: int) -> int:
        return (x % s) * s * s + (y % s) * s + (z % s)

    edges = set()
    for x in range(s):
        for y in range(s):
            for z in range(s):
                here = index(x, y, z)
                for dx, dy, dz in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
                    other = index(x + dx, y + dy, z + dz)
                    if here != other:
                        edges.add((min(here, other), max(here, other)))
    return s ** 3, sorted(edges)


def random_regular_graph(n: int, degree: int = 4, seed: int = 0) -> tuple[int, list[tuple[int, int]]]:
    import numpy as np

    count = int(n)
    if (count * degree) % 2:
        raise ValueError("n*degree must be even")
    rng = np.random.default_rng(int(seed) * 1_000_003 + count)
    for _ in range(10_000):
        stubs = np.repeat(np.arange(count), degree)
        rng.shuffle(stubs)
        pairs = stubs.reshape(-1, 2)
        edges = set()
        simple = True
        for a, b in pairs:
            a, b = int(a), int(b)
            if a == b:
                simple = False
                break
            key = (min(a, b), max(a, b))
            if key in edges:
                simple = False
                break
            edges.add(key)
        if simple:
            return count, sorted(edges)
    raise RuntimeError("configuration model failed to produce a simple graph")


STANDARD_LADDER_MAX_NODES = 20000

CALIBRATION_FAMILIES: tuple[dict, ...] = (
    {
        "name": "periodic_ring",
        "expectation": "MEASURE",
        "theory": {"d_s": 1.0, "d_B": 1.0, "d_w": 2.0, "d_V": 1.0},
        "build": lambda size: periodic_ring(size),
        "size": lambda size: int(size),
        "ladder": (64, 128, 256, 512, 1024, 2048, 4096, 8192,
                   16384, 65536, 262144, 1048576),
        "why": "the 1D torus bounds the probes from below; ordinary diffusion",
    },
    {
        "name": "periodic_square_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 2.0, "d_B": 2.0, "d_w": 2.0, "d_V": 2.0},
        "build": lambda side: periodic_square_lattice(side),
        "size": lambda side: int(side) ** 2,
        "ladder": (8, 12, 16, 24, 32, 48, 64, 96, 128, 256, 512, 1024),
        "why": "2D torus; arrives converged with no boundary",
    },
    {
        "name": "periodic_cubic_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 3.0, "d_B": 3.0, "d_w": 2.0, "d_V": 3.0},
        "build": lambda side: periodic_cubic_lattice(side),
        "size": lambda side: int(side) ** 3,
        "ladder": (4, 5, 6, 8, 10, 12, 16, 20, 25, 40, 64, 101),
        "why": "3D torus; the campaign's plausible upper dimensional range",
    },
    {
        "name": "sierpinski_gasket",
        "expectation": "MEASURE",
        "theory": {"d_s": SIERPINSKI_DS, "d_B": SIERPINSKI_DF, "d_w": SIERPINSKI_DW,
                   "d_V": SIERPINSKI_DF},
        "build": lambda level: sierpinski_gasket(level),
        "size": lambda level: (3 ** (int(level) + 1) + 3) // 2,
        "ladder": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
        "why": "exact fractal: all three channels differ; the finite-size "
               "bias of d_B on this family is the study's known hard case",
    },
    {
        "name": "random_4_regular",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: random_regular_graph(size, degree=4, seed=1),
        "build_seeded": lambda size, seed: random_regular_graph(size, degree=4, seed=seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (128, 256, 512, 1024, 2048, 4096, 8192, 16384,
                   65536, 262144, 1048576),
        "why": "expander: exponential ball growth, no finite dimension of any "
               "kind; every confident probe reading here is a defect",
    },
)


def family_rung_size(family: dict, parameter) -> int:
    size = family.get("size")
    if size is not None:
        return int(size(parameter))
    n, _edges = family["build"](parameter)
    return int(n)


BRANCHING_LINE_REFERENCE: dict[str, dict] = {
    "uniform_random_tree": {
        "structure": "tree", "mean_degree": 2.0, "line": 1.0,
        "d_s_measured": 1.26, "residual": 0.26, "on_line": False,
        "note": "a real tree, exactly d_s = 4/3, a quarter above the line",
    },
    "balanced_binary_tree": {
        "structure": "tree", "mean_degree": 2.0, "line": 1.0,
        "d_s_measured": 1.30, "residual": 0.30, "on_line": False,
        "note": "a real tree, drifting away from the line as N grows",
    },
    "periodic_ring": {
        "structure": "1d lattice", "mean_degree": 2.0, "line": 1.0,
        "d_s_measured": 1.0, "residual": 0.0, "on_line": True,
        "note": "a ring is on the line by coincidence: d_s = 1 and <d> - 1 = 1. "
                "The control-family match, not the line, is what identifies it",
    },
    "random_3_regular": {
        "structure": "expander", "mean_degree": 3.0, "line": 2.0,
        "d_s_measured": 2.06, "residual": 0.06, "on_line": True,
        "note": "on the line, and not a tree: this is what the line describes",
    },
    "erdos_renyi_sparse": {
        "structure": "random graph", "mean_degree": 2.77, "line": 1.77,
        "d_s_measured": 1.80, "residual": 0.03, "on_line": True,
        "note": "giant-component mean degree; on the line",
    },
    "erdos_renyi_mid": {
        "structure": "random graph", "mean_degree": 3.18, "line": 2.18,
        "d_s_measured": 2.16, "residual": -0.02, "on_line": True,
        "note": "giant-component mean degree; on the line to within noise",
    },
    "erdos_renyi_degree_2": {
        "structure": "random graph", "mean_degree": 2.40, "line": 1.40,
        "d_s_measured": 1.50, "residual": 0.10, "on_line": True,
        "note": "529: giant-component mean degree at nominal 2; on the line to +0.10, the "
                "structureless object nearest the laws the gate reads at <d> near 2",
    },
    "erdos_renyi_dense": {
        "structure": "random graph", "mean_degree": 4.08, "line": 3.08,
        "d_s_measured": 2.824, "residual": -0.256, "on_line": False,
        "note": "the dangerous one. A structureless random graph with a d_s that "
                "is stable to 0.006 across ten seeds at 262,144 and sits OFF the "
                "branching line, so the gate does not withhold it. Only the "
                "refusal of the other three channels distinguishes it from a "
                "geometry, which is why the discovery score demands three valid "
                "probes before it scores anything",
    },
    "periodic_square_lattice": {
        "structure": "2d lattice", "mean_degree": 4.0, "line": 3.0,
        "d_s_measured": 2.0, "residual": -1.0, "on_line": False,
        "note": "a real geometry sits a full dimension below the line",
    },
    "periodic_cubic_lattice": {
        "structure": "3d lattice", "mean_degree": 6.0, "line": 5.0,
        "d_s_measured": 3.0, "residual": -2.0, "on_line": False,
        "note": "the gap widens with dimension; a metric graph is never on the line",
    },
    "sierpinski_gasket": {
        "structure": "fractal", "mean_degree": 4.0, "line": 3.0,
        "d_s_measured": 1.365, "residual": -1.635, "on_line": False,
        "note": "an exact fractal is far below the line",
    },
}


TABLE_HOLDS = Path(__file__).resolve().parents[1] / "resources" / "calibration" / "table_holds.json"
CHANNELS_A_REFUSAL_IS_REQUIRED_ON = ("d_s", "d_B", "d_w", "d_V")


@lru_cache(maxsize=1)
def what_the_table_holds() -> dict:
    return json.loads(TABLE_HOLDS.read_text(encoding="utf-8"))


def ladder_tolerance(family_name: str, channel: str, n: int) -> float | None:
    held = (what_the_table_holds()["with_a_dimension"].get(family_name) or {}).get(channel) or {}
    chosen: float | None = None
    for nodes, within in held.get("bands") or ():
        if int(n) >= int(nodes):
            chosen = float(within)
    return chosen


def refusal_required_from(family_name: str) -> dict:
    held = what_the_table_holds()
    if family_name not in held["without_a_dimension"]:
        return {}
    return {channel: int(held["a_refusal_is_required_from_nodes"]) for channel in CHANNELS_A_REFUSAL_IS_REQUIRED_ON}


def periodic_triangular_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    s = int(side)

    def index(x: int, y: int) -> int:
        return (x % s) * s + (y % s)

    edges = set()
    for x in range(s):
        for y in range(s):
            here = index(x, y)
            for dx, dy in ((1, 0), (0, 1), (1, -1)):
                other = index(x + dx, y + dy)
                if here != other:
                    edges.add((min(here, other), max(here, other)))
    return s * s, sorted(edges)


def periodic_honeycomb_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    s = int(side)
    if s % 2:
        raise ValueError("honeycomb side must be even")

    def index(x: int, y: int) -> int:
        return (x % s) * s + (y % s)

    edges = set()
    for x in range(s):
        for y in range(s):
            here = index(x, y)
            neighbours = [index(x, y + 1), index(x, y - 1)]
            neighbours.append(index(x + 1, y) if (x + y) % 2 == 0 else index(x - 1, y))
            for other in neighbours:
                if here != other:
                    edges.add((min(here, other), max(here, other)))
    return s * s, sorted(edges)


def periodic_hypercubic_lattice_4d(side: int) -> tuple[int, list[tuple[int, int]]]:
    s = int(side)

    def index(a: int, b: int, c: int, d: int) -> int:
        return (((a % s) * s + (b % s)) * s + (c % s)) * s + (d % s)

    edges = set()
    for a in range(s):
        for b in range(s):
            for c in range(s):
                for d in range(s):
                    here = index(a, b, c, d)
                    for other in (index(a + 1, b, c, d), index(a, b + 1, c, d),
                                  index(a, b, c + 1, d), index(a, b, c, d + 1)):
                        if here != other:
                            edges.add((min(here, other), max(here, other)))
    return s ** 4, sorted(edges)


def _torus_edges(sites, side: int, steps) -> list[tuple[int, int]]:
    import numpy as np
    s = int(side)
    sites = np.asarray(sites, dtype=np.int64).reshape(-1, 4)
    index = {int(k): i for i, k in enumerate(((sites[:, 0] * s + sites[:, 1]) * s + sites[:, 2]) * s + sites[:, 3])}
    pairs = []
    for step in steps:
        other = (sites + np.asarray(step, dtype=np.int64)) % s
        keys = ((other[:, 0] * s + other[:, 1]) * s + other[:, 2]) * s + other[:, 3]
        target = np.fromiter((index[int(k)] for k in keys), dtype=np.int64, count=len(keys))
        here = np.arange(len(sites), dtype=np.int64)
        keep = here != target
        pairs.append(np.stack([np.minimum(here, target)[keep], np.maximum(here, target)[keep]], axis=1))
    edges = np.unique(np.concatenate(pairs), axis=0)
    return [(int(a), int(b)) for a, b in edges]


def periodic_a4_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    import itertools
    import numpy as np
    s = int(side)
    sites = np.array(list(itertools.product(range(s), repeat=4)), dtype=np.int64)
    unit = np.eye(4, dtype=np.int64)
    steps = [unit[i] for i in range(4)] + [unit[i] - unit[j] for i in range(4) for j in range(4) if i != j]
    steps += [-step for step in steps[:4]]
    return len(sites), _torus_edges(sites, s, steps)


def periodic_d4_lattice(side: int) -> tuple[int, list[tuple[int, int]]]:
    import itertools
    import numpy as np
    s = 2 * (int(side) // 2)
    sites = np.array([p for p in itertools.product(range(s), repeat=4) if sum(p) % 2 == 0], dtype=np.int64)
    steps = []
    for i, j in itertools.combinations(range(4), 2):
        for a, b in itertools.product((1, -1), repeat=2):
            step = [0, 0, 0, 0]
            step[i], step[j] = a, b
            steps.append(step)
    return len(sites), _torus_edges(sites, s, steps)


SIERPINSKI_CARPET_DF = math.log(8) / math.log(3)


def sierpinski_carpet(level: int) -> tuple[int, list[tuple[int, int]]]:
    size = 3 ** int(level)

    def kept(x: int, y: int) -> bool:
        while x or y:
            if x % 3 == 1 and y % 3 == 1:
                return False
            x //= 3
            y //= 3
        return True

    cells = [(x, y) for x in range(size) for y in range(size) if kept(x, y)]
    index = {cell: i for i, cell in enumerate(cells)}
    edges = []
    for (x, y), i in index.items():
        for other in ((x + 1, y), (x, y + 1)):
            j = index.get(other)
            if j is not None:
                edges.append((min(i, j), max(i, j)))
    return len(cells), sorted(edges)


CRT_DF = 2.0
CRT_DW = 3.0
CRT_DS = 4.0 / 3.0


def uniform_random_tree(n: int, seed: int = 0) -> tuple[int, list[tuple[int, int]]]:
    import heapq

    import numpy as np

    count = int(n)
    if count < 2:
        return max(count, 1), []
    if count == 2:
        return 2, [(0, 1)]
    rng = np.random.default_rng(int(seed) * 1_000_003 + count)
    prufer = rng.integers(0, count, size=count - 2)
    degree = np.ones(count, dtype=np.int64)
    for node in prufer:
        degree[node] += 1
    leaves = [i for i in range(count) if degree[i] == 1]
    heapq.heapify(leaves)
    edges: list[tuple[int, int]] = []
    for node in prufer:
        leaf = heapq.heappop(leaves)
        node = int(node)
        edges.append((min(leaf, node), max(leaf, node)))
        degree[node] -= 1
        if degree[node] == 1:
            heapq.heappush(leaves, node)
    a = heapq.heappop(leaves)
    b = heapq.heappop(leaves)
    edges.append((min(a, b), max(a, b)))
    result = sorted(edges)
    if len(result) != count - 1:
        raise RuntimeError("Prufer decoding did not produce a spanning tree")
    return count, result


def balanced_tree(branching: int, height: int) -> tuple[int, list[tuple[int, int]]]:
    edges: list[tuple[int, int]] = []
    count = 1
    frontier = [0]
    for _ in range(int(height)):
        nxt = []
        for parent in frontier:
            for _ in range(int(branching)):
                edges.append((parent, count))
                nxt.append(count)
                count += 1
        frontier = nxt
    return count, sorted(edges)


def erdos_renyi_graph(n: int, mean_degree: float, seed: int = 0) -> tuple[int, list[tuple[int, int]]]:
    import numpy as np

    count = int(n)
    target = int(round(float(mean_degree) * count / 2.0))
    if target < 1:
        return count, []
    rng = np.random.default_rng(int(seed) * 1_000_003 + count)
    chosen: set[tuple[int, int]] = set()
    guard = 0
    while len(chosen) < target:
        guard += 1
        if guard > 512:
            raise RuntimeError("Erdos-Renyi construction failed to reach its edge target")
        need = (target - len(chosen)) * 2 + 16
        left = rng.integers(0, count, size=need)
        right = rng.integers(0, count, size=need)
        for a, b in zip(left, right):
            a, b = int(a), int(b)
            if a != b:
                chosen.add((min(a, b), max(a, b)))
            if len(chosen) >= target:
                break
    return count, sorted(chosen)


CALIBRATION_FAMILIES = CALIBRATION_FAMILIES + (
    {
        "name": "periodic_triangular_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 2.0, "d_B": 2.0, "d_w": 2.0, "d_V": 2.0},
        "build": lambda side: periodic_triangular_lattice(side),
        "size": lambda side: int(side) ** 2,
        "ladder": (8, 12, 16, 24, 32, 48, 64, 96, 128, 256, 512, 1024),
        "why": "2D torus with degree 6: does a 2D reading depend on the lattice or the dimension?",
    },
    {
        "name": "periodic_honeycomb_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 2.0, "d_B": 2.0, "d_w": 2.0, "d_V": 2.0},
        "build": lambda side: periodic_honeycomb_lattice(side),
        "size": lambda side: int(side) ** 2,
        "ladder": (8, 12, 16, 24, 32, 48, 64, 96, 128, 256, 512, 1024),
        "why": "2D torus with degree 3: the sparsest planar lattice",
    },
    {
        "name": "periodic_hypercubic_lattice_4d",
        "expectation": "MEASURE",
        "theory": {"d_s": 4.0, "d_B": 4.0, "d_w": 2.0, "d_V": 4.0},
        "build": lambda side: periodic_hypercubic_lattice_4d(side),
        "size": lambda side: int(side) ** 4,
        "ladder": (3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 28, 32),
        "why": "4D torus: beyond the campaign's plausible range, the integer ceiling of the probes",
    },
    {
        "name": "periodic_a4_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 4.0, "d_B": 4.0, "d_w": 2.0, "d_V": 4.0},
        "build": lambda side: periodic_a4_lattice(side),
        "size": lambda side: int(side) ** 4,
        "ladder": (3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 28),
        "why": "the close-packed 4D lattice of 20 neighbours (A4) on a torus: 4D at a degree inside the cap of 32",
    },
    {
        "name": "periodic_d4_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 4.0, "d_B": 4.0, "d_w": 2.0, "d_V": 4.0},
        "build": lambda side: periodic_d4_lattice(side),
        "size": lambda side: (2 * (int(side) // 2)) ** 4 // 2,
        "ladder": (4, 6, 8, 10, 12, 16, 20, 24, 28, 32),
        "why": "the densest 4D lattice, 24 neighbours (D4, the checkerboard lattice) on a torus: 4D at a degree inside "
               "the cap of 32",
    },
    {
        "name": "sierpinski_carpet",
        "expectation": "MEASURE",
        "theory": {"d_B": SIERPINSKI_CARPET_DF, "d_V": SIERPINSKI_CARPET_DF},
        "build": lambda level: sierpinski_carpet(level),
        "size": lambda level: 8 ** int(level),
        "ladder": (1, 2, 3, 4, 5, 6),
        "why": "second exact fractal (d_f = log8/log3); d_s and d_w have no closed form here and are charted unjudged",
    },
)


CALIBRATION_FAMILIES = CALIBRATION_FAMILIES + (
    {
        "name": "uniform_random_tree",
        "expectation": "MEASURE",
        "theory": {"d_s": CRT_DS, "d_B": CRT_DF, "d_w": CRT_DW, "d_V": CRT_DF},
        "build": lambda size: uniform_random_tree(size, 0),
        "build_seeded": lambda size, seed: uniform_random_tree(size, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "a real tree with three exact and distinct dimensions (Brownian CRT: "
               "d_f=2, d_w=3, d_s=4/3). Every tree has <d> -> 2, so the branching "
               "line predicts d_s = 1 and the truth is 4/3: this family is the "
               "known object that shows the line does not describe trees",
    },
    {
        "name": "balanced_binary_tree",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda height: balanced_tree(2, height),
        "size": lambda height: 2 ** (int(height) + 1) - 1,
        "ladder": (7, 8, 9, 10, 11, 12, 13, 15, 17),
        "why": "a deterministic tree with a fixed branching ratio: exponential ball "
               "growth, no dimension of any kind, and the case where d_s's "
               "false-confidence is easiest to see against a known answer",
    },
    {
        "name": "random_3_regular",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: random_regular_graph(size, degree=3, seed=1),
        "build_seeded": lambda size, seed: random_regular_graph(size, degree=3, seed=seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "the object the branching line actually describes: a locally "
               "tree-like regular expander whose local limit is the Bethe "
               "lattice. <d>-1 = 2 exactly and d_s reads 2.08, so a law on the "
               "line looks like this, not like a tree. random_4_regular sits one "
               "degree higher, where d_s stops answering at all; the two together "
               "bracket the band the survey searches in",
    },
    {
        "name": "erdos_renyi_sparse",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 2.5, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 2.5, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "the survey's null ensemble at the low end of its mean-degree "
               "window. Locally tree-like, log diameter, a positive density of "
               "cycles, no dimension. Measured giant-component <d> 2.77 and d_s "
               "1.80: on the branching line to +0.03",
    },
    {
        "name": "erdos_renyi_mid",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 3.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 3.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "the centre of the band campaign 8 drew from. Measured "
               "giant-component <d> 3.18 and d_s 2.18: on the branching line to "
               "-0.000. Any law whose residual profile matches this family is "
               "reproducing an Erdos-Renyi graph and nothing else",
    },
    {
        "name": "erdos_renyi_dense",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 4.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 4.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "the top of the band, and the dangerous case. d_s does NOT stop "
               "answering here: it refuses intermittently in the middle of the "
               "ladder and answers on all ten seeds at 262,144, reading 2.821 to "
               "2.827. What it does stop doing is tracking <d> - 1: the giant "
               "component sits near 4.08, the branching line predicts 3.08, and "
               "the probe reads 2.824, a residual of -0.26 that puts it OUTSIDE "
               "the branching-line gate. A law reproducing this scores a full 25 "
               "for stability and is not withheld; only the refusal of the other "
               "three channels distinguishes it from a geometry",
    },
    {
        "name": "erdos_renyi_degree_16",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 16.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 16.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "a random graph at mean degree 16, the middle of the cap of 32: no finite dimension, to be refused",
    },
    {
        "name": "erdos_renyi_degree_32",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 32.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 32.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "a random graph at mean degree 32, the top of study 169's cap: no finite dimension, to be refused",
    },
    {
        "name": "erdos_renyi_degree_2",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 2.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 2.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "the structureless case at the mean degree the gate's laws live at: nominal <d> 2, "
               "a giant component of 80% at <d> 2.40. A ring and a random tree are anchored at 2; "
               "this is the random graph beside them. d_s reads 1.47 to 1.52 from 1,024 up, on the "
               "branching line (1.40) to +0.1, and no other channel answers",
    },
    {
        "name": "erdos_renyi_degree_6",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: erdos_renyi_graph(size, 6.0, 1),
        "build_seeded": lambda size, seed: erdos_renyi_graph(size, 6.0, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144),
        "why": "past the top of the band: nominal <d> 6, where 520 found the withheld d_s values "
               "flatten at 5 to 7. The spectral probe refuses here on every seed; what fools the "
               "instrument instead is d_V, near 5 up to 8,192, before its window is long enough to "
               "see the exponential (under analysis-3.0.0; 4.0 refuses it at every rung, 627)",
    },
)


SIZES_A_LAW_RUNS = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)
TRIANGLES_AT_A_NODE = 7
HYPERBOLIC_MEAN_DEGREE = 12.0
HYPERBOLIC_JOINED_WITHIN = 1.0


def lattice_start(family: str, n: int) -> tuple[int, list[tuple[int, int]]]:
    from graph_scale_dynamics.measurements import known_answers
    return int(n), known_answers.edges(family, int(n))


def hyperbolic_triangle_tiling(layers: int) -> tuple[int, list[tuple[int, int]]]:
    from graph_scale_dynamics.measurements import hyperbolic_graphs
    return hyperbolic_graphs.hyperbolic_triangles(int(layers), TRIANGLES_AT_A_NODE)


def hyperbolic_triangle_tiling_nodes(layers: int) -> int:
    before, fibonacci = 1, 1
    for _ in range(2 * int(layers) - 1):
        before, fibonacci = fibonacci, before + fibonacci
    return 1 + TRIANGLES_AT_A_NODE * (fibonacci - 1)


def hyperbolic_geometric_graph(n: int, seed: int = 0) -> tuple[int, list[tuple[int, int]]]:
    from graph_scale_dynamics.measurements import hyperbolic_graphs
    return hyperbolic_graphs.hyperbolic_geometric_points_joined(
        int(n), HYPERBOLIC_MEAN_DEGREE, HYPERBOLIC_JOINED_WITHIN, int(seed))


CALIBRATION_FAMILIES = CALIBRATION_FAMILIES + (
    {
        "name": "periodic_cubic_quotient",
        "expectation": "MEASURE",
        "theory": {"d_s": 3.0, "d_B": 3.0, "d_w": 2.0, "d_V": 3.0},
        "build": lambda n: lattice_start("periodic_cubic_quotient", n),
        "size": lambda n: int(n),
        "ladder": SIZES_A_LAW_RUNS,
        "why": "the cubic start as the fleet builds it at every size a law runs, a torus folded where the size is "
               "no cube",
    },
    {
        "name": "periodic_body_centred_cubic_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 3.0, "d_B": 3.0, "d_w": 2.0, "d_V": 3.0},
        "build": lambda n: lattice_start("periodic_body_centred_cubic_lattice", n),
        "size": lambda n: int(n),
        "ladder": SIZES_A_LAW_RUNS,
        "why": "the body-centred cubic start, eight neighbours: three dimensions on another lattice",
    },
    {
        "name": "periodic_face_centred_cubic_lattice",
        "expectation": "MEASURE",
        "theory": {"d_s": 3.0, "d_B": 3.0, "d_w": 2.0, "d_V": 3.0},
        "build": lambda n: lattice_start("periodic_face_centred_cubic_lattice", n),
        "size": lambda n: int(n),
        "ladder": SIZES_A_LAW_RUNS,
        "why": "the face-centred cubic start, twelve neighbours and triangles: the densest of the three",
    },
    {
        "name": "periodic_tesseract_quotient",
        "expectation": "MEASURE",
        "theory": {"d_s": 4.0, "d_B": 4.0, "d_w": 2.0, "d_V": 4.0},
        "build": lambda n: lattice_start("periodic_tesseract_quotient", n),
        "size": lambda n: int(n),
        "ladder": SIZES_A_LAW_RUNS,
        "why": "the 4D start as the fleet builds it at every size a law runs",
    },
    {
        "name": "hyperbolic_triangle_tiling",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda layers: hyperbolic_triangle_tiling(layers),
        "size": lambda layers: hyperbolic_triangle_tiling_nodes(layers),
        "ladder": (5, 6, 7, 8, 9, 10, 11),
        "why": "seven triangles at a node, grown outward by layers: a negatively curved surface, local structure "
               "everywhere and balls that grow exponentially, so no probe may read a dimension",
    },
    {
        "name": "hyperbolic_geometric_graph",
        "expectation": "REFUSE",
        "theory": {},
        "build": lambda size: hyperbolic_geometric_graph(size, 1),
        "build_seeded": lambda size, seed: hyperbolic_geometric_graph(size, seed),
        "graph_varies_per_seed": True,
        "size": lambda size: int(size),
        "ladder": (1024, 4096, 16384, 65536, 262144),
        "why": "points of a hyperbolic disc joined within a fixed distance, mean degree 12: a drawn hyperbolic "
               "space, which under 4,096 nodes no measure of its balls parts from a geometry",
    },
)


for _family in CALIBRATION_FAMILIES:
    if _family.get("expectation") == "REFUSE":
        _family["refusal_gated_from"] = refusal_required_from(_family["name"])
del _family


KNOWN_FALSE_CONFIDENCE: dict[str, dict] = {
    "balanced_binary_tree": {
        "channel": "d_s", "from_n": 255, "reads": "1.02 to 1.31",
        "expected": "refusal: ball volume grows exponentially in r",
    },
    "random_3_regular": {
        "channel": "d_s", "from_n": 1024, "reads": "2.00 to 2.09",
        "expected": "refusal: an expander has no finite dimension",
    },
    "erdos_renyi_sparse": {
        "channel": "d_s", "from_n": 1024, "reads": "about 1.80 at giant <d> 2.77",
        "expected": "refusal: a random graph has no finite dimension",
    },
    "erdos_renyi_mid": {
        "channel": "d_s", "from_n": 1024, "reads": "about 2.16 at giant <d> 3.18",
        "expected": "refusal: a random graph has no finite dimension",
    },
    "erdos_renyi_degree_2": {
        "channel": "d_s", "from_n": 1024, "reads": "about 1.50 at giant <d> 2.40",
        "expected": "refusal: a random graph has no finite dimension",
    },
    "erdos_renyi_degree_6": {
        "channel": "d_V", "from_n": 2048, "to_n": 8192, "closed_in": "analysis-4.0.0",
        "reads": "4.62 to 5.12, then refuses from 16,384",
        "expected": "refusal: exponential ball growth",
        "note": "529: erdos_renyi_dense's short-window case, one size class further up; it closes "
                "with N, and d_s refuses on every seed at every rung",
    },
    "erdos_renyi_dense": {
        "channel": "d_V", "from_n": 512, "to_n": 2048, "closed_in": "analysis-4.0.0",
        "reads": "about 3.77, then refuses from 4096",
        "expected": "refusal: exponential ball growth",
        "note": "unlike the d_s entries this one closes with N. The volume window "
                "spans less than an octave below 4096, so the power-law and "
                "exponential designs are nearly the same design and cover noise "
                "decides; above it the channel resolves and refuses correctly. "
                "627: not a lack of power. The window had four radii and the AICc was "
                "-inf for both designs, so no comparison ran (MEA-3); under "
                "analysis-4.0.0 it runs and refuses from 1,024",
    },
}

SPECTRAL_FALSE_CONFIDENCE_BAND = (2.0, 8.0)
SPECTRAL_BRANCHING_LINE_BAND = (2.0, 3.5)


CRT_MEASURED_BIAS = {
    "d_s": {"reading": 1.272, "theory": CRT_DS, "bias": -0.061, "shrinks_with_n": True},
    "d_B": {"reading": 1.592, "theory": CRT_DF, "bias": -0.408, "shrinks_with_n": False},
    "d_w": {"reading": 2.470, "theory": CRT_DW, "bias": -0.530, "shrinks_with_n": False},
    "d_V": {"reading": 1.909, "theory": CRT_DF, "bias": -0.091, "shrinks_with_n": True}
}


def control_family_reaches(family: str, n: int) -> bool:
    from graph_scale_dynamics.measurements import known_answers, random_starts, shaped_starts
    if shaped_starts.parse(str(family)) is not None:
        return shaped_starts.reaches(str(family), int(n))
    if random_starts.parse(str(family)) is not None:
        return random_starts.reaches(str(family), int(n))
    for spec in CALIBRATION_FAMILIES:
        if str(spec.get("name")) != str(family):
            continue
        size = spec.get("size")
        for parameter in (spec.get("ladder") or ()) if callable(size) else ():
            try:
                if int(size(parameter)) == int(n):
                    return True
            except Exception:
                continue
        break
    return known_answers.reaches(str(family), int(n))


def control_family_edges(family: str, n: int, seed: int | None = None) -> list[tuple[int, int]] | None:
    from graph_scale_dynamics.measurements import known_answers, random_starts, shaped_starts
    shaped = shaped_starts.parse(str(family))
    if shaped is not None:
        if not shaped_starts.reaches(str(family), int(n)):
            return None
        return shaped_starts.build(int(n), shaped[0], shaped[1], int(seed or 0))
    degree = random_starts.parse(str(family))
    if degree is not None:
        return random_starts.build(int(n), degree, int(seed or 0)) if random_starts.reaches(family, n) else None
    for spec in CALIBRATION_FAMILIES:
        if str(spec.get("name")) != str(family):
            continue
        size, build = spec.get("size"), spec.get("build")
        if not callable(size) or not callable(build):
            break
        for parameter in spec.get("ladder") or ():
            try:
                if int(size(parameter)) != int(n):
                    continue
                built = build(parameter)
            except Exception:
                continue
            nodes, edges = built if isinstance(built, tuple) else (None, built)
            if nodes is not None and int(nodes) != int(n):
                continue
            return [(int(u), int(v)) for u, v in edges]
        break
    return known_answers.edges(str(family), int(n))
