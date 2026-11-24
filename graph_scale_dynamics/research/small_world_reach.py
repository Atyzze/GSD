from __future__ import annotations

import numpy as np

from graph_scale_dynamics.observability import catalogue as K

CONTRACT = "gsd-small-world-reach-1"
SIZES = (1024, 4096, 16384)
DEGREES = (2.0, 2.5, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0)
SEEDS = (0, 1, 2)
WITHIN = 1.05


def reach_of(n: int, edges, seed: int) -> tuple[float | None, float]:
    from graph_scale_dynamics.measurements import estimators as E
    adj = E.build_adjacency(int(n), edges)
    component = E.largest_component(int(n), adj)
    found = E.volume_growth(adj, component, np.random.default_rng(int(seed)))
    return found.get("half_volume_radius"), len(component) / int(n)


def random_rows(sizes=SIZES, degrees=DEGREES, seeds=SEEDS) -> list[dict]:
    from graph_scale_dynamics.measurements import random_starts
    rows = []
    for n in sizes:
        for degree in degrees:
            for seed in seeds:
                edges = random_starts.build(int(n), float(degree), int(seed))
                reach, giant = reach_of(int(n), edges, int(seed))
                expected = K.random_reach(int(n), 2.0 * len(edges) / int(n))
                rows.append({"start": "random", "n": int(n), "degree": float(degree), "seed": int(seed),
                             "reach": None if reach is None else round(float(reach), 4), "giant": round(giant, 4),
                             "random_reach": None if expected is None else round(expected, 4),
                             "off": None if reach is None or expected is None else round(float(reach) - expected, 4)})
    return rows


def lattice_rows(sizes=SIZES) -> list[dict]:
    from graph_scale_dynamics.measurements import starts
    rows = []
    for start in starts.lattices_run():
        for n in sizes:
            edges = start.edges(int(n))
            if not edges:
                continue
            size = 1 + max(max(edge) for edge in edges)
            reach, _giant = reach_of(size, edges, 0)
            expected = K.random_reach(size, 2.0 * len(edges) / size)
            rows.append({"start": start.name, "n": size, "degree": round(2.0 * len(edges) / size, 4),
                         "reach": round(float(reach), 4), "random_reach": round(expected, 4),
                         "ratio": round(float(reach) / expected, 4)})
    return rows


def judge(random: list[dict], lattices: list[dict], within: float = WITHIN) -> dict:
    offs = [abs(row["off"]) for row in random if row["off"] is not None]
    ratios = [row["reach"] / row["random_reach"] for row in random if row["off"] is not None]
    at_most = float(K.rule()["small_world"]["reach_at_most"])
    return {"contract": CONTRACT, "within": within, "reach_at_most": at_most, "random_graphs": len(random),
            "read": len(offs), "widest_off": round(max(offs), 4) if offs else None,
            "largest_ratio": round(max(ratios), 4) if ratios else None,
            "random_within": bool(offs) and len(offs) == len(random) and max(offs) <= within,
            "random_inside_the_band": bool(ratios) and len(ratios) == len(random) and max(ratios) <= at_most,
            "lattices_inside_the_band": [[row["start"], row["n"], row["ratio"]] for row in lattices
                                         if row["ratio"] <= at_most],
            "random": random, "lattices": lattices}
