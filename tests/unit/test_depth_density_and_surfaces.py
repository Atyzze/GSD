from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.research.stability_score import density_diagnostic
from graph_scale_dynamics.scheduling.base_block import BASE_BLOCK_CONTRACT
from graph_scale_dynamics.decisions import evidence

ROOT = Path(__file__).resolve().parents[2]
BASE = [64, 256, 1024, 4096, 16384]
SPEC = {
    "ladder": list(BASE),
    "base_block": {"contract": "rung-phenotype-3", "sizes": list(BASE)},
    "limits": {"mean_degree_window": {"min": 1.5, "max": 8}, "connectivity_floor": 0.9},
}


def _summary(n, d_s=2.0, degree=3.0):
    return {"n": n, "seeds": 3,
            "d_s": {"mean": d_s, "se": 0.09, "n_seeds": 3},
            "d_V": {"mean": None, "n_seeds": 0},
            "d_B": {"mean": None, "n_seeds": 0},
            "d_w": {"mean": None, "n_seeds": 0},
            "mean_degree": {"mean": degree, "se": 0.0, "n_seeds": 3},
            "connected_fraction": {"mean": 1.0, "se": 0.0, "n_seeds": 3},
            "clustering": {"mean": 0.0006, "se": 0.0, "n_seeds": 3},
            "effective_samples": 40.0, "iat_sweeps": 1.3,
            "rung_terminal_classification": "EQUILIBRATED_ACTIVE",
            "probe_refusals": {"d_V": {"EXPONENTIAL_GROWTH": 3},
                               "d_B": {"NOT_POWER_LAW": 3},
                               "d_w": {"EXPONENTIAL_GROWTH": 3}, "d_s": {}}}


def _phenotype_for(sizes):
    summaries = {n: _summary(n, d_s=1.9 + 0.05 * i, degree=2.7 + 0.25 * i)
                 for i, n in enumerate(sizes)}
    states = {n: evidence._b143_rung_sampling_state(SPEC, n, summaries[n], []) for n in summaries}
    return evidence._build_four_rung_phenotype(SPEC, summaries, states)


def test_a_base_block_phenotype_is_unchanged():
    phenotype = _phenotype_for(BASE)
    assert phenotype["base_sizes"] == BASE
    assert len(phenotype["probe_vectors"]["d_s"]) == len(BASE)
    assert phenotype["extension_sizes"] == []


def test_a_deep_rung_reaches_the_phenotype():
    phenotype = _phenotype_for(BASE + [65536, 262144])
    assert phenotype is not None, "a law with depth must still get a phenotype"
    assert phenotype["extension_sizes"] == [65536, 262144]
    assert len(phenotype["extension_probe_vectors"]["d_s"]) == 2
    assert phenotype["extension_per_n"]["262144"]["mean_degree"] is not None
    assert phenotype["base_sizes"] == BASE
    assert len(phenotype["probe_vectors"]["d_s"]) == len(BASE)


def test_the_extension_carries_refusals_not_bare_nulls():
    phenotype = _phenotype_for(BASE + [65536])
    cell = phenotype["extension_per_n"]["65536"]["probes"]
    assert cell["d_s"]["value"] is not None
    assert cell["d_V"]["value"] is None
    assert cell["d_V"]["refusals"] == {"EXPONENTIAL_GROWTH": 3}, (
        "EXPONENTIAL_GROWTH is a finding about the geometry; a phenotype that "
        "prints null for it loses the finding")


def test_the_contract_was_not_bumped_and_is_the_one_read():
    phenotype = _phenotype_for(BASE + [65536])
    assert phenotype["contract"] == "rung-phenotype-3", (
        "the extension is additive: every base-block field keeps its name, "
        "length and meaning, so a v3 reader reads this record correctly")
    assert phenotype["contract"] == BASE_BLOCK_CONTRACT, "only what this tree writes is read"


def test_tolerance_alone_is_not_settling():
    corner = [2.698, 3.060, 3.325, 3.578, 3.789]
    d = density_diagnostic(corner, BASE)
    assert d["evaluable"]
    assert d["flowing"] is False, "the shipped gate admits this law"
    assert d["settled"] is False, "the measured gate does not"


def test_a_genuinely_settling_law_reads_settled():
    d = density_diagnostic([2.0, 2.60, 2.95, 2.97, 2.972], BASE)
    assert d["settled"] is True
    assert d["criteria"]["decelerating_and_within_tolerance"] is True


def test_every_criterion_is_published_so_a_gate_can_be_chosen_on_evidence():
    d = density_diagnostic([2.0, 2.60, 2.95, 2.97, 2.972], BASE)
    assert {"not_flowing", "within_tolerance",
            "decelerating_and_within_tolerance",
            "decelerating_and_within_strict"}.issubset(set(d["criteria"]))
    assert d["tolerance"] == 0.03 and d["strict_tolerance"] == 0.01


def test_a_constant_mean_degree_is_settled_not_flowing():
    d = density_diagnostic([4.0, 4.0, 4.0, 4.0, 4.0], BASE)
    assert d["flowing"] is False
    assert d["settled"] is True


def test_the_landscape_records_which_rung_an_estimate_was_read_at():
    from graph_scale_dynamics.services.api.landscape_worker import _latest_dimension
    entry = {"rungs": [{"n": 16384, "d_s": 2.0}, {"n": 262144, "d_s": 2.6}]}
    value, source, n = _latest_dimension(entry, "d_s")
    assert (value, source, n) == (2.6, "latest_rung", 262144), (
        "the classifier compared a 262,144 reading against a 16,384 anchor "
        "because nothing recorded the rung")
    assert _latest_dimension({"rungs": []}, "d_s") == (None, None, None)


def test_the_cli_parser_can_be_built_without_running_anything():
    import main as gsd_main
    parser = gsd_main.build_parser()
    assert parser.parse_args(["extend-only", "1", "--on"]).on is True
