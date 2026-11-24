from __future__ import annotations

from collections import Counter

from graph_scale_dynamics.scaleflow.probes import (
    Bucket, PROBES, bucket_for_rung, empty_bucket_counts,
)
from graph_scale_dynamics.research.numeric import finite as _finite
from graph_scale_dynamics.research.every_law import every_law_table
from graph_scale_dynamics.research import giant_degree as GD
from graph_scale_dynamics.research.noise_floors import floor_at, noise_floors, noise_floors_by_n
from graph_scale_dynamics.research.plateau_break import population as plateau_population
from graph_scale_dynamics.research.plateau_break import masked, reading as plateau_reading
from graph_scale_dynamics.scheduling.base_block import BASE_BLOCK_CONTRACT

STABILITY_SCORE_CONTRACT = "gsd-stability-score-14"

NO_METRIC_STRUCTURE_BUCKET = "NO_METRIC_STRUCTURE"
METRIC_CLASS_MIN_RUNGS = 3

WITHHELD_SETTLED_BUCKETS = frozenset()

CONTROL_FAMILY_BUCKET_PREFIX = "CONTROL_"
CONTROL_MATCH_MIN_RUNGS = 3
CONTROL_MATCH_TOLERANCE_MULTIPLIER = 3.0
CONTROL_MATCH_ABSOLUTE_FLOOR = 0.12
CONTROL_MATCH_DEGREE_RELATIVE = 0.10
CONTROL_MATCH_AMBIGUITY_MARGIN = 0.33

CONTROL_FAMILY_MEAN_DEGREE = {
    "periodic_ring": 2.0,
    "periodic_square_lattice": 4.0,
    "periodic_triangular_lattice": 6.0,
    "periodic_honeycomb_lattice": 3.0,
    "periodic_cubic_lattice": 6.0,
    "periodic_hypercubic_lattice_4d": 8.0,
    "sierpinski_gasket": 4.0,
    "sierpinski_carpet": 4.0,
    "uniform_random_tree": 2.0,
    "balanced_binary_tree": 2.0,
    "random_3_regular": 3.0,
    "random_4_regular": 4.0,
    "erdos_renyi_sparse": 2.77,
    "erdos_renyi_mid": 3.18,
    "erdos_renyi_dense": 4.08,
    "erdos_renyi_degree_2": 2.40,
    "erdos_renyi_degree_6": 6.01,
}
BLOCK_POINTS = 50.0
SCORED_BLOCKS = ("d_s", "mean_degree")
UNSCORED_BLOCKS = ("d_V", "d_B", "d_w")
MIN_VALID_RUNGS = 3
UNSTABLE_BUCKETS = frozenset({Bucket.DEGRADED_WITH_N.value,
                              Bucket.DRIFTING_MONOTONICALLY.value})
CONTRACTING_BUCKETS = frozenset({Bucket.CONVERGED.value})


def contracting_probes(buckets: dict | None) -> list[str]:
    return [probe for probe in PROBES
            if str((buckets or {}).get(probe) or "") in CONTRACTING_BUCKETS]


TOLERANCE_MULTIPLIER = 2.0
CONSTANCY_SIGNIFICANCE = 0.05

from graph_scale_dynamics.research.step_shape import decelerating, remaining_distance, shown, step_ratios  # noqa: E402


def _constancy(usable: list, ses: list | None):
    if not ses or len(usable) < 2:
        return None, None, None
    points = []
    for index, value in usable:
        se = _finite(ses[index]) if index < len(ses) else None
        if se is None or se <= 0.0:
            return None, None, None
        points.append((value, se))
    weights = [1.0 / (se * se) for _, se in points]
    mean = sum(w * v for w, (v, _) in zip(weights, points, strict=True)) / sum(weights)
    chi_square = sum(((v - mean) / se) ** 2 for v, se in points)
    dof = len(points) - 1
    if dof <= 0:
        return chi_square, dof, None
    try:
        from scipy.stats import chi2
        p = float(chi2.sf(chi_square, dof))
    except Exception:
        return chi_square, dof, None
    return chi_square, dof, p


