#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-study-172-reading-1"
CRITERION = "graph_scale_dynamics/resources/readings/study_172_criterion.json"
FACTS = ("empty", "too_dense", "disconnected")
AT_N, TOP_N = 1024, 65536
ENDS = {("done", "ladder_complete"), ("stop", "over_budget"), ("stop", "failed")}
RANGES = {"R4_one_or_more": (0.08, 0.12), "R4_two_or_more": (0.05, 0.16), "R5": (0.53, 0.66), "R6": (0.0, 0.04),
          "R7": (650.0, 1300.0)}


def _rows(root: Path, name: str):
    with gzip.open(Path(root) / "tables" / name, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _json(value):
    if isinstance(value, str) and value[:1] in "{[":
        return json.loads(value)
    return value if isinstance(value, (dict, list)) else {}


def _inside(value, key: str):
    low, high = RANGES[key]
    return None if value is None else low <= value <= high


def study_campaigns(root: Path) -> tuple[str, list[str]]:
    study = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    return str(study.get("study_id")), [str(c["campaign_id"]) for c in study.get("campaigns") or []
                                        if c.get("study_design")]


def held_by(row: dict) -> list[str]:
    from graph_scale_dynamics.decisions.replay import replay
    inputs = _json(row.get("inputs_json"))
    if not isinstance(inputs, dict) or not inputs.get("policy"):
        return []
    held = []
    others = [[gate, share] for gate, share in inputs["policy"].get("gate_shares") or [] if gate not in FACTS]
    for gate in FACTS:
        shares = others + [[other, 0.0 if other == gate else 1.0] for other in FACTS]
        again = replay(dict(inputs, policy=dict(inputs["policy"], gate_shares=shares)))
        if again.action == "stop" and again.rule == gate:
            held.append(gate)
    return held


def shares_met(row: dict) -> dict:
    from tools.counters_reading import met
    from graph_scale_dynamics.decisions.replay import policy_from_inputs
    inputs = _json(row.get("inputs_json"))
    if not isinstance(inputs, dict) or not inputs.get("policy"):
        return {}
    shares = met(policy_from_inputs(inputs["policy"]), AT_N)["shares"]
    return {gate: shares[gate] for gate in FACTS}


def one_die(root: Path, latest: dict) -> dict:
    from graph_scale_dynamics.decisions import gates as G
    held_counts, went_on, shares, odd = Counter(), Counter(), Counter(), []
    one = None
    for row in (latest.values() if isinstance(latest, dict) else latest):
        law, n = str(row["candidate_id"]), int(row["at_n"])
        if n != AT_N:
            continue
        held = held_by(row)
        if not held:
            continue
        inputs = _json(row.get("inputs_json"))
        one = bool((inputs.get("policy") or {}).get("one_die")) if one is None else one
        met = shares_met(row)
        shares.update(f"{gate} {share:g}" for gate, share in met.items() if gate in held)
        group = "two or more" if len(held) > 1 else "one"
        held_counts[group] += 1
        on = not (row["action"] == "stop" and row["rule"] in FACTS)
        went_on[group] += on
        if (inputs.get("policy") or {}).get("one_die"):
            share = min(met[gate] for gate in held)
            if on != (G.die(law, None, AT_N) < share):
                odd.append(law)
    every = sum(held_counts.values())
    return {"one_die": one, "held": dict(held_counts), "went_on": dict(went_on), "shares_met": dict(shares),
            "share_one_or_more": (sum(went_on.values()) / every) if every else None,
            "share_two_or_more": (went_on["two or more"] / held_counts["two or more"])
            if held_counts["two or more"] else None,
            "against_the_pick": len(odd), "against_the_pick_laws": odd[:20]}


def gates_held(root: Path) -> dict:
    ledger = json.loads((Path(root) / "gates_ledger.json").read_text(encoding="utf-8"))
    held = {gate: {n: int(size.get("held") or 0) for n, size in sizes.items()}
            for gate, sizes in (ledger.get("gates") or {}).items()}
    others = {gate: sum(by.values()) for gate, by in held.items() if gate not in FACTS and sum(by.values())}
    early = {gate: {n: k for n, k in by.items() if int(n) < AT_N and k} for gate, by in held.items() if gate in FACTS}
    return {"held": held, "others_holding": others, "facts_before_1024": {g: v for g, v in early.items() if v}}


def ends(root: Path, campaigns: list[str]) -> dict:
    out = Counter()
    for row in _rows(root, "laws.ndjson.gz"):
        if str(row["campaign_id"]) not in campaigns:
            continue
        decision = row.get("decision") if isinstance(row.get("decision"), dict) else _json(row.get("decision"))
        action, rule = (decision or {}).get("action"), (decision or {}).get("rule")
        if action == "stop" and rule in FACTS:
            out["stopped by the three"] += 1
        elif (action, rule) in ENDS:
            out[f"{action}:{rule}"] += 1
        elif action in ("run_next", "hold", None):
            out["still going"] += 1
        else:
            out[f"other {action}:{rule}"] += 1
    return dict(out)


def unresolved(root: Path, campaigns: list[str]) -> dict:
    zero = {str(row["candidate_id"]) for row in _rows(root, "laws.ndjson.gz")
            if str(row["campaign_id"]) in campaigns and row.get("regime") == "zero_temperature"}
    found, ranked = Counter(), 0
    for campaign in campaigns:
        for report in Path(root).glob(f"campaign_{campaign}_reports_*/23-hang-autopsy.json"):
            body = json.loads(report.read_text(encoding="utf-8")).get("body") or {}
            for law in body.get("ranked") or []:
                ranked += 1
                for rung in law.get("rungs") or []:
                    if rung.get("classification") == "OPERATIONAL_UNRESOLVED":
                        found[(str(law["candidate_id"]) in zero, str(rung.get("worst_reason")))] += 1
    return {"ranked_laws": ranked, "unresolved": {f"{'zero' if z else 'finite'} temperature, {why}": k
                                                  for (z, why), k in sorted(found.items())},
            "zero_after_the_ceiling": sum(k for (z, why), k in found.items() if z and why == "ceiling")}


def core_hours(root: Path, campaigns: list[str]) -> dict:
    by = defaultdict(float)
    for campaign in campaigns:
        for system in Path(root).glob(f"campaign_{campaign}_reports_*/evidence/system.json"):
            for rung in json.loads(system.read_text(encoding="utf-8")).get("rung_distribution") or []:
                by[int(rung["n"])] += float(rung.get("rung_seconds_total") or 0.0) / 3600.0
    return {"total": round(sum(by.values()), 1), "by_size": {str(n): round(h, 1) for n, h in sorted(by.items())}}


def read(root: Path) -> dict:
    from tools import counters_reading
    from tools.decision_index import DecisionIndex
    study, campaigns = study_campaigns(root)
    counters = counters_reading.read(root)
    with DecisionIndex(root) as index:
        decided = stopped = 0
        for row in index.latest(campaigns, AT_N):
            decided += 1
            stopped += int(row["action"] == "stop" and row["rule"] in FACTS)
        over = len({(str(row["campaign_id"]), str(row["candidate_id"])) for row in index.latest(campaigns)
                    if row["rule"] == "over_budget" and int(row["at_n"]) < TOP_N})
        die = one_die(root, index.latest(campaigns, AT_N))
    laws = {(str(row["campaign_id"]), str(row["candidate_id"])) for row in _rows(root, "laws.ndjson.gz")
            if str(row["campaign_id"]) in campaigns}
    gates = gates_held(root)
    ended = ends(root, campaigns)
    cost = core_hours(root, campaigns)
    zero = unresolved(root, campaigns)
    items = {
        "R1": {"holds": counters["C1_replays"] and counters["C2_per_batch_reproduced"],
               "read": {"replay": counters["replay"]["counts"],
                        "learned_decisions": counters["learned_decisions"],
                        "differ": counters["per_batch_differ_count"]}},
        "R2": {"holds": zero["zero_after_the_ceiling"] == 0, "read": zero},
        "R3": {"holds": not gates["others_holding"] and not gates["facts_before_1024"]
               and not any(key.startswith("other") for key in ended), "read": {**gates, "ends": ended}},
        "R4": {"holds": (_inside(die["share_one_or_more"], "R4_one_or_more") is not False
                         and _inside(die["share_two_or_more"], "R4_two_or_more") is not False
                         and die["against_the_pick"] == 0) if die["share_one_or_more"] is not None else None,
               "read": die},
        "R5": {"holds": _inside(stopped / decided, "R5") if decided else None,
               "read": {"stopped_by_the_three": stopped, "decided_at_1024": decided}},
        "R6": {"holds": _inside(over / len(laws), "R6") if laws else None,
               "read": {"over_budget_before_65536": over, "laws": len(laws)}},
        "R7": {"holds": _inside(cost["total"], "R7"), "read": cost},
    }
    return {"contract": CONTRACT, "criterion": CRITERION, "bundle": Path(root).name, "study": study,
            "campaigns": campaigns, "its_own": study == "172", "items": items}


def _pct(part, whole) -> str:
    return f"{part:,} of {whole:,} ({100 * part / whole:.1f}%)" if whole else f"{part:,} of 0"


def render(found: dict) -> str:
    word = {True: "holds", False: "fails", None: "not read"}
    items = found["items"]
    lines = [f"study 172's criterion read ({found['contract']}, {found['criterion']}) on {found['bundle']}, study "
             f"{found['study']}" + ("" if found["its_own"] else ": not 172's bundle, so a dry run of the reading")]
    r1 = items["R1"]["read"]
    lines.append(f"R1 {word[items['R1']['holds']]}: replay {r1['replay']}; {r1['differ']} of "
                 f"{r1['learned_decisions']:,} learned decisions met other shares than the ledger gives")
    r2 = items["R2"]["read"]
    lines.append(f"R2 {word[items['R2']['holds']]}: among report 23's {r2['ranked_laws']} ranked laws, unresolved "
                 f"rungs {r2['unresolved'] or 'none'}; zero temperature after the ceiling {r2['zero_after_the_ceiling']}")
    r3 = items["R3"]["read"]
    lines.append(f"R3 {word[items['R3']['holds']]}: other gates holding {r3['others_holding'] or 'none'}; the three "
                 f"before 1,024 {r3['facts_before_1024'] or 'none'}; laws' ends {r3['ends']}")
    r4 = items["R4"]["read"]
    held, on = r4["held"], r4["went_on"]
    lines.append(f"R4 {word[items['R4']['holds']]} (one die {r4['one_die']}): held back at 1,024 by one gate "
                 f"{held.get('one', 0)}, went on {on.get('one', 0)}; by two or more {held.get('two or more', 0)}, "
                 f"went on {on.get('two or more', 0)}; shares met {r4['shares_met']}; against the pick "
                 f"{r4['against_the_pick']}")
    r5 = items["R5"]["read"]
    lines.append(f"R5 {word[items['R5']['holds']]}: the three stopped "
                 f"{_pct(r5['stopped_by_the_three'], r5['decided_at_1024'])} of the laws decided at 1,024")
    r6 = items["R6"]["read"]
    lines.append(f"R6 {word[items['R6']['holds']]}: over_budget before 65,536 {_pct(r6['over_budget_before_65536'], r6['laws'])}")
    r7 = items["R7"]["read"]
    lines.append(f"R7 {word[items['R7']['holds']]}: {r7['total']:,} core-hours, by size " + ", ".join(
        f"N={int(n):,} {h}" for n, h in r7["by_size"].items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/study_172_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="a study bundle, unpacked or its .tar.zst")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    from tools.replay_bundle import study_root
    root = args.bundle if args.bundle.is_dir() else study_root(args.bundle)
    found = read(root)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if all(item["holds"] is not False for item in found["items"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
