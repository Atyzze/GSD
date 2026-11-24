from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.dsl import dsl

BOLTZMANN_KNOWN_ANSWERS_CONTRACT = "gsd-boltzmann-known-answers-1"
DRAWN, REACH, CONTROL = "drawn", "reach", "control"
SPREAD, SPAN = "spread", "span"
START = "exact_draw"
ENERGY_AGREES_WITHIN = 1e-9


def pairs_of(n: int) -> list[tuple[int, int]]:
    return list(itertools.combinations(range(n), 2))


def edges_of(mask: int, n: int) -> list[tuple[int, int]]:
    return [pair for bit, pair in enumerate(pairs_of(n)) if mask >> bit & 1]


def mask_of(edges, n: int) -> int:
    index = {pair: bit for bit, pair in enumerate(pairs_of(n))}
    return sum(1 << index[(min(int(a), int(b)), max(int(a), int(b)))] for a, b in edges)


def graphs(n: int) -> int:
    return 1 << len(pairs_of(n))


def _term(op: str, c0: float, k: int | None) -> dict:
    return {"op": op, "params": {} if k is None else {"k": int(k)}, "coeff": {"c0": c0, "scale": "one"}}


def anchor_of(op: str, k_draw: float, n: int) -> int | None:
    if "k" not in dsl.OPERATORS[op]["params"]:
        return None
    return 1 + min(n - 2, int(k_draw * (n - 1)))


def law_of(terms: list[dict], dynamics: dict) -> dict:
    swap = float(dynamics["swap"])
    settings = {"kind": "equilibrium", "beta": float(dynamics.get("beta", 1.0)),
                "move_mix": {"add": (1.0 - swap) / 2.0, "delete": (1.0 - swap) / 2.0, "swap": swap},
                "sweeps": int(dynamics["sweeps"])}
    if float(dynamics["locality"]) > 0.0:
        settings["locality"] = float(dynamics["locality"])
    if dynamics.get("local_move", "toggle") != "toggle":
        settings["local_move"] = dynamics["local_move"]
    return {"dsl_version": 1, "init": "empty", "terms": terms, "dynamics": settings}


def unit_spread(op: str, k: int | None, n: int, energy, of: str = SPREAD) -> float:
    spec = law_of([_term(op, 1.0, k)], {"swap": 0.0, "locality": 0.0, "sweeps": 1})
    values = np.array([energy(spec, n, edges_of(mask, n)) for mask in range(graphs(n))], dtype=float)
    return float(values.max() - values.min()) if of == SPAN else float(values.std())


def _drawn_term(rng: np.random.Generator, op: str, strengths: dict, share: float = 1.0) -> dict:
    strength = math.exp(rng.uniform(math.log(strengths["min"]), math.log(strengths["max"]))) * share
    return {"op": op, "strength": round(strength, 6), "sign": int(rng.choice([-1, 1])),
            "k_draw": round(float(rng.random()), 6),
            **({"strength_of": strengths["of"]} if "of" in strengths else {})}


def draw_laws(criterion: dict) -> list[dict]:
    rng = np.random.default_rng(criterion["seed"])
    drawn = criterion["drawn"]
    laws = []
    first = {}
    for op in criterion["terms"]:
        for index in range(drawn["alone_per_term"]):
            term = _drawn_term(rng, op, drawn["strength"])
            first.setdefault(op, term)
            laws.append({"name": f"alone_{op}_{index + 1}", "kind": DRAWN, "terms": [term],
                         "locality": round(float(rng.uniform(0.0, drawn["locality_below"])), 6),
                         "swap": round(float(rng.uniform(0.0, drawn["swap_below"])), 6),
                         "sweeps": drawn["sweeps"]})
    for index in range(drawn["mixed"]):
        while True:
            count = int(rng.choice(drawn["mixed_term_counts"]))
            ops = [str(op) for op in rng.choice(criterion["terms"], size=count, replace=False)]
            if sum(dsl.OPERATORS[op]["cost"] for op in ops) <= drawn["complexity_budget"]:
                break
        laws.append({"name": f"mixed_{index + 1}", "kind": DRAWN,
                     "terms": [_drawn_term(rng, op, drawn["strength"], 1.0 / count) for op in ops],
                     "locality": round(float(rng.uniform(0.0, drawn["locality_below"])), 6),
                     "swap": round(float(rng.uniform(0.0, drawn["swap_below"])), 6),
                     "sweeps": drawn["sweeps"]})
    reach = criterion["reach"]
    for op in criterion["terms"]:
        for locality in reach["localities"]:
            laws.append({"name": f"reach_{op}_locality_{locality:g}", "kind": REACH, "terms": [first[op]],
                         "locality": locality, "swap": reach["swap"], "sweeps": reach["sweeps"]})
    for control in criterion["controls"]:
        laws.append({"name": control["name"], "kind": CONTROL, "expected": control["expected"],
                     "terms": [dict(term) for term in control["terms"]], "locality": control["locality"],
                     "swap": control["swap"], "beta": float(control.get("beta", 1.0)), "sweeps": control["sweeps"],
                     **({"local_move": control["local_move"]} if control.get("local_move", "toggle") != "toggle"
                        else {})})
    return laws