def score_block(values: list, rung_buckets: list, *, floor: float | None,
                sizes: list[int] | None = None,
                floors_by_n: dict[int, float] | None = None,
                ses: list | None = None, measured_ses: list | None = None) -> dict:
    clean = [_finite(v) for v in values]
    usable = [(i, v) for i, v in enumerate(clean)
              if v is not None and (i >= len(rung_buckets) or rung_buckets[i] is None)]
    valid_rungs = len(usable)
    mix = Counter(str(b) for b in rung_buckets if b)
    deltas = [b - a for (_, a), (_, b) in zip(usable, usable[1:], strict=False)]
    abs_deltas = [abs(d) for d in deltas]

    def _tolerance(step: int) -> float | None:
        if sizes and floors_by_n:
            i_a, i_b = usable[step][0], usable[step + 1][0]
            fa = floor_at(floors_by_n, int(sizes[i_a]), fallback=floor) if i_a < len(sizes) else floor
            fb = floor_at(floors_by_n, int(sizes[i_b]), fallback=floor) if i_b < len(sizes) else floor
            base = max(v for v in (fa, fb) if v is not None) if (fa is not None or fb is not None) else None
        else:
            base = floor
        return None if base is None else TOLERANCE_MULTIPLIER * float(base)

    tolerances = [_tolerance(k) for k in range(len(abs_deltas))]
    guard_tolerance = tolerances[-1] if tolerances else None
    from graph_scale_dynamics.research.d_s_slack import step_tolerances
    explicit = step_tolerances(sizes, measured_ses, [(usable[k][0], usable[k + 1][0]) for k in range(len(abs_deltas))])
    if explicit is not None:
        tolerances = explicit
    inside_noise = bool(abs_deltas) and all(t is not None and d <= t for d, t in zip(abs_deltas, tolerances, strict=True))
    last_inside_noise = bool(abs_deltas) and tolerances[-1] is not None and abs_deltas[-1] <= tolerances[-1]

    top_index = len(values) - 1
    top_bucket = rung_buckets[top_index] if 0 <= top_index < len(rung_buckets) else None
    top_se = _finite(ses[top_index]) if ses and top_index < len(ses) else None
    if explicit is not None:
        top_se = _finite(measured_ses[top_index]) if top_index < len(measured_ses) else None
    top_tolerance = tolerances[-1] if tolerances else None
    if explicit is None:
        guard_tolerance = top_tolerance

    def _provisional() -> float:
        if not abs_deltas:
            return 0.0
        inside = [t is not None and d <= t for d, t in zip(abs_deltas, tolerances, strict=True)]
        if all(inside):
            quality = 1.0
        elif len(abs_deltas) >= 2 and abs_deltas[0] > 0.0:
            quality = max(0.0, min(1.0, 1.0 - abs_deltas[-1] / abs_deltas[0]))
        else:
            tol = tolerances[-1]
            quality = (0.0 if (tol is None or abs_deltas[-1] <= 0.0)
                       else max(0.0, min(1.0, tol / abs_deltas[-1])))
        evidence = min(1.0, valid_rungs / float(MIN_VALID_RUNGS))
        return evidence * quality

    result = {
        "valid_rungs": valid_rungs,
        "deltas": [round(d, 6) for d in deltas],
        "noise_floor": floor,
        "tolerances": [None if t is None else round(t, 6) for t in tolerances],
        "tolerance_multiplier": TOLERANCE_MULTIPLIER,
        **({"tolerance_rule": "measured, finite-size (629)"} if explicit is not None else {}),
        "shrink_ratio": None,
        "score": 0.0,
        "approach": round(_provisional(), 4),
        "approach_is_provisional": True,
        "bucket": None,
        "rung_bucket_mix": dict(sorted(mix.items())),
    }

    if top_bucket is not None:
        result["top_rung_bucket"] = str(top_bucket)
        result["top_rung_refused"] = True
        if valid_rungs > 0:
            result["bucket"] = Bucket.DEGRADED_WITH_N.value
            result["measured_through_n"] = (
                int(sizes[usable[-1][0]]) if sizes and usable[-1][0] < len(sizes) else None)
            result["why"] = (f"read through N={result['measured_through_n']}, then stopped reading at a larger N "
                             f"(the top rung refused: {top_bucket}); not a drift")
            result["score"] = 0.0
            result["degraded_from_valid_rungs"] = valid_rungs
            result["approach"] = 0.0
            result["approach_is_provisional"] = False
        else:
            result["bucket"] = str(top_bucket)
        return result
    if valid_rungs < MIN_VALID_RUNGS:
        if valid_rungs >= 2 and inside_noise:
            result["bucket"] = Bucket.INSIDE_NOISE_TOO_FEW_RUNGS.value
        elif mix:
            result["bucket"] = max(sorted(mix), key=lambda b: mix[b])
        else:
            result["bucket"] = Bucket.NOT_ATTEMPTED.value
        return result

    if top_se is not None and guard_tolerance is not None and top_se > guard_tolerance:
        result["bucket"] = Bucket.UNRESOLVED_AT_TOP_RUNG.value
        result["top_rung_se"] = round(top_se, 6)
        return result
    first, last = abs_deltas[0], abs_deltas[-1]
    ratio = None if first == 0.0 else last / first
    result["shrink_ratio"] = None if ratio is None else round(ratio, 6)

    monotone = len(deltas) >= 2 and (all(d > 0 for d in deltas) or all(d < 0 for d in deltas))

    chi_square, dof, constancy_p = _constancy(usable, ses)
    result["chi_square"] = None if chi_square is None else round(chi_square, 6)
    result["chi_square_dof"] = dof
    result["constancy_p"] = None if constancy_p is None else round(constancy_p, 6)
    monotone = len(deltas) >= 2 and (all(d > 0 for d in deltas) or all(d < 0 for d in deltas))
    result["monotone"] = monotone
    result["total_movement"] = round(abs(sum(deltas)), 6)
    moves_beyond_its_errors = constancy_p is not None and constancy_p < CONSTANCY_SIGNIFICANCE
    result["moves_beyond_its_errors"] = moves_beyond_its_errors
    drifting_in_one_direction = bool(moves_beyond_its_errors and monotone)

    ratios_of_deltas = step_ratios(abs_deltas)
    result["step_ratios"] = shown(ratios_of_deltas)
    shrinking = decelerating(ratios_of_deltas)
    result["decelerating"] = shrinking
    remaining = remaining_distance(abs_deltas, ratios_of_deltas)
    result["remaining_distance"] = None if remaining is None else round(remaining, 6)
    arrived = (remaining is not None and top_tolerance is not None
               and remaining <= top_tolerance)
    result["tail_inside_tolerance"] = bool(arrived)
    gapped = bool(sizes) and any(sizes[usable[k + 1][0]] > 4.5 * sizes[usable[k][0]] for k in range(len(abs_deltas))
                                 if usable[k + 1][0] < len(sizes))
    result["steps_span_a_gap"] = gapped
    asymptotic = bool(last_inside_noise and shrinking and arrived
                      and moves_beyond_its_errors and not gapped)
    result["settled_by_asymptotic_approach"] = asymptotic
    flat = ((last_inside_noise or (ratio is None and inside_noise))
            and (not moves_beyond_its_errors or asymptotic))
    if flat:
        score = BLOCK_POINTS
    elif ratio is None:
        score = 0.0
    else:
        score = BLOCK_POINTS * max(0.0, min(1.0, 1.0 - ratio))
    result["score"] = round(score, 3)
    result["approach"] = round(score / BLOCK_POINTS, 4)
    result["approach_is_provisional"] = False
    if score >= BLOCK_POINTS:
        result["bucket"] = Bucket.CONVERGED.value
    elif drifting_in_one_direction:
        result["bucket"] = Bucket.DRIFTING_MONOTONICALLY.value
    else:
        result["bucket"] = Bucket.STILL_DRIFTING.value
    result["scored_by_noise_floor"] = bool(flat)
    return result


