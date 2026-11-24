from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import expm_multiply

from graph_scale_dynamics.probes import quantum_walk as Q


def _ring(n: int) -> list[tuple[int, int]]:
    return [(i, (i + 1) % n) for i in range(n)]


def _torus(side: int) -> list[tuple[int, int]]:
    at = lambda r, c: (r % side) * side + (c % side)
    return [(at(r, c), at(r, c + 1)) for r in range(side) for c in range(side)] + \
           [(at(r, c), at(r + 1, c)) for r in range(side) for c in range(side)]


def _ring_carrying_trees(ring: int, hung: int, seed: int = 1) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    edges = _ring(ring)
    for node in range(ring, ring + hung):
        edges.append((int(rng.integers(node)), node))
    return ring + hung, edges


def _random_regular(n: int, degree: int, seed: int = 3) -> list[tuple[int, int]]:
    rng = np.random.default_rng(seed)
    while True:
        stubs = rng.permutation(np.repeat(np.arange(n), degree)).reshape(-1, 2)
        pairs = {tuple(sorted(map(int, p))) for p in stubs if p[0] != p[1]}
        if len(pairs) == n * degree // 2:
            return sorted(pairs)


def test_one_chebyshev_step_is_the_exact_evolution():
    rng = np.random.default_rng(0)
    adjacency = Q._adjacency(40, [(int(a), int(b)) for a, b in rng.integers(0, 40, size=(90, 2))])
    adjacency = Q._largest_component(adjacency)
    hamiltonian = Q._normalized(adjacency)
    state = np.zeros(adjacency.shape[0], dtype=complex)
    state[0] = 1.0
    stepped = Q.propagate(hamiltonian, state, Q.chebyshev_weights(Q.STEP))
    exact = expm_multiply(-1j * Q.STEP * sparse.csr_matrix(hamiltonian, dtype=complex), state)
    assert np.max(np.abs(stepped - exact)) < 1e-12
    assert abs(np.linalg.norm(stepped) - 1.0) < 1e-12


def test_a_ring_spreads_ballistically_and_its_return_falls_as_one_dimension():
    channels = Q.measure(4096, _ring(4096), 0)["channels"]
    assert channels["q_alpha"]["value"] == pytest.approx(2.0, abs=0.05)
    assert channels["q_decay"]["value"] == pytest.approx(1.0, abs=0.1)


def test_a_square_torus_spreads_ballistically_and_its_return_falls_as_two_dimensions():
    channels = Q.measure(96 * 96, _torus(96), 0)["channels"]
    assert channels["q_alpha"]["value"] == pytest.approx(2.0, abs=0.1)
    assert channels["q_decay"]["value"] == pytest.approx(2.0, abs=0.3)


def test_a_ring_carrying_trees_holds_the_walk():
    n, edges = _ring_carrying_trees(1024, 3072)
    channels = Q.measure(n, edges, 0)["channels"]
    assert channels["q_alpha"]["value"] < 1.0
    assert channels["q_decay"]["value"] < 0.3


def test_an_expander_is_refused_because_the_walk_fills_it_before_anything_can_be_read():
    result = Q.measure(4096, _random_regular(4096, 4), 0)
    assert {c["refusal"] for c in result["channels"].values()} == {"SATURATES_EARLY"}


def test_a_graph_too_small_or_empty_is_refused_by_name():
    assert {c["refusal"] for c in Q.measure(10, _ring(10), 0)["channels"].values()} == {"TOO_SMALL"}
    assert {c["refusal"] for c in Q.measure(10, [], 0)["channels"].values()} == {"EMPTY_GRAPH"}


def test_the_same_graph_and_seed_read_the_same_bytes():
    assert Q.measure(2048, _ring(2048), 7) == Q.measure(2048, _ring(2048), 7)
