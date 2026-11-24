from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.domain.randomness import derive_seed
from graph_scale_dynamics.measurements import certificate
from graph_scale_dynamics.measurements import estimators
from graph_scale_dynamics.research import certificate_known_answers as C
from graph_scale_dynamics.research import look_alikes
from graph_scale_dynamics.research import planted_geometries as planted
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]
STEEPEST = "to_the_steepest_radius"
ITS_STREAM = "analysis-4.0.0"
LATTICES = {"cubic_torus": lambda n: look_alikes.torus(n, 3), "tesseract_torus": lambda n: look_alikes.torus(n, 4)}
SEEDED = {**{name: family["build"] for name, family in planted.FAMILIES.items()}, **look_alikes.RANDOM}


def _json(name: str) -> dict:
    return json.loads(committed.path(name).read_text(encoding="utf-8"))


def _curves(family: str, n: int, seed: int):
    nodes, edges = LATTICES[family](n) if family in LATTICES else SEEDED[family](n, seed)
    rng = np.random.default_rng(derive_seed("analysis-estimators", ITS_STREAM, int(seed), int(nodes)) % (2 ** 63))
    adj = estimators.build_adjacency(nodes, edges)
    component = estimators.largest_component(nodes, adj)
    volume = estimators.volume_growth(adj, component, rng, keep_sources=True)
    returned = estimators.return_probability(adj, component, rng, keep_probes=True)
    return len(component), volume, returned


@pytest.mark.parametrize("family,n,seed,its_dimension,d_v_within", [
    ("cubic_torus", 3375, 11, 3.0, 0.1), ("rgg_3d", 4096, 12, 3.0, 0.25), ("erdos_renyi_4", 4096, 11, None, None),
    ("tesseract_torus", 2401, 13, 4.0, 0.6)])
def test_today_s_fits_read_a_lattice_s_dimension_and_refuse_a_random_graph(family, n, seed, its_dimension, d_v_within):
    size, volume, returned = _curves(family, n, seed)
    spectral = estimators.fit_ds(returned, size)
    balls = estimators.fit_dh(volume, size)
    if its_dimension is None:
        assert not spectral.get("valid") and spectral["refusal"] == "NO_DIFFUSIVE_WINDOW", (
            "a random graph of mean degree 4 is not read")
        assert not balls.get("valid")
        return
    assert abs(spectral["d_s"] - its_dimension) < 0.06, "d_s on its latest stretch, within 0.05 of the dimension (809)"
    assert balls.get("valid") and abs(balls["d_V_window"] - its_dimension) < d_v_within, (
        "the ball fit reads near the dimension; the 4D torus of 2,401 nodes is short of it, 3.47 at 809")


def test_the_certificate_counts_the_smaller_of_the_windowed_and_the_batch_means_count():
    rng = np.random.default_rng(754)
    for phi in (0.0, 0.6, 0.95):
        series = C.ar1(phi, 240, 1, rng)[0]
        counted = certificate.equilibration_certificate(C.envelope_of(series))
        assert counted["effective_samples"] == pytest.approx(C.counts(series, [8])[C.name_of(8)])
        assert counted["effective_samples"] == min(counted["effective_samples_counted"]["windowed"],
                                                   counted["effective_samples_counted"]["batch_means"])
        assert C.window_count(series) == counted["effective_samples_counted"]["windowed"]
        late = series[int(len(series) * 0.4):]
        assert certificate.batch_means_samples(late) == pytest.approx(C.batch_means_count(series, 8))
    still = certificate.equilibration_certificate(C.envelope_of(np.ones(240)))
    assert certificate.batch_means_samples(np.ones(144)) is None and still["effective_samples"] is None