def realise(law: dict, n: int, energy, spreads: dict | None = None) -> dict | None:
    spreads = {} if spreads is None else spreads
    terms = []
    for term in law["terms"]:
        k = anchor_of(term["op"], term.get("k_draw", 0.0), n) if "k" not in term else term["k"]
        if "c0" in term:
            terms.append(_term(term["op"], float(term["c0"]), k))
            continue
        key = (term["op"], k, n, term.get("strength_of", SPREAD))
        if key not in spreads:
            spreads[key] = unit_spread(term["op"], k, n, energy, key[3])
        if spreads[key] <= 0.0:
            return None
        terms.append(_term(term["op"], float(f"{term['sign'] * term['strength'] / spreads[key]:.12g}"), k))
    return law_of(terms, law)


def energies_of(spec: dict, n: int, energy, reverse: bool = False) -> np.ndarray:
    out = np.empty(graphs(n))
    for mask in range(graphs(n)):
        edges = edges_of(mask, n)
        out[mask] = energy(spec, n, edges[::-1] if reverse else edges)
    return out


def exact_measure(energies: np.ndarray, factor: float = 1.0) -> np.ndarray:
    weights = np.exp(-factor * (np.asarray(energies, dtype=float) - float(np.min(energies))))
    return weights / weights.sum()


def pooled_chi_square(counts, measure, at_least: float) -> dict:
    counts = np.asarray(counts, dtype=float)
    total = float(counts.sum())
    order = np.argsort(measure, kind="stable")
    cells: list[list[float]] = []
    expected = observed = 0.0
    for index in order:
        expected += float(measure[index]) * total
        observed += float(counts[index])
        if expected >= at_least:
            cells.append([expected, observed])
            expected = observed = 0.0
    if expected > 0.0 or observed > 0.0:
        if cells:
            cells[-1][0] += expected
            cells[-1][1] += observed
        else:
            cells.append([expected, observed])
    distance = 0.5 * float(np.abs(counts / total - measure).sum())
    if len(cells) < 2:
        return {"cells": len(cells), "chi_square": None, "p": None, "distance": round(distance, 6)}
    statistic = sum((seen - want) ** 2 / want for want, seen in cells)
    return {"cells": len(cells), "chi_square": round(statistic, 4),
            "p": float(stats.chi2.sf(statistic, len(cells) - 1)), "distance": round(distance, 6)}


def taken(counts: dict) -> dict:
    out = {"local": 0, "global_toggle": 0, "swap": 0}
    for key, count in counts.items():
        kind, scope, _sign, outcome = str(key).split(".")
        if outcome == "accepted":
            out["swap" if kind == "swap" else "local" if scope == "local" else "global_toggle"] += int(count)
    return out


def cell_seed(criterion: dict, law_index: int, n: int, engine_name: str) -> int:
    return (int(criterion["seed"]) * 1_000_003 + law_index * 10_007 + n * 101
            + criterion["engines"][engine_name]["seed_offset"])


