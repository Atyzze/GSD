from __future__ import annotations

import json
import math

CONTRACT = "gsd-cost-model-1"

MIN_ATTEMPTS_TO_SCORE = 20


def _operators(signature: str) -> list[str]:
    try:
        terms = json.loads(signature)
    except (TypeError, ValueError):
        return []
    return sorted({str(t.get("op")) for t in terms if isinstance(t, dict) and t.get("op")})


def _fit(rows: list[dict], names: list[str]):
    import numpy as np
    index = {name: i for i, name in enumerate(names)}
    design = np.zeros((len(rows), len(names) + 1), dtype=float)
    target = np.zeros(len(rows), dtype=float)
    weight = np.zeros(len(rows), dtype=float)
    for r, row in enumerate(rows):
        design[r, 0] = 1.0
        for op in row["ops"]:
            design[r, index[op] + 1] = 1.0
        target[r] = math.log(row["rate"])
        weight[r] = math.sqrt(float(row["attempts"]))
    solution, *_ = np.linalg.lstsq(design * weight[:, None], target * weight, rcond=None)
    return float(solution[0]), {name: float(solution[i + 1]) for name, i in index.items()}


def build_cost_model(cost_by_operator: dict, *, holdout_every: int = 4) -> dict:
    raw = (cost_by_operator or {}).get("operators") or []
    rows = []
    for row in raw:
        rate = row.get("wall_seconds_per_attempted_move_proxy")
        ops = _operators(str(row.get("operator_signature") or ""))
        attempts = int(row.get("attempts") or 0)
        if not ops or not isinstance(rate, (int, float)) or rate <= 0 or attempts <= 0:
            continue
        rows.append({"ops": ops, "rate": float(rate), "attempts": attempts,
                     "signature": str(row.get("operator_signature")),
                     "candidates": int(row.get("candidates") or 0)})
    if len(rows) < 12:
        return {"contract": CONTRACT, "available": False,
                "reason": f"{len(rows)} usable operator signatures; a fit needs at least 12"}

    rows.sort(key=lambda r: r["signature"])
    names = sorted({op for row in rows for op in row["ops"]})
    train = [r for i, r in enumerate(rows) if i % holdout_every]
    test = [r for i, r in enumerate(rows) if not i % holdout_every
            and r["attempts"] >= MIN_ATTEMPTS_TO_SCORE]
    if len(train) < len(names) + 2 or not test:
        train, test = rows, []

    intercept, coefficients = _fit(train, names)

    def predict(ops) -> float:
        return math.exp(intercept + sum(coefficients.get(op, 0.0) for op in ops))

    errors = sorted(abs(math.log(r["rate"] / predict(r["ops"]))) for r in test)
    within = lambda f: (sum(1 for e in errors if e <= math.log(f)) / len(errors)) if errors else None
    spread = sorted(r["rate"] for r in rows)

    return {
        "contract": CONTRACT,
        "available": True,
        "target": "wall_seconds_per_attempted_move_proxy",
        "moves": "recorded per attempt (cpu_speed.moves, every chain)",
        "signatures_fitted": len(train),
        "signatures_held_out": len(test),
        "base_rate_per_attempted_move": round(math.exp(intercept), 12),
        "operator_multipliers": {name: round(math.exp(c), 4)
                                 for name, c in sorted(coefficients.items(),
                                                       key=lambda kv: -kv[1])},
        "held_out_accuracy": {
            "median_factor_error": (round(math.exp(errors[len(errors) // 2]), 3)
                                    if errors else None),
            "within_2x": (None if not errors else round(within(2.0), 3)),
            "within_4x": (None if not errors else round(within(4.0), 3)),
            "n": len(errors),
            "basis": ("every 4th signature by sorted operator signature, held out of "
                      "the fit and scored against it; signatures with fewer than "
                      f"{MIN_ATTEMPTS_TO_SCORE} attempts are fitted but not scored"),
        },
        "observed_rate_spread": {
            "min": spread[0], "median": spread[len(spread) // 2], "max": spread[-1],
            "max_over_min": (round(spread[-1] / spread[0], 1) if spread[0] > 0 else None),
        },
        "reading": (
            "`operator_multipliers` is what each term does to the cost of one "
            "attempted move, holding the rest fixed, so a proposed law's price is "
            "the base rate times the product of its terms' multipliers. Read "
            "`held_out_accuracy` before using it: `median_factor_error` of 1.4 "
            "means a typical prediction is within 40% of the truth, on signatures "
            "the fit never saw. This predicts the bill and says nothing about the "
            "science -- a cheap law is not a likely law"),
        "not_a_claim_about": ("whether a law settles, has a dimension, or is worth "
                              "running; only what running it costs per move"),
    }
