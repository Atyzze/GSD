from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass

DIMENSION_TEST_CONTRACT = "gsd-dimension-test-1"
INPUTS = ("n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction")


@dataclass(frozen=True)
class Rule:
    from_n: int = 1024
    piece_at_least: float = 0.95
    degree_above: float = 0.5
    degree_below: float = 15.5
    sizes_at_least: int = 2
    sizes_fitted: int = 3
    reach_exponent_at_least: float = 0.125
    growth_agrees_within: float = 0.4
    d_step_within: float = 0.75


RULE = Rule()


def _value(row: dict, probe: str):
    found = row.get(probe)
    if isinstance(found, dict):
        found = found.get("value")
    return float(found) if isinstance(found, (int, float)) and math.isfinite(found) else None


def usable(rows: list[dict], rule: Rule = RULE) -> list[dict]:
    keep = []
    for row in rows:
        n, degree, piece = row.get("n"), _value(row, "mean_degree"), _value(row, "giant_fraction")
        if n is None or n < rule.from_n or degree is None or piece is None:
            continue
        if degree <= rule.degree_above or degree >= rule.degree_below or piece < rule.piece_at_least:
            continue
        keep.append(row)
    return sorted(keep, key=lambda r: r["n"])


def mass_dimension(row: dict) -> float | None:
    found = [v for v in (_value(row, "d_V"), _value(row, "d_B")) if v is not None]
    return statistics.mean(found) if found else None


def einstein_gap(row: dict) -> float | None:
    d_f, d_s, d_w = mass_dimension(row), _value(row, "d_s"), _value(row, "d_w")
    if d_f is None or d_s is None or d_w is None or d_w <= 0:
        return None
    return abs(d_s - 2.0 * d_f / d_w)


def reach_exponent(rows: list[dict]) -> float | None:
    points = [(math.log(r["n"]), math.log(_value(r, "reach"))) for r in rows if (_value(r, "reach") or 0) > 0]
    if len(points) < 2:
        return None
    xs, ys = [x for x, _ in points], [y for _, y in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    spread = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in points) / spread if spread else None


def signals(rows: list[dict], rule: Rule = RULE) -> dict:
    kept = usable(rows, rule)
    out = {"sizes": [r["n"] for r in kept]}
    if not kept:
        return out
    top = kept[-1]
    fitted = kept[-rule.sizes_fitted:]
    exponent = reach_exponent(fitted)
    d_f = mass_dimension(top)
    out.update({"mass_dimension": d_f, "reach_exponent": exponent,
                "growth_dimension": 1.0 / exponent if exponent and exponent > 0 else None,
                "einstein_gap": einstein_gap(top), "d_s": _value(top, "d_s"), "d_w": _value(top, "d_w")})
    out["growth_gap"] = (abs(out["growth_dimension"] - d_f) / d_f
                         if out["growth_dimension"] is not None and d_f else None)
    previous = mass_dimension(kept[-2]) if len(kept) > 1 else None
    out["d_step"] = abs(d_f - previous) if d_f is not None and previous is not None else None
    return out


def judge_chain(rows: list[dict], rule: Rule = RULE) -> dict:
    found = signals(rows, rule)
    failed = []
    if len(found["sizes"]) < rule.sizes_at_least:
        failed.append("fewer usable sizes than the rule needs")
    else:
        if found["mass_dimension"] is None:
            failed.append("no mass dimension read at the top size")
        if found["reach_exponent"] is None or found["reach_exponent"] < rule.reach_exponent_at_least:
            failed.append("its reach does not grow as a power of N: a small world")
        elif found["mass_dimension"] is not None and (found["growth_gap"] is None
                                                     or found["growth_gap"] > rule.growth_agrees_within):
            failed.append("its reach and its balls disagree on the dimension")
        if found["d_step"] is not None and found["d_step"] > rule.d_step_within:
            failed.append("its mass dimension moves between the last two sizes")
    return {"verdict": "not_dimensional" if failed else "dimensional",
            "d": None if failed else found["mass_dimension"], "why": failed, "signals": found}


def chains(measured: list[dict]) -> dict:
    grouped: dict = defaultdict(list)
    for block in measured:
        for row in block["rows"]:
            if row.get("built"):
                grouped[(block["part"], row["family"], row["seed"])].append(row)
    return grouped


def judge_against(criterion: dict, measured: list[dict], rule: Rule = RULE) -> dict:
    grouped = chains(measured)
    cases = []
    for part in ("training", "held_out"):
        if part not in {block["part"] for block in measured}:
            continue
        for case in criterion[part]["cases"]:
            seeds = []
            for seed in criterion[part]["seeds"]:
                rows = grouped.get((part, case["family"], seed))
                if not rows:
                    continue
                judged = judge_chain(rows, rule)
                band = case.get("d")
                in_band = band is None or (judged["d"] is not None and band[0] <= judged["d"] <= band[1])
                early = []
                if case["verdict"] == "not_dimensional":
                    for size in sorted({r["n"] for r in rows if r["n"] >= 4096}):
                        if judge_chain([r for r in rows if r["n"] <= size], rule)["verdict"] == "dimensional":
                            early.append(size)
                right = judged["verdict"] == case["verdict"] and (case["verdict"] != "dimensional" or in_band)
                seeds.append({"seed": seed, "verdict": judged["verdict"], "d": judged["d"], "why": judged["why"],
                              "signals": judged["signals"], "right": right and not early,
                              "dimensional_early_at": early})
            needed = len(seeds) if part == "training" else 2
            cases.append({"part": part, "family": case["family"], "expected": case["verdict"], "d_band": case.get("d"),
                          "seeds": seeds, "passes": bool(seeds) and sum(s["right"] for s in seeds) >= needed})
    return {"contract": DIMENSION_TEST_CONTRACT, "rule": asdict(rule), "cases": cases,
            "passes": bool(cases) and all(c["passes"] for c in cases)}


def _short(value, digits=2):
    return "" if value is None else f"{value:.{digits}f}"


def render(judged: dict) -> str:
    lines = ["# The dimension test on its known answers", "",
             f"{judged['contract']}; rule: " + ", ".join(f"{k} {v}" for k, v in judged["rule"].items()) + ".", "",
             f"Passes: **{'yes' if judged['passes'] else 'no'}**.", "",
             "| part | family | expected | band | seeds right | d read | reach exponent | growth gap | Einstein gap | why not |",
             "|---|---|---|---|---:|---|---|---|---|---|"]
    for case in judged["cases"]:
        seeds = case["seeds"]
        read = ", ".join(s["verdict"][:3] + ("" if s["d"] is None else f" {s['d']:.2f}") for s in seeds)
        cols = [", ".join(_short(s["signals"].get(key)) for s in seeds)
                for key in ("reach_exponent", "growth_gap", "einstein_gap")]
        why = "; ".join(sorted({w for s in seeds if not s["right"] for w in s["why"]}
                               | {f"dimensional already at {n:,}" for s in seeds for n in s["dimensional_early_at"]}))
        band = "" if case["d_band"] is None else f"{case['d_band'][0]} to {case['d_band'][1]}"
        lines.append(f"| {case['part']} | `{case['family']}` | {case['expected']} | {band} | "
                     f"{sum(s['right'] for s in seeds)} of {len(seeds)} | {read} | {' | '.join(cols)} | {why} |")
    return "\n".join(lines) + "\n"
