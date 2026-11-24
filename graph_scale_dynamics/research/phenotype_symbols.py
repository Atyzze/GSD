from __future__ import annotations

import math

SYMBOL_CONTRACT = "phenotype-symbols-2"

BUCKET_SYMBOLS = {
    "REFUSED_NO_SCALING_WINDOW": "N",
    "REFUSED_NEVER_EQUILIBRATED": "E",
    "REFUSED_CHAINS_DISAGREED": "T",
    "REFUSED_NO_EFFECTIVE_SAMPLE": "S",
    "REFUSED_BELOW_CONNECTIVITY_FLOOR": "F",
    "NOT_ATTEMPTED": "X",
}

DYNAMICS_SYMBOLS = {
    "EQUILIBRATED_ACTIVE": "EA",
    "EQUILIBRATED_LOW_ACTIVITY": "EL",
    "AT_REST": "AR",
    "FROZEN_OR_ABSORBING": "FR",
    "METASTABLE_OR_NONMIXING": "MX",
    "RELAXING_AT_CEILING": "RL",
    "INSUFFICIENT_EFFECTIVE_SAMPLES": "ES",
    "NUMERICAL_FAILURE": "NF",
    "RESOURCE_LIMIT": "RS",
    "OPERATIONAL_UNRESOLVED": "OU",
}


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None


def _probe_track(row: dict, probe: str) -> str:
    if _num(row.get(probe)) is not None:
        return "V"
    bucket = row.get(f"{probe}_bucket")
    if bucket:
        return BUCKET_SYMBOLS.get(str(bucket), "R")
    return "?"


def _connected(row: dict) -> str:
    value = _num(row.get("connected_fraction"))
    if value is None:
        return "?"
    if value >= 0.90:
        return "C"
    if value >= 0.50:
        return "c"
    return "f"


def _activity(row: dict) -> str:
    value = _num(row.get("accepted_changes_per_node_late"))
    if value is None:
        return "?"
    if value >= 0.50:
        return "A"
    if value <= 0.05:
        return "F"
    return "a"


def _two_core(row: dict) -> str:
    value = _num(row.get("two_core_fraction"))
    if value is None:
        return "?"
    if value >= 0.50:
        return "2"
    if value >= 0.20:
        return "t"
    return "b"


def _flow(values: list) -> str:
    out = []
    for a, b in zip(values, values[1:], strict=False):
        x, y = _num(a), _num(b)
        if x is None or y is None:
            out.append("?")
        elif y > x:
            out.append("+")
        elif y < x:
            out.append("-")
        else:
            out.append("=")
    return "".join(out)


def symbolize_phenotype(phenotype: dict) -> dict:
    per_n = phenotype.get("per_n") or {}
    sizes = [int(n) for n in phenotype.get("base_sizes") or (64, 256, 1024, 4096)]
    rows = [per_n.get(str(n)) or {} for n in sizes]
    from graph_scale_dynamics.scaleflow.probes import PROBES
    probe_tracks = {probe: "".join(_probe_track(row, probe) for row in rows) for probe in PROBES}
    probe_flows = {probe: _flow([row.get(probe) for row in rows]) for probe in PROBES}
    connected = "".join(_connected(row) for row in rows)
    activity = "".join(_activity(row) for row in rows)
    two_core = "".join(_two_core(row) for row in rows)
    dynamics = ".".join(DYNAMICS_SYMBOLS.get(str(row.get("rung_terminal_classification") or ""), "??") for row in rows)
    radius_flow = _flow([row.get("half_volume_radius") for row in rows])
    probe_part = "|".join(f"{probe}:{probe_tracks[probe]}/{probe_flows[probe]}" for probe in PROBES)
    region_key = f"{probe_part}|C:{connected}|A:{activity}|2:{two_core}|R:{radius_flow}|K:{dynamics}"
    return {
        "contract": SYMBOL_CONTRACT,
        "probe_tracks": probe_tracks,
        "probe_flow_signs": probe_flows,
        "connected_track": connected,
        "activity_track": activity,
        "two_core_track": two_core,
        "radius_flow_signs": radius_flow,
        "dynamics_track": dynamics,
        "region_key": region_key,
        "legend": {
            "probe": "V measured; R refused (see the bucket for which refusal); "
                     "N no scaling window; E never equilibrated; T chains disagreed; "
                     "S no effective sample; F below connectivity floor; X not attempted; ? unknown",
            "connected": "C >=0.90; c >=0.50; f <0.50; ? unavailable",
            "activity": "A >=0.50 changes/node late; F <=0.05; a intermediate; descriptive only",
            "two_core": "2 >=0.50; t >=0.20; b <0.20; ? unavailable",
            "flow": "+ increasing; - decreasing; = equal; ? missing",
        },
    }
