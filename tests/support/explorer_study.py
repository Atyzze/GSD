from __future__ import annotations

import json
import random
from pathlib import Path

BASE = (64, 256, 1024, 4096)
OPS = ("degree_anchor", "square_count", "triangle_count", "wedge_count", "edge_count", "degree_square_sum")


def _law_numbers(rng: random.Random, whole: bool) -> dict:
    k = float(rng.choice((3, 4, 5, 6))) if whole else round(rng.uniform(2.6, 6.4), 3)
    return {"k": k, "d_s": rng.uniform(1.0, 4.0)}


def _phenotype(rng: random.Random, numbers: dict, extension: bool) -> dict:
    probes = {p: [] for p in ("d_s", "d_V", "d_B", "d_w")}
    errors = {p: [] for p in probes}
    per_n = {}
    for i, n in enumerate(BASE):
        d_s = numbers["d_s"] + 0.1 * i + rng.uniform(-0.2, 0.2)
        values = {"d_s": d_s, "d_V": d_s + rng.uniform(-0.4, 0.4), "d_B": d_s + rng.uniform(-0.6, 0.3),
                  "d_w": rng.choice((2.0, 2.5)) + rng.uniform(-0.1, 0.1)}
        if i == 0:
            values["d_B"] = None
        for p, v in values.items():
            probes[p].append(v)
            errors[p].append(None if v is None else rng.uniform(0.01, 0.2))
        per_n[str(n)] = {"mean_degree": numbers["k"] + (0.0 if float(numbers["k"]).is_integer() else rng.uniform(-0.01, 0.01)),
                         "max_degree": int(numbers["k"]) + 3,
                         "census": {"squares": {"mean": rng.uniform(0, 2) * n}, "triangles": {"mean": rng.uniform(0, 0.5) * n},
                                    "spectral_gap": {"mean": rng.uniform(0.0001, 0.05)},
                                    "assortativity": {"mean": rng.uniform(-0.3, 0.3)},
                                    "largest_component_diameter": {"mean": float(rng.randint(5, 40))}}}
    ph = {"base_sizes": list(BASE), "probe_vectors": probes, "probe_se_vectors": errors, "per_n": per_n,
          "clustering_vector": [rng.uniform(0, 0.3) for _ in BASE],
          "half_volume_radius_vector": [2.0 + i for i, _ in enumerate(BASE)],
          "connected_fraction_vector": [1.0 for _ in BASE], "two_core_fraction_vector": [0.9 for _ in BASE]}
    if extension:
        d_s = numbers["d_s"] + 0.5
        ph.update({"extension_sizes": [16384], "extension_probe_vectors": {"d_s": [d_s], "d_V": [d_s], "d_B": [None],
                                                                          "d_w": [None]},
                   "extension_probe_se_vectors": {"d_s": [0.1], "d_V": [0.1], "d_B": [None], "d_w": [None]},
                   "extension_mean_degree_vector": [numbers["k"]], "extension_clustering_vector": [0.01],
                   "extension_half_volume_radius_vector": [9.0], "extension_connected_fraction_vector": [1.0]})
    return ph