def measure_cell(criterion: dict, law_index: int, law: dict, n: int, engine_name: str, engine: dict) -> dict:
    row = {"law": law["name"], "kind": law["kind"], "n": n, "engine": engine_name,
           **({"expected": law["expected"]} if "expected" in law else {})}
    spec = realise(law, n, engine["energy"])
    if spec is None:
        return {**row, "built": False, "why": "a term is the same on every graph of this size"}
    runs = int(criterion["engines"][engine_name]["runs"])
    energies = energies_of(spec, n, engine["energy"])
    measure = exact_measure(energies)
    seed = cell_seed(criterion, law_index, n, engine_name)
    starts = np.random.default_rng(seed).choice(graphs(n), size=runs, p=measure)
    given, from_empty = np.zeros(graphs(n)), np.zeros(graphs(n))
    moved = left = off_ledger = 0
    accepted = {"local": 0, "global_toggle": 0, "swap": 0}
    for index, start in enumerate(starts.tolist()):
        envelope = engine["run"](spec, n, seed + index, record_points=2,
                                 given_start={"edges": edges_of(start, n), "family": START})
        ended = CL.block(envelope, CL.GIVEN)
        end = mask_of(ended["edge_list"], n)
        given[end] += 1
        from_empty_end = mask_of(CL.edges(envelope, CL.FROM_EMPTY), n)
        from_empty[from_empty_end] += 1
        took = taken(ended["accounting"]["counts"])
        for kind, count in took.items():
            accepted[kind] += count
        moved += bool(sum(took.values()))
        left += end != start
        scale = max(1.0, float(np.max(np.abs(energies))))
        off_ledger += abs(float(ended["energy"]) - energies[end]) > 1e-6 * scale
        off_ledger += abs(float(CL.record(envelope, CL.FROM_EMPTY)["final"]["energy"]) - energies[from_empty_end]) > 1e-6 * scale
    at_least = criterion["rule"]["pooled_cells_expect_at_least"]
    wrong = {f"{factor:g}": pooled_chi_square(given, exact_measure(energies, factor), at_least)["p"]
             for factor in criterion["wrong_measures"]}
    return {**row, "built": True, "runs": runs, "seed": seed, "sweeps": spec["dynamics"]["sweeps"],
            "locality": spec["dynamics"].get("locality", 0.0), "swap": spec["dynamics"]["move_mix"]["swap"],
            "beta": spec["dynamics"]["beta"],
            "terms": [{"op": term["op"], "c0": term["coeff"]["c0"], **term["params"]} for term in spec["terms"]],
            "energy_span": round(float(np.max(energies) - np.min(energies)), 6),
            "largest_weight": round(float(measure.max()), 6),
            "given": pooled_chi_square(given, measure, at_least),
            "empty": pooled_chi_square(from_empty, measure, at_least),
            "given_against_wrong_measures": wrong,
            "runs_that_moved": moved, "runs_that_left_their_start": left,
            "accepted": accepted, "ends_off_the_ledger": int(off_ledger)}


def energies_agree(criterion: dict, laws: list[dict], engines: dict) -> dict:
    worst = {"between_engines": 0.0, "between_orders": 0.0}
    checked = 0
    names = sorted(engines)
    for law in laws:
        for n in criterion["sizes"]:
            spec = realise(law, n, engines[names[0]]["energy"])
            if spec is None:
                continue
            forward = {name: energies_of(spec, n, engines[name]["energy"]) for name in names}
            scale = max(1.0, float(np.max(np.abs(forward[names[0]]))))
            for name in names:
                backward = energies_of(spec, n, engines[name]["energy"], reverse=True)
                worst["between_orders"] = max(worst["between_orders"],
                                              float(np.max(np.abs(backward - forward[name]))) / scale)
            for name in names[1:]:
                worst["between_engines"] = max(worst["between_engines"],
                                               float(np.max(np.abs(forward[name] - forward[names[0]]))) / scale)
            checked += graphs(n)
    return {"graphs_checked": checked, "engines": names, **worst,
            "agree": max(worst.values()) <= ENERGY_AGREES_WITHIN}


def tests_judged(rows: list[dict]) -> int:
    kept = sum(1 for row in rows if row.get("built") and (row["kind"] != CONTROL or row.get("expected") == "kept"))
    reached = sum(1 for row in rows if row.get("built") and row["kind"] == REACH)
    return kept + reached