def control_family_reference(calibration_table: dict | None) -> dict:
    from graph_scale_dynamics.calibration import cell_is_current
    cells = (calibration_table or {}).get("cells") or {}
    acc: dict[str, dict[int, dict[str, list]]] = {}
    for cell in (cells.values() if isinstance(cells, dict) else cells):
        if str(cell.get("status") or "ok") != "ok" or not cell_is_current(cell):
            continue
        family = str(cell.get("family") or "")
        n = int(cell.get("n") or 0)
        if family not in CONTROL_FAMILY_MEAN_DEGREE or n <= 0:
            continue
        for probe, channel in (cell.get("channels") or {}).items():
            if not isinstance(channel, dict) or not channel.get("valid"):
                continue
            value = _finite(channel.get("value"))
            if value is None:
                continue
            acc.setdefault(family, {}).setdefault(n, {}).setdefault(probe, []).append(
                (value, _finite(channel.get("se")) or 0.0))
    reference: dict[str, dict[int, dict[str, dict]]] = {}
    for family, by_n in acc.items():
        for n, probes in by_n.items():
            for probe, values in probes.items():
                mean = sum(v for v, _ in values) / len(values)
                se = max((s for _, s in values), default=0.0)
                reference.setdefault(family, {}).setdefault(n, {})[probe] = {"mean": mean, "se": se}
    return reference


def control_family_match(probe_vectors: dict, mean_degree_vector: list | None,
                         sizes: list[int] | None, reference: dict | None,
                         *, probe_se_vectors: dict | None = None) -> dict:
    result: dict = {"family": None, "rungs_matched": 0, "candidates": {}}
    if not reference or not sizes:
        return result
    degrees = list(mean_degree_vector or [])
    for family, by_n in reference.items():
        target_degree = CONTROL_FAMILY_MEAN_DEGREE.get(family)
        matched = 0
        disagreed = False
        worst = 0.0
        compared_indices: set[int] = set()
        for i, n in enumerate(sizes):
            cell = by_n.get(int(n))
            if not cell:
                continue
            degree = _finite(degrees[i]) if i < len(degrees) else None
            if target_degree is not None and degree is not None \
                    and abs(degree - target_degree) > CONTROL_MATCH_DEGREE_RELATIVE * target_degree:
                disagreed = True
                break
            compared = 0
            for probe, ref in cell.items():
                values = list((probe_vectors or {}).get(probe) or [])
                value = _finite(values[i]) if i < len(values) else None
                if value is None:
                    continue
                ses = list((probe_se_vectors or {}).get(probe) or [])
                se = (_finite(ses[i]) if i < len(ses) else None) or 0.0
                tolerance = max(CONTROL_MATCH_ABSOLUTE_FLOOR,
                                CONTROL_MATCH_TOLERANCE_MULTIPLIER * (se + float(ref["se"])))
                deviation = abs(value - float(ref["mean"]))
                worst = max(worst, deviation / tolerance)
                compared += 1
                if deviation > tolerance:
                    disagreed = True
                    break
            if disagreed:
                break
            if compared:
                matched += 1
                compared_indices.add(i)
        top_index = max((i for probe in (probe_vectors or {})
                         for i, v in enumerate((probe_vectors or {}).get(probe) or [])
                         if _finite(v) is not None), default=None)
        top_compared = (top_index is not None and top_index < len(sizes)
                        and bool(by_n.get(int(sizes[top_index]))) and top_index in compared_indices)
        result["candidates"][family] = {"rungs_matched": matched, "disagreed": disagreed,
                                        "top_rung_compared": top_compared,
                                        "worst_deviation_over_tolerance": round(worst, 3)}
    survivors = [(name, c) for name, c in result["candidates"].items()
                 if not c["disagreed"] and c["top_rung_compared"]
                 and c["rungs_matched"] >= CONTROL_MATCH_MIN_RUNGS]
    survivors.sort(key=lambda item: (item[1]["worst_deviation_over_tolerance"],
                                     -item[1]["rungs_matched"]))
    result["survivors"] = [{"family": n, "deviation": c["worst_deviation_over_tolerance"],
                            "rungs_matched": c["rungs_matched"]} for n, c in survivors]
    if survivors:
        best_name, best = survivors[0]
        rivals = [n for n, c in survivors[1:]
                  if c["worst_deviation_over_tolerance"] - best["worst_deviation_over_tolerance"]
                  <= CONTROL_MATCH_AMBIGUITY_MARGIN]
        result["ambiguous_with"] = rivals
        if rivals:
            result["family"] = None
            result["rungs_matched"] = 0
            result["reading"] = (
                f"this law fits {best_name} at deviation "
                f"{best['worst_deviation_over_tolerance']} and also fits "
                f"{', '.join(rivals)} within {CONTROL_MATCH_AMBIGUITY_MARGIN} of that. "
                "The instrument cannot separate them here, so no family is named; "
                "a deeper rung is what would separate them, not a tie-break")
        else:
            result["family"] = best_name
            result["rungs_matched"] = best["rungs_matched"]
            result["deviation"] = best["worst_deviation_over_tolerance"]
            result["reading"] = (
                f"best fit among {len(survivors)} surviving candidate(s), at deviation "
                f"{best['worst_deviation_over_tolerance']} over the next at "
                f"{survivors[1][1]['worst_deviation_over_tolerance'] if len(survivors) > 1 else '-'}")
    return result


MEAN_DEGREE_DRIFT_TOLERANCE = 0.03
MEAN_DEGREE_STRICT_TOLERANCE = 0.01
DENSITY_DECEL_RATIO_MAX = 1.0
DENSITY_FLOWING_BUCKET = "DENSITY_FLOWING"
DENSITY_MIN_RUNGS = 3
DENSITY_CLAMPED_BUCKETS = frozenset({"REFUSED_MEAN_DEGREE_ABOVE_WINDOW"})
DENSITY_CLAMPED_BUCKET = "DENSITY_CLAMPED"


