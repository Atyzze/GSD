from __future__ import annotations

import copy
import random

import pytest

from graph_scale_dynamics.services.proposer.main import (
    coordination_seed_library, generate_batch, mutate, random_law, seed_library,
)
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_family
from graph_scale_dynamics.research.coupling import BETA_MAX, COUPLING_STRATA, coupling_stratum, coupling_strength, coverage, rescale_coupling, sweeps_for_coupling
from graph_scale_dynamics.research.flow_fitness import metric_flow_contraction, selection_value, flow_fitness

FOUNDER = {
    "dsl_version": 1, "init": "empty",
    "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": -1.0, "scale": "one"}},
              {"op": "degree_square_sum", "params": {},
               "coeff": {"c0": 0.05, "scale": "one"}}],
    "dynamics": {"kind": "equilibrium", "beta": 100.0,
                 "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 90},
}


def _coordination(spec):
    ops = {term["op"]: term["coeff"]["c0"] for term in spec["terms"]}
    return -ops["edge_count"] / (2 * ops["degree_square_sum"]) - 1


def test_founder_law_is_valid_and_classified_strong():
    assert dsl.validate(FOUNDER) == []
    assert coupling_strength(FOUNDER) == pytest.approx(100.0)
    assert coupling_stratum(FOUNDER) == "strong"


def test_rescale_preserves_direction_and_stays_legal():
    for target in (0.1, 2.0, 20.0, 200.0, 2000.0):
        law = rescale_coupling(copy.deepcopy(FOUNDER), target)
        assert dsl.validate(law, complexity_budget=7) == [], (target, dsl.validate(law))
        assert _coordination(law) == pytest.approx(9.0, rel=1e-6)
        assert coupling_strength(law) == pytest.approx(target, rel=1e-3)


def test_rescale_absorbs_into_beta_before_coefficients():
    law = rescale_coupling(copy.deepcopy(FOUNDER), 20.0)
    assert law["dynamics"]["beta"] <= BETA_MAX
    assert law["terms"][0]["coeff"]["c0"] == pytest.approx(-1.0)


def test_strata_partition_the_axis_without_gaps():
    seen = {coupling_stratum({"terms": [{"op": "edge_count", "params": {},
                                         "coeff": {"c0": value, "scale": "one"}}],
                              "dynamics": {"beta": 1.0}})
            for value in (0.05, 0.5, 3.0, 50.0, 500.0, 5000.0)}
    assert seen == set(COUPLING_STRATA)


def test_sweeps_grow_with_coupling_but_stay_bounded():
    assert sweeps_for_coupling(30, 0.5) == 30
    assert sweeps_for_coupling(30, 100.0) > 30
    assert sweeps_for_coupling(30, 1e9) <= 100_000


def test_random_laws_span_the_whole_coupling_axis():
    rng = random.Random(11)
    specs = [law for law, _, _ in generate_batch(
        rng, 600, {"ladder": [256, 1024, 4096]}, set(), [])]
    report = coverage(specs)
    assert report["unsampled_strata"] == []
    assert report["observed_strength"]["decades_spanned"] > 3.0
    assert report["observed_strength"]["max"] >= 100.0


def test_the_founder_coupling_region_is_reachable_in_one_draw():
    rng = random.Random(3)
    strengths = [coupling_strength(random_law(rng, list(dsl.OPERATORS),
                                              coupling_target="strong"))
                 for _ in range(200)]
    assert sum(1 for value in strengths if value >= 10.0) > 150


def test_mutation_moves_beta():
    rng = random.Random(5)
    parent = dict(FOUNDER, dynamics=dict(FOUNDER["dynamics"], beta=1.0))
    betas = {mutate(rng, parent, list(dsl.OPERATORS))["dynamics"]["beta"]
             for _ in range(400)}
    assert len(betas) > 20


def test_every_generated_law_validates():
    rng = random.Random(7)
    for law, _, _ in generate_batch(rng, 300, {"ladder": [256, 1024]}, set(), []):
        assert dsl.validate(law, complexity_budget=7) == [], law


