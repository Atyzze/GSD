from __future__ import annotations


def tuple_state(value):
    if isinstance(value, list):
        return tuple(tuple_state(item) for item in value)
    if isinstance(value, tuple):
        return tuple(tuple_state(item) for item in value)
    return value


def structural_summary(state, n: int) -> dict:
    cached = getattr(state, "structural_summary_cache", None)
    if cached is not None:
        return dict(cached)
    seen = set()
    component_sizes = []
    components = []
    for start in range(n):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp = []
        while stack:
            node = stack.pop()
            comp.append(node)
            for other in state.adj[node]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        component_sizes.append(len(comp))
        components.append(comp)
    largest = max(components, key=len) if components else []
    largest_set = set(largest)
    largest_edges = sum(sum(1 for other in state.adj[v] if other in largest_set)
                        for v in largest_set) // 2
    cycle_rank = max(0, largest_edges - len(largest_set) + (1 if largest_set else 0))
    degree = {v: sum(1 for other in state.adj[v] if other in largest_set) for v in largest_set}
    queue = [v for v, value in degree.items() if value < 2]
    removed = set(queue)
    cursor = 0
    while cursor < len(queue):
        v = queue[cursor]
        cursor += 1
        for other in state.adj[v]:
            if other in degree and other not in removed:
                degree[other] -= 1
                if degree[other] < 2:
                    removed.add(other)
                    queue.append(other)
    return {
        "connected_fraction": len(largest_set) / max(1, n),
        "component_count": len(component_sizes),
        "largest_component_cycle_rank_density": cycle_rank / max(1, len(largest_set)),
        "two_core_fraction": (len(largest_set) - len(removed)) / max(1, len(largest_set)),
    }


def late_stats(rows, n: int) -> dict:
    import statistics
    series = {"energy_per_node": [r["energy"] / n for r in rows],
              "mean_degree": [r["mean_degree"] for r in rows],
              "edge_count_per_node": [r["edges"] / n for r in rows]}
    return {key: {"mean": statistics.fmean(values),
                  "std": statistics.pstdev(values),
                  "values": values} for key, values in series.items()}


def trajectory_diagnostics(rows, given_rows, n: int) -> dict:
    late_start = max(0, int(len(rows) * 0.70))
    late = rows[late_start:] or rows

    def slope(key):
        usable = [(float(row["move"]), float(row[key])) for row in late
                  if isinstance(row.get(key), (int, float))]
        if len(usable) < 2:
            return 0.0
        x_mean = sum(x for x, _ in usable) / len(usable)
        y_mean = sum(y for _, y in usable) / len(usable)
        denominator = sum((x - x_mean) ** 2 for x, _ in usable)
        if denominator <= 0:
            return 0.0
        return sum((x - x_mean) * (y - y_mean) for x, y in usable) / denominator

    edge_slope_move = slope("edges")
    degree_slope_move = slope("mean_degree")
    energy_slope_move = slope("energy")
    move_span = max(1.0, float(late[-1]["move"] - late[0]["move"])) if late else 1.0
    mean_late_edges = sum(float(row["edges"]) for row in late) / max(1, len(late))
    relative_edge_drift = edge_slope_move * move_span / max(1.0, abs(mean_late_edges))

    def first_crossing(key, threshold):
        for row in rows:
            if float(row.get(key, 0.0)) >= threshold:
                return int(row["move"])
        return None

    given_late = given_rows[-max(3, len(given_rows) // 3):] if given_rows else []
    empty_degree = sum(float(row["mean_degree"]) for row in late) / max(1, len(late))
    given_degree = sum(float(row["mean_degree"]) for row in given_late) / max(1, len(given_late))
    degree_gap = abs(empty_degree - given_degree)
    return {
        "late_fraction": 0.30,
        "late_edge_slope_per_move": edge_slope_move,
        "late_edge_slope_per_sweep": edge_slope_move * n,
        "late_mean_degree_slope_per_sweep": degree_slope_move * n,
        "late_energy_slope_per_sweep": energy_slope_move * n,
        "late_relative_edge_drift": relative_edge_drift,
        "declared_still_growing": bool(relative_edge_drift > 0.05 and edge_slope_move > 0),
        "declared_still_shrinking": bool(relative_edge_drift < -0.05 and edge_slope_move < 0),
        "time_to_first_edge_moves": first_crossing("edges", 1.0),
        "time_to_mean_degree_1_moves": first_crossing("mean_degree", 1.0),
        "time_to_mean_degree_2_moves": first_crossing("mean_degree", 2.0),
        "empty_given_late_mean_degree_gap": degree_gap,
        "empty_given_late_mean_degree_relative_gap": degree_gap / max(1.0, abs(given_degree)),
    }
