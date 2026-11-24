#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-design-on-a-bundle-1"
GOING = ("run_next", "hold")
LEDGER_STATE = ("salt_shares", "known_results")
PRICED = "over_budget"
CUT = "cut"
SECONDS = ("simulation_seconds", "d_s_seconds", "d_V_seconds", "d_B_seconds", "d_w_seconds", "kappa_seconds")
LISTED = 40


def design_policy(study: str, tree: Path | None = None) -> tuple[dict, dict]:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    if Path(str(study)).is_file():
        import hashlib
        raw = Path(str(study)).read_bytes()
        design = dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=str(study))
    else:
        design = SD.design_for(tree or ROOT, str(study))
    if design is None:
        raise ValueError(f"no design is committed for study {study}")
    spec = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                            design["campaigns"][0], 0)
    return design, asdict(Policy.from_spec(spec))


def under(inputs: dict, policy: dict) -> dict:
    recorded = inputs.get("policy") or {}
    return dict(inputs, policy=dict(policy, **{key: recorded[key] for key in LEDGER_STATE if key in recorded}))


def law_rows(index, campaigns: set[str] | None):
    from decision_index import json_of
    for (_campaign, law), rows in index.by_law(campaigns):
        pairs = []
        for row in rows:
            inputs = json_of(row.get("inputs_json"))
            if inputs and row.get("at_n") is not None:
                pairs.append((row, inputs))
        if pairs:
            yield law, pairs


def verdicts(decision) -> list[str]:
    from graph_scale_dynamics.decisions import gates as G
    named = [str(G.today(gate)) for gate in ((decision.facts or {}).get("salted") or [])]
    if decision.action == "stop" and decision.rule in G.LET_THROUGH_GATES and decision.rule not in named:
        named.append(str(decision.rule))
    return named


def acting_gates(policy: dict) -> set[str]:
    from graph_scale_dynamics.decisions import gates as G
    own = {str(G.today(name)): float(share) for name, share in policy.get("gate_shares") or ()}
    return {gate for gate in G.LET_THROUGH_GATES if own.get(gate, 0.0) < 1.0
            and (gate != CUT or policy.get("cut_gate"))}


def cut_at(inputs: dict, n: int) -> bool:
    rung = next((row for row in inputs.get("rungs") or [] if int(row["n"]) == int(n)), None)
    return any(seed.get("termination") == "budget" for seed in (rung or {}).get("seeds") or [])


def walk(rows: list, policy: dict) -> dict:
    from graph_scale_dynamics.decisions.replay import replay
    sizes: dict = {}
    end = None
    for row, inputs in rows:
        n = int(row["at_n"])
        again = replay(under(inputs, policy))
        goes = again.action in GOING
        withheld = verdicts(again)
        sizes[n] = {"recorded": f"{row['action']}:{row['rule']}", "design": f"{again.action}:{again.rule}",
                    "withheld": withheld, "goes": goes, "cut_seed": cut_at(inputs, n), "next_n": again.next_n}
        if again.action == "done":
            end = {"how": "done", "n": n, "rule": again.rule}
        elif not goes:
            end = {"how": "stops", "n": n, "rule": again.rule}
        elif row["action"] not in GOING:
            end = {"how": "goes on where the record stopped", "n": n, "rule": again.rule,
                   "recorded": str(row["rule"])}
        elif again.next_n != row.get("next_n"):
            end = {"how": "buys another run than the record", "n": n, "rule": again.rule,
                   "recorded": str(row["rule"])}
        else:
            continue
        break
    if end is None:
        last = max(sizes) if sizes else None
        end = {"how": "in flight when the bundle was made", "n": last, "rule": None}
    return {"sizes": sizes, "end": end}


