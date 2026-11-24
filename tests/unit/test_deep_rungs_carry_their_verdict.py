from __future__ import annotations

from graph_scale_dynamics.decisions import evidence
from graph_scale_dynamics.scaleflow.equilibration import CERT_SPLIT_DISAGREED

BASE = [64, 256, 1024, 4096]
DEEP = 16384
SPEC = {"ladder": BASE + [DEEP], "base_block": {"contract": "rung-phenotype-3", "sizes": BASE},
        "limits": {"mean_degree_window": {"min": 0.0, "max": 16}, "connectivity_floor": 0.5}}


def _summary(n):
    return {"n": n, "seeds": 3,
            "d_s": {"mean": 2.0, "se": 0.05, "n_seeds": 3},
            "d_V": {"mean": None, "n_seeds": 0}, "d_B": {"mean": None, "n_seeds": 0},
            "d_w": {"mean": None, "n_seeds": 0},
            "mean_degree": {"mean": 3.0, "se": 0.0, "n_seeds": 3},
            "connected_fraction": {"mean": 1.0, "se": 0.0, "n_seeds": 3},
            "clustering": {"mean": 0.001, "se": 0.0, "n_seeds": 3},
            "effective_samples": 40.0, "iat_sweeps": 1.3,
            "probe_refusals": {"d_s": {}, "d_V": {}, "d_B": {}, "d_w": {}}}


def _seed(n, *, failures=(), classification="EQUILIBRATED_ACTIVE"):
    return {"health": {"n": n, "rung_terminal": {
        "reason": "budget" if failures else "completed", "classification": classification,
        "failures": list(failures), "final_multiplier": 8}}}


def _phenotype(deep_seeds):
    summaries = {n: _summary(n) for n in BASE + [DEEP]}
    history = [_seed(n) for n in BASE for _ in range(3)] + deep_seeds
    states = {n: evidence._b143_rung_sampling_state(SPEC, n, summaries[n], history) for n in summaries}
    return evidence._build_four_rung_phenotype(SPEC, summaries, states)


def test_a_deep_rung_whose_given_chains_disagreed_says_so():
    disagreed = [{"code": CERT_SPLIT_DISAGREED, "detail": "the chain from empty and the given chain disagree"}]
    phenotype = _phenotype([_seed(DEEP, failures=disagreed, classification="METASTABLE_OR_NONMIXING")
                            for _ in range(3)])
    cell = phenotype["extension_per_n"][str(DEEP)]
    assert cell["rung_terminal_classification"] == "METASTABLE_OR_NONMIXING"
    assert cell["chains_verdict"] == "CHAINS_DISAGREED"
    assert str(phenotype["extension_probe_bucket_vectors"]["d_s"][0]).startswith("REFUSED"), (
        "a deep d_s the given chains disagreed about must not read as a measurement the engine can settle on")


def test_a_clean_deep_rung_reads_as_its_seeds_did():
    phenotype = _phenotype([_seed(DEEP) for _ in range(3)])
    cell = phenotype["extension_per_n"][str(DEEP)]
    assert cell["rung_terminal_classification"] == "EQUILIBRATED_ACTIVE"
    assert cell["chains_verdict"] is None
    assert not str(phenotype["extension_probe_bucket_vectors"]["d_s"][0]).startswith("REFUSED")