def test_seed_library_has_strong_generic_anchors_but_not_founder_family():
    strata = {coupling_stratum(law) for law in coordination_seed_library()}
    assert "strong" in strata or "extreme" in strata
    seeds = seed_library()
    assert all(dsl.validate(law, complexity_budget=7) == [] for law in seeds)
    founder_family = equilibrium_family(FOUNDER)[0]
    assert all(equilibrium_family(law)[0] != founder_family for law in seeds)


def test_blind_novelty_can_reach_founder_like_family_without_a_seed():
    rng = random.Random(123)
    found = None
    for _ in range(5000):
        law = random_law(rng, list(dsl.OPERATORS), target_profile="unscaled",
                         coupling_target="strong")
        terms = {term["op"]: term for term in law["terms"]}
        if set(terms) != {"edge_count", "degree_square_sum"}:
            continue
        edge = float(terms["edge_count"]["coeff"]["c0"])
        quadratic = float(terms["degree_square_sum"]["coeff"]["c0"])
        if edge >= 0 or quadratic <= 0:
            continue
        ratio = abs(edge / quadratic)
        if 15.0 <= ratio <= 27.0 and 10.0 <= coupling_strength(law) < 200.0:
            found = law
            break
    assert found is not None


def _rungs(values, metric="d_s", valid=1.0):
    return {n: {metric: {"mean": v, "se": 0.05}, f"{metric}_valid_fraction": valid}
            for n, v in values.items()}


def test_flattening_series_outscores_a_diverging_one():
    settling = _rungs({256: 3.0, 1024: 3.6, 4096: 3.85, 16384: 3.90})
    diverging = _rungs({256: 3.0, 1024: 3.6, 4096: 4.6, 16384: 6.2})
    assert (flow_fitness(settling)["score"]
            > flow_fitness(diverging)["score"])


def test_either_metric_counts_so_the_score_is_a_maximum():
    rungs = {}
    flat = _rungs({256: 4.0, 1024: 4.02, 4096: 4.03, 16384: 4.03}, metric="d_s")
    noisy = _rungs({256: 2.0, 1024: 3.4, 4096: 1.9, 16384: 4.4}, metric="d_V")
    for n in flat:
        rungs[n] = {**flat[n], **noisy[n]}
    fitness = flow_fitness(rungs)
    assert fitness["best_metric"] == "d_s"
    assert fitness["score"] == pytest.approx(
        metric_flow_contraction(rungs, "d_s")["score"])


def test_depth_is_rewarded_for_the_same_flatness():
    ladder = [256, 1024, 4096, 16384, 65536]
    shallow = flow_fitness(_rungs({256: 4.0, 1024: 4.05, 4096: 4.06}),
                                    ladder=ladder)["score"]
    deep = flow_fitness(
        _rungs({256: 4.0, 1024: 4.05, 4096: 4.06, 16384: 4.06, 65536: 4.06}),
        ladder=ladder)["score"]
    assert deep > shallow


def test_an_unmeasurable_window_cannot_score():
    rungs = _rungs({256: 4.0, 1024: 4.0, 4096: 4.0}, valid=0.0)
    assert flow_fitness(rungs)["score"] == pytest.approx(0.0)


def test_two_rungs_are_not_evidence_of_settling():
    assert flow_fitness(_rungs({256: 4.0, 1024: 4.0}))["scored"] is False


def test_selection_keeps_unbred_lineages_competitive():
    strong = {"score": 0.8}
    unknown = {"score": 0.0}
    assert selection_value(unknown, attempts=0, total_attempts=400) > 0.0
    assert (selection_value(strong, attempts=40, total_attempts=400)
            > selection_value(unknown, attempts=40, total_attempts=400))


from graph_scale_dynamics.research.flow_fitness import (
    fit_quality, seed_reproducibility,
)


