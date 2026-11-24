#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.decisions.let_through import NOT_A_VERDICT, WITHHOLDING_ACTIONS, salted_of  # noqa: E402

CONTRACT = "gsd-budget-reading-1"
CONNECTED = 0.9
MULTIPLES = (2, 4, 8)
TIMED_FROM_SECONDS = 1.0
WORST = 12
DEGREE_BANDS = ((0.0, 1.0), (1.0, 4.0), (4.0, 8.0), (8.0, 16.0), (16.0, float("inf")))
OVER_BUDGET = "over_budget"
CEILING = "ceiling"


def _ndjson(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _facts(row: dict) -> dict:
    found = row.get("facts_json", row.get("facts"))
    if isinstance(found, str):
        try:
            found = json.loads(found)
        except ValueError:
            return {}
    return found if isinstance(found, dict) else {}


def _quantile(values: list[float], share: float) -> float | None:
    ordered = sorted(values)
    return ordered[int(share * (len(ordered) - 1))] if ordered else None


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


def _sig(value: float | None) -> float | None:
    return None if value is None else float(f"{float(value):.3g}")


def seed_rows(body: dict) -> list[dict]:
    seeds = body.get("seeds") or {}
    columns, laws = seeds.get("columns") or [], seeds.get("laws") or []
    out = []
    for values in seeds.get("rows") or []:
        row = dict(zip(columns, values, strict=True))
        law = row.get("law")
        row["law"] = str(laws[law]) if isinstance(law, int) and 0 <= law < len(laws) else str(law)
        out.append(row)
    return out


def campaigns_of(root: Path) -> list[tuple[str, dict]]:
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    out = []
    for entry in study.get("campaigns") or []:
        if entry.get("controls") is not None:
            continue
        report = root / str(entry.get("bundle")) / "28-decision-engine.json"
        if not report.is_file():
            continue
        body = json.loads(report.read_text(encoding="utf-8")).get("body") or {}
        out.append((str(entry.get("campaign_id")), body))
    return out


def gate_sizes(decisions: list[dict]) -> dict:
    found: dict = defaultdict(set)
    for row in decisions:
        if row.get("at_n") is None:
            continue
        key = (str(row.get("campaign_id")), str(row.get("candidate_id")))
        rule, action = str(row.get("rule")), str(row.get("action"))
        facts = _facts(row)
        if salted_of(facts.get("salted")) or (action in WITHHOLDING_ACTIONS and rule not in NOT_A_VERDICT
                                              and rule != "failed"):
            found[key].add(int(row["at_n"]))
    return found


def stopped_over_budget(decisions: list[dict]) -> dict:
    out = {}
    for row in decisions:
        if str(row.get("rule")) != OVER_BUDGET or row.get("at_n") is None:
            continue
        facts = _facts(row)
        chunk = facts.get("first_chunk") or {}
        budget, predicted = chunk.get("budget"), chunk.get("predicted")
        out[(str(row.get("campaign_id")), str(row.get("candidate_id")))] = {
            "at_n": int(row["at_n"]), "budget": budget, "predicted": predicted,
            "multiple": _round(predicted / budget, 2) if budget and predicted is not None else None,
            "mean_degree": _round(facts.get("mean_degree"), 2),
            "connected_fraction": _round(facts.get("connected_fraction"), 3),
            "seeds_cut": sum(1 for use in facts.get("budget_use") or [] if use.get("termination") == "budget")}
    return out


def connected_by_rung(rungs: list[dict]) -> dict:
    return {(str(row.get("campaign_id")), str(row.get("candidate_id")), int(row["n"])): row.get("connected_fraction")
            for row in rungs if row.get("n") is not None}


def _moves(row: dict) -> int:
    return int(((row.get("work_parts") or {}).get("moves")) or 0)


def _seconds_a_unit(row: dict) -> float | None:
    seconds, units = row.get("simulation_seconds"), row.get("work_units")
    if not units or seconds is None or float(seconds) < TIMED_FROM_SECONDS:
        return None
    return float(seconds) / float(units)


def needed_multiple(row: dict, below: list[dict], ratio: float) -> float | None:
    capped = [_moves(seed) for seed in below if seed.get("ended") == CEILING and _moves(seed) > 0]
    if not capped or not _moves(row) or not row.get("work_budget"):
        return None
    units_a_move = float(row["work_units"]) / _moves(row)
    return max(capped) * ratio * units_a_move / float(row["work_budget"])


def _leading_part(row: dict, weights: dict) -> str | None:
    parts = row.get("work_parts") or {}
    weighed = {name: int(parts.get(name) or 0) * int(weights.get(name) or 0) for name in weights}
    return max(weighed, key=weighed.get) if weighed and max(weighed.values()) > 0 else None


def read(root: Path) -> dict:
    root = Path(root)
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    decisions = _ndjson(root / "tables" / "decisions.ndjson.gz")
    connected = connected_by_rung(_ndjson(root / "tables" / "rungs.ndjson.gz"))
    gated, stopped = gate_sizes(decisions), stopped_over_budget(decisions)
    seeds, budgets, weights = [], {}, {}
    for campaign, body in campaigns_of(root):
        for size, units in ((body.get("budgets") or {}).get("in_force") or {}).items():
            budgets.setdefault(int(size), set()).add(int(units))
        weights = weights or dict(((body.get("budgets") or {}).get("unit") or {}).get("weights") or {})
        seeds += [dict(row, campaign=campaign) for row in seed_rows(body)]
    by_law: dict = defaultdict(lambda: defaultdict(list))
    for row in seeds:
        by_law[(row["campaign"], row["law"])][int(row["n"])].append(row)
    sizes = sorted({int(row["n"]) for row in seeds} | set(budgets))
    stopped = {key: value for key, value in stopped.items() if key[0] in {c for c, _ in by_law}}
    rows = []
    for position, n in enumerate(sizes):
        here = [row for row in seeds if int(row["n"]) == n]
        before = sizes[position - 1] if position else None
        cut = [row for row in here if row.get("budget_ended")]
        laws_here = {(row["campaign"], row["law"]) for row in here}
        laws_cut = {(row["campaign"], row["law"]) for row in cut}
        joined = {key for key in laws_here if (connected.get((*key, n)) or 0.0) >= CONNECTED}
        passing = {key for key in laws_here if not any(at <= n for at in gated.get(key, ()))}
        stopped_here = {key: value for key, value in stopped.items() if value["at_n"] == n}
        multiples = [value["multiple"] for value in stopped_here.values() if value["multiple"] is not None]
        needs, extra, upper = [], dict.fromkeys(MULTIPLES, 0.0), dict.fromkeys(MULTIPLES, 0.0)
        for row in cut:
            below = by_law[(row["campaign"], row["law"])].get(before, []) if before else []
            need = needed_multiple(row, below, n / before) if before else None
            if need is not None:
                needs.append(need)
            per_unit = (float(row.get("simulation_seconds") or 0.0) / float(row["work_units"])
                        if row.get("work_units") else 0.0)
            for k in MULTIPLES:
                ceiling = k * float(row.get("work_budget") or 0)
                reach = ceiling if need is None else min(need * float(row.get("work_budget") or 0), ceiling)
                extra[k] += max(0.0, reach - float(row.get("work_units") or 0)) * per_unit
                upper[k] += max(0.0, ceiling - float(row.get("work_units") or 0)) * per_unit
        timed = [value for row in here if (value := _seconds_a_unit(row)) is not None]
        fractions = [float(row["budget_fraction"]) for row in here if row.get("budget_fraction") is not None]
        budget = sorted(budgets.get(n, set()))
        rows.append({
            "n": n, "budget": budget[0] if len(budget) == 1 else budget,
            "budget_a_node": _sig(budget[0] / n) if len(budget) == 1 else None,
            "seeds": len(here), "ended": dict(Counter(str(row.get("ended")) for row in here).most_common()),
            "seeds_cut": len(cut), "laws": len(laws_here), "laws_cut": len(laws_cut),
            "budget_fraction": {"p50": _round(_quantile(fractions, 0.5)), "p90": _round(_quantile(fractions, 0.9)),
                                "p99": _round(_quantile(fractions, 0.99))},
            "core_hours": round(sum(float(row.get("simulation_seconds") or 0.0) for row in here) / 3600, 1),
            "seconds_a_unit": {"p10": _sig(_quantile(timed, 0.1)), "p50": _sig(_quantile(timed, 0.5)),
                               "p90": _sig(_quantile(timed, 0.9)), "seeds": len(timed)},
            "connected_laws": len(joined), "connected_laws_cut": len(joined & laws_cut),
            "other_laws": len(laws_here - joined), "other_laws_cut": len(laws_cut - joined),
            "passed_every_gate": len(passing), "passed_every_gate_then_stopped": len(passing & set(stopped_here)),
            "stopped_over_budget": len(stopped_here),
            "stopped_would_fit": {str(k): sum(1 for m in multiples if m <= k) for k in MULTIPLES},
            "more": {"cut_seeds_estimated": len(needs), "cut_seeds_without_a_ceiling_below": len(cut) - len(needs),
                     "multiple_p50": _round(_quantile(needs, 0.5), 2), "multiple_p90": _round(_quantile(needs, 0.9), 2),
                     "reach_their_end": {str(k): _round(sum(1 for v in needs if v <= k) / len(needs), 2)
                                         if needs else None for k in MULTIPLES},
                     "extra_core_hours": {str(k): round(extra[k] / 3600, 1) for k in MULTIPLES},
                     "extra_core_hours_at_most": {str(k): round(upper[k] / 3600, 1) for k in MULTIPLES}},
        })
    past = [row for row in seeds if (row.get("budget_fraction") or 0) > 1.0]
    worst = sorted(past, key=lambda row: -float(row["budget_fraction"]))[:WORST]
    degree = []
    for n in sizes:
        cells = []
        for low, high in DEGREE_BANDS:
            timed = [value for row in seeds if int(row["n"]) == n and row.get("final_mean_degree") is not None
                     and low <= float(row["final_mean_degree"]) < high
                     and (value := _seconds_a_unit(row)) is not None]
            cells.append({"from": low, "below": None if high == float("inf") else high, "seeds": len(timed),
                          "p50": _sig(_quantile(timed, 0.5))})
        degree.append({"n": n, "bands": cells})
    return {
        "contract": CONTRACT, "bundle": root.name, "study": str(study.get("study_id")),
        "build_number": study.get("build_number"), "built_utc": study.get("built_utc"),
        "campaigns": sorted({c for c, _ in by_law}), "laws": len(by_law), "seeds": len(seeds),
        "core_hours": round(sum(float(row.get("simulation_seconds") or 0.0) for row in seeds) / 3600, 1),
        "connected_from": CONNECTED, "sizes": rows,
        "past_budget": {"seeds": len(past), "past_twice": sum(1 for row in past if row["budget_fraction"] > 2),
                        "past_tenfold": sum(1 for row in past if row["budget_fraction"] > 10),
                        "interrupted": sum(1 for row in past if row.get("interrupted")),
                        "core_hours_past": round(sum(float(row.get("simulation_seconds") or 0.0)
                                                     * (1 - 1 / float(row["budget_fraction"])) for row in past)
                                                 / 3600, 1),
                        "worst": [{"law": row["law"], "campaign": row["campaign"], "n": int(row["n"]),
                                   "seed": row.get("seed"), "ended": row.get("ended"),
                                   "budget_fraction": _round(row["budget_fraction"], 2),
                                   "simulation_seconds": _round(row.get("simulation_seconds"), 1),
                                   "final_mean_degree": _round(row.get("final_mean_degree"), 2),
                                   "leading_part": _leading_part(row, weights),
                                   "interrupted": bool(row.get("interrupted"))} for row in worst]},
        "stopped": sorted(({"law": law, "campaign": campaign, **value} for (campaign, law), value in stopped.items()),
                          key=lambda row: (row["at_n"], -(row["multiple"] or 0), row["law"])),
        "seconds_a_unit_by_mean_degree": degree,
    }


def _n(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def _units(value) -> str:
    if not isinstance(value, (int, float)):
        return "several" if value else "-"
    for scale, name in ((1e12, "T"), (1e9, "G"), (1e6, "M")):
        if value >= scale:
            return f"{value / scale:g} {name}"
    return f"{value:g}"


def _share(part: int, whole: int) -> str:
    return f"{part:,} of {whole:,}" + (f" ({part / whole:.0%})" if whole else "")


def render(result: dict) -> str:
    out = [f"# The budgets in work, from {result['bundle']}", "",
           f"Study {result['study']}, made on build {result['build_number']} at {result['built_utc']}: "
           f"{_n(result['laws'])} laws, {_n(result['seeds'])} seeds, {result['core_hours']} core-hours of simulation "
           "(the controls left out). A seed is cut when its next chunk would not fit its budget; a law is stopped "
           "`over_budget` at a size when its first chunk at the next would not fit, with no let-through.", "",
           "| size | budget | a node | seeds cut | laws cut | budget used, p50 / p90 | laws stopped, next not fitting "
           "| core-hours |", "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in result["sizes"]:
        out.append(f"| {_n(row['n'])} | {_units(row['budget'])} | {_units(row['budget_a_node'])} | "
                   f"{_share(row['seeds_cut'], row['seeds'])} | {_n(row['laws_cut'])} | "
                   f"{row['budget_fraction']['p50']} / {row['budget_fraction']['p90']} | "
                   f"{_n(row['stopped_over_budget'])} | {row['core_hours']} |")
    out += ["", f"## Who is cut (connected: the largest piece at least {result['connected_from']} of the graph at that "
            "size)", "", "| size | connected laws cut | other laws cut | laws that passed every gate there and before "
            "| of them stopped, next not fitting |", "|---:|---:|---:|---:|---:|"]
    for row in result["sizes"]:
        out.append(f"| {_n(row['n'])} | {_share(row['connected_laws_cut'], row['connected_laws'])} | "
                   f"{_share(row['other_laws_cut'], row['other_laws'])} | {_n(row['passed_every_gate'])} | "
                   f"{_n(row['passed_every_gate_then_stopped'])} |")
    out += ["", "## What a larger budget buys, an estimate", "",
            "A cut seed's need is its law's most moves to the chain cap a size below, times the sizes' ratio, at the "
            "cut seed's own units a move, over its budget: what it would take to reach the cap, where a seed ends if "
            "nothing ends it before. Seeds whose law has no seed at the cap a size below are not estimated, and are "
            "counted at the whole of the larger budget in the bound on hours. The laws stopped are counted by their "
            "own predicted first chunk.", "",
            "| size | cut seeds estimated | need p50 / p90 | reach their end at " + " / ".join(f"{k}x" for k in MULTIPLES)
            + " | more core-hours at " + " / ".join(f"{k}x" for k in MULTIPLES) + " (at most) | stopped laws "
            "fitting the next size's budget at " + " / ".join(f"{k}x" for k in MULTIPLES) + " |",
            "|---:|---:|---:|---:|---:|---:|"]
    for row in result["sizes"]:
        more = row["more"]
        if not row["seeds_cut"] and not row["stopped_over_budget"]:
            continue
        reach = " / ".join("-" if more["reach_their_end"][str(k)] is None else f"{more['reach_their_end'][str(k)]:.0%}"
                           for k in MULTIPLES)
        hours = " / ".join(f"{more['extra_core_hours'][str(k)]} ({more['extra_core_hours_at_most'][str(k)]})"
                           for k in MULTIPLES)
        fits = (" / ".join(f"{row['stopped_would_fit'][str(k)]} of {row['stopped_over_budget']}" for k in MULTIPLES)
                if row["stopped_over_budget"] else "-")
        need = ("-" if more["multiple_p50"] is None else f"{more['multiple_p50']} / {more['multiple_p90']}")
        out.append(f"| {_n(row['n'])} | {more['cut_seeds_estimated']} of {row['seeds_cut']} | {need} | {reach} | "
                   f"{hours} | {fits} |")
    past = result["past_budget"]
    out += ["", "## Seeds past their budget", "",
            f"{_n(past['seeds'])} seeds ran past their budget, {_n(past['past_twice'])} past twice and "
            f"{_n(past['past_tenfold'])} past ten times, {past['core_hours_past']} core-hours beyond it (interrupted "
            f"and resumed: {_n(past['interrupted'])}). The budget is read between chunks, so a chunk whose work a move "
            "climbs past the last one's runs whole.", "",
            "| law | size | seed | ended | of its budget | seconds | mean degree | most of its work |",
            "|---|---:|---:|---|---:|---:|---:|---|"]
    for row in past["worst"]:
        out.append(f"| `{row['law'][:12]}` | {_n(row['n'])} | {row['seed']} | {row['ended']} | "
                   f"{row['budget_fraction']}x | {row['simulation_seconds']:,} | {row['final_mean_degree']} | "
                   f"{row['leading_part']} |")
    out += ["", "## The laws stopped `over_budget`", "",
            "| law | at | first chunk over the budget | mean degree | connected | its seeds cut there |",
            "|---|---:|---:|---:|---:|---:|"]
    for row in result["stopped"]:
        out.append(f"| `{row['law'][:12]}` | {_n(row['at_n'])} | {row['multiple']}x | {row['mean_degree']} | "
                   f"{row['connected_fraction']} | {row['seeds_cut']} |")
    bands = result["seconds_a_unit_by_mean_degree"]
    if bands:
        heads = [f"{b['from']:g} to {b['below']:g}" if b["below"] is not None else f"{b['from']:g} up"
                 for b in bands[0]["bands"]]
        out += ["", "## Seconds a unit on the host, by the graph's mean degree", "",
                f"The median over seeds that ran at least {TIMED_FROM_SECONDS:g} s; the unit is fitted once in the "
                "sandbox and decides nothing by the clock.", "",
                "| size | " + " | ".join(heads) + " |", "|---:|" + "---:|" * len(heads)]
        for row in bands:
            out.append(f"| {_n(row['n'])} | " + " | ".join(
                "-" if cell["p50"] is None else f"{cell['p50']:.2e} ({cell['seeds']:,})" for cell in row["bands"])
                + " |")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/budget_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    path = Path(args.bundle)
    if path.is_dir():
        result = read(unpacked(path, path))
    else:
        with tempfile.TemporaryDirectory(prefix="gsd_budgets_") as scratch:
            result = read(unpacked(path, Path(scratch)))
    page = render(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
