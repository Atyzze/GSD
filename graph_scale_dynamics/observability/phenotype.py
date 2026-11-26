from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "resources" / "catalogue" / "phenotype.json"


@lru_cache(maxsize=1)
def rule() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def _line(xs: list[float], ys: list[float], ws: list[float]) -> tuple[float, float]:
    total = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs, strict=True)) / total
    my = sum(w * y for w, y in zip(ws, ys, strict=True)) / total
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs, strict=True))
    if sxx == 0:
        return my, 0.0
    slope = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys, strict=True)) / sxx
    return my - slope * mx, slope


def _relative_rms(values: list[float], predicted: list[float], ws: list[float]) -> float:
    terms = [w * ((value - guess) / value) ** 2 if value else w * (value - guess) ** 2
             for value, guess, w in zip(values, predicted, ws, strict=True)]
    return math.sqrt(sum(terms) / sum(ws))


def fit(series) -> dict:
    found = rule()
    points = sorted((int(n), float(value), float(weight or 1.0)) for n, value, weight in series
                    if value is not None and math.isfinite(float(value)) and int(n) >= found["from_n"])
    if len(points) < found["least_sizes"]:
        return {"form": None, "sizes": len(points), "readings": sum(p[2] for p in points)}
    ns, values, ws = [p[0] for p in points], [p[1] for p in points], [p[2] for p in points]
    readings = sum(ws)
    mean = sum(w * v for w, v in zip(ws, values, strict=True)) / readings
    spread = _relative_rms(values, [mean] * len(values), ws)
    base = {"sizes": len(points), "readings": readings, "from_n": ns[0], "to_n": ns[-1]}
    if spread <= found["constant_within"]:
        return dict(base, form="constant", a=mean, b=0.0, residual=spread)
    logs = [math.log(n) for n in ns]
    log_a, log_b = _line(logs, values, ws)
    log_residual = _relative_rms(values, [log_a + log_b * x for x in logs], ws)
    if all(v > 0 for v in values):
        power_c, power_b = _line(logs, [math.log(v) for v in values], ws)
        power_residual = _relative_rms(values, [math.exp(power_c + power_b * x) for x in logs], ws)
        if power_residual < log_residual:
            return dict(base, form="power", a=math.exp(power_c), b=power_b, residual=power_residual)
    return dict(base, form="log", a=log_a, b=log_b, residual=log_residual)


def reach_band(found: dict) -> str | None:
    if found.get("form") == "log":
        return "reach as log N, an expander or a tree"
    if found.get("form") == "constant":
        return "reach nearly flat in N"
    if found.get("form") != "power":
        return None
    for low, high, words in rule()["reach_bands"]:
        if low <= found["b"] < high:
            return words
    return "reach faster than N"


def categories(phenotype: dict) -> list[str]:
    out = []
    for start, quantities in sorted(phenotype.items()):
        for quantity, found in sorted(quantities.items()):
            if found.get("form") is None:
                continue
            if quantity == "reach":
                band = reach_band(found)
                if band:
                    out.append(band)
            elif found["form"] == "constant":
                out.append(f"{quantity} constant")
            else:
                out.append(f"{quantity} {'rising' if found['b'] > 0 else 'falling'} as {found['form']}")
    return sorted(set(out))


def of_series(by_start: dict[str, dict[str, list]]) -> dict:
    return {start: {quantity: fit(series) for quantity, series in quantities.items()}
            for start, quantities in by_start.items()}


def alike(a: dict, b: dict) -> float:
    shared = set(categories(a)) & set(categories(b))
    either = set(categories(a)) | set(categories(b))
    return len(shared) / len(either) if either else 0.0


def nearest_seen(phenotype: dict, seen: dict[str, dict]) -> tuple[str | None, float]:
    best, score = None, 0.0
    for name, other in sorted(seen.items()):
        found = alike(phenotype, other)
        if found > score:
            best, score = name, found
    return best, round(score, 3)
