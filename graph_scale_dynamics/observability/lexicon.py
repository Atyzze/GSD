from __future__ import annotations

import json
import math
import statistics
from functools import lru_cache
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "resources" / "catalogue" / "lexicon.json"
PROBES = ("d_s", "d_V", "d_B", "d_w")
REFUSED = "refused"


@lru_cache(maxsize=1)
def lexicon() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def types() -> list[str]:
    return list(lexicon()["types"])


def type_of_family() -> dict[str, str]:
    return {family: name for name, families in lexicon()["types"].items() for family in families}


def _cell_key(key: str) -> tuple[str, int]:
    family, _parameter, seed = key.rsplit(":", 2)
    return family, int(seed)


def cell_features(cell: dict) -> dict:
    out = {}
    for probe in PROBES:
        channel = (cell.get("channels") or {}).get(probe) or {}
        value = channel.get("value")
        out[probe] = value if channel.get("valid") and isinstance(value, (int, float)) else REFUSED
    structure = cell.get("structure") or {}
    out["mean_degree"] = structure.get("mean_degree")
    out["giant"] = structure.get("giant_fraction")
    return out


def _nearest_size(known: dict[int, list], n: int):
    sizes = [size for size, values in known.items() if values]
    if not sizes:
        return None
    return statistics.median(known[min(sizes, key=lambda size: (abs(math.log(size / n)), size))])


def _summary(values: list) -> tuple | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    numbers = [float(value) for value in present if value != REFUSED]
    if len(present) - len(numbers) >= lexicon()["refused_from_share"] * len(present) and len(numbers) * 2 < len(present):
        return (REFUSED,)
    if not numbers:
        return (REFUSED,)
    return (statistics.fmean(numbers), statistics.pstdev(numbers) if len(numbers) > 1 else 0.0)


def profiles(cells: dict, *, below_seed: int | None = None) -> dict[str, dict[int, dict]]:
    known = type_of_family()
    readings: dict[tuple[str, int], list[dict]] = {}
    degree: dict[str, dict[int, list]] = {}
    giant: dict[str, dict[int, list]] = {}
    for key, cell in cells.items():
        family, seed = _cell_key(key)
        if family not in known or not isinstance(cell, dict) or cell.get("n") is None:
            continue
        if below_seed is not None and seed >= below_seed:
            continue
        n = int(cell["n"])
        features = cell_features(cell)
        if features["mean_degree"] is not None:
            degree.setdefault(family, {}).setdefault(n, []).append(features["mean_degree"])
        if features["giant"] is not None:
            giant.setdefault(family, {}).setdefault(n, []).append(features["giant"])
        readings.setdefault((family, n), []).append(features)
    out: dict[str, dict[int, dict]] = {}
    for (family, n), rows in readings.items():
        filled_degree = _nearest_size(degree.get(family, {}), n)
        filled_giant = _nearest_size(giant.get(family, {}), n)
        profile = {}
        for feature in lexicon()["features"]:
            values = [row.get(feature) for row in rows]
            if feature == "mean_degree" and not any(value is not None for value in values):
                values = [filled_degree]
            if feature == "giant" and not any(value is not None for value in values):
                values = [filled_giant]
            found = _summary(values)
            if found is not None:
                profile[feature] = found
        out.setdefault(family, {})[n] = profile
    return out


def distance(features: dict, profile: dict) -> float | None:
    rule = lexicon()
    apart = []
    for feature, kept in profile.items():
        value = features.get(feature)
        if value is None:
            continue
        if kept[0] == REFUSED or value == REFUSED:
            apart.append(0.0 if kept[0] == REFUSED and value == REFUSED else rule["refused_apart"])
            continue
        mean, spread = kept
        floor = rule["floors"][feature] * (abs(mean) if feature in rule["relative"] else 1.0)
        scale = max(spread, floor, rule["floors"][feature])
        apart.append(min(abs(float(value) - mean) / scale, rule["most_apart"]))
    if not apart:
        return None
    return math.sqrt(sum(value * value for value in apart) / len(apart))


