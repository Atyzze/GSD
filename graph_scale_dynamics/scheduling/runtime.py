from __future__ import annotations
import math
import statistics


def observed_profile(conn, *, campaign_id: str | None = None,
                     candidate_id: str | None = None,
                     nonterminal_only: bool = False) -> dict[int, float]:
    clauses = ["a.exit_code = 0", "a.wall_seconds IS NOT NULL", "j.kind='simulate'"]
    params: list[object] = []
    joins = ""
    if campaign_id is not None:
        clauses.append("j.campaign_id=?")
        params.append(campaign_id)
    if candidate_id is not None:
        clauses.append("j.candidate_id=?")
        params.append(candidate_id)
    if nonterminal_only:
        from graph_scale_dynamics.db.repo import TERMINAL_STATES
        joins += (
            " JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
        )
        marks = ",".join("?" for _ in TERMINAL_STATES)
        clauses.append(f"cc.state NOT IN ({marks})")
        params.extend(TERMINAL_STATES)
    rows = conn.execute(
        "SELECT j.n AS n, a.wall_seconds AS w FROM attempts a "
        "JOIN jobs j ON j.job_id = a.job_id " + joins +
        "WHERE " + " AND ".join(clauses), tuple(params)).fetchall()
    by_n: dict[int, list[float]] = {}
    for row in rows:
        by_n.setdefault(int(row["n"]), []).append(float(row["w"]))
    return {n: statistics.median(walls) for n, walls in sorted(by_n.items())}


MIN_COST_EXPONENT = 0.25
MAX_COST_EXPONENT = 2.0
EXTRAPOLATION_FACTOR = 4
MAX_EXTRAPOLATION_STEPS = 2


def power_fit(profile: dict[int, float]) -> tuple[float, float] | None:
    points = [(n, w) for n, w in profile.items() if w > 0]
    if len(points) < 2:
        return None
    xs = [math.log(n) for n, _ in points]
    ys = [math.log(w) for _, w in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    b = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    a = math.exp(mean_y - b * mean_x)
    return a, b


def predict_wall(profile: dict[int, float], n: int, multiplier: int = 1) -> float | None:
    if n in profile:
        return profile[n] * multiplier
    fit = power_fit(profile)
    if fit is None:
        return None
    observed = [size for size, wall in profile.items() if wall > 0]
    if not observed:
        return None
    largest = max(observed)
    if n > largest * (EXTRAPOLATION_FACTOR ** MAX_EXTRAPOLATION_STEPS):
        return None
    a, b = fit
    b = max(MIN_COST_EXPONENT, min(MAX_COST_EXPONENT, float(b)))
    a = max(0.0, float(a))
    predicted = a * (n ** b) * multiplier
    floor = max(profile[size] for size in observed) * multiplier
    return max(predicted, floor)


def observed_analysis_profile(conn) -> dict[int, float]:
    rows = conn.execute(
        "SELECT n,wall_seconds AS w FROM analysis_queue "
        "WHERE status='done' AND wall_seconds IS NOT NULL"
    ).fetchall()
    by_n: dict[int, list[float]] = {}
    for row in rows:
        by_n.setdefault(int(row["n"]), []).append(float(row["w"]))
    return {n: statistics.median(walls) for n, walls in sorted(by_n.items())}
