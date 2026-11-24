from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, shortest_path

from graph_scale_dynamics.measurements import calibration, known_answers as K
from graph_scale_dynamics.research import start_admission as A

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
CRITERION = json.loads((READINGS / "start_admission_criterion_2.json").read_text(encoding="utf-8"))
JUDGED = json.loads((READINGS / "start_admission_2_judged.json").read_text(encoding="utf-8"))
PAGE = ROOT / "docs" / "readings" / "start_admission_2_judged.md"
LADDER = [4 ** k for k in range(3, 11)]
NEW = {K.TRIANGULAR_TORUS: 6, K.BODY_CENTRED_CUBIC: 8, K.FACE_CENTRED_CUBIC: 12}
SHELLS = {K.TRIANGULAR_TORUS: [6, 12, 18], K.BODY_CENTRED_CUBIC: [8, 26, 56], K.FACE_CENTRED_CUBIC: [12, 42, 92],
          A.DIAMOND: [4, 12, 24]}


def _adjacency(n: int, edges) -> csr_matrix:
    u, v = np.asarray(edges, dtype=np.int64).T
    return csr_matrix((np.ones(2 * len(edges)), (np.concatenate([u, v]), np.concatenate([v, u]))), shape=(n, n))


def _shells(n: int, edges, node: int = 0) -> list[int]:
    distance = shortest_path(_adjacency(n, edges), unweighted=True, indices=[node])[0]
    counted = collections.Counter(distance.astype(int).tolist())
    return [counted[r] for r in range(1, 4)]


@pytest.mark.parametrize("family,degree", sorted(NEW.items()))
def test_each_new_lattice_is_built_at_the_ladder_s_sizes_with_its_neighbours(family, degree):
    for n in LADDER:
        assert K.reaches(family, n) and calibration.control_family_reaches(family, n), (family, n)
    for n in LADDER[:6]:
        edges = K.edges(family, n)
        assert A.degree_of(n, edges) == degree and len(edges) == n * degree // 2, (family, n)
        assert len(set(edges)) == len(edges) and all(0 <= u < v < n for u, v in edges), (family, n)
        assert connected_components(_adjacency(n, edges))[0] == 1, (family, n)
        assert calibration.control_family_edges(family, n) == edges, "a campaign's start is this graph"
    for node in (0, 1, 4095):
        assert _shells(4096, K.edges(family, 4096), node) == SHELLS[family], "every node sees the lattice's own shells"
    assert not K.reaches(family, 1001) and K.edges(family, 1001) is None


def test_the_two_cubic_starts_are_folded_by_a_lattice_with_the_cube_s_symmetry_at_every_size():
    folds = {K.BODY_CENTRED: [(4, 4), (8, 2), (16, 1), (16, 4), (32, 2), (64, 1), (64, 4), (128, 2)],
             K.FACE_CENTRED: [(4, 2), (8, 1), (8, 4), (16, 2), (32, 1), (32, 4), (64, 2), (128, 1)]}
    for lattice, expected in folds.items():
        assert [K.cubic_fold(lattice, n) for n in LADDER] == expected, lattice
        assert K.cubic_fold(lattice, 8) is None and K.cubic_fold(lattice, 1001) is None
    assert K.cubic_fold(K.BODY_CENTRED, 1000) == (10, 4) and K.cubic_fold(K.FACE_CENTRED, 1000) == (10, 2), (
        "a cube of nodes is reached too")


@pytest.mark.parametrize("lattice,family", [(K.BODY_CENTRED, K.BODY_CENTRED_CUBIC), (K.FACE_CENTRED, K.FACE_CENTRED_CUBIC)])
@pytest.mark.parametrize("n", [256, 1024, 4096])
def test_no_axis_of_a_cubic_start_is_longer_than_another(lattice, family, n):
    points, node_of = K.cubic_torus_points(lattice, n)
    edges = set(K.edges(family, n))
    for turned in (points[:, [1, 2, 0]], points[:, [1, 0, 2]], points * np.array([-1, 1, 1])):
        image = node_of(turned)
        assert sorted(image.tolist()) == list(range(n)), "the turn or the mirror maps the nodes onto themselves"
        moved = {(min(int(image[u]), int(image[v])), max(int(image[u]), int(image[v]))) for u, v in edges}
        assert moved == edges, "and every edge onto an edge: the torus has the cube's symmetry"


def test_the_triangular_start_is_the_calibration_s_triangular_lattice():
    for side in (3, 4, 8, 16, 32):
        assert K.edges(K.TRIANGULAR_TORUS, side * side) == calibration.periodic_triangular_lattice(side)[1]


def test_the_body_centred_lattice_has_no_triangle_and_the_face_centred_eight_a_node():
    for family, triangles in ((K.BODY_CENTRED_CUBIC, 0), (K.FACE_CENTRED_CUBIC, 8), (K.TRIANGULAR_TORUS, 2)):
        adjacency = _adjacency(1024, K.edges(family, 1024))
        assert int((adjacency @ adjacency).multiply(adjacency).sum()) == 6 * triangles * 1024, family


