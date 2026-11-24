from __future__ import annotations

import copy

import numpy as np
import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements import analysis
from graph_scale_dynamics.measurements import certificate
from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import version as V
from graph_scale_dynamics.scaleflow import engine_door

SPEC = {"dsl_version": 1, "init": "empty",
        "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "log_N"}},
                  {"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 0.3, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 20}}


def test_the_probes_stream_keeps_its_label_since_its_label_is_part_of_its_draws():
    assert V.PROBE_STREAM == "probe-streams-2"


def test_a_hutchinson_probe_is_the_same_whatever_block_it_is_drawn_in(monkeypatch):
    n, edges = C.uniform_random_tree(512, seed=1)
    adj = E.build_adjacency(n, edges)
    component = E.largest_component(n, adj)

    def read(block):
        monkeypatch.setenv("GSD_SPECTRAL_PROBE_BLOCK", str(block))
        return E.return_probability(adj, component, np.random.default_rng(5), keep_probes=True)

    by_four, by_sixteen = read(4), read(16)
    assert (by_four["probe_block_size"], by_sixteen["probe_block_size"]) == (4, 16)
    assert np.array_equal(by_four["p0_per_probe"], by_sixteen["p0_per_probe"]), "each probe is drawn whole, in turn"
    assert np.allclose(by_four["p0"], by_sixteen["p0"], rtol=1e-12, atol=0.0)
    again = read(4)
    assert again["p0"] == by_four["p0"], "deterministic"


def _two_chunks():
    from graph_scale_dynamics.scaleflow.engine_door import run_simulation
    first = run_simulation(SPEC, 96, 3, target_sweeps=20, record_points=40)
    return run_simulation(SPEC, 96, 3, target_sweeps=60, record_points=40,
                          resume_checkpoint=first["sampling_checkpoint"])


def test_the_certificate_reads_the_chunk_that_ended_the_rung():
    envelope = _two_chunks()
    start = int(envelope["continued_from_sweeps"]) * int(envelope["n"])
    assert start > 0
    own = certificate._last_chunk(envelope, CL.trajectory(envelope))
    assert own and all(float(row["move"]) >= start for row in own) and len(own) < len(CL.trajectory(envelope))
    assert certificate._last_chunk({**envelope, "continued_from_sweeps": 0}, CL.trajectory(envelope)) == CL.trajectory(envelope)
    last = certificate.equilibration_certificate(envelope)
    shortened = copy.deepcopy(envelope)
    CL.block(shortened, CL.FROM_EMPTY)["trajectory"] = own
    alone = certificate.equilibration_certificate({**shortened, "continued_from_sweeps": 0})
    assert last is not None
    assert last["chains"]["empty"]["effective_samples"] == alone["chains"]["empty"]["effective_samples"]
    assert last["chains"]["empty"]["tau_int_sweeps"] == alone["chains"]["empty"]["tau_int_sweeps"]
    assert last["effective_samples"] == min(row["effective_samples"] for row in last["chains"].values()), (
        "the rung's count is the smallest of its chains' own")


def test_the_health_block_carries_the_certificate():
    envelope = _two_chunks()
    adj = E.build_adjacency(envelope["n"], CL.sorted_edges(envelope))
    component = E.largest_component(envelope["n"], adj)
    read = analysis.health_metrics(envelope, adj, component)["equilibration"]
    assert read == dict(certificate.equilibration_certificate(envelope, CL.ran_names(envelope)),
                        twin_chains=["empty", "given"], left_out={})
    assert read["decide"] == ["empty", "given"], "every chain that ran, each read alike"


def test_a_mean_of_n_points_has_n_over_tau_effective_samples():
    from graph_scale_dynamics.scaleflow.engine_door import run_simulation
    envelope = run_simulation(SPEC, 96, 3, target_sweeps=20, record_points=60)
    counted = certificate.equilibration_certificate(envelope)["effective_samples_counted"]
    late = CL.trajectory(envelope)[int(len(CL.trajectory(envelope)) * 0.4):]
    tau = certificate.integrated_autocorrelation_time([row["energy"] for row in late])
    assert counted["windowed"] == pytest.approx(len(late) / tau)
    from graph_scale_dynamics.operations import campaign_control as control
    assert control.shipped_spec()["policy"]["min_effective_samples"] == 16


def test_the_chunk_loop_certifies_as_the_campaign_s_contract_does():
    from graph_scale_dynamics.scaleflow import equilibration as EQ
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    envelope = _two_chunks()
    structure = envelope.get("final_structure")
    keys = ("effective_samples", "tau_int_sweeps", "split")

    def read(cert):
        return {key: cert[key] for key in keys}

    assert read(EQ.inline_health(envelope)["equilibration"]) == read(certificate.equilibration_certificate(envelope, structure))
    from graph_scale_dynamics.operations import campaign_control as control
    spec = control.shipped_spec()
    assert one_shot_policy(spec, 1024)["analysis_version"] == V.ANALYSIS_VERSION
    counted = EQ.inline_health(envelope, one_shot_policy(spec, 1024))["equilibration"]
    assert read(counted) == read(certificate.equilibration_certificate(envelope, structure))
    assert counted["effective_samples"] <= counted["effective_samples_counted"]["windowed"], "the smaller count certifies"


def test_the_random_regular_builder_comes_out_for_every_seed():
    for seed in range(60):
        n, edges = C.random_regular_graph(64, 4, seed=seed)
        assert len(edges) == 128 and len({tuple(sorted(e)) for e in edges}) == 128


def test_the_envelope_names_the_stream_derivation_it_was_made_by():
    from graph_scale_dynamics.domain.randomness import STREAM_VERSION
    from graph_scale_dynamics.engine.engine import ENGINE_VERSION
    from graph_scale_dynamics.scaleflow.engine_door import run_simulation
    assert ENGINE_VERSION == "engine-3.3.0"
    assert run_simulation(SPEC, 64, 1)["random_streams"]["version"] == STREAM_VERSION


def test_a_given_chain_ended_at_the_cap_is_carried_and_not_rebuilt_at_all(monkeypatch):
    from graph_scale_dynamics.engine import engine as G
    first = engine_door.run_simulation(SPEC, 96, 3, target_sweeps=20, record_points=40, chain_runner=G.run_chain)
    checkpoint = dict(first["sampling_checkpoint"], chains=[
        dict(block, ended={"reason": "mean_degree_cap", "at_move": 1}) if block["start"] == CL.GIVEN else block
        for block in first["sampling_checkpoint"]["chains"]])
    seen = []
    real = G._rebuild_in_python

    def recording(chain, **kwargs):
        seen.append(chain.get("start"))
        return real(chain, **kwargs)

    monkeypatch.setattr(G, "_rebuild_in_python", recording)
    engine_door.run_simulation(SPEC, 96, 3, target_sweeps=60, record_points=40, chain_runner=G.run_chain,
                     resume_checkpoint=checkpoint)
    assert seen == [CL.FROM_EMPTY], "only the chain that runs is rebuilt"


@pytest.mark.parametrize("edges, why", [
    ([(0, 1), (1, 8)], "outside"), ([(0, 1), (2, 2)], "loop"), ([(0, 1), (1, 0)], "twice")])
def test_the_python_engine_refuses_the_checkpoints_the_rust_one_does(edges, why):
    from graph_scale_dynamics.engine.checkpoint import check_edges
    with pytest.raises(ValueError, match=why):
        check_edges(8, edges)
    check_edges(8, [(0, 1), (1, 2), (7, 0)])


EDGES = [{"op": "edge_count", "coeff": 1.0}]


def _doors():
    from tests.support.engines import every_door_of_every_engine
    return every_door_of_every_engine()


def _rebuild(call, n, edges, **kwargs):
    return call("rebuild_graph", {"n": n, "terms": EDGES, "edge_list": [list(edge) for edge in edges], **kwargs})


def _run(call, n, edges, energy, **kwargs):
    from tests.support.engines import a_chain_request
    return call("run_chain", a_chain_request(n, EDGES, edges, energy, **kwargs))


@pytest.mark.parametrize("edges, why", [
    ([(0, 1), (1, 8)], "outside"), ([(0, 1), (2, 2)], "loop"), ([(0, 1), (1, 0)], "twice")])
def test_a_bad_checkpoint_edge_is_refused_not_a_panic(edges, why):
    for _door, call in _doors():
        with pytest.raises(ValueError, match=why):
            _rebuild(call, 8, edges)
        with pytest.raises(ValueError, match=why):
            _run(call, 8, edges, 0.0)


def test_the_triangle_count_is_the_same_and_a_hub_is_not_scanned_per_neighbour():
    n = 600
    hub = [(0, v) for v in range(1, n)]
    ring = [(v, v + 1) for v in range(1, n - 1)]
    chords = [(v, v + 2) for v in range(1, n - 2, 7)]
    edges = hub + ring + chords
    for door, call in _doors():
        out = _run(call, n, edges, float(len(edges)), words=[9] * 623 + [1])
        adj = [set(map(int, row)) for row in out["adj"]]
        triangles = sum(1 for u in range(n) for v in adj[u] if v > u for w in adj[u] & adj[v] if w > v)
        assert triangles >= 80, "the hub closes a triangle on every ring edge"
        assert out["trajectory"][0]["triangles"] == triangles, door


def test_the_starts_group_on_distances_as_computed():
    from graph_scale_dynamics.observability import starts_reading as F
    assert F.groups(["a", "b"], {F.pair_key("a", "b"): 1.0004}) == [["a"], ["b"]]
    assert F.groups(["a", "b"], {F.pair_key("a", "b"): 1.0}) == [["a", "b"]]


def test_the_probe_step_ratios_are_judged_unrounded():
    from graph_scale_dynamics.research.step_shape import decelerating, shown, step_ratios
    ratios = step_ratios([1.0, 0.99999, 0.99998])
    assert decelerating(ratios) and shown(ratios) == [1.0, 1.0], "shown 1.0, judged below one"