def density_diagnostic(mean_degree_vector: list | None, sizes: list[int] | None,
                       rung_buckets: list | None = None) -> dict:
    pairs = list(zip(mean_degree_vector or [], sizes or [], strict=False))
    buckets = list(rung_buckets or [])
    clamped = [bool(i < len(buckets) and str(buckets[i] or "") in DENSITY_CLAMPED_BUCKETS)
               for i in range(len(pairs))]
    clamped_rungs = [int(n) for (_, n), drop in zip(pairs, clamped, strict=True) if drop]
    degrees = [(_finite(d), n) for (d, n), drop in zip(pairs, clamped, strict=True) if not drop]
    degrees = [(d, n) for d, n in degrees if d is not None and d > 0]
    if len(degrees) < DENSITY_MIN_RUNGS:
        return {"contract": "density-gate-3", "flowing": False, "evaluable": False,
                "rungs_compared": len(degrees),
                "clamped_rungs": clamped_rungs,
                "clamped_rungs_dropped": len(clamped_rungs),
                "reading": (
                    f"the mean-degree cap stopped {len(clamped_rungs)} of this law's rungs "
                    f"({clamped_rungs}); the cap is not a measurement of the law, so those "
                    f"rungs are dropped and {len(degrees)} remain, fewer than the three "
                    "needed to see whether the rise is slowing"
                    if clamped_rungs else
                    "fewer than three rungs carry a mean degree; two steps are needed "
                    "to see whether the rise is slowing")}
    steps = [b[0] - a[0] for a, b in zip(degrees, degrees[1:], strict=False)]
    abs_steps = [abs(x) for x in steps]
    exact_relative = [abs(b[0] - a[0]) / max(abs(a[0]), 1e-9) for a, b in zip(degrees, degrees[1:], strict=False)]
    exact_ratios = [abs_steps[i + 1] / abs_steps[i] if abs_steps[i] > 1e-9 else None
                    for i in range(len(abs_steps) - 1)]
    relative_steps = [round(x, 4) for x in exact_relative]
    ratios = [None if r is None else round(r, 4) for r in exact_ratios]
    judged = [r for r in exact_ratios[-2:] if r is not None]
    decelerating = bool(judged) and all(r < DENSITY_DECEL_RATIO_MAX for r in judged)
    (prev, n_prev), (top, n_top) = degrees[-2], degrees[-1]
    last_ratio = judged[-1] if judged else None
    remaining = (abs_steps[-1] * last_ratio / (1.0 - last_ratio)
                 if last_ratio is not None and 0.0 < last_ratio < 1.0 else None)
    limit = (top + (remaining if steps[-1] >= 0 else -remaining)) if remaining is not None else None
    already_converged = exact_relative[-1] <= MEAN_DEGREE_DRIFT_TOLERANCE
    flowing = (not decelerating) and (not already_converged)
    return {
        "contract": "density-gate-3", "flowing": bool(flowing), "evaluable": True,
        "decelerating": bool(decelerating),
        "rungs_compared": len(degrees),
        "clamped_rungs": clamped_rungs,
        "clamped_rungs_dropped": len(clamped_rungs),
        "mean_degree_top": round(top, 4), "mean_degree_previous": round(prev, 4),
        "top_rungs": [int(n_prev), int(n_top)],
        "relative_step": relative_steps[-1], "relative_steps": relative_steps,
        "step_ratios": ratios, "ratio_max": DENSITY_DECEL_RATIO_MAX,
        "extrapolated_limit": (round(limit, 4) if limit is not None else None),
        "remaining_relative": (round(remaining / max(abs(top), 1e-9), 4)
                               if remaining is not None else None),
        "converged_at_this_rung": bool(already_converged),
        "settled": bool(len(relative_steps) >= 2
                        and max(exact_relative[-2:]) <= MEAN_DEGREE_STRICT_TOLERANCE),
        "settled_rungs_flat": (3 if len(relative_steps) >= 2
                               and max(exact_relative[-2:]) <= MEAN_DEGREE_STRICT_TOLERANCE
                               else 0),
        "settled_strict": bool(len(relative_steps) >= 3
                               and max(exact_relative[-3:]) <= MEAN_DEGREE_STRICT_TOLERANCE),
        "criteria": {
            "not_flowing": bool(not flowing),
            "within_tolerance": bool(already_converged),
            "decelerating_and_within_tolerance": bool(
                already_converged and (decelerating or not judged)),
            "last_two_steps_within_strict": bool(
                len(relative_steps) >= 2
                and max(exact_relative[-2:]) <= MEAN_DEGREE_STRICT_TOLERANCE),
            "last_two_steps_within_tolerance": bool(
                len(relative_steps) >= 2
                and max(exact_relative[-2:]) <= MEAN_DEGREE_DRIFT_TOLERANCE),
            "decelerating_and_within_strict": bool(
                (decelerating or not judged)
                and exact_relative[-1] <= MEAN_DEGREE_STRICT_TOLERANCE),
            "last_three_steps_within_strict": bool(
                len(relative_steps) >= 3
                and max(exact_relative[-3:]) <= MEAN_DEGREE_STRICT_TOLERANCE),
        },
        "tolerance": MEAN_DEGREE_DRIFT_TOLERANCE,
        "strict_tolerance": MEAN_DEGREE_STRICT_TOLERANCE,
        "settled_reading": (
            "settled: the last two steps are both inside the strict tolerance, so "
            "three consecutive rungs show essentially no drift. On campaign 1's 424 "
            "laws with a rung beyond the base block this held at the next rung "
            "99.1% of the time (one wrong in 117), against 93.2% for the "
            "decelerating rule it replaces and 53.5% for `flowing`."
            if (decelerating and already_converged) else
            "not settled: one small step is not settling. A mean degree can fall "
            "the whole length of the block and land a 0.6% step at the top; three "
            "consecutive rungs with essentially no drift is the claim being made."),
        "reading": (
            f"mean degree's rise is not slowing (last step ratios {[round(r, 4) for r in judged]}); the ensemble has "
            "no limit in sight and whatever the probes read is the reading of something "
            "still being decided"
            if flowing else
            f"mean degree is converging: successive x4 steps shrink by {last_ratio}, "
            f"extrapolated limit about {limit:.2f}, "
            f"{100 * remaining / max(abs(top), 1e-9):.0f}% still to go at N={n_top}"
            if remaining is not None else
            f"mean degree moved {100 * relative_steps[-1]:.1f}% at the top rung, inside the "
            f"{100 * MEAN_DEGREE_DRIFT_TOLERANCE:g}% convergence tolerance"
            if already_converged else
            "mean degree is converging"),
    }


