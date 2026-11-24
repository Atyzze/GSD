from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
import random
from typing import Iterable

import numpy as np

from graph_scale_dynamics.research.coupling import (
    BETA_MAX, BETA_MIN, REFERENCE_N, coupling_strength,
)
from graph_scale_dynamics.research.hamiltonian_preflight import effective_basis, equilibrium_family
from graph_scale_dynamics.research.numeric import finite as _finite

CARTOGRAPHY_VERSION = "dimensional-cartography-2"
CARTOGRAPHY_ASSESSMENT_MODE = "active"
DEFAULT_METRIC = "d_s"


def _metric_mean(summary: dict | None, metric: str = DEFAULT_METRIC) -> float | None:
    stat = (summary or {}).get(metric)
    if not isinstance(stat, dict):
        return None
    return _finite(stat.get("mean"))


def _metric_se(summary: dict | None, metric: str = DEFAULT_METRIC) -> float | None:
    stat = (summary or {}).get(metric)
    if not isinstance(stat, dict):
        return None
    value = _finite(stat.get("se"))
    return None if value is None or value < 0 else value


def trajectory(rows: Iterable[dict], metric: str = DEFAULT_METRIC) -> list[dict]:
    out = []
    for row in sorted(rows, key=lambda item: int(item.get("n") or 0)):
        mean = _metric_mean(row.get("summary") or {}, metric)
        if mean is None:
            continue
        out.append({"n": int(row["n"]), "value": mean,
                    "se": _metric_se(row.get("summary") or {}, metric)})
    return out


def _signed_log(value: float) -> float:
    return math.copysign(math.log1p(abs(float(value))), float(value))


def coefficient_vector(spec: dict) -> tuple[tuple, np.ndarray]:
    family_id, family_label = equilibrium_family(spec)
    basis = effective_basis(spec)
    structure = tuple(
        (row["op"], json.dumps(row.get("params") or {}, sort_keys=True), row["scale"],
         None if "p" not in row else float(row["p"]))
        for row in basis
    )
    values = np.asarray([_signed_log(float(row["coefficient"])) for row in basis], dtype=float)
    return (family_id, family_label, structure), values


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return math.inf
    return float(np.linalg.norm(a - b) / math.sqrt(float(a.size)))


def choose_checkpoint(observations: list[dict], *, checkpoint_n: int | None = None,
                      min_candidates: int = 80, min_fraction: float = 0.10) -> dict:
    total = max(1, len(observations))
    counts = Counter()
    for row in observations:
        for point in row.get("trajectory") or []:
            counts[int(point["n"])] += 1
    if checkpoint_n is not None:
        count = counts.get(int(checkpoint_n), 0)
        return {
            "n": int(checkpoint_n), "count": count, "total_candidates": len(observations),
            "fraction": count / total,
            "adequate": count >= int(min_candidates) and count / total >= float(min_fraction),
            "counts_by_n": dict(sorted(counts.items())),
        }
    adequate = [n for n, count in counts.items()
                if count >= int(min_candidates) and count / total >= float(min_fraction)]
    chosen = max(adequate) if adequate else (max(counts, default=None))
    count = counts.get(chosen, 0) if chosen is not None else 0
    return {
        "n": chosen, "count": count, "total_candidates": len(observations),
        "fraction": count / total,
        "adequate": bool(chosen in adequate),
        "counts_by_n": dict(sorted(counts.items())),
    }


def build_observations(candidates: Iterable[dict], summaries: dict[str, list[dict]], *,
                       metric: str = DEFAULT_METRIC) -> list[dict]:
    rows = []
    for candidate in candidates:
        points = trajectory(summaries.get(candidate["candidate_id"], []), metric)
        family_key, vector = coefficient_vector(candidate["spec"])
        values = [point["value"] for point in points]
        log_ns = [math.log(float(point["n"])) for point in points]
        if len(points) >= 2:
            x = np.asarray(log_ns, dtype=float)
            y = np.asarray(values, dtype=float)
            slope = float(np.polyfit(x, y, 1)[0])
            latest_drift = float(values[-1] - values[-2])
        else:
            slope = None
            latest_drift = None
        rows.append({
            "candidate_id": candidate["candidate_id"],
            "campaign_id": candidate.get("campaign_id"),
            "state": candidate.get("state"),
            "spec": candidate["spec"],
            "family_id": family_key[0], "family_label": family_key[1],
            "family_structure": family_key[2], "coefficient_vector": vector,
            "trajectory": points, "top_n": (points[-1]["n"] if points else None),
            "latest_value": (points[-1]["value"] if points else None),
            "latest_se": (points[-1]["se"] if points else None),
            "flow_slope_per_log_n": slope,
            "latest_drift": latest_drift,
            "stability_score": candidate.get("stability_score"),
        })
    return rows


