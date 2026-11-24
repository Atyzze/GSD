from __future__ import annotations

from collections import defaultdict

CURVATURE_TEST_CONTRACT = "gsd-curvature-test-1"
COMPARED_AT = 4096
OUTCOME_AT = 65536


def kappa_by_law(measurements: list[dict] | None) -> dict:
    latest: dict = {}
    for row in measurements or []:
        if row.get("n") is None:
            continue
        key = (str(row.get("candidate_id")), int(row["n"]), row.get("seed"))
        if key not in latest or str(row.get("created_utc") or "") >= str(latest[key].get("created_utc") or ""):
            latest[key] = row
    values: dict = defaultdict(lambda: defaultdict(list))
    for (law, n, _seed), row in latest.items():
        reading = (((row.get("metrics") or {}).get("curvature") or {}).get("empty")) or {}
        if reading.get("measured") and isinstance(reading.get("mean"), (int, float)):
            values[law][n].append(float(reading["mean"]))
    return {law: {n: round(sum(v) / len(v), 5) for n, v in sorted(by_n.items())} for law, by_n in values.items()}


def outcome_by_law(measurements: list[dict] | None, *, outcome_at: int = OUTCOME_AT) -> dict:
    from graph_scale_dynamics.research.structure_reading import law_structure
    by_law: dict = defaultdict(list)
    for row in measurements or []:
        if row.get("n") is not None and int(row["n"]) <= outcome_at:
            by_law[str(row.get("candidate_id"))].append(row)
    return {law: law_structure(rows).get("finite_dimension") for law, rows in by_law.items()
            if any(int(r["n"]) == outcome_at for r in rows)}


def auc(scores: list[float], outcomes: list[bool]) -> float | None:
    positive = [s for s, o in zip(scores, outcomes, strict=True) if o]
    negative = [s for s, o in zip(scores, outcomes, strict=True) if not o]
    if not positive or not negative:
        return None
    wins = sum((p > q) + 0.5 * (p == q) for p in positive for q in negative)
    return round(wins / (len(positive) * len(negative)), 4)


def judge(rows: list[dict], rule: dict) -> dict:
    at = str(COMPARED_AT)
    pairs = [(float((row.get("kappa") or {})[at]), float((row.get("mean_degree") or {})[at]),
              bool(row["finite_at_65536"]))
             for row in rows
             if at in (row.get("kappa") or {}) and at in (row.get("mean_degree") or {})
             and row.get("finite_at_65536") is not None]
    finite = sum(1 for _, _, o in pairs if o)
    out = {"laws": len(pairs), "finite": finite, "not_finite": len(pairs) - finite,
           "auc_curvature": auc([-abs(k) for k, _, _ in pairs], [o for _, _, o in pairs]),
           "auc_mean_degree": auc([-abs(d - 2.0) for _, d, _ in pairs], [o for _, _, o in pairs])}
    if finite < int(rule["min_finite"]) or out["not_finite"] < int(rule["min_not_finite"]):
        out.update(verdict="NOT YET", beyond_degree="NOT YET")
        return out
    out["verdict"] = "HELD" if out["auc_curvature"] >= float(rule["auc_at_least"]) else "DID NOT HOLD"
    out["beyond_degree"] = ("YES" if out["auc_curvature"] >= out["auc_mean_degree"] + float(rule["beyond_degree_by"])
                            else "NO")
    return out