def score_density_block(density: dict) -> dict:
    block = {"score": 0.0, "approach": 0.0, "bucket": Bucket.NOT_ATTEMPTED.value,
             "valid_rungs": 0, "why": "no mean degree on three or more rungs",
             "settled": False, "settled_strict": False}
    if not density or not density.get("evaluable"):
        if (density or {}).get("clamped_rungs_dropped"):
            block["bucket"] = DENSITY_CLAMPED_BUCKET
            block["clamped_rungs"] = list(density.get("clamped_rungs") or [])
            block["why"] = ("the mean-degree cap stopped this law above the window; the "
                            "rungs it stopped publish the cap rather than a measurement "
                            "and are not evidence that the ensemble settled")
        return block
    steps = [s for s in (density.get("relative_steps") or []) if s is not None]
    block["valid_rungs"] = int(density.get("rungs_compared") or len(steps) + 1)
    block["settled"] = bool(density.get("settled"))
    block["settled_strict"] = bool(density.get("settled_strict"))
    block["relative_step"] = density.get("relative_step")
    if density.get("settled"):
        block.update({"score": BLOCK_POINTS, "approach": 1.0,
                      "bucket": Bucket.CONVERGED.value,
                      "why": "mean degree inside tolerance and its steps shrinking"})
        return block
    first, last = (steps[0] if steps else None), (steps[-1] if steps else None)
    if first and last is not None and first > 0:
        contraction = max(0.0, 1.0 - (last / first))
        block["score"] = round(BLOCK_POINTS * contraction, 3)
        block["approach"] = round(contraction, 4)
    block["bucket"] = (DENSITY_FLOWING_BUCKET if density.get("flowing")
                       else Bucket.DEGRADED_WITH_N.value)
    block["why"] = ("mean degree still moving between the top two rungs; "
                    "credit is how much the steps contracted")
    return block


def metric_class_diagnostic(half_volume_radius_vector: list | None,
                            connected_fraction_vector: list | None,
                            sizes: list[int] | None,
                            connectivity_floor: float | None = None) -> dict:
    from graph_scale_dynamics.scaleflow.ladder import radius_scaling_dimension
    radii = list(half_volume_radius_vector or [])
    connected = list(connected_fraction_vector or [])
    rungs = []
    for i, n in enumerate(sizes or []):
        radius = _finite(radii[i]) if i < len(radii) else None
        fraction = _finite(connected[i]) if i < len(connected) else None
        if radius is None or radius <= 0 or fraction is None or fraction <= 0:
            continue
        if connectivity_floor is not None and fraction < float(connectivity_floor):
            continue
        rungs.append({"n": int(n), "component_size": max(1.0, fraction * float(n)),
                      "half_volume_radius": radius})
    if len(rungs) < METRIC_CLASS_MIN_RUNGS:
        return {"verdict": "insufficient_rungs", "rungs": len(rungs),
                "required": METRIC_CLASS_MIN_RUNGS, "dimension": None,
                "reason": f"{len(rungs)} connected rungs with a half-volume radius; need "
                          f"{METRIC_CLASS_MIN_RUNGS}"}
    DROP = ("slope_interval", "residual_rms", "power_law_rms", "logarithmic_rms",
            "required")
    result = radius_scaling_dimension(rungs)
    out = {k: v for k, v in result.items() if k not in DROP}
    for k in ("slope", "slope_se", "radius_growth", "volume_growth", "fit_ratio",
              "dimension", "log_diameter_slope", "log_diameter_separation_sigma"):
        if isinstance(out.get(k), float):
            out[k] = round(out[k], 4)
    out["sizes"] = [r["n"] for r in rungs]
    verdict = out.get("verdict")
    out["reading"] = (
        "a logarithm fits the half-volume radius better than any power on the base rungs: "
        "bounded diameter, no dimension; every block's points are withheld"
        if verdict == "no_metric_structure" else
        "a power law fits the base rungs better than a logarithm, which on five rungs is "
        "not a finding: the laws campaign 1 sent to 262144 read this way at N=16384 and "
        "were rejected as expanders there; nothing is withheld and nothing is claimed"
        if verdict == "metric" else
        "the base rungs cannot separate a power law from a logarithm"
        if verdict == "undetermined" else
        "too few connected rungs with a radius to fit")
    return out