def judge(criterion: dict, rows: list[dict], energies: dict) -> dict:
    built = [row for row in rows if row.get("built")]
    alpha = criterion["rule"]["family_wise"] / max(1, tests_judged(built))

    def holds(found: dict) -> bool:
        return found["p"] is not None and found["p"] >= alpha

    cells = []
    for row in built:
        judged_kept = row["kind"] != CONTROL or row["expected"] == "kept"
        entry = {**row, "kept": holds(row["given"]), "reached": holds(row["empty"]),
                 "kept_is_judged": judged_kept, "reached_is_judged": row["kind"] == REACH}
        entry["wrong_measures_refused"] = {factor: (p is not None and p < alpha)
                                           for factor, p in row["given_against_wrong_measures"].items()}
        cells.append(entry)
    k1_cells = [cell for cell in cells if cell["kept_is_judged"]]
    k2_cells = [cell for cell in cells if cell["reached_is_judged"]]
    k1 = bool(k1_cells) and all(cell["kept"] for cell in k1_cells)
    k2 = bool(k2_cells) and all(cell["reached"] for cell in k2_cells)
    k3 = bool(energies["agree"]) and not any(cell["ends_off_the_ledger"] for cell in cells)
    alive = {}
    for name in sorted({cell["engine"] for cell in cells}):
        own = [cell for cell in cells if cell["engine"] == name and cell["kind"] == DRAWN]
        alive[name] = {kind: sum(cell["accepted"][kind] for cell in own)
                       for kind in ("local", "global_toggle", "swap")}
    k4 = bool(alive) and all(all(count > 0 for count in kinds.values()) for kinds in alive.values())
    predictions = [{"law": cell["law"], "n": cell["n"], "engine": cell["engine"], "expected": cell["expected"],
                    "kept": cell["kept"], "right": cell["kept"] == (cell["expected"] == "kept")}
                   for cell in cells if cell["kind"] == CONTROL]
    by_term = {}
    for cell in cells:
        if cell["kind"] == CONTROL:
            continue
        for term in cell["terms"]:
            found = by_term.setdefault(term["op"], {"cells": 0, "kept": 0, "reach_cells": 0, "reached": 0})
            found["cells"] += 1
            found["kept"] += cell["kept"]
            found["reach_cells"] += cell["reached_is_judged"]
            found["reached"] += cell["reached_is_judged"] and cell["reached"]
    refused = {factor: {"refused": sum(1 for cell in k1_cells if cell["wrong_measures_refused"][factor]),
                        "of": len(k1_cells)} for factor in (f"{f:g}" for f in criterion["wrong_measures"])}
    return {"contract": BOLTZMANN_KNOWN_ANSWERS_CONTRACT, "alpha": alpha, "tests_judged": tests_judged(built),
            "k1_the_measure_is_kept": k1, "k2_the_measure_is_reached": k2, "k3_the_energies_agree": k3,
            "k4_every_kind_of_move_is_taken": k4, "passes": k1 and k2 and k3 and k4,
            "kept": {"held": sum(cell["kept"] for cell in k1_cells), "of": len(k1_cells)},
            "reached": {"held": sum(cell["reached"] for cell in k2_cells), "of": len(k2_cells)},
            "energies": energies, "accepted_by_engine": alive, "by_term": by_term,
            "wrong_measures": refused, "predictions": predictions,
            "predictions_right": sum(1 for p in predictions if p["right"]),
            "not_built": [row for row in rows if not row.get("built")], "cells": cells}


def _p(found: dict) -> str:
    return "unread" if found["p"] is None else f"{found['p']:.3g}"


