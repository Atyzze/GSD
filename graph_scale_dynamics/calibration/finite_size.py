from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

CONTRACT = "gsd-finite-size-tolerance-1"

FAMILIES = ("periodic_ring", "periodic_square_lattice", "periodic_triangular_lattice", "periodic_honeycomb_lattice",
            "periodic_cubic_lattice", "periodic_hypercubic_lattice_4d", "sierpinski_gasket")

MIN_SEEDS = 5
OMEGAS = tuple(round(0.05 * k, 2) for k in range(2, 41))
SCATTER_SIGMAS = 2.0

COMMITTED = Path(__file__).resolve().parents[1] / "resources" / "calibration" / "finite_size_tolerance.json"


def _means(table: dict) -> dict[str, list[tuple[int, float]]]:
    by: dict[str, dict[int, list[float]]] = {}
    for cell in (table.get("cells") or {}).values():
        if cell.get("family") not in FAMILIES or cell.get("status") != "ok":
            continue
        channel = (cell.get("channels") or {}).get("d_s") or {}
        if channel.get("valid") and isinstance(channel.get("value"), (int, float)):
            by.setdefault(cell["family"], {}).setdefault(int(cell["n"]), []).append(float(channel["value"]))
    return {family: sorted((n, sum(v) / len(v)) for n, v in rungs.items() if len(v) >= MIN_SEEDS)
            for family, rungs in by.items()}


def in_the_flow(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    kept = list(points)
    trend = kept[-1][1] - kept[0][1] if len(kept) > 1 else 0.0
    while len(kept) > 4 and (kept[1][1] - kept[0][1]) * trend < 0:
        kept.pop(0)
        trend = kept[-1][1] - kept[0][1]
    return kept


def fit_flow(points: list[tuple[int, float]]) -> dict:
    points = in_the_flow(points)
    best = None
    for omega in OMEGAS:
        xs = [n ** -omega for n, _ in points]
        ys = [d for _, d in points]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        a = 0.0 if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
        d_inf = my - a * mx
        sse = sum((y - d_inf - a * x) ** 2 for x, y in zip(xs, ys, strict=True))
        if best is None or sse < best["sse"]:
            best = {"omega": omega, "a": a, "d_inf": d_inf, "sse": sse}
    dof = max(1, len(points) - 3)
    return {"omega": best["omega"], "a": round(best["a"], 6), "d_inf": round(best["d_inf"], 6),
            "scatter": round(math.sqrt(best["sse"] / dof), 6), "rungs": [n for n, _ in points],
            "n_min": min(n for n, _ in points)}


def measure(table: dict) -> dict:
    raw = json.dumps(table, sort_keys=True).encode("utf-8")
    fits = {family: fit_flow(points) for family, points in sorted(_means(table).items()) if len(points) >= 4}
    return {"contract": CONTRACT, "families": fits, "scatter_sigmas": SCATTER_SIGMAS,
            "source": {"table_sha256": hashlib.sha256(raw).hexdigest(),
                       "estimator_fingerprint": table.get("estimator_fingerprint")}}


def committed() -> dict:
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


def family_drift(fit: dict, n_small: int, n_large: int, sigmas: float = SCATTER_SIGMAS) -> float:
    lo, hi = sorted((max(int(n_small), fit["n_min"]), max(int(n_large), fit["n_min"])))
    flow = abs(fit["a"]) * abs(lo ** -fit["omega"] - hi ** -fit["omega"])
    return flow + sigmas * fit["scatter"]


def tolerance(n_small: int, n_large: int, fits: dict | None = None) -> float:
    document = fits or committed()
    sigmas = float(document.get("scatter_sigmas", SCATTER_SIGMAS))
    return max(family_drift(fit, n_small, n_large, sigmas) for fit in document["families"].values())


def settled(d_a: float, err_a: float, n_a: int, d_b: float, err_b: float, n_b: int, *, sigmas: float = 2.0,
            fits: dict | None = None) -> tuple[bool, dict]:
    noise = sigmas * math.sqrt(float(err_a) ** 2 + float(err_b) ** 2)
    slack = tolerance(n_a, n_b, fits)
    step = abs(float(d_b) - float(d_a))
    return step <= noise + slack, {"step": step, "noise": noise, "finite_size": slack, "contract": CONTRACT}