def score_law(probe_vectors: dict, probe_bucket_vectors: dict | None, *,
              floors: dict[str, float | None], sizes: list[int] | None = None,
              floors_by_n: dict[str, dict[int, float]] | None = None,
              probe_se_vectors: dict | None = None,
              connectivity_vector: list | None = None,
              connectivity_floor: float | None = None,
              mean_degree_vector: list | None = None,
              clustering_vector: list | None = None,
              control_reference: dict | None = None,
              half_volume_radius_vector: list | None = None,
              probe_measured_se_vectors: dict | None = None,
              giant_mean_degree_vector: list | None = None) -> dict:
    blocks = {}
    total = 0.0
    below_floor = []
    if connectivity_vector and connectivity_floor is not None:
        below_floor = [(_finite(c) is not None and float(c) < float(connectivity_floor))
                       for c in connectivity_vector]
    for probe in PROBES:
        values = list((probe_vectors or {}).get(probe) or [])
        buckets = list((probe_bucket_vectors or {}).get(probe) or [None] * len(values))
        if below_floor:
            buckets = [(Bucket.REFUSED_BELOW_CONNECTIVITY_FLOOR.value if (i < len(below_floor) and below_floor[i]) else b)
                       for i, b in enumerate(buckets + [None] * (len(values) - len(buckets)))]
        ses = list((probe_se_vectors or {}).get(probe) or [])
        measured = list((probe_measured_se_vectors or {}).get(probe) or []) if probe == "d_s" else []
        block = score_block(values, buckets, floor=floors.get(probe), sizes=sizes,
                            floors_by_n=(floors_by_n or {}).get(probe), ses=ses or None,
                            measured_ses=measured or None)
        block["scored"] = probe in SCORED_BLOCKS
        if not block["scored"]:
            block["unscored_score"] = round(float(block["score"]), 3)
            block["score"] = 0.0
            block["approach"] = 0.0
        blocks[probe] = block
        total += block["score"]
    metric = metric_class_diagnostic(half_volume_radius_vector, connectivity_vector, sizes,
                                     connectivity_floor=connectivity_floor)
    metric["withheld_points"] = 0.0
    metric["gate_applied"] = False
    if metric.get("verdict") == "no_metric_structure":
        metric["withheld_points"] = round(total, 3)
        relabelled = False
        for probe in PROBES:
            block = blocks[probe]
            if block["score"]:
                block["withheld_points"] = round(float(block["score"]) + float(block.get("withheld_points") or 0.0), 3)
                block["score"] = 0.0
            if block["bucket"] in ({Bucket.CONVERGED.value} | WITHHELD_SETTLED_BUCKETS):
                block["converged_before_metric_gate"] = True
                block["bucket"] = NO_METRIC_STRUCTURE_BUCKET
                relabelled = True
        metric["gate_applied"] = bool(total > 0 or relabelled)
        total = 0.0
    line, used = GD.line_degrees(mean_degree_vector, giant_mean_degree_vector)
    control = control_family_match(probe_vectors, line, sizes, control_reference,
                                   probe_se_vectors=probe_se_vectors)
    control["line_degree"] = GD.reading(used)
    if control["family"]:
        control["withheld_points"] = round(total, 3)
        bucket = CONTROL_FAMILY_BUCKET_PREFIX + str(control["family"]).upper()
        for probe in PROBES:
            block = blocks[probe]
            if block["score"]:
                block["withheld_points"] = round(float(block["score"]) + float(block.get("withheld_points") or 0.0), 3)
                block["score"] = 0.0
            if block["bucket"] in ({Bucket.CONVERGED.value} | WITHHELD_SETTLED_BUCKETS):
                block["converged_before_control_gate"] = True
                block["bucket"] = bucket
        total = 0.0
    else:
        control["withheld_points"] = 0.0
    density = density_diagnostic(
        mean_degree_vector, sizes,
        rung_buckets=((probe_bucket_vectors or {}).get("d_s")
                      or next((v for v in (probe_bucket_vectors or {}).values() if v), None)))
    if density["flowing"]:
        density["withheld_points"] = round(total, 3)
        for probe in PROBES:
            block = blocks[probe]
            if block["score"]:
                block["withheld_points"] = round(float(block["score"]) + float(block.get("withheld_points") or 0.0), 3)
                block["score"] = 0.0
            if block["bucket"] in ({Bucket.CONVERGED.value} | WITHHELD_SETTLED_BUCKETS) \
                    or str(block["bucket"]).startswith(CONTROL_FAMILY_BUCKET_PREFIX) \
                    or block["bucket"] == NO_METRIC_STRUCTURE_BUCKET:
                block["converged_before_density_gate"] = True
                block["bucket"] = DENSITY_FLOWING_BUCKET
        total = 0.0
    else:
        density["withheld_points"] = 0.0
    blocks["mean_degree"] = score_density_block(density)
    d_s_values = masked((probe_vectors or {}).get("d_s"), (probe_bucket_vectors or {}).get("d_s"))
    return {
        "contract": STABILITY_SCORE_CONTRACT,
        "metric_class": metric,
        "control_family": control,
        "density": density,
        "plateau_break": plateau_reading(sizes or [], d_s_values, (probe_se_vectors or {}).get("d_s") or [],
                                         mean_degree_vector),
        "penalised_probes": sorted(
            probe for probe in PROBES if blocks[probe]["bucket"] in UNSTABLE_BUCKETS),
        "demonstrates_instability": any(
            blocks[probe]["bucket"] in UNSTABLE_BUCKETS for probe in PROBES),
        "blocks": blocks,
        "valid_rungs": {probe: blocks[probe]["valid_rungs"] for probe in PROBES},
        "buckets": {probe: blocks[probe]["bucket"] for probe in PROBES},
    }


