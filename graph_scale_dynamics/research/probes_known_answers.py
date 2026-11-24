from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

EVERY_PROBE = ("d_s", "d_V", "d_B", "d_w")


def build(structure: dict, size, seed: int):
    from graph_scale_dynamics.measurements import calibration, known_answers
    from graph_scale_dynamics.research import planted_geometries as planted
    kind = structure["build"]
    if kind == "start":
        n = int(size)
        return (n, known_answers.edges(structure["family"], n)) if known_answers.reaches(structure["family"], n) else None
    if kind == "ring":
        return calibration.periodic_ring(int(size))
    if kind == "sierpinski_gasket":
        return calibration.sierpinski_gasket(int(size))
    if kind == "sierpinski_carpet":
        return calibration.sierpinski_carpet(int(size))
    if kind == "random_tree":
        return calibration.uniform_random_tree(int(size), int(seed))
    if kind == "percolation":
        return planted.critical_percolation_cluster(int(size), int(seed))
    if kind == "random_geometric":
        return planted.random_geometric(int(size), int(structure["dimension"]), float(structure["mean_degree"]), int(seed))
    if kind == "random_regular":
        return planted.random_regular(int(size), int(structure["degree"]), int(seed))
    if kind == "erdos_renyi":
        return planted._largest(*planted.erdos_renyi(int(size), float(structure["mean_degree"]), int(seed)))
    if kind == "preferential_attachment":
        return planted.preferential_attachment(int(size), int(structure["links"]), int(seed))
    from graph_scale_dynamics.research import known_structures as known
    if kind == "kagome":
        return known.kagome_torus(int(size))
    if kind == "diamond":
        return known.diamond_torus(int(size))
    if kind == "hypercubic":
        return known.hypercubic_torus(int(size), int(structure["dimension"]))
    if kind == "sierpinski_tetrahedron":
        return known.sierpinski_tetrahedron(int(size))
    if kind == "vicsek":
        return known.vicsek_fractal(int(size))
    if kind == "random_recursive_tree":
        return known.random_recursive_tree(int(size), int(seed))
    if kind == "ring_with_shortcuts":
        return known.ring_with_shortcuts(int(size), float(structure["shortcuts_a_node"]), int(seed))
    if kind == "box":
        return known.box_torus([int(size) if side == "n" else int(side) for side in structure["sides"]])
    if kind == "king":
        return known.king_torus(int(size))
    if kind == "open_square":
        return known.open_square(int(size))
    if kind == "subdivided_square":
        return known.subdivided(*known.box_torus((int(size), int(size))), int(structure["pieces"]))
    if kind == "t_fractal":
        return known.t_fractal(int(size))
    if kind == "hyperbolic_triangles":
        return known.hyperbolic_triangles(int(size))
    if kind == "hyperbolic_squares":
        return known.hyperbolic_squares(int(size))
    if kind == "hyperbolic_random":
        return known.hyperbolic_random_graph(int(size), float(structure["mean_degree"]), float(structure["alpha"]),
                                             int(seed))
    if kind == "hyperbolic_geometric":
        return known.hyperbolic_geometric_graph(int(size), float(structure["mean_degree"]),
                                                float(structure["within"]), int(seed))
    if kind == "diluted_square":
        from graph_scale_dynamics.research import look_alikes
        return look_alikes.diluted_square(int(size), float(structure["kept"]), int(seed))
    if kind == "square_with_local_chords":
        from graph_scale_dynamics.research import look_alikes
        return look_alikes.square_with_local_chords(int(size), float(structure["chords_a_node"]),
                                                    int(structure["within"]), int(seed))
    if kind == "torus_with_shortcuts":
        from graph_scale_dynamics.research import look_alikes
        return look_alikes.with_shortcuts(look_alikes.torus(int(size), int(structure["dimension"])),
                                          float(structure["shortcuts_a_node"]), int(seed))
    if kind == "subdivided_regular":
        return planted.subdivided_regular(int(size), int(structure["path_length"]), int(seed))
    if kind == "subdivided_random_tree":
        return known.subdivided(*calibration.uniform_random_tree(int(size), int(seed)), int(structure["pieces"]))
    if kind == "cycle_soup":
        return known.cycle_soup(int(size), int(structure["largest"]), int(structure["small"]))
    if kind == "table_family":
        family = next(f for f in calibration.CALIBRATION_FAMILIES if f["name"] == structure["family"])
        return family["build_seeded"](size, int(seed)) if family.get("build_seeded") else family["build"](size)
    raise ValueError(f"unknown structure {kind!r}")


def read_cell(task: tuple) -> dict:
    from graph_scale_dynamics.scaleflow.one_shot import chain_probes
    structure, size, seed = task
    row = {"structure": structure["name"], "size": size, "seed": int(seed)}
    built = build(structure, size, seed)
    if built is None or built[1] is None:
        return {**row, "built": False}
    n, edges = built
    found = chain_probes(int(n), edges, seed=int(seed), name=structure["name"])
    probes = {}
    for probe in EVERY_PROBE:
        block = found.get(probe) or {}
        error = block.get("measured_se", block.get("se"))
        probes[probe] = {"value": float(block["value"]) if block.get("valid") else None,
                         "se": float(error) if block.get("valid") and error is not None else None,
                         "refusal": None if block.get("valid") else block.get("refusal")}
    reach = found.get("half_volume_radius")
    return {**row, "built": True, "n": int(n), "component": found.get("component"), "probes": probes,
            "reach": float(reach) if isinstance(reach, (int, float)) else None}


def measure(criterion: dict, workers: int = 1, *, sets: tuple[str, ...] = ("structures",)) -> list[dict]:
    tasks = [(structure, size, seed) for key in sets for structure in criterion.get(key) or []
             for size in structure["sizes"] for seed in structure.get("seeds") or criterion["seeds"]]
    if int(workers) <= 1:
        return [read_cell(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=int(workers)) as pool:
        return list(pool.map(read_cell, tasks))
