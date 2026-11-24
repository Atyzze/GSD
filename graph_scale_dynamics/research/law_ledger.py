from __future__ import annotations

from collections import defaultdict

from graph_scale_dynamics.dsl.dsl import dynamics_record, dynamics_regime
from graph_scale_dynamics.research.degree_prediction import (
    KIND_DEGREES, accuracy, law_kind, predicted_mean_degree,
)
from graph_scale_dynamics.research.degree_prediction_extended import ledger_entry

CURVATURE_OPS = frozenset({"ollivier_curvature"})
KIND_CURVATURE = "sees curvature"


def reading_kind(spec: dict) -> str:
    ops = {term.get("op") for term in (spec or {}).get("terms") or []}
    return KIND_CURVATURE if ops & CURVATURE_OPS else law_kind(spec)


def ledger_prediction(spec: dict, n: int, cap: float) -> list:
    if reading_kind(spec) == KIND_CURVATURE:
        regime = dynamics_regime(spec)
        return [None, f"curvature / {'zero temperature' if regime == 'zero_temperature' else 'finite temperature'}"]
    return ledger_entry(spec, n, cap)

LEDGER_CONTRACT = "gsd-law-ledger-1"
COMPARED_AT = 4096


def compact_spec(spec: dict) -> dict:
    terms = []
    for term in (spec or {}).get("terms") or []:
        coeff = term.get("coeff") or {}
        terms.append([term.get("op"), (term.get("params") or {}).get("k"), coeff.get("c0"), coeff.get("scale"),
                      coeff.get("p")])
    record = dynamics_record(spec)
    return {"terms": terms, "regime": record["regime"], "beta": record["beta"],
            "zero_temperature": record["zero_temperature"], "locality": record["locality"],
            "local_move": record["local_move"], "swap_share": record["swap_share"],
            "sweeps": ((spec or {}).get("dynamics") or {}).get("sweeps")}


def mean_degrees(seed_table: dict) -> dict:
    columns = list((seed_table or {}).get("columns") or [])
    if not {"law", "n", "final_mean_degree"} <= set(columns):
        return {}
    law_i, n_i, md_i = columns.index("law"), columns.index("n"), columns.index("final_mean_degree")
    laws = list(seed_table.get("laws") or [])
    values: dict = defaultdict(lambda: defaultdict(list))
    for row in seed_table.get("rows") or []:
        if row[md_i] is not None:
            values[str(laws[row[law_i]])][int(row[n_i])].append(float(row[md_i]))
    return {law: {n: round(sum(v) / len(v), 4) for n, v in sorted(by_n.items())} for law, by_n in values.items()}


def build_law_ledger(candidates: list[dict], seed_table: dict, laws: list[dict], *, cap: float,
                     measurements: list[dict] | None = None) -> dict:
    from graph_scale_dynamics.research.curvature_reading import kappa_by_law, outcome_by_law
    measured = mean_degrees(seed_table)
    curvature, outcome = kappa_by_law(measurements), outcome_by_law(measurements)
    fate = {str(row.get("candidate_id")): [row.get("rule"), row.get("at_n")] for row in laws or []}
    rows, pairs, kinds, l2_pairs = [], defaultdict(list), defaultdict(int), defaultdict(list)
    for candidate in candidates or []:
        cid, spec = str(candidate.get("candidate_id")), candidate.get("spec") or {}
        kind = reading_kind(spec)
        kinds[kind] += 1
        by_n = measured.get(cid) or {}
        entry = {"candidate_id": cid, "spec": compact_spec(spec), "kind": kind, "fate": fate.get(cid),
                 "mean_degree": {str(n): v for n, v in by_n.items()}}
        entry["admitted_utc"] = candidate.get("created_utc")
        if curvature.get(cid):
            entry["kappa"] = {str(n): v for n, v in curvature[cid].items()}
        if cid in outcome:
            entry["finite_at_65536"] = outcome[cid]
        if COMPARED_AT in by_n:
            entry["l2"] = ledger_prediction(spec, COMPARED_AT, cap)
            l2_pairs[entry["l2"][1]].append((entry["l2"][0], by_n[COMPARED_AT]))
        if kind == KIND_DEGREES:
            predicted = predicted_mean_degree(spec, COMPARED_AT, cap)
            entry["predicted"] = predicted
            if predicted is not None and COMPARED_AT in by_n:
                pairs[entry["spec"]["regime"]].append((predicted["mean_degree"], by_n[COMPARED_AT]))
        rows.append(entry)
    every = [pair for values in pairs.values() for pair in values]
    return {"contract": LEDGER_CONTRACT, "laws": len(rows), "by_kind": dict(kinds), "compared_at": COMPARED_AT,
            "mean_degree_cap": cap,
            "prediction": {"all": accuracy(every), **{regime: accuracy(v) for regime, v in sorted(pairs.items())}},
            "prediction_l2": {stratum: accuracy(v) for stratum, v in sorted(l2_pairs.items())},
            "reading": ("A law that sees only degrees is predicted by arithmetic before its chain runs "
                        "(research/degree_prediction.py): its mean degree at N = 4,096 against the measured one, "
                        "over its seeds. Nothing here is fitted to this campaign."),
            "rows": rows}
