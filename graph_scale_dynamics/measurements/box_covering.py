from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.measurements.fits import exponential_is_better, line

BOX_COVERING_CONTRACT = "gsd-box-covering-2"

BOX_COVERING_EXPONENT = "box_covering_exponent"
BOX_COVERING_ALIAS = "d_B"

SMALLEST_RADIUS = 3
LARGEST_BALL_SHARE = 0.125
MIN_BOX_RADII = 4
MAX_BOX_RADII = 16
COVERS_A_RADIUS = 3


def window_radii(mean_ball, n_component: int, settled_from: int = 1) -> list[int]:
    ball = np.asarray(mean_ball, dtype=float)
    first = max(SMALLEST_RADIUS, int(settled_from))
    top = SMALLEST_RADIUS - 1
    while top + 1 < len(ball) and ball[top + 1] <= LARGEST_BALL_SHARE * n_component:
        top += 1
    if top < first:
        return []
    if top - first + 1 <= MAX_BOX_RADII:
        return list(range(first, top + 1))
    return sorted({int(round(value)) for value in np.geomspace(first, top, MAX_BOX_RADII)})


def _bfs_ball(adj, source: int, radius: int, covered: np.ndarray) -> list[int]:
    if radius <= 0:
        return [source]
    seen = {source}
    frontier = [source]
    members = [source]
    for _ in range(radius):
        nxt = []
        for vertex in frontier:
            for neighbour in adj[vertex]:
                neighbour = int(neighbour)
                if neighbour not in seen:
                    seen.add(neighbour)
                    nxt.append(neighbour)
                    if not covered[neighbour]:
                        members.append(neighbour)
        if not nxt:
            break
        frontier = nxt
    return members


def greedy_box_centres(adj, component: np.ndarray, radius: int, rng: np.random.Generator) -> list[int]:
    order = np.array(component, dtype=np.int64)
    rng.shuffle(order)

    max_index = int(order.max()) + 1 if len(order) else 1
    covered = np.zeros(max_index, dtype=bool)
    in_component = np.zeros(max_index, dtype=bool)
    in_component[order] = True

    centres = []
    for seed in order:
        seed = int(seed)
        if covered[seed]:
            continue
        centres.append(seed)
        for member in _bfs_ball(adj, seed, radius, covered):
            if in_component[member]:
                covered[member] = True
    return centres


def greedy_box_cover(adj, component: np.ndarray, radius: int, rng: np.random.Generator) -> int:
    return len(greedy_box_centres(adj, component, radius, rng))


def box_covering_profile(adj, component: np.ndarray, rng: np.random.Generator, mean_ball,
                         *, covers: int = COVERS_A_RADIUS, settled_from: int = 1) -> dict:
    n_component = len(component)
    radii = window_radii(mean_ball, n_component, settled_from)
    if len(radii) < MIN_BOX_RADII:
        first = max(SMALLEST_RADIUS, int(settled_from))
        return {"valid": False, "refusal": "WINDOW_TOO_SHORT",
                "reason": (f"{len(radii)} radii between a box {2 * first + 1} nodes across"
                           + (", where the balls' exponent has settled," if first > SMALLEST_RADIUS else "")
                           + f" and a ball that holds {LARGEST_BALL_SHARE:g} of the component; need {MIN_BOX_RADII}"),
                "radii": radii}
    counted = [[greedy_box_cover(adj, component, radius, rng) for _ in range(covers)] for radius in radii]
    return {"valid": True, "radii": radii,
            "box_counts": [float(np.mean(row)) for row in counted],
            "box_count_sd": [float(np.std(row, ddof=1)) if len(row) > 1 else 0.0 for row in counted],
            "covers": int(covers), "n_component": int(n_component)}


def fit_box_dimension(profile: dict) -> dict:
    if not profile.get("valid"):
        return {"valid": False, "refusal": profile.get("refusal") or "WINDOW_TOO_SHORT",
                "reason": profile.get("reason", "no usable profile")}
    radii = np.asarray(profile["radii"], dtype=float)
    counts = np.asarray(profile["box_counts"], dtype=float)
    sd = np.asarray(profile["box_count_sd"], dtype=float)
    covers = max(1, int(profile.get("covers") or 1))
    width = 2.0 * radii + 1.0
    x = np.log(width)
    fitted = line(x, np.log(counts))
    against = exponential_is_better(width, np.log(counts))
    noise_a_box = float(np.mean(sd ** 2 / np.maximum(counts, 1e-12)))
    relative_variance = noise_a_box / np.maximum(counts, 1e-12) / covers
    centred = x - x.mean()
    se_of_the_covers = math.sqrt(float(np.sum(centred ** 2 * relative_variance))) / float(np.sum(centred ** 2))
    se_of_the_line = fitted["rms"] * math.sqrt(len(x) / max(1, len(x) - 2)) / math.sqrt(float(np.sum(centred ** 2)))
    se = max(se_of_the_covers, se_of_the_line)
    power_law = not against["exponential"]
    return {
        "valid": True,
        "box_covering_exponent": -fitted["slope"],
        "se": se,
        "slope": fitted["slope"],
        "radii_used": [int(r) for r in radii],
        "window_radii": [int(radii[0]), int(radii[-1])],
        "points": int(len(radii)),
        "power_law_rms": against["power_law_rms"],
        "exponential_rms": against["exponential_rms"],
        "delta_aicc": against["delta_aicc"],
        "power_law_preferred": bool(power_law),
        "power_law_precondition": "supported" if power_law else "unsupported",
        "reason": (
            None if power_law else
            "box counts fall exponentially with radius; no finite box dimension "
            "exists and the fitted exponent must not be read as one"
        ),
        "contract": BOX_COVERING_CONTRACT,
    }


def box_covering_dimension(adj, component: np.ndarray, rng: np.random.Generator, mean_ball, **kwargs) -> dict:
    return fit_box_dimension(box_covering_profile(adj, component, rng, mean_ball, **kwargs))


CONCORDANT = "DIMENSION_CHANNELS_CONCORDANT"
DISCORDANT = "DIMENSION_CHANNELS_DISCORDANT"
CONCORDANCE_UNRESOLVED = "DIMENSION_CONCORDANCE_UNRESOLVED"


def dimension_concordance(*, spectral=None, distance_volume=None,
                          box_covering=None, tolerance: float = 0.5) -> dict:
    channels = {
        "spectral_dimension_estimate": spectral,
        "distance_volume_exponent": distance_volume,
        BOX_COVERING_EXPONENT: box_covering,
    }
    measured = {
        name: float(value) for name, value in channels.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value))
    }

    if len(measured) < 2:
        return {
            "contract": BOX_COVERING_CONTRACT,
            "verdict": CONCORDANCE_UNRESOLVED,
            "channels": measured,
            "reason": "at least two measured channels are required to compare",
        }

    values = list(measured.values())
    spread = max(values) - min(values)
    verdict = CONCORDANT if spread <= tolerance else DISCORDANT

    pairwise = {}
    names = sorted(measured)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            pairwise[f"{left}__vs__{right}"] = measured[left] - measured[right]

    return {
        "contract": BOX_COVERING_CONTRACT,
        "verdict": verdict,
        "channels": measured,
        "channels_measured": len(measured),
        "spread": spread,
        "tolerance": tolerance,
        "pairwise_gaps": pairwise,
        "reason": (
            f"channel spread {spread:.4f} <= {tolerance}: independent "
            "constructions agree"
            if verdict == CONCORDANT else
            f"channel spread {spread:.4f} > {tolerance}: independent "
            "constructions disagree, which is itself a finding about the space"
        ),
    }