def render(judged: dict) -> str:
    lines = ["# The engines' chains against exact Boltzmann measures", "",
             f"{judged['contract']}: on every graph of 4 and of 5 nodes the engine's own energy gives the exact "
             "measure of a law at a finite temperature. Each run starts one chain at a graph drawn from that "
             "measure and one at the empty graph, and the graphs the chains end on are counted against the "
             "measure (a chi-square on the graphs, the rare ones pooled). A chain that keeps the measure ends "
             "distributed as it started, however long it ran, so the given chain tests the balance of the moves without "
             "assuming the chain mixed; the chain from empty tests that the measure is reached from empty. A count agrees "
             f"when its p is at least {judged['alpha']:.3g}, which is 1% shared over the {judged['tests_judged']} "
             "counts judged.", "",
             f"* K1, the measure is kept: **{judged['kept']['held']} of {judged['kept']['of']}** cells "
             f"({'held' if judged['k1_the_measure_is_kept'] else 'missed'}).",
             f"* K2, the measure is reached from empty: **{judged['reached']['held']} of {judged['reached']['of']}** "
             f"cells ({'held' if judged['k2_the_measure_is_reached'] else 'missed'}).",
             f"* K3, the energies agree: the engines ({', '.join(judged['energies']['engines'])}) differ by at most "
             f"{judged['energies']['between_engines']:.3g} of the largest energy on "
             f"{judged['energies']['graphs_checked']:,} graphs, the two orders of a graph's edges by at most "
             f"{judged['energies']['between_orders']:.3g}, and "
             f"{sum(cell['ends_off_the_ledger'] for cell in judged['cells'])} chain ends carried an energy that was "
             f"not their graph's ({'held' if judged['k3_the_energies_agree'] else 'missed'}).",
             "* K4, every kind of move is taken: "
             + "; ".join(f"{name}: {kinds['local']:,} local toggles, {kinds['global_toggle']:,} other toggles, "
                         f"{kinds['swap']:,} swaps accepted" for name, kinds in judged["accepted_by_engine"].items())
             + f" ({'held' if judged['k4_every_kind_of_move_is_taken'] else 'missed'}).",
             "", f"The criterion {'passes' if judged['passes'] else 'does not pass'}.", "",
             "## By term", "",
             "| term | cells | kept | reached from empty |", "|---|---:|---:|---:|"]
    for op, found in judged["by_term"].items():
        lines.append(f"| `{op}` | {found['cells']} | {found['kept']} of {found['cells']} | "
                     f"{found['reached']} of {found['reach_cells']} |")
    lines += ["", "## What the count can tell apart", "",
              "The same counts read against a wrong measure, the law's energies multiplied by a factor:", "",
              "| factor on the energies | cells refusing the wrong measure |", "|---:|---:|"]
    for factor, found in judged["wrong_measures"].items():
        lines.append(f"| {factor} | {found['refused']} of {found['of']} |")
    by_cell = {(cell["law"], cell["n"], cell["engine"]): cell for cell in judged["cells"]}
    hot = any(float(by_cell[(p["law"], p["n"], p["engine"])].get("beta", 1.0)) != 1.0 for p in judged["predictions"])
    lines += ["", "## The controls", ""]
    if hot:
        lines += ["A control's chain runs at its own beta and is judged against the law's measure at beta 1; the last "
                  "column reads the same count against the measure its chain keeps, the energies multiplied by its "
                  "beta.", "", "| law | nodes | engine | its chain's beta | expected | kept | p | right | "
                  "p at its chain's beta |", "|---|---:|---|---:|---|---|---:|---|---:|"]
    else:
        lines += ["| law | nodes | engine | expected | kept | p | right |", "|---|---:|---|---|---|---:|---|"]
    for p in judged["predictions"]:
        cell = by_cell[(p["law"], p["n"], p["engine"])]
        beta = float(cell.get("beta", 1.0))
        said = f"{'kept' if p['kept'] else 'refused'} | {_p(cell['given'])} | {'right' if p['right'] else 'wrong'}"
        if not hot:
            lines.append(f"| `{p['law']}` | {p['n']} | {p['engine']} | {p['expected']} | {said} |")
            continue
        own = (_p(cell["given"]) if beta == 1.0
               else _p({"p": cell["given_against_wrong_measures"].get(f"{beta:g}")}))
        lines.append(f"| `{p['law']}` | {p['n']} | {p['engine']} | {beta:g} | {p['expected']} | {said} | {own} |")
    missed = [cell for cell in judged["cells"]
              if (cell["kept_is_judged"] and not cell["kept"]) or (cell["reached_is_judged"] and not cell["reached"])]
    lines += ["", "## The cells that missed", ""]
    if not missed:
        lines.append("None.")
    else:
        lines += ["| law | nodes | engine | locality | swap share | given p | from empty p |",
                  "|---|---:|---|---:|---:|---:|---:|"]
        for cell in missed:
            lines.append(f"| `{cell['law']}` | {cell['n']} | {cell['engine']} | {cell['locality']:g} | "
                         f"{cell['swap']:g} | {_p(cell['given'])} | {_p(cell['empty'])} |")
    lines += ["", "## Every cell", "",
              "| law | nodes | engine | runs | locality | swap share | energy span | given p | from empty p | "
              "runs that moved |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for cell in judged["cells"]:
        lines.append(f"| `{cell['law']}` | {cell['n']} | {cell['engine']} | {cell['runs']:,} | {cell['locality']:g} | "
                     f"{cell['swap']:g} | {cell['energy_span']:.2f} | {_p(cell['given'])} | {_p(cell['empty'])} | "
                     f"{cell['runs_that_moved']:,} |")
    if judged["not_built"]:
        lines += ["", "Not built: " + "; ".join(f"`{row['law']}` at {row['n']} ({row['why']})"
                                                for row in judged["not_built"]) + "."]
    lines.append("")
    return "\n".join(lines)