def near(features: dict, n: int, table: dict[str, dict[int, dict]]) -> list[dict]:
    rule = lexicon()
    known = type_of_family()
    best: dict[str, float] = {}
    for family, by_size in table.items():
        sizes = [size for size in by_size if abs(math.log(size / n)) <= rule["sizes_within"]]
        if not sizes:
            continue
        size = min(sizes, key=lambda found: (abs(math.log(found / n)), found))
        apart = distance(features, by_size[size])
        if apart is None:
            continue
        name = known[family]
        if name not in best or apart < best[name]:
            best[name] = apart
    return [{"type": name, "spreads": round(apart, 3)}
            for name, apart in sorted(best.items(), key=lambda item: (item[1], item[0]))]


def reading(features: dict, n: int | None, table: dict[str, dict[int, dict]]) -> dict:
    if n is None or not features:
        return {"n": n, "type": None, "spreads": None, "new_zone": False, "near": []}
    found = near(features, int(n), table)
    if not found:
        return {"n": int(n), "type": None, "spreads": None, "new_zone": False, "near": []}
    first = found[0]
    new = first["spreads"] > lexicon()["new_zone_beyond"]
    return {"n": int(n), "type": None if new else first["type"], "spreads": first["spreads"], "new_zone": new,
            "nearest": first["type"], "near": found}


def _refused_or(value, valid_fraction):
    if valid_fraction is not None and valid_fraction < lexicon()["refused_from_share"]:
        return REFUSED
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def features_of_summary(summary: dict | None) -> dict:
    summary = summary or {}

    def mean(key):
        node = summary.get(key)
        return node.get("mean") if isinstance(node, dict) else None
    out = {probe: _refused_or(mean(probe), summary.get(f"{probe}_valid_fraction")) for probe in PROBES}
    out["mean_degree"] = mean("mean_degree")
    out["giant"] = mean("connected_fraction")
    return {key: value for key, value in out.items() if value is not None}


def features_of_rung_row(row: dict | None) -> dict:
    row = row or {}
    out = {probe: _refused_or(row.get(probe), row.get(f"{probe}_valid_fraction")) for probe in PROBES}
    out["mean_degree"] = row.get("mean_degree")
    out["giant"] = row.get("connected_fraction")
    return {key: value for key, value in out.items() if value is not None}


def table_path(root: Path | None = None) -> Path | None:
    from graph_scale_dynamics.calibration import durable_artifact_path
    durable = durable_artifact_path(root)
    if durable.is_file():
        return durable
    seed = durable.parent / "seed_table.json"
    return seed if seed.is_file() else None


@lru_cache(maxsize=4)
def _profiles_of(path: str, stamp: float) -> dict[str, dict[int, dict]]:
    return profiles(json.loads(Path(path).read_text(encoding="utf-8")).get("cells") or {})


def table_profiles(path: Path | None = None) -> dict[str, dict[int, dict]]:
    found = Path(path) if path is not None else table_path()
    if found is None or not found.is_file():
        return {}
    return _profiles_of(str(found), found.stat().st_mtime)


def matrix(rows: list[dict], table: dict[str, dict[int, dict]]) -> dict:
    laws = []
    for row in rows:
        found = reading(row.get("features") or {}, row.get("n"), table)
        laws.append({key: row.get(key) for key in ("campaign_id", "candidate_id", "code", "law_score")}
                    | {"n": found["n"], "type": found["type"], "spreads": found["spreads"],
                       "new_zone": found["new_zone"], "near": {cell["type"]: cell["spreads"] for cell in found["near"]}})
    by_type: dict[str, int] = {}
    for law in laws:
        key = law["type"] or ("a new zone" if law["new_zone"] else "unread")
        by_type[key] = by_type.get(key, 0) + 1
    return {"contract": lexicon()["contract"], "types": types(), "laws": laws,
            "by_type": dict(sorted(by_type.items(), key=lambda item: (-item[1], item[0])))}
