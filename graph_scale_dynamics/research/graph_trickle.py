from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

GRAPHS_CONTRACT = "gsd-graphs-by-rung-1"
BRANCHES = ("on", "done", "held", "stopped", "other", "in_progress")
GIVEN_DEGREE_TOLERANCE, GIVEN_GIANT_TOLERANCE = 0.10, 0.05


def _branch(row: dict | None) -> str:
    if row is None:
        return "in_progress"
    return {"run_next": "on", "hold": "held", "stop": "stopped", "done": "done"}.get(str(row.get("action")),
                                                                                       "other")


def _final_by_rung(decisions: dict) -> dict:
    from graph_scale_dynamics.research.gate_tree import _final_by_rung as final_by_rung
    out = {}
    for law, rows in (decisions or {}).items():
        rows = sorted(rows or [], key=lambda r: str(r.get("decision_id") or ""))
        for n, row in final_by_rung(rows).items():
            out[(str(law), int(n))] = row
    return out


def _census_shape(n: int, census: dict | None) -> tuple[float, float] | None:
    if not isinstance(census, dict):
        return None
    histogram = census.get("degree_histogram")
    pairs = []
    if isinstance(histogram, dict):
        pairs = [(int(k), float(v)) for k, v in histogram.items()]
    elif isinstance(histogram, list):
        pairs = [(k, float(v)) for k, v in enumerate(histogram)]
    total = sum(v for _, v in pairs)
    if not total or not n:
        return None
    mean_degree = sum(k * v for k, v in pairs) / total
    giant = (census.get("largest_component") or {}).get("size") or 0
    return mean_degree, float(giant) / float(n)


def _latest_measurements(measurements: list[dict] | None) -> dict:
    latest: dict = {}
    for row in measurements or []:
        if row.get("n") is None:
            continue
        key = (str(row.get("candidate_id")), int(row["n"]), row.get("seed"))
        if key not in latest or str(row.get("created_utc") or "") >= str(latest[key].get("created_utc") or ""):
            latest[key] = row
    return latest


def _median(values: list[float], digits: int = 3):
    return round(float(median(values)), digits) if values else None


def _share(part: int, whole: int):
    return round(part / whole, 4) if whole else None


def graphs_per_law_rung(seeds: dict | None) -> dict:
    out: Counter = Counter()
    if not seeds:
        return out
    columns = seeds.get("columns") or []
    laws = seeds.get("laws") or []
    try:
        i_law, i_n = columns.index("law"), columns.index("n")
    except ValueError:
        return out
    for row in seeds.get("rows") or []:
        if grown(row, columns):
            out[(str(laws[row[i_law]]), int(row[i_n]))] += 1
    return out


ONE_SHOT_ENDS = frozenset({"completed", "ceiling", "frozen", "budget", "mean_degree_cap"})


def grown(row: list, columns: list) -> bool:
    at = {name: i for i, name in enumerate(columns)}
    if "simulation_seconds" not in at or row[at["simulation_seconds"]] is None:
        return False
    ended = row[at["ended"]] if "ended" in at else None
    if ended is None or str(ended) in ONE_SHOT_ENDS:
        return True
    return any(row[at[name]] is not None for name in ("final_edges", "final_mean_degree") if name in at)


def build_graphs_by_rung(seeds: dict | None, measurements: list[dict] | None, decisions: dict | None) -> dict:
    columns = (seeds or {}).get("columns") or []
    laws = (seeds or {}).get("laws") or []
    final = _final_by_rung(decisions or {})
    measured = _latest_measurements(measurements)
    rungs: dict = defaultdict(lambda: {"graphs": 0, "by_branch": Counter(), "laws": set(), "degrees": [],
                                       "giant": [], "measured": 0, "d_s_valid": 0, "given_chains": 0, "given_agree": 0,
                                       "kappa": []})
    if columns:
        index = {name: columns.index(name) for name in ("law", "n", "seed", "simulation_seconds",
                                                          "final_mean_degree")}
        for row in (seeds or {}).get("rows") or []:
            if not grown(row, columns):
                continue
            law, n, seed = str(laws[row[index["law"]]]), int(row[index["n"]]), row[index["seed"]]
            entry = rungs[n]
            entry["graphs"] += 1
            entry["laws"].add(law)
            entry["by_branch"][_branch(final.get((law, n)))] += 1
            degree = row[index["final_mean_degree"]]
            if isinstance(degree, (int, float)):
                entry["degrees"].append(float(degree))
            metrics = (measured.get((law, n, seed)) or {}).get("metrics") or {}
            if not metrics:
                continue
            entry["measured"] += 1
            if (metrics.get("d_s") or {}).get("valid"):
                entry["d_s_valid"] += 1
            kappa = ((metrics.get("curvature") or {}).get("empty") or {})
            if kappa.get("measured") and isinstance(kappa.get("mean"), (int, float)):
                entry["kappa"].append(float(kappa["mean"]))
            census = metrics.get("census") or {}
            from_empty = _census_shape(n, census.get("empty"))
            if from_empty is not None:
                entry["giant"].append(from_empty[1])
            given = _census_shape(n, census.get("given"))
            if from_empty is not None and given is not None:
                entry["given_chains"] += 1
                degree_close = abs(given[0] - from_empty[0]) <= GIVEN_DEGREE_TOLERANCE * max(from_empty[0], 1e-9)
                if degree_close and abs(given[1] - from_empty[1]) <= GIVEN_GIANT_TOLERANCE:
                    entry["given_agree"] += 1
    by_rung = [{"n": n, "graphs": e["graphs"], "laws": len(e["laws"]),
                "by_branch": {key: e["by_branch"][key] for key in BRANCHES if e["by_branch"].get(key)},
                "given_chains": e["given_chains"], "median_mean_degree": _median(e["degrees"]),
                "median_giant_share": _median(e["giant"], 4), "measured": e["measured"],
                "d_s_readable_share": _share(e["d_s_valid"], e["measured"]),
                "given_agrees_share": _share(e["given_agree"], e["given_chains"]),
                "median_curvature": _median(e["kappa"], 4), "curvature_read": len(e["kappa"])}
               for n, e in sorted(rungs.items())]
    return {"contract": GRAPHS_CONTRACT, "graphs": sum(r["graphs"] for r in by_rung),
            "given_chains": sum(r["given_chains"] for r in by_rung), "rungs": by_rung,
            "reading": ("A graph is a seed whose simulation finished: the final graph of the chain from empty, which the "
                        "probes measure; a second graph is the given chain's, where a law ran one. by_branch says where "
                        "the graph's law went from the rung (in_progress: it has not finished the rung yet). The "
                        "medians are over the graphs; d_s_readable_share and given_agrees_share over the measured "
                        "ones (a second graph agrees at mean degree within 10% and giant share within 0.05). median_curvature is the "
                        "median of the graphs' mean Ollivier curvature per edge, over the curvature_read "
                        "graphs that carry it.")}
