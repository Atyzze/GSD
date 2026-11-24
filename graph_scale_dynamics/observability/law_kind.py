from __future__ import annotations

from graph_scale_dynamics.observability import catalogue as K
from graph_scale_dynamics.observability import law_score as L

VALUES = ("d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction")


def _mean(block) -> float | None:
    return L._num((block or {}).get("mean")) if isinstance(block, dict) else None


def read(chains: dict, given: dict | None = None) -> tuple[dict, dict]:
    given = given or K.rule()
    views: dict[int, dict[str, dict]] = {}
    values: dict[str, dict[int, dict]] = {}
    for rung in (chains or {}).get("rungs") or []:
        n = int(rung["n"])
        sides = {"empty": rung.get("empty"), "given": rung.get("given"), **dict(rung.get("more_given") or {})}
        for name, side in sides.items():
            if not isinstance(side, dict):
                continue
            row = {key: _mean(side.get(key)) for key in VALUES}
            values.setdefault(name, {})[n] = row
            views.setdefault(n, {})[name] = {
                "d": K.d_of(row), "mean_degree": row["mean_degree"], "reach": row["reach"],
                "giant": row["giant_fraction"], "moved": L.moved_of(side),
                "full": L.full_of(side, float(given["full_share"]))}
    return views, values


def kinds(chains: dict, given: dict | None = None) -> dict[int, str]:
    views, values = read(chains, given)
    return K.kinds_of(views, values, L.margins()["relative"], given)


def at(found: dict[int, str], n: int = 4096) -> str | None:
    sizes = [size for size in found if size <= int(n)]
    return found[max(sizes)] if sizes else None


def deepest(found: dict[int, str]) -> str | None:
    return found[max(found)] if found else None
