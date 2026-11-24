from __future__ import annotations

from graph_scale_dynamics.dsl import dsl

LAW_DYNAMICS_CONTRACT = "gsd-law-dynamics-1"


def law_dynamics_of(spec: dict | None) -> dict:
    spec = spec or {}
    dyn = spec.get("dynamics") or {}
    record = dsl.dynamics_record(spec)
    zero = bool(record["zero_temperature"])
    beta = record["beta"]
    locality = float(record["locality"])
    return {
        "contract": LAW_DYNAMICS_CONTRACT,
        **record,
        "beta_used": not zero,
        "temperature": None if zero or not beta else 1.0 / float(beta),
        "global_share": 1.0 - locality,
        "sweeps": None if dyn.get("sweeps") is None else int(dyn["sweeps"]),
        "cooling": dsl.cooling_schedule(spec),
        "init": spec.get("init"),
        "written_in_the_spec": sorted(key for key in dyn if key != "kind"),
    }