def score_phenotype(phenotype: dict, *, floors: dict[str, float | None],
                    floors_by_n: dict[str, dict[int, float]] | None = None,
                    connectivity_floor: float | None = None,
                    control_reference: dict | None = None) -> dict:
    from graph_scale_dynamics.scheduling.limits import DEFAULT_LIMITS
    base = [int(n) for n in (phenotype.get("base_sizes") or [])]
    floor = DEFAULT_LIMITS["connectivity_floor"] if connectivity_floor is None else float(connectivity_floor)
    per_n = phenotype.get("per_n") or {}
    ext_per_n = phenotype.get("extension_per_n") or {}
    extension = [int(n) for n in (phenotype.get("extension_sizes") or [])
                 if not base or int(n) > base[-1]]

    def _column(vector_key: str, ext_key: str, cell_key: str) -> list:
        head = list(phenotype.get(vector_key) or [])
        if len(head) != len(base):
            head = [_finite((per_n.get(str(n)) or {}).get(cell_key)) for n in base]
        tail = list(phenotype.get(ext_key) or [])
        if len(tail) != len(extension):
            tail = [_finite((ext_per_n.get(str(n)) or {}).get(cell_key)) for n in extension]
        return head + tail

    def _probe_column(vector_key: str, ext_key: str, field: str) -> dict:
        head, tail = phenotype.get(vector_key) or {}, phenotype.get(ext_key) or {}

        def _half(stored: dict, rungs: list[int], cells: dict) -> list:
            column = list(stored.get(probe) or [])
            if len(column) == len(rungs):
                return column
            return [((cells.get(str(n)) or {}).get("probes") or {}).get(probe, {}).get(field)
                    for n in rungs]

        out: dict[str, list] = {}
        for probe in set(head) | set(tail) | set(PROBES):
            out[probe] = _half(head, base, per_n) + _half(tail, extension, ext_per_n)
        return out

    sizes = base + extension
    return score_law(_probe_column("probe_vectors", "extension_probe_vectors", "value"),
                     _probe_column("probe_bucket_vectors",
                                   "extension_probe_bucket_vectors", "bucket"),
                     floors=floors,
                     sizes=sizes or None, floors_by_n=floors_by_n,
                     probe_se_vectors=_probe_column("probe_se_vectors",
                                                    "extension_probe_se_vectors", "se"),
                     probe_measured_se_vectors=_probe_column("probe_measured_se_vectors",
                                                             "extension_probe_measured_se_vectors", "measured_se"),
                     connectivity_vector=_column("connected_fraction_vector",
                                                 "extension_connected_fraction_vector",
                                                 "connected_fraction"),
                     connectivity_floor=floor,
                     mean_degree_vector=_column("mean_degree_vector",
                                                "extension_mean_degree_vector", "mean_degree"),
                     giant_mean_degree_vector=GD.phenotype_giant_degrees(phenotype),
                     clustering_vector=_column("clustering_vector",
                                               "extension_clustering_vector", "clustering"),
                     control_reference=control_reference,
                     half_volume_radius_vector=_column("half_volume_radius_vector",
                                                       "extension_half_volume_radius_vector",
                                                       "half_volume_radius"))


def score_rung_rows(rows: list[dict], *, floors: dict[str, float | None],
                    connectivity_floor: float | None = None,
                    floors_by_n: dict[str, dict[int, float]] | None = None,
                    control_reference: dict | None = None) -> dict:
    vectors = {probe: [] for probe in PROBES}
    buckets = {probe: [] for probe in PROBES}
    ses = {probe: [] for probe in PROBES}
    measured = {probe: [] for probe in PROBES}
    degrees, giants, clustering, radii, connectivity = [], [], [], [], []
    for row in rows:
        summary = row.get("summary") or {}
        mean = {k: _finite(v.get("mean")) for k, v in summary.items() if isinstance(v, dict)}
        degrees.append(mean.get("mean_degree"))
        giants.append(mean.get("giant_mean_degree"))
        radii.append(mean.get("half_volume_radius"))
        connectivity.append(mean.get("connected_fraction"))
        clustering.append(mean.get("clustering"))
        floor_failed = (connectivity_floor is not None and connectivity[-1] is not None
                        and connectivity[-1] < float(connectivity_floor))
        refusals = summary.get("probe_refusals") or {}
        for probe in PROBES:
            node = summary.get(probe) if isinstance(summary.get(probe), dict) else None
            value = _finite((node or {}).get("mean"))
            codes = dict(refusals.get(probe) or {})
            entry = {"valid": value is not None}
            if value is None and codes:
                entry["refusal"] = max(sorted(codes), key=lambda c: codes[c])
            bucket = bucket_for_rung(
                entry if (value is not None or codes) else None,
                terminal_classification=row.get("terminal_classification"),
                chains_verdict=row.get("chains_verdict"),
                connectivity_floor_failed=floor_failed,
            )
            vectors[probe].append(value)
            buckets[probe].append(bucket.value if bucket else None)
            ses[probe].append(_finite((node or {}).get("se")))
            measured[probe].append(_finite(summary.get(f"{probe}_measured_se")))
    sizes = [int(row.get("n")) for row in rows if row.get("n") is not None]
    return score_law(vectors, buckets, floors=floors,
                     sizes=sizes if len(sizes) == len(rows) else None, floors_by_n=floors_by_n,
                     probe_se_vectors=ses, mean_degree_vector=degrees, giant_mean_degree_vector=giants,
                     probe_measured_se_vectors=measured,
                     clustering_vector=clustering, control_reference=control_reference,
                     connectivity_vector=connectivity, connectivity_floor=connectivity_floor,
                     half_volume_radius_vector=radii)


def metric_class_population(scored: list[dict]) -> dict:
    classed = [r.get("metric_class") or {} for r in scored]
    have = [m for m in classed if m.get("verdict") in
            ("metric", "no_metric_structure", "undetermined")]
    growth = sorted(float(m["radius_growth"]) for m in classed
                    if m.get("radius_growth") is not None)

    def _at(fraction: float):
        return round(growth[min(len(growth) - 1, int(fraction * len(growth)))], 3) if growth else None

    return {
        "laws_scored": len(scored),
        "laws_with_a_verdict": len(have),
        "logarithmic_radius": sum(1 for m in have if m["verdict"] == "no_metric_structure"),
        "power_law_radius": sum(1 for m in have if m["verdict"] == "metric"),
        "undetermined": sum(1 for m in have if m["verdict"] == "undetermined"),
        "residual_comparison_disagrees": sum(
            1 for m in have if m.get("logarithmic_wins") is not None
            and m["logarithmic_wins"] != (m["verdict"] == "no_metric_structure")),
        "untested": len(classed) - len(have),
        "laws_gated": sum(1 for m in classed if m.get("gate_applied")),
        "points_withheld_total": round(sum(float(m.get("withheld_points") or 0.0)
                                           for m in classed), 1),
        "radius_growth": {"count": len(growth), "min": _at(0.0), "p10": _at(0.10),
                          "median": _at(0.5), "p90": _at(0.90), "max": _at(1.0)},
        "reading": (
            "logarithmic_radius is the count of laws with bounded diameter: the "
            "half-volume radius is fitted better by a logarithm of component size "
            "than by any power of it, so there is no metric dimension to measure "
            "whatever the spectral probe returns. Read radius_growth beside it: "
            "across a 256x increase in volume a plane grows 16x and a small-world "
            "graph grows two to three. This is the verdict the lattice benchmark "
            "turns on"),
    }


