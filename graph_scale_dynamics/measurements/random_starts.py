from __future__ import annotations

import re

PREFIX = "random_mean_degree_"
DRAWN = "random_at_drawn_degree"
_NAME = re.compile(r"^random_mean_degree_(\d+(?:\.\d+)?)$")
DECIMALS = 6


def family(degree: float) -> str:
    if not float(degree) > 0:
        raise ValueError("a random start's mean degree is above zero")
    text = f"{float(degree):.{DECIMALS}f}".rstrip("0").rstrip(".")
    return f"{PREFIX}{text}"


def parse(name: str) -> float | None:
    match = _NAME.match(str(name))
    if not match:
        return None
    degree = float(match.group(1))
    return degree if degree > 0 else None


def drawn_degree(candidate_id: str, start: str, cap: float) -> float:
    from graph_scale_dynamics.domain.randomness import derive_seed
    if not float(cap) > 0:
        raise ValueError("a drawn degree needs a mean-degree cap above zero")
    share = derive_seed("twin-start-random-degree", str(candidate_id), str(start)) / float(2 ** 256)
    return max(10.0 ** -DECIMALS, round(float(cap) * (1.0 - share), DECIMALS))


def drawn_family(candidate_id: str, start: str, cap: float) -> str:
    return family(drawn_degree(candidate_id, start, cap))


def links(n: int, degree: float) -> int:
    return int(round(float(degree) * int(n) / 2.0))


def reaches(name: str, n: int) -> bool:
    degree = parse(name)
    return degree is not None and int(n) >= 2 and links(n, degree) <= int(n) * (int(n) - 1) // 2


def build(n: int, degree: float, seed: int) -> list[tuple[int, int]]:
    import numpy as np

    from graph_scale_dynamics.domain.randomness import derive_seed
    n, want = int(n), links(n, degree)
    if want > n * (n - 1) // 2:
        raise ValueError(f"a random start of mean degree {degree} has more links than {n} nodes have pairs")
    rng = np.random.default_rng(derive_seed("twin-start-random-graph", family(degree), n, int(seed)) % (2 ** 63))
    keys = np.empty(0, dtype=np.int64)
    while len(keys) < want:
        draws = 16 + int(1.1 * (want - len(keys)))
        u, v = rng.integers(0, n, size=draws), rng.integers(0, n, size=draws)
        apart = u != v
        low, high = np.minimum(u, v)[apart], np.maximum(u, v)[apart]
        keys = np.unique(np.concatenate([keys, low.astype(np.int64) * n + high]))
    if len(keys) > want:
        keys = np.sort(rng.choice(keys, size=want, replace=False))
    return list(zip((keys // n).tolist(), (keys % n).tolist(), strict=True))


def _random_wiring(n: int, edges, seed: int = 0) -> list[tuple[int, int]]:
    import numpy as np
    degree = np.zeros(int(n), dtype=np.int64)
    for u, v in edges:
        degree[u] += 1
        degree[v] += 1
    stubs = np.repeat(np.arange(int(n)), degree)
    np.random.default_rng(seed).shuffle(stubs)
    pairs = stubs[: len(stubs) // 2 * 2].reshape(-1, 2)
    pairs = np.sort(pairs[pairs[:, 0] != pairs[:, 1]], axis=1)
    return [tuple(map(int, p)) for p in np.unique(pairs, axis=0)]
