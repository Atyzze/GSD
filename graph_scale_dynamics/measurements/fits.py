from __future__ import annotations

import math

import numpy as np

EXPONENTIAL_AICC_MARGIN = 4.0


def aicc(residuals, parameters: int) -> float:
    count = len(residuals)
    rss = float(np.sum(np.asarray(residuals, dtype=float) ** 2))
    if count <= parameters + 1:
        return float("-inf")
    aic = count * math.log(max(rss / count, 1e-300)) + 2 * parameters
    return aic + (2 * parameters * (parameters + 1)) / (count - parameters - 1)


def line(x, y, weights=None) -> dict:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    w = np.ones_like(x) if weights is None else np.asarray(weights, dtype=float)
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design * w[:, None], y * w, rcond=None)
    residuals = y - design @ coefficients
    spread = float(np.sum(w ** 2 * (x - np.sum(w ** 2 * x) / np.sum(w ** 2)) ** 2))
    return {"intercept": float(coefficients[0]), "slope": float(coefficients[1]), "residuals": residuals,
            "rms": float(np.sqrt(np.mean(residuals ** 2))),
            "slope_se_of_the_weights": (1.0 / math.sqrt(spread)) if spread > 0 else float("inf"),
            "chi_square_a_point": float(np.sum((w * residuals) ** 2) / max(1, len(x) - 2))}


def exponential_is_better(scale, log_value, weights=None) -> dict:
    scale, log_value = np.asarray(scale, dtype=float), np.asarray(log_value, dtype=float)
    power = line(np.log(scale), log_value, weights)
    exponential = line(scale, log_value, weights)
    delta = aicc(power["residuals"], 2) - aicc(exponential["residuals"], 2)
    return {"delta_aicc": float(delta), "power_law_rms": power["rms"], "exponential_rms": exponential["rms"],
            "exponential": bool(delta >= EXPONENTIAL_AICC_MARGIN)}