def seed_costs(root: Path, campaigns: set[str] | None) -> dict:
    found: dict = {}
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        campaign = Path(path).parent.name.split("_reports_")[0].replace("campaign_", "")
        if campaigns is not None and campaign not in campaigns:
            continue
        seeds = (json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}).get("seeds") or {}
        columns, laws = list(seeds.get("columns") or []), list(seeds.get("laws") or [])
        if not {"law", "n", "simulation_seconds"} <= set(columns):
            continue
        at = {name: columns.index(name) for name in columns}
        for row in seeds.get("rows") or []:
            key = (str(laws[row[at["law"]]]), int(row[at["n"]]))
            entry = found.setdefault(key, {"seeds": 0, "seconds": 0.0})
            entry["seeds"] += 1
            entry["seconds"] += sum(float(row[at[name]] or 0.0) for name in SECONDS if name in at)
    return found


def scorers(root: Path) -> list[dict]:
    import score_list
    return [row for row in score_list.read_report_28(Path(root))["list"] if not row.get("control")]


def _range(count: float, share: float) -> list[int]:
    spread = 2.0 * math.sqrt(max(count * (1.0 - min(1.0, max(0.0, share))), 1.0))
    return [max(0, int(math.floor(count - spread))), int(math.ceil(count + spread))]


