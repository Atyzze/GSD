from __future__ import annotations

import math

import numpy as np
import pytest

from graph_scale_dynamics.measurements import structure_census as SC


def ring(n):
    return [(i, (i + 1) % n) for i in range(n)]


def torus(k):
    edges = set()
    for x in range(k):
        for y in range(k):
            v = x * k + y
            for w in (((x + 1) % k) * k + y, x * k + (y + 1) % k):
                edges.add((min(v, w), max(v, w)))
    return sorted(edges)


def cliques(count, size):
    return [(b * size + i, b * size + j) for b in range(count) for i in range(size) for j in range(i + 1, size)]


def path(n):
    return [(i, i + 1) for i in range(n - 1)]


def test_a_ring():
    c = SC.census(200, ring(200))
    giant = c["largest_component"]
    assert giant["diameter"]["lower_bound"] == 100 and giant["cycle_rank"] == 1
    assert math.isclose(giant["spectral_gap"]["value"], 1 - math.cos(2 * math.pi / 200), rel_tol=1e-6)
    assert c["cliques"]["triangles"] == 0 and c["squares"] == 0 and c["k_core"]["degeneracy"] == 2
    assert c["degree_histogram"] == {"2": 200}


def test_a_long_ring_takes_the_factorised_solve_and_is_still_exact():
    c = SC.census(20000, ring(20000))
    gap = c["largest_component"]["spectral_gap"]
    assert gap["method"] == "shift_invert"
    assert math.isclose(gap["value"], 1 - math.cos(2 * math.pi / 20000), rel_tol=1e-4)


def test_a_torus():
    c = SC.census(400, torus(20))
    assert c["largest_component"]["diameter"]["lower_bound"] == 20
    assert math.isclose(c["largest_component"]["spectral_gap"]["value"], 0.5 * (1 - math.cos(2 * math.pi / 20)),
                        rel_tol=1e-6)
    assert c["squares"] == 400 and c["cliques"]["triangles"] == 0


def test_disjoint_cliques():
    c = SC.census(200, cliques(40, 5))
    assert c["components"] == {"count": 40, "size_histogram": {"5": 40}}
    assert {k: c["cliques"][k] for k in ("triangles", "k4", "k5", "largest_clique")} == {
        "triangles": 400, "k4": 200, "k5": 40, "largest_clique": 5}
    assert c["cliques"]["largest_clique_exact"] and c["cliques"]["k5_exact"]
    assert c["k_core"]["degeneracy"] == 4 and c["squares"] == 40 * 15
    assert math.isclose(c["largest_component"]["spectral_gap"]["value"], 1.25), "K5: every other eigenvalue n/(n-1)"


def test_a_path_is_a_tree_and_its_diameter_is_exact():
    c = SC.census(300, path(300))
    diameter = c["largest_component"]["diameter"]
    assert diameter["lower_bound"] == 299 and diameter["exact"]
    assert c["largest_component"]["cycle_rank"] == 0 and c["k_core"]["degeneracy"] == 1


def test_an_empty_graph_and_isolated_nodes():
    c = SC.census(10, [])
    assert c["components"]["count"] == 10 and c["largest_component"]["size"] == 1
    assert c["largest_component"]["spectral_gap"]["value"] is None and c["assortativity"] is None


def test_each_costly_part_stops_at_its_declared_size_and_says_so(monkeypatch):
    monkeypatch.setattr(SC, "CLIQUE_MAX_N", 50)
    monkeypatch.setattr(SC, "SQUARE_MAX_N", 50)
    monkeypatch.setattr(SC, "GAP_MAX_N", 50)
    c = SC.census(100, ring(100))
    assert c["cliques"]["triangles"] is None and "N=50" in c["cliques"]["reason"]
    assert c["squares"] is None and "N=50" in c["squares_reason"]
    assert c["largest_component"]["spectral_gap"]["value"] is None
    assert c["largest_component"]["diameter"]["lower_bound"] == 50, "the diameter runs at every N"


