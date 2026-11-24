from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from graph_scale_dynamics.research import chained_family as C
from graph_scale_dynamics.research.structure_reading import LOCAL_D_S_WITHIN, three_readings

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
CRITERION = json.loads((READINGS / "chained_cubic_criterion.json").read_text(encoding="utf-8"))
CHECKS = READINGS / "chained_cubic_judged.json"


def test_a_chained_cubic_graph_is_a_cubic_skeleton_joined_by_chains():
    n, edges = C.chained_cubic(2000, 10, seed=1)
    degree = Counter()
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    skeleton = sum(1 for d in degree.values() if d == 3)
    assert set(degree.values()) == {2, 3} and len(degree) == n
    assert len(edges) == int(1.5 * skeleton) * 10, "every edge of the skeleton is a chain of ten"
    parent = list(range(n))

    def root(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for a, b in edges:
        parent[root(a)] = root(b)
    assert len({root(v) for v in range(n)}) == 1, "one connected graph"
    assert C.chained_cubic(2000, 10, seed=1) == (n, edges), "the same graph for the same seed"


def _rows(sizes, radius, local, gap, diameter):
    return [{"n": n, "measured_giant_fraction": 1.0, "half_volume_radius": radius(n), "local_d_s": local,
             "spectral_gap": {"mean": gap(n)}, "diameter": {"mean": diameter(n)}} for n in sizes]


def test_the_three_readings_agree_on_a_geometry_and_not_on_chains_the_extremes_read_as_one():
    sizes = (4096, 16384, 65536, 262144)
    square = _rows(sizes, lambda n: 0.4 * n ** 0.5, 2.02, lambda n: 4.0 / n, lambda n: n ** 0.5)
    agreed = three_readings(square, {"finite_dimension": True, "implied_spectral_dimension": 2.0})
    assert agreed["agree"] is True and agreed["bulk_finite"] and agreed["local_agrees_with_gap"]
    assert abs(agreed["bulk_implied_dimension"] - 2.0) < 0.01
    chains = _rows(sizes, lambda n: 60 * n ** 0.4, 1.01, lambda n: 1.0 / n, lambda n: n ** 0.4)
    refused = three_readings(chains, {"finite_dimension": True, "implied_spectral_dimension": 2.6})
    assert refused["agree"] is False and refused["local_agrees_with_gap"] is False
    assert refused["bulk_finite"] is True, "the bulk alone is fooled by chains too: the local d_s is the tell"
    expander = _rows(sizes, lambda n: 1.5 * __import__("math").log(n), None, lambda n: 0.2, lambda n: 20.0)
    unread = three_readings(expander, {"finite_dimension": False, "implied_spectral_dimension": None})
    assert unread["agree"] is False and unread["bulk_finite"] is False and unread["local_agrees_with_gap"] is None
    assert LOCAL_D_S_WITHIN == 0.4


def test_the_recorded_chained_family_is_refused_three_ways_on_every_seed():
    checks = json.loads(CHECKS.read_text(encoding="utf-8"))
    assert checks["contract"] == C.CHAINED_CONTRACT and checks["criterion"] == CRITERION["contract"]
    assert checks["computed_utc"] > CRITERION["committed_utc"] and checks["sizes"] == CRITERION["sizes"]
    chained = checks["chained"]
    assert len(chained) == len(CRITERION["chains"]) * len(CRITERION["seeds"])
    for key, reading in chained.items():
        assert reading["three_readings"]["agree"] is not True, key
        assert all(abs(row["local_d_s"] - 1.0) < 0.1 for row in reading["rows"] if row.get("local_d_s")), \
            "locally a chain"
    assert checks["summary"]["the_rule_reads_finite"] == sum(1 for r in chained.values() if r["rule_finite"])


def test_the_three_readings_do_not_refuse_the_known_geometries():
    checks = json.loads(CHECKS.read_text(encoding="utf-8"))
    finite = checks["finite_families"]
    unread = {"sierpinski_gasket", "sierpinski_carpet"}
    for name in ("periodic_ring", "periodic_square_lattice", "periodic_triangular_lattice",
                 "periodic_honeycomb_lattice", "periodic_cubic_lattice", "periodic_hypercubic_lattice_4d",
                 "uniform_random_tree"):
        readings = finite[name]["three_readings"]
        assert readings["agree"] is True, (name, readings)
        assert abs(readings["local_d_s"] - readings["gap_implied_d_s"]) <= LOCAL_D_S_WITHIN
    for name in unread:
        assert finite[name]["three_readings"]["agree"] is None, "two sizes under 65,536: no bulk exponent, no verdict"
        assert len(finite[name]["rows"]) == 2
    assert checks["summary"]["finite_families_the_three_readings_accept"] == len(finite) - len(unread)
