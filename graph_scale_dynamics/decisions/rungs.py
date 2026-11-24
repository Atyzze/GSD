from __future__ import annotations

from graph_scale_dynamics.decisions.engine import PROBES, Rung


def rung_from_entry(n: int, entry: dict, seeds=(), structure: dict | None = None, *,
                    longer_chain: bool = False) -> Rung | None:
    if entry.get("mean_degree") is None:
        return None
    probes = {}
    for probe in PROBES:
        refused = str(entry.get(probe + "_bucket") or "").startswith("REFUSED")
        if entry.get(probe) is not None and not refused:
            probes[probe] = (entry[probe], ((entry.get("probes") or {}).get(probe) or {}).get("se"))
    bucket = str(entry.get("d_s_bucket") or "")
    measured = {}
    for probe in probes:
        value = ((entry.get("probes") or {}).get(probe) or {}).get("measured_se")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            measured[probe] = float(value)
    valid = {probe: float(entry[f"{probe}_valid_fraction"]) for probe in PROBES
             if isinstance(entry.get(f"{probe}_valid_fraction"), (int, float))}
    small_world = entry.get("small_world_fraction")
    return Rung(n=int(n), mean_degree=entry["mean_degree"], connected_fraction=entry.get("connected_fraction"),
                probes=probes, chains_disagreed=entry.get("chains_verdict") == "CHAINS_DISAGREED",
                seeds_measured=int(entry.get("measurement_seed_count") or 0), seeds=tuple(seeds),
                structure=dict(structure or {}),
                d_s_refusal=(bucket if bucket.startswith("REFUSED") and "d_s" not in probes else None),
                longer_chain=bool(longer_chain), measured_se=measured,
                small_world_fraction=(float(small_world) if isinstance(small_world, (int, float)) else None),
                valid_fractions=valid,
                giant_mean_degree=entry.get("giant_mean_degree"))


def rungs_from_phenotype(phenotype: dict) -> list:
    per_n = dict(phenotype.get("per_n") or {})
    per_n.update(phenotype.get("extension_per_n") or {})
    rungs = (rung_from_entry(int(key), per_n[key]) for key in sorted(per_n, key=int))
    return [r for r in rungs if r is not None]