def gate_bucket_names() -> tuple[str, ...]:
    families = sorted(CONTROL_FAMILY_BUCKET_PREFIX + name.upper()
                      for name in CONTROL_FAMILY_MEAN_DEGREE)
    return (NO_METRIC_STRUCTURE_BUCKET, DENSITY_FLOWING_BUCKET, *families)


def population_summary(scored: list[dict]) -> dict:
    per_probe = {probe: {**empty_bucket_counts(),
                         **{name: 0 for name in gate_bucket_names()}}
                 for probe in PROBES}
    unaccounted: dict[str, int] = {}
    for s in scored:
        for probe in PROBES:
            bucket = (s.get("buckets") or {}).get(probe)
            if bucket in per_probe[probe]:
                per_probe[probe][bucket] += 1
            elif bucket is not None:
                unaccounted[f"{probe}:{bucket}"] = unaccounted.get(f"{probe}:{bucket}", 0) + 1
    return {
        "laws": len(scored),
        "bucket_counts_by_probe": per_probe,
        "bucket_counts_reconcile": {
            probe: {"counted": sum(counts.values()), "laws": len(scored),
                    "balanced": sum(counts.values()) == len(scored)}
            for probe, counts in per_probe.items()
        },
        "bucket_counts_unaccounted": unaccounted,
        "settled_then_withheld_by_probe": {
            probe: sum(counts.get(name, 0) for name in gate_bucket_names())
            for probe, counts in per_probe.items()
        },
        "settled_then_withheld_reading": (
            "blocks that reached CONVERGED and had their points withheld by the "
            "branching-line, metric-class or control-family gate, so a campaign whose every "
            "settled probe was gated does not read as a campaign in which nothing settled"),
    }


def build_stability_report(phenotypes: list[dict], calibration_table: dict | None,
                           *, connectivity_floor: float | None = None) -> dict:
    floors = noise_floors(calibration_table)
    floors_by_n = noise_floors_by_n(calibration_table)
    reference = control_family_reference(calibration_table)
    rows = []
    for item in phenotypes:
        phenotype = item.get("phenotype") or {}
        if phenotype.get("contract") != BASE_BLOCK_CONTRACT:
            continue
        scored = score_phenotype(phenotype, floors=floors, floors_by_n=floors_by_n,
                                 connectivity_floor=connectivity_floor, control_reference=reference)
        measured_sizes = [int(n) for n in (phenotype.get("base_sizes") or [])
                          if str(n) in (phenotype.get("per_n") or {})]
        measured_sizes += [int(n) for n in (phenotype.get("extension_sizes") or [])
                           if str(n) in (phenotype.get("extension_per_n") or {})]
        rows.append({"candidate_id": str(item.get("candidate_id") or ""),
                     "top_measured_rung": (max(measured_sizes) if measured_sizes else None),
                     **scored})
    rows.sort(key=lambda r: r["candidate_id"])
    skipped = len(phenotypes) - len(rows)
    from graph_scale_dynamics.research import stability_report_parts as parts
    return {
        "contract": STABILITY_SCORE_CONTRACT,
        "definition": parts.definition(),
        "noise_floors": floors,
        "noise_floors_by_n": floors_by_n,
        "tolerance_multiplier": TOLERANCE_MULTIPLIER,
        "population": population_summary(rows),
        "density": {
            "laws_flowing": sum(1 for r in rows if (r.get("density") or {}).get("flowing")),
            "laws_evaluable": sum(1 for r in rows if (r.get("density") or {}).get("evaluable")),
            "points_withheld_total": round(sum(float((r.get("density") or {}).get("withheld_points") or 0.0)
                                               for r in rows), 1),
            "tolerance": MEAN_DEGREE_DRIFT_TOLERANCE,
            "strict_tolerance": MEAN_DEGREE_STRICT_TOLERANCE,
            "criteria": {
                name: sum(1 for r in rows
                          if ((r.get("density") or {}).get("criteria") or {}).get(name))
                for name in sorted({
                    key
                    for r in rows
                    for key in ((r.get("density") or {}).get("criteria") or {})
                })
            },
            "laws_settled": sum(1 for r in rows if (r.get("density") or {}).get("settled")),
            "laws_settled_strict": sum(1 for r in rows
                                       if (r.get("density") or {}).get("settled_strict")),
            "measured_precision_at_the_next_rung": parts.next_rung_precision(phenotypes),
            "reading": ("laws whose mean degree still moves by more than the tolerance between "
                        "their top two rungs have not reached the ensemble limit in which a "
                        "dimension is defined; whatever their probes read there is withheld. "
                        "This is a precondition on the four probes, not a fifth one. "
                        "`laws_flowing` is what the withholding acts on today and it is the "
                        "weakest of the four criteria: it admits four fifths of the population "
                        "at nine points above chance. Nothing here changes the gate; the counts "
                        "and the precisions are published so a change can be argued from them"),
        },
        "plateau_then_break": plateau_population(rows),
        "metric_class": metric_class_population(rows),
        "control_families": {
            "matched": dict(sorted(Counter(str(r["control_family"]["family"]) for r in rows
                                           if (r.get("control_family") or {}).get("family")).items())),
            "points_withheld_total": round(sum(float((r.get("control_family") or {}).get("withheld_points") or 0.0)
                                               for r in rows), 1),
            "reading": "laws that reproduce a calibration family rung for rung; the instrument "
                       "finding a known answer is validation, not discovery",
        },
        "every_law": every_law_table(rows),
        "laws_scored": len(rows),
        "laws_on_pre_253_phenotype_contract": skipped,
        "note": (
            "Laws whose stored phenotype predates rung-phenotype-3 are not "
            "scored; rebuild them (`main.py rebuild-phenotypes --apply`) rather than reading two probes."
        ) if skipped else None,
    }