@pytest.mark.parametrize("flag,lower,upper,expected", [
    (True, 3, 6, True),
    (False, 40, None, False),
    (False, 5, None, None),
    (False, None, None, None),
])
def test_the_log_diameter_flag_has_three_states(flag, lower, upper, expected):
    metrics = {"log_diameter_flag": flag, "diameter_lower_bound": lower, "diameter_upper_bound": upper}
    giant = {"largest_component": {"size": 1024, "diameter": {"lower_bound": lower}}}
    state = SC.log_diameter_state(metrics, giant)
    assert state["flag"] is expected, state
    assert math.isclose(state["threshold"], 16.0)


def test_the_census_diameter_decides_where_the_capped_bfs_could_not():
    metrics = {"log_diameter_flag": False, "diameter_lower_bound": None, "diameter_upper_bound": None}
    census = SC.census(3000, ring(3000))
    assert SC.log_diameter_state(metrics, census)["flag"] is False


def test_a_graph_given_as_an_array_or_a_list_reads_the_same():
    edges = torus(10)
    assert SC.census(100, np.array(edges))["squares"] == SC.census(100, edges)["squares"]


def test_the_clique_census_stops_at_its_budget_on_a_near_complete_graph():
    import time
    from graph_scale_dynamics.measurements import structure_census as S
    cocktail = [(i, j) for i in range(64) for j in range(i + 1, 64) if j != i + 32]
    started = time.perf_counter()
    cliques = S.census(64, cocktail)["cliques"]
    assert time.perf_counter() - started < 20
    assert cliques["largest_clique_exact"] is False and 2 <= cliques["largest_clique"] <= 32
    assert cliques["work"]["search_calls"] <= S.LARGEST_CLIQUE_BUDGET + 1
    complete = [(i, j) for i in range(64) for j in range(i + 1, 64)]
    full = S.census(64, complete)["cliques"]
    assert full["largest_clique"] == 64 and full["largest_clique_exact"] is True
    assert full["k5"] == 7624512 and full["k5_exact"] is True


def test_the_gap_limit_is_the_callers_to_raise():
    from graph_scale_dynamics.measurements import structure_census as S
    ring = [(i, (i + 1) % 100) for i in range(100)]
    assert S.census(100, ring, gap_max_n=64)["largest_component"]["spectral_gap"]["value"] is None
    assert S.census(100, ring)["largest_component"]["spectral_gap"]["value"] > 0


def _expander(n, degree=6, seed=0):
    rng = np.random.default_rng(seed)
    stubs = np.repeat(np.arange(n), degree)
    rng.shuffle(stubs)
    return sorted({(int(min(a, b)), int(max(a, b))) for a, b in zip(stubs[0::2], stubs[1::2], strict=True) if a != b})


def _hung(n, edges, length, closed=False):
    out, prev = list(edges), 0
    for i in range(length):
        out.append((prev, n + i))
        prev = n + i
    if closed:
        out.append((prev, 0))
    return n + length, out


def test_a_tail_hung_on_a_torus_no_longer_sets_its_gap():
    n, edges = _hung(400, torus(20), 40)
    gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
    assert gap["on"] == "2-core" and gap["size"] == 400 and math.isclose(gap["core_fraction"], 400 / 440)
    assert math.isclose(gap["value"], 0.5 * (1 - math.cos(2 * math.pi / 20)), rel_tol=1e-6)


def test_a_tail_hung_on_an_expander_does_not_send_it_to_the_factorisation():
    bulk = SC.census(1024, _expander(1024))["largest_component"]["spectral_gap"]
    n, edges = _hung(1024, _expander(1024), 60)
    gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
    assert gap["method"] == "lanczos_deflated" and gap["on"] == "2-core"
    assert math.isclose(gap["value"], bulk["value"], rel_tol=1e-6) and gap["value"] > 0.2


def test_a_long_cycle_hung_on_an_expander_is_not_factorised_either():
    n, edges = _hung(2048, _expander(2048), 100, closed=True)
    gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
    assert gap["diameter_lower_bound"] > SC.GAP_SHIFT_INVERT_MIN_DIAMETER_LOGS * math.log2(gap["size"])
    assert gap["half_volume_radius"] <= SC.GAP_SHIFT_INVERT_MIN_HALF_RADIUS_LOGS * math.log2(gap["size"])
    assert gap["method"] == "lanczos_deflated"


def test_a_tree_has_no_2_core_and_is_read_whole():
    gap = SC.census(300, path(300))["largest_component"]["spectral_gap"]
    assert gap["on"] == "component" and gap["size"] == 300 and gap["core_fraction"] == 0.0
    assert gap["method"] == "shift_invert" and gap["value"] is not None