def _rungs_with_seeds(values, sd, metric="d_s", n_seeds=3):
    return {n: {metric: {"mean": v, "se": 0.05, "n_seeds": n_seeds,
                         "between_seed_sd": sd},
                f"{metric}_valid_fraction": 1.0}
            for n, v in values.items()}


def test_tight_seeds_outscore_scattered_ones_on_the_same_curve():
    values = {256: 4.0, 1024: 4.05, 4096: 4.06, 16384: 4.06}
    tight = flow_fitness(_rungs_with_seeds(values, 0.02))
    scattered = flow_fitness(_rungs_with_seeds(values, 0.9))
    assert tight["score"] > scattered["score"]
    assert (tight["metrics"]["d_s"]["components"]["reproducibility"]
            > scattered["metrics"]["d_s"]["components"]["reproducibility"])


def test_unmeasured_reproducibility_is_neutral_not_perfect():
    values = {256: 4.0, 1024: 4.05, 4096: 4.06}
    single = seed_reproducibility(_rungs_with_seeds(values, None, n_seeds=1), "d_s")
    assert single["measured"] is False and single["score"] is None

    unmeasured = flow_fitness(_rungs_with_seeds(values, None, n_seeds=1))
    tight = flow_fitness(_rungs_with_seeds(values, 0.02))
    scattered = flow_fitness(_rungs_with_seeds(values, 0.9))
    assert tight["score"] > unmeasured["score"] > scattered["score"]
    assert "reproducibility" in unmeasured["metrics"]["d_s"]["imputed_components"]
    assert unmeasured["metrics"]["d_s"]["components"]["reproducibility"] == 0.5


def test_a_good_fit_scores_above_a_poor_one():
    good = {"fitted": True, "reduced_chi2": 1.1, "max_standardized_residual": 0.8,
            "ci_width": 0.4, "model_spread": 0.15, "drop_smallest_shift": 0.05}
    poor = {"fitted": True, "reduced_chi2": 8.5, "max_standardized_residual": 3.8,
            "ci_width": 2.4, "model_spread": 0.95, "drop_smallest_shift": 0.7}
    assert fit_quality(good)["score"] > fit_quality(poor)["score"]
    values = {256: 4.0, 1024: 4.05, 4096: 4.06, 16384: 4.06}
    rungs = _rungs_with_seeds(values, 0.05)
    assert (flow_fitness(rungs, fit_records={"d_s": good})["score"]
            > flow_fitness(rungs, fit_records={"d_s": poor})["score"])


def test_a_fit_at_the_policy_limits_scores_the_same_as_no_fit():
    at_limit = {"fitted": True, "reduced_chi2": 10.0, "max_standardized_residual": 4.0,
                "ci_width": 2.5, "model_spread": 1.0, "drop_smallest_shift": 0.75}
    assert fit_quality(at_limit)["score"] == pytest.approx(0.5, abs=1e-9)

    values = {256: 4.0, 1024: 4.05, 4096: 4.06}
    rungs = _rungs_with_seeds(values, 0.05)
    unfitted = flow_fitness(rungs)
    assert "fit_quality" in unfitted["metrics"]["d_s"]["imputed_components"]
    worse = {"fitted": True, "reduced_chi2": 25.0, "max_standardized_residual": 12.0,
             "ci_width": 7.5, "model_spread": 3.0, "drop_smallest_shift": 2.25}
    assert unfitted["score"] > flow_fitness(
        rungs, fit_records={"d_s": worse})["score"]


def test_ci_width_is_derived_from_the_interval_when_absent():
    assert fit_quality({"fitted": True, "ci": [3.5, 4.1]})["measured"] is True


def test_stabilization_still_dominates_the_score():
    flat_noisy = flow_fitness(
        _rungs_with_seeds({256: 4.0, 1024: 4.02, 4096: 4.02, 16384: 4.02}, 0.5))
    drifting_clean = flow_fitness(
        _rungs_with_seeds({256: 3.0, 1024: 4.0, 4096: 5.2, 16384: 6.6}, 0.01))
    assert flat_noisy["score"] > drifting_clean["score"]
