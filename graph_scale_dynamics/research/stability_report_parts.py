from __future__ import annotations

from collections import Counter

NEXT_RUNG_POPULATION = "laws whose top rung with a mean degree is past the base block, with three rungs below it"


def definition() -> dict:
    from graph_scale_dynamics.research import stability_score as S
    return {
        "contract": S.STABILITY_SCORE_CONTRACT,
        "blocks": "each probe's and the mean degree's settling over the law's valid rungs, its bucket and the gates",
        "not_in_blocks": ["probe magnitude", "agreement between probes", "Einstein relation"],
        "zero_rule": (
            "A block has no points when it has not demonstrated stability, whether it was "
            "never attempted, degraded with N, or is expanding. The bucket says which."
        ),
    }


def _ladder(phenotype: dict) -> list[tuple[float, int]]:
    from graph_scale_dynamics.research.numeric import finite
    from graph_scale_dynamics.research.stability_score import DENSITY_CLAMPED_BUCKETS
    out = []
    base = [int(n) for n in phenotype.get("base_sizes") or []]
    halves = (("", base, "per_n"),
              ("extension_", [int(n) for n in phenotype.get("extension_sizes") or [] if not base or int(n) > base[-1]],
               "extension_per_n"))
    for prefix, rungs, cells_key in halves:
        cells = phenotype.get(cells_key) or {}
        degrees = list(phenotype.get(f"{prefix}mean_degree_vector") or [])
        if len(degrees) != len(rungs):
            degrees = [(cells.get(str(n)) or {}).get("mean_degree") for n in rungs]
        buckets = list((phenotype.get(f"{prefix}probe_bucket_vectors") or {}).get("d_s") or [])
        if len(buckets) != len(rungs):
            buckets = [((((cells.get(str(n)) or {}).get("probes") or {}).get("d_s")) or {}).get("bucket")
                       for n in rungs]
        for n, degree, bucket in zip(rungs, degrees, buckets, strict=True):
            degree = finite(degree)
            if degree is not None and degree > 0 and str(bucket or "") not in DENSITY_CLAMPED_BUCKETS:
                out.append((float(degree), n))
    return out


def next_rung_precision(phenotypes: list[dict]) -> dict:
    from graph_scale_dynamics.research.stability_score import (
        DENSITY_MIN_RUNGS, MEAN_DEGREE_DRIFT_TOLERANCE, density_diagnostic)
    met, held = Counter(), Counter()
    laws = truly = 0
    steps = Counter()
    for item in phenotypes:
        phenotype = item.get("phenotype") or {}
        base = {int(n) for n in phenotype.get("base_sizes") or []}
        ladder = _ladder(phenotype)
        if len(ladder) < DENSITY_MIN_RUNGS + 1 or ladder[-1][1] in base:
            continue
        below = density_diagnostic([d for d, _ in ladder[:-1]], [n for _, n in ladder[:-1]])
        if not below.get("evaluable"):
            continue
        (previous, n_previous), (top, n_top) = ladder[-2], ladder[-1]
        settled = abs(top - previous) / abs(previous) < MEAN_DEGREE_DRIFT_TOLERANCE
        laws += 1
        truly += int(settled)
        steps[f"{n_previous}->{n_top}"] += 1
        criteria = dict(below.get("criteria") or {}, settled=below.get("settled"),
                        settled_strict=below.get("settled_strict"))
        for name, value in criteria.items():
            if value:
                met[name] += 1
                held[name] += int(settled)
    names = sorted(set(met) | {"not_flowing", "within_tolerance", "settled", "settled_strict"})
    return {
        "basis": (f"this campaign's {laws} {NEXT_RUNG_POPULATION}: each criterion read on the rungs below the top, "
                  f"truly settled meaning mean degree then moved under {100 * MEAN_DEGREE_DRIFT_TOLERANCE:g}% to "
                  f"the top rung, which {truly} of {laws} did" if laws else
                  f"no {NEXT_RUNG_POPULATION} in this campaign: no precision is measured"),
        "laws": laws,
        "truly_settled": truly,
        "steps": dict(sorted(steps.items())),
        "base_rate": round(truly / laws, 3) if laws else None,
        **{name: (round(held[name] / met[name], 3) if met[name] else None) for name in names},
        "laws_meeting": {name: met[name] for name in names},
    }
