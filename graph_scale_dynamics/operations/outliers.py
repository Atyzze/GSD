from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CRITERION = Path(__file__).resolve().parents[1] / "resources" / "readings" / "outliers_1.json"
LUCKY = "lucky strike"


@lru_cache(maxsize=1)
def criterion() -> dict:
    return json.loads(CRITERION.read_text(encoding="utf-8"))


def over_the_line(repo, campaign_ids) -> list[tuple[str, str]]:
    rule = criterion()
    found = set()
    for campaign_id in campaign_ids:
        for row in repo.conn.execute("SELECT candidate_id,n,summary_json FROM rung_summaries WHERE campaign_id=? AND n>=?",
                                     (str(campaign_id), int(rule["from_n"]))).fetchall():
            try:
                summary = json.loads(row["summary_json"] or "{}")
            except ValueError:
                continue
            for probe, line in rule["lines"].items():
                node = summary.get(probe) if isinstance(summary.get(probe), dict) else {}
                highest = max((value for value in (node.get("mean"), node.get("max")) if isinstance(value, (int, float))),
                              default=None)
                if highest is not None and highest > line:
                    found.add((str(campaign_id), str(row["candidate_id"])))
    return sorted(found)


def seed_readings(rows: list[dict], starts) -> dict[int, dict[int, dict[str, float]]]:
    from graph_scale_dynamics.observability import two_chains as T
    metrics = [row["metrics"] for row in rows if isinstance(row.get("metrics"), dict)]
    names = T.more_given_names(starts, metrics)
    out: dict[int, dict[int, dict[str, float]]] = {}
    for row in rows:
        if not isinstance(row.get("metrics"), dict):
            continue
        n, seed = int(row["n"]), int(row["seed"])
        chains = [T.seed_values(row["metrics"], n, chain) for chain in T.CHAINS]
        chains += [T.seed_values(row["metrics"], n, "given", name) for name in names]
        kept = out.setdefault(n, {}).setdefault(seed, {})
        for probe in T.PROBES:
            values = [chain[probe]["value"] for chain in chains if chain[probe]["value"] is not None]
            if values:
                kept[probe] = max(max(values), kept.get(probe, float("-inf")))
    return out


def judged(readings: dict[int, dict[int, dict[str, float]]]) -> dict | None:
    rule, best = criterion(), None
    for n, seeds in sorted(readings.items()):
        if n < int(rule["from_n"]):
            continue
        for probe, line in rule["lines"].items():
            over = {seed: values[probe] for seed, values in seeds.items() if values.get(probe, 0.0) > line}
            if not over:
                continue
            strength = max(over.values()) / line
            if best is None or strength > best["strength"]:
                best = {"probe": probe, "n": n, "value": round(max(over.values()), 4), "line": line,
                        "strength": round(strength, 4), "seeds_over": sorted(over), "seeds": len(seeds),
                        "lucky": len(over) < int(rule["repeated_by_seeds_at_least"])}
    return best


def outliers(repo, campaign_ids, *, rows_of) -> list[dict]:
    found = []
    for campaign_id, law in over_the_line(repo, campaign_ids):
        rows, starts = rows_of(repo, campaign_id, law)
        verdict = judged(seed_readings(rows, starts))
        if verdict is not None:
            found.append({"candidate_id": law, "campaign": campaign_id, "outlier": verdict})
    return sorted(found, key=lambda e: (-e["outlier"]["strength"], e["campaign"], e["candidate_id"]))


def next_outlier(repo, state: dict, *, rows_of, inside, label) -> dict | None:
    from graph_scale_dynamics.operations import focus as F
    seen = ({entry["law"] for entry in state["done"]} | set(state.setdefault("inside", {}))
            | set(state.get("skipped") or {}) | set(state.setdefault("lucky", {}))
            | {(state.get("current") or {}).get("law")})
    for entry in outliers(repo, F.own_campaigns(repo, state["study"]), rows_of=rows_of):
        law = entry["candidate_id"]
        if law in seen:
            continue
        entry["label"] = label(repo, entry["campaign"], law)
        if entry["outlier"]["lucky"]:
            state["lucky"][law] = dict(entry["outlier"], label=entry["label"], campaign=entry["campaign"])
            continue
        found = inside(repo, state, dict(entry, score=0))
        if found is not None:
            state["inside"][law] = dict(found, label=entry["label"], outlier=entry["outlier"])
            continue
        return dict(entry, score=0, graph=F.graph_number(repo, entry["campaign"], law))
    return None