def _point_at(row: dict, n: int) -> dict | None:
    for point in row.get("trajectory") or []:
        if int(point["n"]) == int(n):
            return point
    return None


def boundary_pairs(observations: list[dict], checkpoint_n: int, *,
                   k_neighbors: int = 5, limit: int = 128) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in observations:
        point = _point_at(row, checkpoint_n)
        if point is not None:
            grouped[row["family_id"]].append(row)
    found: dict[tuple[str, str], dict] = {}
    for family_rows in grouped.values():
        if len(family_rows) < 2:
            continue
        matrix = np.vstack([row["coefficient_vector"] for row in family_rows])
        for index, row in enumerate(family_rows):
            distances = np.linalg.norm(matrix - matrix[index], axis=1)
            distances[index] = np.inf
            neighbors = np.argsort(distances)[:max(1, int(k_neighbors))]
            a_point = _point_at(row, checkpoint_n)
            for other_index in neighbors:
                other = family_rows[int(other_index)]
                b_point = _point_at(other, checkpoint_n)
                distance = _distance(row["coefficient_vector"], other["coefficient_vector"])
                if not math.isfinite(distance) or a_point is None or b_point is None:
                    continue
                delta = abs(float(a_point["value"]) - float(b_point["value"]))
                gradient = delta / max(0.05, distance)
                ids = tuple(sorted((row["candidate_id"], other["candidate_id"])))
                record = {
                    "a": row["candidate_id"], "b": other["candidate_id"],
                    "family_id": row["family_id"], "family_label": row["family_label"],
                    "checkpoint_n": int(checkpoint_n),
                    "a_value": float(a_point["value"]), "b_value": float(b_point["value"]),
                    "delta": delta, "coordinate_distance": distance,
                    "gradient": gradient,
                    "score": gradient * math.sqrt(max(delta, 1e-12)),
                }
                if ids not in found or record["score"] > found[ids]["score"]:
                    found[ids] = record
    return sorted(found.values(), key=lambda row: row["score"], reverse=True)[:int(limit)]


def flow_edges(observations: list[dict], *, min_rungs: int = 3,
               limit: int = 128) -> list[dict]:
    rows = []
    for row in observations:
        points = row.get("trajectory") or []
        if len(points) < max(2, int(min_rungs)):
            continue
        values = [float(point["value"]) for point in points]
        steps = [values[i + 1] - values[i] for i in range(len(values) - 1)]
        latest = abs(steps[-1])
        curvature = abs(steps[-1] - steps[-2]) if len(steps) >= 2 else 0.0
        slope = abs(float(row.get("flow_slope_per_log_n") or 0.0))
        score = latest + 0.5 * curvature + 0.25 * slope
        rows.append({
            "candidate_id": row["candidate_id"], "family_id": row["family_id"],
            "family_label": row["family_label"], "top_n": row["top_n"],
            "latest_value": row["latest_value"], "latest_abs_drift": latest,
            "curvature": curvature, "abs_flow_slope_per_log_n": slope,
            "score": score,
        })
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:int(limit)]


def _trajectory_rms(a: dict, b: dict, min_common_rungs: int) -> tuple[float, list[int]] | None:
    by_a = {int(point["n"]): float(point["value"]) for point in a.get("trajectory") or []}
    by_b = {int(point["n"]): float(point["value"]) for point in b.get("trajectory") or []}
    common = sorted(set(by_a) & set(by_b))
    if len(common) < int(min_common_rungs):
        return None
    diffs = np.asarray([by_a[n] - by_b[n] for n in common], dtype=float)
    return float(np.sqrt(np.mean(diffs * diffs))), common


def resonance_pairs(observations: list[dict], *, min_common_rungs: int = 3,
                    max_candidates: int = 320, limit: int = 96) -> list[dict]:
    eligible = [row for row in observations if len(row.get("trajectory") or []) >= min_common_rungs]
    eligible.sort(key=lambda row: (len(row["trajectory"]), row["top_n"]), reverse=True)
    eligible = eligible[:max(2, int(max_candidates))]
    rows = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            if a["family_id"] == b["family_id"]:
                continue
            result = _trajectory_rms(a, b, min_common_rungs)
            if result is None:
                continue
            rms, common = result
            depth = math.log2(max(common) / min(common)) if len(common) >= 2 else 0.0
            score = (1.0 + depth) / (0.10 + rms)
            rows.append({
                "a": a["candidate_id"], "b": b["candidate_id"],
                "a_family_id": a["family_id"], "b_family_id": b["family_id"],
                "a_family_label": a["family_label"], "b_family_label": b["family_label"],
                "common_rungs": common, "trajectory_rms": rms,
                "score": score,
            })
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:int(limit)]


