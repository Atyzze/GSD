from __future__ import annotations

from collections import Counter

import pytest

from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements.calibration import control_family_edges, control_family_reaches
from graph_scale_dynamics.research.control_verdict import judge_probes
from graph_scale_dynamics.scheduling.job_creation import resolve_given_start

LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304]


def test_the_cubic_quotient_reaches_every_rung_of_the_ladder_and_the_square_torus_too():
    assert [K._fold(n) for n in LADDER] == [(4, 1), (4, 4), (8, 2), (16, 1), (16, 4), (32, 2), (64, 1), (64, 4),
                                            (128, 2)]
    for n in LADDER:
        assert control_family_reaches(K.CUBIC_QUOTIENT, n), n
        assert control_family_reaches("periodic_square_lattice", n), n
    assert not control_family_reaches(K.CUBIC_QUOTIENT, 1000 * 3)


@pytest.mark.parametrize("n", [64, 256, 1024, 4096, 16384])
def test_every_node_has_the_six_neighbours_of_the_cubic_lattice(n):
    size, edges = K.periodic_cubic_quotient(n)
    assert size == n and len(edges) == 3 * n, "six neighbours a node, each edge once"
    degree = Counter()
    for a, b in edges:
        assert 0 <= a < b < n
        degree[a] += 1
        degree[b] += 1
    assert set(degree.values()) == {6} and len(degree) == n
    assert control_family_edges(K.CUBIC_QUOTIENT, n) == edges


def test_from_m_3_up_the_quotient_has_no_triangle():
    _, edges = K.periodic_cubic_quotient(1024)
    neighbours = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    assert not any(neighbours[a] & neighbours[b] for a, b in edges), "the cubic lattice has no triangle"


def test_each_law_starts_its_given_chain_at_its_own_answer():
    spec = {"sampling_contract": {"given_start": {"family": "periodic_square_lattice"},
                                  "given_start_by_law": {"c1": {"family": K.CUBIC_QUOTIENT}}}}
    assert resolve_given_start(spec, 4096, "c1") == {"family": K.CUBIC_QUOTIENT, "n": 4096}
    assert resolve_given_start(spec, 4096, "p1") == {"family": "periodic_square_lattice", "n": 4096}, \
        "a law the campaign does not name takes the campaign's start"
    assert resolve_given_start({"sampling_contract": {}}, 4096, "c1") is None
    with pytest.raises(ValueError):
        resolve_given_start(spec, 3000, "c1")


THEORY = {"theory": {"d_s": 3, "d_V": 3, "d_B": 3, "d_w": 2}, "bands": "periodic_cubic_lattice"}


def test_a_given_chain_s_probes_are_judged_at_the_top_two_rungs_they_read():
    good = {str(n): {"d_s": {"mean": 3.0}, "d_V": {"mean": 3.0}, "d_B": {"mean": 3.0}, "d_w": {"mean": 2.0}}
            for n in (4096, 16384, 65536)}
    verdict, problems, shown = judge_probes(THEORY, good)
    assert verdict == "pass" and not problems
    assert [n for n, _ in shown["d_s"]] == [16384, 65536], "the top two rungs"
    off = dict(good, **{"65536": dict(good["65536"], d_s={"mean": 1.2})})
    verdict, problems, _ = judge_probes(THEORY, off)
    assert verdict == "fail" and "given d_s 1.20 at N=65,536" in problems[0]
    verdict, _, _ = judge_probes(THEORY, {"4096": good["4096"]})
    assert verdict == "not decidable yet", "one rung read is not two"
    assert judge_probes(THEORY, None)[0] == "not decidable yet"