def write_study(root: Path, *, laws: int = 40, ledger_only: int = 5, seed: int = 0, growth: bool = False,
                campaigns: tuple = ((True, 16.0), (True, 32.0), (False, 16.0), (False, 32.0)),
                front: bool = False) -> Path:
    rng = random.Random(seed)
    study = Path(root) / "study_999_2026-10-03T00-00-00Z"
    study.mkdir(parents=True)
    records = []
    for c, (zero, cap) in enumerate(campaigns, start=1):
        part = study / f"campaign_{c}_reports_2026-10-03T00-00-00Z_abcdef{c}"
        (part / "evidence").mkdir(parents=True)
        label = f"{'zero' if zero else 'finite'} temperature, mean degree to {int(cap)}"
        record = {"campaign_id": str(c), "name": f"engine_survey: {label}", "bundle": part.name,
                  "quadrant": {"label": label, "zero_temperature": zero, "dense_cap": cap}}
        specimens, ledger, plan, given_chains, primaries, chains = [], [], [], {}, {}, []
        for j in range(laws + ledger_only):
            cid = f"{c:02d}{j:04d}" + "ab" * 29
            numbers = _law_numbers(rng, whole=j % 3 != 0)
            if j < laws:
                specimens.append({"candidate_id": cid, "dimensional_class": rng.choice(("STABLE_SOME_PROBES",
                                                                                         "DEGRADED_WITH_N")),
                                  "connectivity_class": "ROBUST_COHERENT",
                                  "phenotype": _phenotype(rng, numbers, extension=j % 4 == 0)})
            rungs = BASE if j < laws else BASE[:2]
            ledger.append({"candidate_id": cid, "fate": ["base_block", 4096] if j < laws else ["empty", 256],
                           "kind": rng.choice(("sees cycles", "degree sequence only")),
                           "mean_degree": {str(n): numbers["k"] for n in rungs},
                           "kappa": {str(n): round(rng.uniform(-1, 0.3), 4) for n in rungs},
                           "spec": {"beta": round(rng.uniform(0.5, 10), 4), "locality": round(rng.uniform(0, 1), 3),
                                    "swap_share": round(rng.uniform(0, 1), 3), "sweeps": rng.choice((20, 40, 60)),
                                    "local_move": "toggle", "zero_temperature": zero,
                                    "terms": [[op, None, round(rng.uniform(-1, 1), 4), "one", None]
                                              for op in rng.sample(OPS, rng.randint(1, 3))]}})
            if growth and c == 1:
                plan.append({"candidate_id": cid, "label": f"L{j}", "role": "anchor" if j % 2 else "neighbour",
                             "given_start": {"family": "random_geometric_2d_degree_4"}})
                given_chains[cid] = {str(n): {"d_s": {"mean": 1.8 + 0.01 * j}, "kappa": {"mean": -0.1},
                                       "half_volume_radius": {"mean": 10.0 + n / 1024}} for n in rungs}
                primaries[cid] = {str(n): {"d_s": {"mean": 3.0}, "kappa": {"mean": -0.5},
                                           "half_volume_radius": {"mean": 4.0}} for n in rungs}
                chains.append({"candidate_id": cid, "top_n": rungs[-1], "empty": "no finite dimension",
                               "given": "finite dimension" if j % 2 else "not decidable yet",
                               "from_empty_implied_d_s": None, "given_implied_d_s": 2.0})
        engine = {"law_ledger": {"mean_degree_cap": cap, "rows": ledger}}
        if growth and c == 1:
            tree = Path(root) / "tree"
            (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True, exist_ok=True)
            (tree / "graph_scale_dynamics" / "resources" / "readings" / "study_999_laws.json").write_text(json.dumps({"laws": plan}))
            record["growth_study"] = {"plan": "docs/readings/study_999_laws.json"}
            record["quadrant"] = {"label": "not set (a growth study)"}
            record["name"] = "campaign-growth-study-999"
            engine["the_record"] = {"structure_by_the_committed_rule": {
                "given_probes_by_law": given_chains, "from_empty_probes_by_law": primaries, "chains_by_law": chains}}
        if front:
            engine["gate_tree"] = _gate_tree(ledger, salted_every=3)
        (part / "05-phenotypes.json").write_text(json.dumps({"body": {"specimens": specimens}}))
        (part / "28-decision-engine.json").write_text(json.dumps({"body": engine}))
        if front:
            model = ({"available": True, "base_rate_per_attempted_move": 4.5e-06,
                      "operator_multipliers": {"degree_anchor": 1.08, "square_count": 1.0, "triangle_count": 0.70},
                      "held_out_accuracy": {"median_factor_error": 1.64, "n": 42},
                      "observed_rate_spread": {"max_over_min": 40.6}} if c == 1 else
                     {"available": False, "reason": "3 usable operator signatures; a fit needs at least 12"})
            (part / "16-efficiency.json").write_text(json.dumps({"body": {"cost_model": model}}))
        (part / "evidence" / "probe_calibration.json").write_text(json.dumps(calibration_table()))
        records.append(record)
    (study / "study.json").write_text(json.dumps({"study_id": "999", "built_utc": "2026-10-03T00:00:00Z",
                                                  "build_number": 572, "campaigns": records}))
    return study


def _gate_tree(ledger: list[dict], *, salted_every: int) -> dict:
    from graph_scale_dynamics.decisions import gates as G
    from graph_scale_dynamics.research.gate_tree import build_gate_tree
    decisions, graphs = {}, {}
    for i, row in enumerate(ledger):
        rule, top = row["fate"]
        rows = []
        for step, n in enumerate(n for n in BASE if n <= top):
            last = n == top
            action = "stop" if last and rule in G.BY_NAME else "run_next"
            facts = {"salted": ["empty"]} if n == 256 and action == "run_next" and i % salted_every == 0 else {}
            rows.append({"decision_id": f"{i:05d}-{step}", "at_n": n, "action": action,
                         "rule": rule if last else "base_block", "facts": facts})
            graphs[(row["candidate_id"], n)] = 3
        decisions[row["candidate_id"]] = rows
    return build_gate_tree(decisions, graphs)


def calibration_table() -> dict:
    cells = {}
    for family, (d_s, k) in {"periodic_square_lattice": (1.9, 4.0), "periodic_cubic_lattice": (2.8, 6.0)}.items():
        for n in (64, 256, 1024):
            for seed in range(3):
                value = d_s + 0.02 * seed + (0.05 if n == 1024 else 0.0)
                cells[f"{family}|{n}|{seed}"] = {
                    "family": family, "n": n, "status": "ok", "structure": {"mean_degree": k},
                    "channels": {p: {"valid": True, "value": value + (0.1 if p == "d_w" else 0.0)}
                                 for p in ("d_s", "d_V", "d_B", "d_w")}}
    return {"contract": "a made-up table", "cells": cells}
