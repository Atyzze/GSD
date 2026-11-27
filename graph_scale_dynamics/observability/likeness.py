from __future__ import annotations

from graph_scale_dynamics.observability import phenotype as P

CONTRACT = "gsd-likeness-1"
FROM_ROW = {"mean_degree": "mean_degree", "giant_fraction": "connected_fraction", "d_s": "d_s", "d_V": "d_V",
            "d_B": "d_B", "d_w": "d_w", "reach": "half_volume_radius"}


def rows_of(repo, campaign_id: str, law: str) -> list[dict]:
    from graph_scale_dynamics.reporting import study_tables as T
    return T.law_rung_rows(repo, str(campaign_id), str(law))


def curves(rows: list[dict], upto_n: int) -> dict[str, dict]:
    series: dict[str, list] = {}
    for row in rows:
        if int(row["n"]) > int(upto_n):
            continue
        for quantity, column in FROM_ROW.items():
            if row.get(column) is not None:
                series.setdefault(quantity, []).append((int(row["n"]), float(row[column]), float(row.get("seeds") or 1)))
    return {quantity: P.fit(found) for quantity, found in series.items()}


def locked(found: dict[str, dict]) -> dict[str, dict]:
    return {q: f for q, f in (found or {}).items() if f.get("form") is not None}


def same_curve(a: dict, b: dict) -> tuple[bool, str]:
    rule = P.rule()
    if a["form"] != b["form"]:
        return False, f"{a['form']} against {b['form']}"
    if a["form"] == "power":
        gap = abs(float(a["b"]) - float(b["b"]))
        return gap <= float(rule["exponent_within"]) + 1e-12, f"exponents {a['b']:.3f} and {b['b']:.3f}"
    key = "a" if a["form"] == "constant" else "b"
    x, y = float(a[key]), float(b[key])
    gap = abs(x - y) / max(abs(x), abs(y), 1e-12)
    what = "values" if a["form"] == "constant" else "slopes in log N"
    return gap <= float(rule["constant_within"]) + 1e-12, f"{what} {x:.4g} and {y:.4g}"


def alike(centre: dict | None, other: dict | None) -> dict:
    if centre is None or other is None or centre.get("kind") is None or other.get("kind") is None:
        return {"alike": None, "why": "not read yet", "curves": 0}
    if other["kind"] != centre["kind"]:
        return {"alike": False, "why": f"reads {other['kind']}, not {centre['kind']}", "curves": 0}
    mine, theirs = locked(centre.get("curves") or {}), locked(other.get("curves") or {})
    shared = sorted(set(mine) & set(theirs))
    apart = []
    for quantity in shared:
        same, said = same_curve(mine[quantity], theirs[quantity])
        if not same:
            apart.append(f"{quantity}: {said}")
    if apart:
        return {"alike": False, "why": f"its kind, but {'; '.join(apart)}", "curves": len(shared)}
    if not shared:
        return {"alike": True, "why": f"its kind ({centre['kind']}); no curve locked in by both", "curves": 0}
    return {"alike": True, "why": f"its kind and its {len(shared)} curves locked in by both", "curves": len(shared)}


__all__ = ["CONTRACT", "FROM_ROW", "alike", "curves", "locked", "rows_of", "same_curve"]
