from __future__ import annotations

import json

from graph_scale_dynamics.operations.push_ladder import is_push
from graph_scale_dynamics.scheduling.rungs import max_seed_attempts_for_rung


def analysis_execution_family(job_spec: dict) -> str:
    execution = dict((job_spec or {}).get("execution") or {})
    execution.pop("sweeps_multiplier", None)
    payload = {
        "engine_version": (job_spec or {}).get("engine_version"),
        "execution": execution,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def analysis_generation(job_spec: dict) -> int:
    return max(1, int(((job_spec or {}).get("execution") or {}).get("sweeps_multiplier", 1)))


def superseded_analysis_keys(rows: list[dict]) -> list[tuple[str, str, str]]:
    rung_groups: dict[tuple, list[dict]] = {}
    for row in rows:
        spec = row.get("spec") or {}
        key = (
            str(row["campaign_id"]), str(row["candidate_id"]), int(row["n"]),
            analysis_execution_family(spec),
        )
        rung_groups.setdefault(key, []).append(row)

    allowed_seeds: dict[tuple, set[int]] = {}
    for key, family in rung_groups.items():
        campaign_spec = family[0].get("campaign_spec") or {}
        ceiling = (len({int(row["seed"]) for row in family}) if is_push(campaign_spec)
                   else max_seed_attempts_for_rung(campaign_spec, int(key[2])))
        first_seen: dict[int, str] = {}
        for row in family:
            seed = int(row["seed"])
            created = str(row.get("job_created_utc") or row.get("created_utc") or "")
            previous = first_seen.get(seed)
            if previous is None or created < previous:
                first_seen[seed] = created
        ordered = sorted(first_seen, key=lambda seed: (first_seen[seed], seed))
        allowed_seeds[key] = set(ordered[:max(1, int(ceiling))])

    superseded: list[tuple[str, str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    seed_groups: dict[tuple, list[dict]] = {}
    for row in rows:
        spec = row.get("spec") or {}
        rung_key = (
            str(row["campaign_id"]), str(row["candidate_id"]), int(row["n"]),
            analysis_execution_family(spec),
        )
        seed = int(row["seed"])
        if seed not in allowed_seeds.get(rung_key, {seed}):
            if str(row.get("status")) == "queued":
                key = (str(row["campaign_id"]), str(row["input_artifact"]),
                       str(row["analysis_version"]))
                if key not in seen_keys:
                    superseded.append(key)
                    seen_keys.add(key)
            continue
        seed_key = (*rung_key, seed)
        seed_groups.setdefault(seed_key, []).append(row)

    for family in seed_groups.values():
        highest = max(analysis_generation(row.get("spec") or {}) for row in family)
        highest_done = any(
            str(row.get("status")) == "done"
            and analysis_generation(row.get("spec") or {}) == highest
            for row in family
        )
        kept_highest_queued = False
        for row in sorted(family, key=lambda item: str(item.get("created_utc") or ""), reverse=True):
            if str(row.get("status")) != "queued":
                continue
            generation = analysis_generation(row.get("spec") or {})
            redundant = generation < highest
            if generation == highest:
                if highest_done or kept_highest_queued:
                    redundant = True
                else:
                    kept_highest_queued = True
            if redundant:
                key = (str(row["campaign_id"]), str(row["input_artifact"]),
                       str(row["analysis_version"]))
                if key not in seen_keys:
                    superseded.append(key)
                    seen_keys.add(key)
    return superseded