def read(root: Path, study: str, campaigns: set[str] | None = None, laws: int | None = None) -> dict:
    from decision_index import DecisionIndex
    design, policy = design_policy(study)
    walked, decisions = {}, 0
    with DecisionIndex(root) as index:
        for law, rows in law_rows(index, campaigns):
            decisions += len(rows)
            walked[law] = walk(rows, policy)
    costs = seed_costs(root, campaigns)
    acting = acting_gates(policy)
    sizes = sorted({n for found in walked.values() for n in found["sizes"]})
    seeds_a_law = int(design["ladder"]["seeds"])
    whole = {}
    for (law, n), cost in costs.items():
        if cost["seeds"] >= seeds_a_law:
            entry = whole.setdefault(n, [0.0, 0])
            entry[0] += cost["seconds"]
            entry[1] += 1
    by_size: dict = {}
    for n in sizes:
        here = [(law, found) for law, found in walked.items() if n in found["sizes"]]
        entry = {"decided": len(here), "stops": Counter(), "held": 0, "held_by_gate": Counter(), "let_through": 0,
                 "recorded_only": Counter(), "goes_on": 0, "done": 0, "cut_seed": 0, "not_followed": Counter(),
                 "recorded_stops": Counter()}
        seconds, counted = 0.0, 0
        for law, found in here:
            step, end = found["sizes"][n], found["end"]
            entry["cut_seed"] += int(step["cut_seed"])
            if step["recorded"].startswith("stop:"):
                entry["recorded_stops"][step["recorded"].split(":", 1)[1]] += 1
            held = [gate for gate in step["withheld"] if gate in acting]
            entry["recorded_only"].update(gate for gate in step["withheld"] if gate not in acting)
            if held:
                entry["held"] += 1
                entry["held_by_gate"].update(held)
            ended_here = end["n"] == n
            if ended_here and end["how"] == "stops":
                entry["stops"][end["rule"]] += 1
            elif ended_here and end["how"] == "done":
                entry["done"] += 1
            else:
                entry["goes_on"] += 1
                entry["let_through"] += int(bool(held))
                if ended_here:
                    entry["not_followed"][end["how"]] += 1
            cost = costs.get((law, n))
            if cost and cost["seeds"] >= seeds_a_law:
                seconds += cost["seconds"]
                counted += 1
        every = whole.get(n) or [0.0, 0]
        entry.update(stopped=sum(entry["stops"].values()),
                     seconds_a_law=(round(seconds / counted, 3) if counted else None), laws_timed=counted,
                     seconds_a_law_in_the_bundle=(round(every[0] / every[1], 3) if every[1] else None),
                     laws_timed_in_the_bundle=every[1])
        by_size[n] = entry
    total = int(laws if laws is not None else design.get("law_budget") or len(walked))
    projected, arriving = {}, float(total)
    for n in sizes:
        entry = by_size[n]
        if not entry["decided"]:
            break
        share = lambda count: count / entry["decided"]
        stops = {rule: round(arriving * share(count), 1) for rule, count in sorted(entry["stops"].items())}
        hours = lambda key: (round(arriving * entry[key] / 3600.0, 1) if entry[key] is not None else None)
        projected[n] = {"laws": round(arriving, 1), "laws_range": _range(arriving, arriving / total),
                        "stopped": round(arriving * share(entry["stopped"]), 1), "stops": stops,
                        "held": round(arriving * share(entry["held"]), 1),
                        "let_through": round(arriving * share(entry["let_through"]), 1),
                        "core_hours": hours("seconds_a_law"),
                        "core_hours_at_the_bundle_s_mean": hours("seconds_a_law_in_the_bundle"),
                        "from": entry["decided"]}
        arriving *= share(entry["goes_on"])
    hours = [row["core_hours"] for row in projected.values()]
    hours_whole = [row["core_hours_at_the_bundle_s_mean"] for row in projected.values()]
    listed = []
    for row in scorers(root):
        found = walked.get(str(row["law"]))
        if found is None:
            continue
        end = found["end"]
        listed.append({"law": str(row["law"])[:12], "score": row["score"], "by": row["by"], "to_n": row["to_n"],
                       "end": end["how"], "at_n": end["n"], "rule": end["rule"],
                       "lost": bool(end["how"] == "stops" and end["n"] is not None and int(end["n"]) < int(row["to_n"]))})
    cut_again = Counter()
    for found in walked.values():
        steps = found["sizes"]
        for n in sorted(steps):
            later = [m for m in steps if m > n]
            if CUT in steps[n]["withheld"] and steps[n]["goes"] and later:
                cut_again["followed"] += 1
                cut_again["cut_again"] += int(steps[min(later)]["cut_seed"])
    ends = Counter(found["end"]["how"] for found in walked.values())
    return {"contract": CONTRACT, "bundle": Path(root).name, "design": str(design["study"]),
            "design_sha256": design["sha256"], "campaigns": sorted(campaigns) if campaigns else "every campaign",
            "laws": len(walked), "decisions": decisions, "ends": dict(ends),
            "stops_by_rule": dict(sorted(Counter(found["end"]["rule"] for found in walked.values()
                                                 if found["end"]["how"] == "stops").items())),
            "by_size": {str(n): {key: (dict(sorted(value.items())) if isinstance(value, Counter) else value)
                                 for key, value in entry.items()} for n, entry in by_size.items()},
            "acting": sorted(acting),
            "projected": {"laws": total, "sizes": {str(n): row for n, row in projected.items()},
                          "core_hours": (round(sum(hours), 1) if hours and None not in hours else None),
                          "core_hours_at_the_bundle_s_mean": (round(sum(hours_whole), 1)
                                                              if hours_whole and None not in hours_whole else None)},
            "cut": dict(cut_again), "scorers": listed,
            "scorers_lost": [row for row in listed if row["lost"]],
            "reading": ("Every law's decisions replayed in the order they were made, each from its own recorded "
                        "inputs under the design's policy, the ledger's state as recorded. A law is followed until "
                        "the design stops it; where the design lets it on and the record has no later decision (the "
                        "record stopped it, bought another run, or the law was in flight) it counts as going on at "
                        "that size and is not followed. by_size counts the laws followed to each size: held is the "
                        "laws a gate that acts under the design would hold back there, let_through the ones of them "
                        "that go on, recorded_only the verdicts of the gates that only record. A seed's ending is "
                        "the record's: a seed the record cut on a budget the design would have doubled still counts "
                        "as cut. projected carries each size's shares to the design's number of laws; its hours are "
                        "each size's seconds a law, evolving and probing, over the laws the design follows there "
                        "with every seed finished, and beside them over every such law of the bundle. laws_range "
                        "is two standard deviations of that count as a draw.")}


def _n(value) -> str:
    return f"{int(value):,}"


