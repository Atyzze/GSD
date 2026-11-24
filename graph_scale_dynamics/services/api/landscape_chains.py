from __future__ import annotations

import json
import math

from graph_scale_dynamics.domain import chain_list as CL

PROBE_KEYS = ("d_s", "d_V", "d_B", "d_w")
CHAINS_CONTRACT = "landscape-every-chain-1"

_PROBE_PART = ("jsonb_build_object('d_s',e.v->'d_s','d_V',e.v->'d_V','d_B',e.v->'d_B','d_w',e.v->'d_w',"
               "'radius',e.v->'half_volume_radius','small_world',e.v->'small_world')")
_CENSUS_PART = "jsonb_build_object('edges',e.v->'edges','giant',e.v#>'{largest_component,size}')"


def _each(path: str, part: str) -> str:
    return (f"(SELECT jsonb_object_agg(e.k,{part}) FROM jsonb_each(CASE WHEN jsonb_typeof({path})='object' "
            f"THEN {path} ELSE '{{}}'::jsonb END) AS e(k,v) WHERE jsonb_typeof(e.v)='object')::text")


CHAIN_PROBES, CENSUS = "j->'chain_probes'", "j->'census'"
ROWS_SQL = ("SELECT candidate_id,n,seed,(j#>>'{health,sweeps_multiplier}') AS multiplier,"
            "(j#>>'{health,sampler,sampler_audit}') AS audit,"
            + _each(CHAIN_PROBES, _PROBE_PART) + " AS chain_probes,"
            + _each(CENSUS, _CENSUS_PART) + " AS census "
            "FROM measurements CROSS JOIN LATERAL (SELECT metrics_json::jsonb AS j) AS d "
            "WHERE campaign_id=? AND analysis_version=?")


def chain_names(spec: dict | None) -> list[tuple[str, str]]:
    starts = [s for s in (((spec or {}).get("sampling_contract") or {}).get("given_starts") or [])
              if isinstance(s, dict) and s.get("name")]
    if not starts:
        return [(CL.GIVEN, CL.GIVEN)]
    return [(CL.GIVEN, str(starts[0]["name"]))] + [(str(s["name"]), str(s["name"])) for s in starts[1:]]


def _loaded(text):
    try:
        found = json.loads(text) if text else None
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def chain_seeds(rows) -> dict:
    best: dict = {}
    for row in rows:
        if str(row["audit"] or "").lower() == "true":
            continue
        try:
            multiplier = int(float(row["multiplier"] or 1))
        except (TypeError, ValueError):
            multiplier = 1
        key = (str(row["candidate_id"]), int(row["n"]), str(row["seed"]))
        if key not in best or multiplier >= best[key][0]:
            best[key] = (multiplier, row)
    out: dict = {}
    for (law, n, _seed), (_multiplier, row) in best.items():
        probes = _loaded(row["chain_probes"]) or {}
        census = _loaded(row["census"]) or {}
        for name, found in probes.items():
            counted = census.get(name) or {}
            edges, giant = _number(counted.get("edges")), _number(counted.get("giant"))
            out.setdefault((law, str(name)), {}).setdefault(int(n), []).append(
                dict(found, degree=None if edges is None else 2.0 * edges / max(1, int(n)),
                     giant=None if giant is None else giant / max(1, int(n))))
    return out


def _stat(values: list, ses: list | None = None) -> dict | None:
    values = [v for v in (_number(x) for x in values) if v is not None]
    if not values:
        return None
    k = len(values)
    mean = sum(values) / k
    between = sum((v - mean) ** 2 for v in values) / (k - 1) if k > 1 else 0.0
    within = [s for s in (_number(x) for x in ses or []) if s is not None]
    se = math.sqrt(sum(s * s for s in within) / (k * k) + (between / k if k > 1 else 0.0))
    return {"mean": mean, "se": se if se > 0 else None, "n_seeds": k, "within_seeds_with_se": len(within),
            "between_seed_sd": math.sqrt(between) if k > 1 else None}


def chain_summary(seeds: list[dict]) -> dict:
    out: dict = {"seeds": len(seeds), "probe_refusals": {}}
    for probe in PROBE_KEYS:
        read = [s.get(probe) or {} for s in seeds]
        valid = [block for block in read if block.get("valid") and _number(block.get("value")) is not None]
        out[probe] = _stat([b["value"] for b in valid], [b.get("se") for b in valid])
        out[f"{probe}_valid_fraction"] = len(valid) / max(1, len(seeds))
        codes: dict = {}
        for block in read:
            if not block.get("valid") and block.get("refusal"):
                codes[str(block["refusal"])] = codes.get(str(block["refusal"]), 0) + 1
        if codes:
            out["probe_refusals"][probe] = codes
    out["mean_degree"] = _stat([s.get("degree") for s in seeds])
    out["connected_fraction"] = _stat([s.get("giant") for s in seeds])
    out["half_volume_radius"] = _stat([s.get("radius") for s in seeds])
    flags = [bool(s["small_world"]) for s in seeds if isinstance(s.get("small_world"), bool)]
    out["small_world_fraction"] = (sum(flags) / len(flags)) if flags else None
    return out
