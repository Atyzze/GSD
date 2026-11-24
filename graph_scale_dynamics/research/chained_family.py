from __future__ import annotations

import random

import numpy as np

CHAINED_CONTRACT = "gsd-chained-cubic-1"


def random_cubic(m: int, rng: random.Random) -> list[tuple[int, int]]:
    if m % 2 or m < 4:
        raise ValueError("a cubic graph needs an even number of nodes, at least 4")
    while True:
        stubs = [v for v in range(m) for _ in range(3)]
        rng.shuffle(stubs)
        edges: set = set()
        for a, b in zip(stubs[::2], stubs[1::2], strict=True):
            edge = (min(a, b), max(a, b))
            if a == b or edge in edges:
                break
            edges.add(edge)
        else:
            return sorted(edges)


def chained_cubic(n_target: int, ell: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    m = max(4, int(round(n_target / (1 + 1.5 * (ell - 1)))))
    m += m % 2
    rng = random.Random(f"chained-cubic:{n_target}:{ell}:{seed}")
    skeleton = random_cubic(m, rng)
    edges, following = [], m
    for a, b in skeleton:
        previous = a
        for _ in range(int(ell) - 1):
            edges.append((previous, following))
            previous, following = following, following + 1
        edges.append((previous, b))
    return following, edges


def read_graph(n: int, edges, *, rung: int | None = None, seed: int = 0) -> dict:
    from graph_scale_dynamics.measurements import estimators as E
    from graph_scale_dynamics.measurements.structure_census import GAP_MAX_N, census
    rung = int(n) if rung is None else int(rung)
    record = census(n, edges, gap_max_n=(max(int(n), GAP_MAX_N) if rung <= GAP_MAX_N else None))
    giant = record["largest_component"]
    adj = E.build_adjacency(n, edges)
    component = E.largest_component(n, adj)
    rng = np.random.default_rng(seed)
    volume = E.volume_growth(adj, component, rng)
    fit = E.fit_ds(E.return_probability(adj, component, rng), len(component))
    gap = (giant.get("spectral_gap") or {}).get("value")
    return {"n": rung, "nodes": int(n), "giant_fraction": round(int(giant["size"]) / max(1, rung), 6),
            "gap": gap, "diameter": int((giant.get("diameter") or {}).get("lower_bound") or 0),
            "half_volume_radius": volume.get("half_volume_radius"),
            "local_d_s": (float(fit["d_s"]) if fit.get("valid") else None),
            "local_d_s_refusal": (None if fit.get("valid") else fit.get("refusal"))}


def as_rungs(rows: list[dict]) -> list[dict]:
    return [{"n": int(r["n"]), "spectral_gap": {"mean": r.get("gap")}, "diameter": {"mean": r.get("diameter")},
             "measured_giant_fraction": {"mean": r.get("giant_fraction")},
             "half_volume_radius": {"mean": r.get("half_volume_radius")},
             "local_d_s": {"mean": r.get("local_d_s")}} for r in sorted(rows, key=lambda r: int(r["n"]))]


def judge(rows: list[dict]) -> dict:
    from graph_scale_dynamics.research.structure_reading import three_readings, verdict
    rungs = as_rungs(rows)
    rule = verdict(rungs)
    readings = three_readings(rungs, rule)
    return {"rule_finite": rule.get("finite_dimension"), "rule_why": rule.get("why"),
            "implied_spectral_dimension": rule.get("implied_spectral_dimension"),
            "implied_fractal_dimension": rule.get("implied_fractal_dimension"),
            "three_readings": readings}