def render(found: dict) -> str:
    lines = [f"study {found['design']}'s design on {found['bundle']} ({found['contract']}): {found['decisions']:,} "
             f"decisions of {found['laws']:,} laws replayed under the design, campaigns {found['campaigns']}",
             "how the laws end under the design: " + ", ".join(f"{how} {count:,}" for how, count in
                                                                sorted(found["ends"].items(), key=lambda kv: -kv[1])),
             "stops by rule: " + ", ".join(f"{rule} {count:,}" for rule, count in
                                           sorted(found["stops_by_rule"].items(), key=lambda kv: -kv[1])),
             "the gates that act: " + ", ".join(found["acting"]),
             "", "| size | laws followed | a gate would hold | let through | stopped | goes on | cut seed | "
             "seconds a law | in the bundle |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    seconds = lambda value: "" if value is None else f"{value:,.1f}"
    by_n = sorted(found["by_size"].items(), key=lambda kv: int(kv[0]))
    for n, entry in by_n:
        share = (f" ({entry['let_through'] / entry['held']:.0%})" if entry["held"] else "")
        lines.append(f"| {_n(n)} | {entry['decided']:,} | {entry['held']:,} | {entry['let_through']:,}{share} | "
                     f"{entry['stopped']:,} | {entry['goes_on']:,} | {entry['cut_seed']:,} | "
                     f"{seconds(entry['seconds_a_law'])} | {seconds(entry['seconds_a_law_in_the_bundle'])} |")
    listed = lambda counts: ", ".join(f"{name} {count}" for name, count in counts.items()) or "none"
    for n, entry in by_n:
        if entry["stops"] or entry["held_by_gate"] or entry["recorded_only"]:
            lines.append(f"N={_n(n)}: stops {listed(entry['stops'])}; verdicts of the gates that act "
                         f"{listed(entry['held_by_gate'])}; recorded only {listed(entry['recorded_only'])}"
                         + (f"; not followed: {listed(entry['not_followed'])}" if entry["not_followed"] else ""))
    projected = found["projected"]
    lines += ["", f"projected on {projected['laws']:,} laws:", "| size | laws | range | stopped | let through | "
              "core-hours | at the bundle's mean |", "|---:|---:|---:|---:|---:|---:|---:|"]
    for n, row in sorted(projected["sizes"].items(), key=lambda kv: int(kv[0])):
        lines.append(f"| {_n(n)} | {row['laws']:,} | {row['laws_range'][0]:,} to {row['laws_range'][1]:,} | "
                     f"{row['stopped']:,} | {row['let_through']:,} | {seconds(row['core_hours'])} | "
                     f"{seconds(row['core_hours_at_the_bundle_s_mean'])} |")
    if projected["core_hours"] is not None:
        lines.append(f"core-hours in all: {projected['core_hours']:,} on the laws the design follows, "
                     f"{seconds(projected['core_hours_at_the_bundle_s_mean'])} at the bundle's mean a law")
    cut = found["cut"]
    if cut.get("followed"):
        lines.append(f"let through past cut and followed one size on: {cut['followed']}, cut again there "
                     f"{cut.get('cut_again', 0)}")
    lost = found["scorers_lost"]
    lines.append(f"scoring laws: {len(found['scorers'])}; stopped by the design below the size they score at: "
                 f"{len(lost)}" + (": " + ", ".join(f"{row['law']} ({row['score']}, {row['rule']} at N={_n(row['at_n'])})"
                                                    for row in lost[:LISTED]) if lost else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from disordered_reading import study_campaigns
    from read_bundle import scratch_dir, unpacked
    parser = argparse.ArgumentParser(description="tools/design_on_a_bundle.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--design", required=True, help="the study whose committed design is replayed, as 173, "
                                                        "or a design file")
    parser.add_argument("--laws", type=int, help="the number of laws the shares are carried to; the design's own")
    parser.add_argument("--every-campaign", action="store_true", help="the controls too")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = unpacked(args.bundle, scratch_dir("gsd_design_on_"))
    if not (root / "tables" / "decisions.ndjson.gz").is_file():
        print("this bundle carries no decisions table (tables/decisions.ndjson.gz, since 798)", file=sys.stderr)
        return 2
    found = read(root, args.design, None if args.every_campaign else study_campaigns(root), args.laws)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