def test_the_diamond_lattice_is_built_to_be_read_and_is_no_start():
    for n in (1024, 4096):
        edges = A.periodic_diamond(n)
        assert A.degree_of(n, edges) == 4 and len(edges) == 2 * n
        assert connected_components(_adjacency(n, edges))[0] == 1
    assert _shells(4096, A.periodic_diamond(4096)) == SHELLS[A.DIAMOND]
    assert A.periodic_diamond(1000) is None and A.edges_of(A.DIAMOND, 1024) == A.periodic_diamond(1024)
    assert not K.reaches(A.DIAMOND, 1024), "it is built by the reader, not offered to a campaign"
    with pytest.raises(ValueError, match="not a regular graph"):
        A.degree_of(4, [(0, 1), (1, 2)])


def test_a_term_tells_by_an_amount_a_node_that_does_not_shrink():
    criterion = {"sizes": [1024, 4096, 16384], "tells_at_least": 0.05, "keeps_at_least": 0.5}
    assert A.tells({1024: 1.0, 4096: 1.0, 16384: 1.0}, criterion)
    assert A.tells({1024: -2.0, 4096: -1.5, 16384: -1.1}, criterion), "a difference of either sign"
    assert not A.tells({1024: 0.8, 4096: 0.2, 16384: 0.06}, criterion), "a fixed amount in all shrinks a node"
    assert not A.tells({1024: 0.04, 4096: 0.04, 16384: 0.04}, criterion), "too little a node"
    assert not A.tells({1024: 1.0, 4096: 1.0}, criterion), "read at every size or not told"
    assert A.law_of("degree_anchor", 6)["terms"] == [{"op": "degree_anchor", "params": {"k": 6},
                                                      "coeff": {"c0": 1.0, "scale": "one"}}]
    assert A.law_of("square_count", 6)["terms"][0]["params"] == {}


def test_a_lattice_is_admitted_by_one_term_under_the_cap_and_built():
    criterion = {"sizes": [64, 256], "seeds": [0], "tells_at_least": 0.05, "keeps_at_least": 0.5, "mean_degree_cap": 16,
                 "lattices": [{"name": name, "family": name, "dimension": 2, "admitted": admitted, "told_by": told}
                              for name, admitted, told in (("told", True, ["square_count"]), ("untold", False, []),
                                                           ("dense", True, ["square_count"]), ("unbuilt", True, ["x"]))]}

    def row(name, n, op, difference, degree=4):
        return {"name": name, "n": n, "built": True, "degree": degree, "op": op, "difference": difference}
    rows = [row("told", n, "square_count", 1.0) for n in (64, 256)] + [row("told", n, "edge_count", 0.0) for n in (64, 256)]
    rows += [row("untold", 64, "square_count", 0.5), row("untold", 256, "square_count", 0.01)]
    rows += [row("dense", n, "square_count", 1.0, degree=16) for n in (64, 256)]
    rows += [{"name": "unbuilt", "n": 64, "built": False}, row("unbuilt", 256, "x", 1.0)]
    judged = A.judge(criterion, rows)
    by_name = {entry["name"]: entry for entry in judged["lattices"]}
    assert by_name["told"]["admitted"] and by_name["told"]["told_by"] == ["square_count"]
    assert not by_name["untold"]["admitted"] and by_name["untold"]["told_by"] == []
    assert not by_name["dense"]["admitted"] and not by_name["dense"]["under_the_cap"], "a start at the cap is no start"
    assert not by_name["unbuilt"]["admitted"] and not by_name["unbuilt"]["built_at_every_size"]
    assert judged["admitted"] == ["told"] and not judged["passes"], "two were expected and are not admitted"
    assert "It does not pass" in A.render(judged)


def test_the_criterion_was_committed_before_the_reading_and_the_page_is_the_reading():
    assert CRITERION["committed_utc"] < JUDGED["measured_utc"].replace("+00:00", "Z")
    assert JUDGED["contract"] == A.CONTRACT and JUDGED["criterion"] == CRITERION["contract"] and JUDGED["passes"]
    assert JUDGED["admitted"] == ["square", "triangular", "cubic", "body-centred cubic", "face-centred cubic", "4D"]
    assert JUDGED["not_admitted"] == ["honeycomb", "diamond"]
    assert JUDGED["told_otherwise_than_expected"] == ["triangular"], "every chord of its four-cycles: no induced square"
    assert A.judge(CRITERION, JUDGED["rows"])["lattices"] == JUDGED["lattices"], "the judgement follows from the rows"
    assert A.render(JUDGED) == PAGE.read_text(encoding="utf-8")


def test_a_cell_of_the_reading_is_what_measuring_gives():
    from tests.support.engines import require_rust_engine
    require_rust_engine()
    sys.path.insert(0, str(ROOT / "tools"))
    import start_admission as tool
    small = dict(CRITERION, sizes=[1024], lattices=[entry for entry in CRITERION["lattices"]
                                                     if entry["name"] in ("honeycomb", "square")])
    rows = A.measure(small, tool.rust_energy, operators=["ollivier_curvature", "square_count", "edge_count"])
    committed = {(r["name"], r["n"], r["op"]): r for r in JUDGED["rows"] if r.get("built")}
    assert len(rows) == 6
    for row in rows:
        kept = committed[(row["name"], row["n"], row["op"])]
        assert row["lattice"] == kept["lattice"] and row["random"] == kept["random"], (row["name"], row["op"])
    edge = next(r for r in rows if r["name"] == "square" and r["op"] == "edge_count")
    assert edge["lattice"] == 2.0 and edge["difference"] == 0.0, "a degree-only term reads a regular graph by its degree"
    assert next(r for r in rows if r["name"] == "square" and r["op"] == "square_count")["lattice"] == 1.0
