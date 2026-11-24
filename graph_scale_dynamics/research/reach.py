from __future__ import annotations

import math


def half_volume_radius(n: int, edges) -> float | None:
    import numpy as np

    from graph_scale_dynamics.measurements import estimators as M
    matrix = M.build_adjacency(int(n), [(int(u), int(v)) for u, v in edges])
    component = M.largest_component(int(n), matrix)
    if len(component) < 16:
        return None
    return M.volume_growth(matrix, component, np.random.default_rng(0)).get("half_volume_radius")


def kept(radius, random_radius, start_radius) -> float | None:
    if not radius or not random_radius or not start_radius or start_radius <= random_radius:
        return None
    return math.log(radius / random_radius) / math.log(start_radius / random_radius)
