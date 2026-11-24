from __future__ import annotations

import math
import random
from collections import defaultdict

STRATA_CONTRACT = "gsd-strata-1"
GRID_STRATA = "strata"
ZERO_T, FINITE_T = "zeroT", "finiteT"
DEGREE_ONLY, SEES_MORE = "degree-only", "sees more"
FEW_TERMS, MANY_TERMS = "1-2 terms", "3-4 terms"
STRATA = tuple(f"{t}/{k}/{c}" for t in (ZERO_T, FINITE_T) for k in (SEES_MORE, DEGREE_ONLY)
               for c in (MANY_TERMS, FEW_TERMS))
VALID_OUTCOMES = frozenset({"admitted", "set_aside", "duplicate_law", "duplicate_identity"})
SET_ASIDE = "set_aside"


def stratum_of(law: dict) -> str:
    from graph_scale_dynamics.research.degree_prediction import KIND_DEGREES, law_kind
    dynamics = (law or {}).get("dynamics") or {}
    temperature = ZERO_T if bool(dynamics.get("zero_temperature")) else FINITE_T
    kind = DEGREE_ONLY if law_kind(law) == KIND_DEGREES else SEES_MORE
    count = FEW_TERMS if len((law or {}).get("terms") or []) <= 2 else MANY_TERMS
    return f"{temperature}/{kind}/{count}"


def allocation_of(grid: dict | None) -> dict[str, float] | None:
    declared = ((grid or {}).get(GRID_STRATA) or {}).get("allocation") if isinstance(grid, dict) else None
    if not declared:
        return None
    total = sum(float(declared.get(h, 0.0)) for h in STRATA)
    if not total > 0:
        raise ValueError("a strata allocation needs a positive weight (`strata_problems` refuses the grid)")
    return {h: float(declared.get(h, 0.0)) / total for h in STRATA if float(declared.get(h, 0.0)) > 0.0}


def draw_stratum(rng: random.Random, allocation: dict[str, float]) -> str:
    u = rng.random()
    cumulative = 0.0
    last = None
    for h in STRATA:
        weight = allocation.get(h, 0.0)
        if weight <= 0.0:
            continue
        last = h
        cumulative += weight
        if u < cumulative:
            return h
    return last


def strata_problems(grid: dict, whitelist: list[str] | None = None) -> list[str]:
    where = f"search_policy.grid.{GRID_STRATA}"
    entry = grid.get(GRID_STRATA)
    if not isinstance(entry, dict) or not isinstance(entry.get("allocation"), dict) or not entry["allocation"]:
        return [f"{where} must be {{\"allocation\": {{stratum: weight}}}} over {list(STRATA)}"]
    allocation = entry["allocation"]
    problems = []
    unknown = sorted(set(allocation) - set(STRATA))
    if unknown:
        problems.append(f"{where}.allocation names unknown strata {unknown}; the strata are {list(STRATA)}")
    weights = [allocation[h] for h in allocation if h in STRATA]
    if not all(isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and w >= 0
               for w in weights) or not sum(float(w) for w in weights if isinstance(w, (int, float))) > 0:
        problems.append(f"{where}.allocation weights must be non-negative numbers with a positive sum")
        return problems
    temperatures = {bool(v) for v in (grid.get("zero_temperature") or [False])}
    counts = {int(c) for c in (grid.get("term_counts") or []) if isinstance(c, int)}
    for h, weight in allocation.items():
        if h not in STRATA or not float(weight) > 0:
            continue
        temperature, kind, count = h.split("/")
        if (temperature == ZERO_T) not in temperatures:
            problems.append(f"{where}: {h} has weight but the grid's zero_temperature never draws it")
        if counts and not counts & ({1, 2} if count == FEW_TERMS else {3, 4, 5, 6, 7, 8}):
            problems.append(f"{where}: {h} has weight but the grid's term_counts never draw it")
        if whitelist is not None and kind == SEES_MORE:
            from graph_scale_dynamics.research.degree_prediction import DEGREE_OPS
            if not set(whitelist) - set(DEGREE_OPS):
                problems.append(f"{where}: {h} has weight but every selected term sees only degrees")
    if set(entry) - {"allocation", "source"}:
        problems.append(f"{where} may declare only allocation and source")
    return problems


def _stratum(row: dict) -> str:
    return str(row["stratum"]) if row.get("stratum") else stratum_of(row.get("law") or {})


def _valid_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows
            if str(row.get("outcome")) in VALID_OUTCOMES or str(row.get("outcome")).startswith("predicted:")]


def stratum_shares(rows: list[dict]) -> dict:
    valid = _valid_rows(rows)
    by_stream: dict = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for row in valid:
        h = _stratum(row)
        by_stream[row.get("stream_index", 0)][h] += 1
        totals[h] += 1
    n = len(valid)
    out = {"contract": STRATA_CONTRACT, "valid_draws": n, "streams": len(by_stream), "strata": {}}
    if not n:
        return out
    clusters = len(by_stream)
    correction = clusters / (clusters - 1) if clusters > 1 else float("nan")
    for h in STRATA:
        share = totals[h] / n
        squares = sum((counts.get(h, 0) - share * sum(counts.values())) ** 2 for counts in by_stream.values())
        se = math.sqrt(correction * squares) / n if clusters > 1 else float("nan")
        out["strata"][h] = {"draws": totals[h], "share": share, "se": se}
    return out


def reweighted_rate(rows: list[dict], counts: dict[str, tuple[int, int]]) -> dict:
    shares = stratum_shares(rows)
    weights = {h: row["share"] for h, row in shares["strata"].items() if row["share"] > 0}
    uncovered = sorted(h for h in weights if int((counts.get(h) or (0, 0))[1]) <= 0)
    by_stratum = {}
    for h, (events, laws) in counts.items():
        if int(laws) > 0:
            by_stratum[h] = {"events": int(events), "laws": int(laws), "rate": int(events) / int(laws),
                             "share": weights.get(h, 0.0)}
    if uncovered or not weights:
        return {"contract": STRATA_CONTRACT, "rate": None, "se": None, "uncovered": uncovered,
                "by_stratum": by_stratum, "valid_draws": shares["valid_draws"]}
    rate = sum(weights[h] * by_stratum[h]["rate"] for h in weights)
    binomial = sum(weights[h] ** 2 * by_stratum[h]["rate"] * (1 - by_stratum[h]["rate"]) / by_stratum[h]["laws"]
                   for h in weights)
    valid = _valid_rows(rows)
    n = len(valid)
    per_stream: dict = defaultdict(lambda: [0.0, 0])
    for row in valid:
        h = _stratum(row)
        entry = per_stream[row.get("stream_index", 0)]
        entry[0] += (by_stratum[h]["rate"] if h in by_stratum else 0.0)
        entry[1] += 1
    clusters = len(per_stream)
    if clusters > 1:
        squares = sum((total - rate * size) ** 2 for total, size in per_stream.values())
        share_part = clusters / (clusters - 1) * squares / (n * n)
    else:
        share_part = float("nan")
    return {"contract": STRATA_CONTRACT, "rate": rate, "se": math.sqrt(binomial + share_part),
            "se_rates": math.sqrt(binomial), "se_shares": math.sqrt(share_part) if share_part == share_part else None,
            "uncovered": [], "by_stratum": by_stratum, "valid_draws": n}
