from __future__ import annotations

import math
import statistics


ANCHOR_CONTRACT = "gsd-measured-anchors-1"

PROBES = ("d_s", "d_V", "d_B", "d_w")

MIN_SEEDS_FOR_ANCHOR = 3

SPREAD_FLOOR = 0.02


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def measured_anchors(table: dict | None) -> dict:
    cells = (table or {}).get("cells") or {}
    grouped: dict[tuple[str, int], dict[str, list[float]]] = {}
    refused: dict[tuple[str, int], dict[str, int]] = {}
    for cell in cells.values():
        if str(cell.get("status") or "ok") != "ok":
            continue
        family, n = cell.get("family"), cell.get("n")
        if not family or n is None:
            continue
        key = (str(family), int(n))
        bucket = grouped.setdefault(key, {p: [] for p in PROBES})
        declined = refused.setdefault(key, {p: 0 for p in PROBES})
        channels = cell.get("channels") or {}
        for probe in PROBES:
            entry = channels.get(probe) or {}
            value = _finite(entry.get("value")) if entry.get("valid") else None
            if value is None:
                declined[probe] += 1
            else:
                bucket[probe].append(value)
    out: dict[str, dict[int, dict[str, dict]]] = {}
    for (family, n), per_probe in grouped.items():
        row = {}
        for probe, values in per_probe.items():
            if len(values) < MIN_SEEDS_FOR_ANCHOR:
                row[probe] = {"mean": None, "spread": None, "seeds": len(values),
                              "refused": refused[(family, n)][probe]}
                continue
            spread = statistics.pstdev(values) if len(values) > 1 else 0.0
            row[probe] = {"mean": round(statistics.fmean(values), 4),
                          "spread": round(max(spread, SPREAD_FLOOR), 4),
                          "seeds": len(values),
                          "refused": refused[(family, n)][probe]}
        out.setdefault(family, {})[n] = row
    return out


def anchor_at(anchors: dict, family: str, n: int, probe: str) -> dict | None:
    rungs = (anchors.get(family) or {})
    if not rungs:
        return None
    candidates = [r for r in rungs if r <= int(n)]
    if not candidates:
        return None
    rung = max(candidates)
    entry = (rungs[rung] or {}).get(probe)
    if not entry or entry.get("mean") is None:
        return None
    return {"family": family, "probe": probe, "n": rung,
            "mean": entry["mean"], "spread": entry["spread"], "seeds": entry["seeds"]}


def anchor_distance(value: float, anchor: dict) -> float:
    return abs(float(value) - float(anchor["mean"])) / max(float(anchor["spread"]), SPREAD_FLOOR)


def anchors_for_table(table: dict | None) -> dict:
    if not table:
        return {}
    stamp = str(table.get("written_utc") or "") + str(len(table.get("cells") or {}))
    key = ("anchors", stamp)
    store = getattr(anchors_for_table, "_store", None)
    if store is None:
        store = anchors_for_table._store = {}
    if key not in store:
        store.clear()
        store[key] = measured_anchors(table)
    return store[key]


def family_degrees(table: dict | None) -> dict[str, dict[int, float]]:
    sums: dict[tuple[str, int], list[float]] = {}
    for cell in ((table or {}).get("cells") or {}).values():
        degree = _finite(((cell or {}).get("structure") or {}).get("mean_degree"))
        if degree is not None and cell.get("family") and cell.get("n"):
            sums.setdefault((str(cell["family"]), int(cell["n"])), []).append(degree)
    out: dict[str, dict[int, float]] = {}
    for (family, n), values in sums.items():
        out.setdefault(family, {})[n] = sum(values) / len(values)
    return out


def short(family: str) -> str:
    return (str(family).replace("periodic_", "").replace("_lattice", "").replace("sierpinski_", "")
            .replace("uniform_random_tree", "CRT"))
