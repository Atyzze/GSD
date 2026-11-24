from __future__ import annotations

from graph_scale_dynamics.research.numeric import finite as _finite

GIANT = "giant component"
WHOLE = "whole graph"


def line_degrees(whole: list | None, giant: list | None) -> tuple[list, list]:
    whole, giant = list(whole or []), list(giant or [])
    degrees: list = []
    used: list = []
    for i in range(max(len(whole), len(giant))):
        g = _finite(giant[i]) if i < len(giant) else None
        w = _finite(whole[i]) if i < len(whole) else None
        if g is not None and g > 0:
            degrees.append(g)
            used.append(GIANT)
        else:
            degrees.append(w)
            used.append(WHOLE if w is not None else None)
    return degrees, used


def reading(used: list) -> str | None:
    kinds = {u for u in used if u}
    return None if not kinds else kinds.pop() if len(kinds) == 1 else "mixed"


def phenotype_giant_degrees(phenotype: dict) -> list:
    base = [int(n) for n in (phenotype.get("base_sizes") or [])]
    extension = [int(n) for n in (phenotype.get("extension_sizes") or []) if not base or int(n) > base[-1]]

    def half(vector_key: str, cells_key: str, rungs: list) -> list:
        stored = list(phenotype.get(vector_key) or [])
        if len(stored) == len(rungs):
            return stored
        cells = phenotype.get(cells_key) or {}
        return [_finite((cells.get(str(n)) or {}).get("giant_mean_degree")) for n in rungs]

    return (half("giant_mean_degree_vector", "per_n", base)
            + half("extension_giant_mean_degree_vector", "extension_per_n", extension))
