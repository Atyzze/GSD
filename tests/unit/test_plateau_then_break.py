from __future__ import annotations

import math

from graph_scale_dynamics.research import plateau_break as PB

LADDER_COMPLETE = {
    "base_sizes": [64, 256, 1024, 4096], "extension_sizes": [16384, 65536, 262144, 1048576, 4194304],
    "mean_degree_vector": None,
    "extension_mean_degree_vector": [3.998535, 3.984446, 3.984711, 3.984835, 3.990086],
    "probe_vectors": {"d_s": [1.76109, 1.932194, 1.94758, 2.030799]},
    "extension_probe_vectors": {"d_s": [2.012829, 1.901311, 1.972745, 1.986048, 2.517496]},
    "probe_se_vectors": {"d_s": [0.641187, 0.559663, 0.186329, 0.082082]},
    "extension_probe_se_vectors": {"d_s": [0.046128, 0.083271, 0.026862, 0.028191, 0.085118]},
}


def test_the_first_law_to_finish_the_ladder_is_marked():
    found = PB.breaks(*PB.ladder(LADDER_COMPLETE))
    assert len(found) == 1
    one = found[0]
    assert (one["plateau_from"], one["plateau_to"], one["steps"]) == (1024, 1048576, 5)
    assert abs(one["plateau_value"] - 1.975) < 0.001 and one["plateau_spread"] < 0.13
    assert (one["break_at"], one["direction"]) == (4194304, "up")
    assert abs(one["jump"] - 0.531) < 0.001 and abs(one["sigmas"] - 5.93) < 0.01
    assert abs(one["mean_degree_step"] - 0.00132) < 1e-5, "3.9848 to 3.9901 on every seed"
    assert PB.toward(one, -2.0 / -0.323) is True
    assert PB.toward(one, 1.0) is False and PB.toward(one, None) is None


def test_a_plateau_that_holds_a_wobble_a_gap_and_the_small_rungs_mark_nothing():
    sizes = [64, 256, 1024, 4096, 16384, 65536]
    errors = [0.5, 0.3, 0.05, 0.05, 0.05, 0.05]
    assert PB.breaks(sizes, [1.0, 1.9, 2.0, 2.0, 2.01, 2.0], errors) == [], "held to the top"
    wobble = PB.breaks(sizes, [1.0, 1.9, 2.0, 2.0, 2.0, 2.18], errors)
    assert wobble == [], "2.5 standard errors: unsettled, not a break"
    gap = PB.breaks(sizes, [1.0, 1.9, 2.0, None, 2.0, 3.0], errors)
    assert gap == [], "a refused rung ends a run: one settled step after it is no plateau"
    small = PB.breaks([64, 256, 1024, 4096], [2.0, 2.0, 2.0, 3.0], [0.05] * 4)
    assert small == [], "the rungs below 1,024 do not make a plateau"
    two_steps = PB.breaks(sizes, [1.0, 1.9, 2.0, 2.0, 2.0, 1.2], errors)
    assert [(b["plateau_from"], b["break_at"], b["direction"]) for b in two_steps] == [(1024, 65536, "down")]
    assert PB.reading(sizes, [1.0, 1.9, 2.0, 2.0, 2.0, 1.2], errors)["label"] == PB.LABEL


def test_the_score_carries_the_label_and_report_22_counts_it():
    from graph_scale_dynamics.research.stability_score import score_phenotype

    scored = score_phenotype(LADDER_COMPLETE, floors={"d_s": 0.234, "d_V": 0.06, "d_B": 0.14, "d_w": 0.08})
    assert scored["plateau_break"]["label"] == PB.LABEL
    assert scored["plateau_break"]["breaks"][0]["break_at"] == 4194304
    counted = PB.population([scored, {"plateau_break": {"label": None, "breaks": []}}])
    assert counted["laws"] == 1 and counted["by_break_rung"] == {"4194304": 1} and counted["by_direction"] == {"up": 1}


def _census_row(law, n, seed):
    component = {"size": n, "cycle_rank": n, "spectral_gap": {"value": 2.0 * n ** -0.323},
                 "diameter": {"lower_bound": int(round(3.0 * n ** 0.12))}}
    census = {"degree_histogram": {"4": n}, "largest_component": component}
    return {"candidate_id": law, "n": n, "seed": seed,
            "metrics": {"census": {"empty": census, "given": census}}}


def test_report_28_marks_each_law_with_the_structure_beside_it():
    measurements = [_census_row("L", n, seed) for n in (4096, 16384, 65536, 262144) for seed in (0, 1, 2)]
    section = PB.record_section([{"candidate_id": "L", "phenotype": LADDER_COMPLETE},
                                 {"candidate_id": "flat", "phenotype": {"base_sizes": [1024, 4096, 16384],
                                                                        "probe_vectors": {"d_s": [2.0, 2.0, 2.0]},
                                                                        "probe_se_vectors": {"d_s": [0.05] * 3}}}],
                                measurements)
    assert section["laws_marked"] == 1 and section["by_break_rung"] == {"4194304": 1}
    law = section["laws"][0]
    assert law["candidate_id"] == "L" and math.isclose(law["implied_spectral_dimension"], 2 / 0.323, rel_tol=0.05)
    assert law["breaks"][0]["toward_the_structure"] is True
    assert section["relative_to_the_structure"] == {"toward": 1}