def test_a_ring_and_a_torus_read_as_before_on_their_own_2_core():
    for n, edges, method in ((20000, ring(20000), "shift_invert"), (400, torus(20), "lanczos_deflated")):
        gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
        assert gap["on"] == "2-core" and gap["core_fraction"] == 1.0 and gap["method"] == method


def _hub(n, degree, mean=4.0, seed=0):
    rng = np.random.default_rng(seed)
    m = int(mean * n / 2) - degree
    a, b = rng.integers(1, n, size=m), rng.integers(1, n, size=m)
    pairs = {(int(min(x, y)), int(max(x, y))) for x, y in zip(a, b, strict=True) if x != y}
    return sorted(pairs | {(0, int(t)) for t in rng.choice(np.arange(1, n), size=degree, replace=False)})


def _squares_by_the_matrix(n, edges):
    adj = SC._adjacency(n, edges).astype(np.int64)
    degree = np.asarray(adj.sum(axis=1)).ravel()
    trace4 = int(np.sum((adj @ adj).data.astype(np.int64) ** 2))
    return (trace4 - 2 * (int(degree.sum()) // 2) - 4 * int(np.sum(degree * (degree - 1) // 2))) // 8


@pytest.mark.parametrize("n,edges", [(4000, _hub(4000, 3999)), (400, torus(20)), (2000, _expander(2000, 8)),
                                     (12, [(i, j) for i in range(12) for j in range(i + 1, 12)])])
def test_squares_are_counted_in_degree_order_as_the_matrix_counts_them(n, edges, monkeypatch):
    expected = _squares_by_the_matrix(n, edges)
    assert SC.census(n, edges)["squares"] == expected
    monkeypatch.setattr(SC, "SQUARE_CHUNK", 5)
    assert SC.census(n, edges)["squares"] == expected


def test_a_hub_of_every_node_costs_the_square_count_nothing():
    edges = _hub(65536, 65535)
    adj = SC._adjacency(65536, edges)
    degree = np.asarray(adj.sum(axis=1), dtype=np.int64).ravel()
    assert int(np.sum(degree ** 2)) > 4e9
    assert SC._squares(adj, degree, budget=5_000_000) is not None, "the walk is near the edges' count"


def test_a_square_count_past_its_budget_is_not_made_and_says_why(monkeypatch):
    monkeypatch.setattr(SC, "SQUARE_WORK_BUDGET", 10)
    c = SC.census(400, torus(20))
    assert c["squares"] is None and "work budget" in c["squares_reason"]


def test_a_part_that_fails_is_recorded_not_raised(monkeypatch):
    def boom(*_args, **_kwargs):
        raise MemoryError("synthetic")
    monkeypatch.setattr(SC, "_squares", boom)
    monkeypatch.setattr(SC, "_gap_on_the_core", boom)
    c = SC.census(400, torus(20))
    assert c["squares"] is None and c["squares_reason"] == "the square count failed: MemoryError"
    gap = c["largest_component"]["spectral_gap"]
    assert gap["value"] is None and gap["reason"] == "the gap failed: MemoryError"
    assert c["cliques"]["triangles"] == 0, "the other parts are read"


def test_a_tree_with_one_cycle_is_read_whole_not_on_its_three_node_core():
    for n in (4096, 16384):
        edges = path(n) + [(0, 2)]
        gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
        assert gap["on"] == "component" and gap["size"] == n and gap["core_fraction"] < 1e-3
        assert gap["value"] < 1e-5, "a path's gap, nearly shut"


def test_a_ring_with_a_tail_longer_than_itself_is_read_whole():
    n, edges = _hung(400, ring(400), 1000)
    gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
    assert gap["on"] == "component" and gap["size"] == 1400 and math.isclose(gap["core_fraction"], 400 / 1400)


def test_a_ring_with_a_short_tail_is_read_on_its_ring():
    n, edges = _hung(1000, ring(1000), 100)
    gap = SC.census(n, edges)["largest_component"]["spectral_gap"]
    assert gap["on"] == "2-core" and gap["size"] == 1000
    assert math.isclose(gap["value"], 1 - math.cos(2 * math.pi / 1000), rel_tol=1e-6)