def cartography_plan(observations: list[dict], config: dict | None = None) -> dict:
    cfg = {
        "metric": DEFAULT_METRIC,
        "checkpoint_n": None,
        "min_checkpoint_candidates": 80,
        "min_checkpoint_fraction": 0.10,
        "k_neighbors": 5,
        "max_anchor_count": 128,
        "min_common_rungs": 3,
        "resonance_max_candidates": 320,
    } | (config or {})
    checkpoint = choose_checkpoint(
        observations,
        checkpoint_n=cfg.get("checkpoint_n"),
        min_candidates=int(cfg["min_checkpoint_candidates"]),
        min_fraction=float(cfg["min_checkpoint_fraction"]),
    )
    if checkpoint["n"] is None:
        return {
            "version": CARTOGRAPHY_VERSION, "status": "INSUFFICIENT_EVIDENCE",
            "reason": "no valid spectral-dimension estimates exist yet",
            "checkpoint": checkpoint, "boundary_pairs": [], "flow_edges": [],
            "resonance_pairs": [],
        }
    boundaries = boundary_pairs(
        observations, int(checkpoint["n"]), k_neighbors=int(cfg["k_neighbors"]),
        limit=int(cfg["max_anchor_count"]),
    )
    edges = flow_edges(observations, min_rungs=int(cfg["min_common_rungs"]),
                       limit=int(cfg["max_anchor_count"]))
    resonances = resonance_pairs(
        observations, min_common_rungs=int(cfg["min_common_rungs"]),
        max_candidates=int(cfg["resonance_max_candidates"]),
        limit=int(cfg["max_anchor_count"]),
    )
    adequate = bool(checkpoint["adequate"] and (boundaries or edges or resonances))
    reason = (
        "fixed-rung map has enough support for local cartography"
        if adequate else
        "map evidence is not yet adequate for a local boundary probe; no generic search fallback is allowed"
    )
    return {
        "version": CARTOGRAPHY_VERSION,
        "status": "READY" if adequate else "INSUFFICIENT_EVIDENCE",
        "reason": reason, "checkpoint": checkpoint,
        "boundary_pairs": boundaries, "flow_edges": edges,
        "resonance_pairs": resonances,
    }


def local_perturbation(spec: dict, rng: random.Random, *, sigma: float = 0.12,
                       allow_discrete_step: bool = False) -> tuple[dict, dict]:
    child = json.loads(json.dumps(spec))
    terms = child.get("terms") or []
    axes: list[tuple[str, int | None]] = [("beta", None)]
    axes.extend(("coefficient", index) for index in range(len(terms)))
    if allow_discrete_step:
        axes.extend(("power", index) for index, term in enumerate(terms)
                    if (term.get("coeff") or {}).get("scale") == "power")
        axes.extend(("anchor", index) for index, term in enumerate(terms)
                    if term.get("op") in {"degree_anchor", "degree_anchor_abs"})
    axis, index = rng.choice(axes)
    detail = {"axis": axis, "index": index, "sigma": float(sigma)}
    if axis == "beta":
        old = float((child.get("dynamics") or {}).get("beta", 1.0))
        new = min(BETA_MAX, max(BETA_MIN, old * math.exp(rng.gauss(0.0, sigma))))
        child["dynamics"]["beta"] = float(f"{new:.8g}")
        detail.update({"old": old, "new": child["dynamics"]["beta"]})
    elif axis == "coefficient":
        coeff = terms[int(index)]["coeff"]
        old = float(coeff.get("c0") or 0.0)
        factor = math.exp(rng.gauss(0.0, sigma))
        new = old * factor
        if abs(new) < 1e-9:
            new = math.copysign(1e-9, old if old else 1.0)
        coeff["c0"] = float(f"{new:.8g}")
        detail.update({"old": old, "new": coeff["c0"]})
    elif axis == "power":
        coeff = terms[int(index)]["coeff"]
        old = float(coeff.get("p") or 0.0)
        new = min(2.0, max(-2.0, old + rng.choice((-1.0, 1.0)) * max(0.05, sigma)))
        coeff["p"] = float(f"{new:.8g}")
        detail.update({"old": old, "new": coeff["p"]})
    else:
        params = terms[int(index)].setdefault("params", {})
        old = int(params.get("k") or 2)
        direction = rng.choice((-1, 1))
        new = min(32, max(2, old + direction))
        if new == old:
            new = min(32, max(2, old - direction))
        params["k"] = int(new)
        detail.update({"old": old, "new": new})

    strength = coupling_strength(child, REFERENCE_N)
    detail["coupling_strength"] = float(strength)
    detail["declared_sweeps"] = int((child.get("dynamics") or {}).get("sweeps") or 0)
    return child, detail
