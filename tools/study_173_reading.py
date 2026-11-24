#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-study-173-reading-1"
CRITERION = "graph_scale_dynamics/resources/readings/study_173_criterion.json"
FACTS = ("empty", "too_dense", "disconnected")
JUDGMENTS = ("starts_alike", "starts_apart_by_history", "nothing_read")
SIX = FACTS + JUDGMENTS
LADDER = (64, 256, 1024, 4096, 16384, 65536)
GOING = ("run_next", "hold")
TOP_N = 65536
CUT = "cut"
RANGES = {"P4": (0.07, 0.13), "P5": (0.51, 0.61), "P6": (0.75, 0.87), "P7_16384": (150, 260),
          "P7_65536": (30, 110), "P8_4096": (0, 12), "P8_share": (0.0, 0.015), "P9": (0.60, 0.92),
          "P10": (2.0, float("inf")), "P11": (0, 1), "P12": (100.0, 260.0), "P12_top": (1 / 3, 1 / 2)}
TENTH = 0.1


def _inside(value, key: str):
    low, high = RANGES[key]
    return None if value is None else low <= value <= high


def _rows(root: Path, name: str):
    with gzip.open(Path(root) / "tables" / name, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def study_campaigns(root: Path) -> tuple[str, list[str], dict]:
    study = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    ours = [c for c in study.get("campaigns") or [] if c.get("study_design")]
    return (str(study.get("study_id")), [str(c["campaign_id"]) for c in ours],
            {str(c["campaign_id"]): str(c.get("state")) for c in ours})


def closed_six(inputs: dict, gates=SIX) -> dict:
    shares = [[gate, (0.0 if gate in gates else share)] for gate, share in inputs["policy"].get("gate_shares") or []]
    named = {gate for gate, _ in shares}
    shares += [[gate, 0.0] for gate in gates if gate not in named]
    return dict(inputs, policy=dict(inputs["policy"], gate_shares=shares))


def held_by(row: dict, gates=SIX) -> str | None:
    from decision_index import json_of
    from graph_scale_dynamics.decisions.replay import replay
    inputs = json_of(row.get("inputs_json"))
    if not isinstance(inputs, dict) or not inputs.get("policy"):
        return None
    again = replay(closed_six(inputs, gates))
    return str(again.rule) if again.action == "stop" and again.rule in gates else None


def seeds_cut(inputs: dict) -> dict:
    out = {}
    for rung in inputs.get("rungs") or []:
        seeds = rung.get("seeds") or []
        if seeds:
            out[int(rung["n"])] = sum(1 for seed in seeds if seed.get("termination") == "budget")
    return out


def _next_size(n: int) -> int | None:
    return next((m for m in LADDER if m > int(n)), None)


def tenth(index, campaigns) -> dict:
    from decision_index import json_of
    from graph_scale_dynamics.decisions.replay import policy_from_inputs
    found, shares = {}, {}
    for n in (1024, 4096):
        held = went = 0
        by_gate, last = Counter(), None
        for row in index.latest(campaigns, n):
            gate = held_by(row)
            if gate is None:
                continue
            held += 1
            by_gate[gate] += 1
            went += int(row["action"] in GOING)
            last = row
        found[str(n)] = {"held": held, "went_on": went, "share": (went / held) if held else None,
                         "by_gate": dict(by_gate)}
        if last is not None:
            policy = policy_from_inputs(json_of(last["inputs_json"])["policy"])
            shares[str(n)] = {gate: float(policy.live_share(gate, n)) for gate in SIX}
    every = [found[n]["share"] for n in found if found[n]["share"] is not None]
    still = all(abs(share - TENTH) < 1e-12 for by in shares.values() for share in by.values()) if shares else None
    holds = (all(_inside(share, "P4") for share in every) and still) if every and still is not None else None
    return {"holds": holds, "by_size": found, "shares_at_the_last_decision": shares}


def stops_at(index, campaigns, n: int, gates) -> dict:
    decided = stopped = 0
    by = Counter()
    for row in index.latest(campaigns, n):
        decided += 1
        if row["action"] == "stop" and row["rule"] in gates:
            stopped += 1
            by[row["rule"]] += 1
    return {"decided": decided, "stopped": stopped, "share": (stopped / decided) if decided else None,
            "by_rule": dict(by)}


def reached(root: Path, campaigns) -> dict:
    tops = Counter()
    laws = 0
    for row in _rows(root, "laws.ndjson.gz"):
        if str(row["campaign_id"]) not in campaigns:
            continue
        laws += 1
        top = row.get("top_n")
        for n in LADDER:
            if top is not None and int(top) >= n:
                tops[n] += 1
    return {"laws": laws, "reached": {str(n): tops[n] for n in LADDER}}


def gates_held(root: Path) -> dict:
    ledger = json.loads((Path(root) / "gates_ledger.json").read_text(encoding="utf-8"))
    held = {gate: {n: 0 if size.get("label") == "records only" else int(size.get("held") or 0)
                   for n, size in sizes.items()}
            for gate, sizes in (ledger.get("gates") or {}).items()}
    priced = {gate: total for gate, sizes in (ledger.get("gates") or {}).items()
              if (total := sum(int(size.get("priced") if "priced" in size else size.get("held") or 0)
                               for size in sizes.values() if size.get("label") == "records only"))}
    others = {gate: sum(by.values()) for gate, by in held.items() if gate not in SIX and sum(by.values())}
    early = {gate: {n: k for n, k in by.items() if int(n) < 1024 and k} for gate, by in held.items() if gate in FACTS}
    return {"held": held, "others_holding": others, "facts_before_1024": {g: v for g, v in early.items() if v},
            "recording_gates_priced": priced}


def cut_recorded(index, campaigns) -> dict:
    from decision_index import json_of
    buying = recorded = 0
    missing: dict = {}
    for row in index.every(campaigns):
        if row.get("at_n") is None or row["action"] not in GOING or row.get("next_n") is None:
            continue
        at_n, next_n = int(row["at_n"]), int(row["next_n"])
        if not (next_n > at_n or row["rule"] == "longer_chain"):
            continue
        inputs = json_of(row.get("inputs_json"))
        if not isinstance(inputs, dict) or not seeds_cut(inputs).get(at_n):
            continue
        buying += 1
        facts = json_of(row.get("facts_json"))
        if isinstance(facts, dict) and isinstance(facts.get(CUT), dict):
            recorded += 1
        else:
            missing.setdefault(str(row["candidate_id"])[:12], int(row["at_n"]))
    return {"buying_with_a_cut_seed": buying, "cut_recorded": recorded, "missing": dict(list(missing.items())[:20]),
            "missing_count": len(missing)}


def cut_laws(index, campaigns) -> dict:
    from decision_index import json_of
    cut, followed, again, laws = set(), 0, 0, 0
    for row in index.last_of_each_law(campaigns):
        laws += 1
        inputs = json_of(row.get("inputs_json"))
        if not isinstance(inputs, dict):
            continue
        by = seeds_cut(inputs)
        if any(by.values()):
            cut.add(str(row["candidate_id"]))
        for n, k in by.items():
            up = _next_size(n)
            if k and up is not None and up in by:
                followed += 1
                again += int(by[up] > 0)
    return {"laws": laws, "cut_laws": cut, "followed_one_size_up": followed, "cut_again": again,
            "share_cut_again": (again / followed) if followed else None}


def scorers(root: Path) -> dict:
    import score_list
    return {str(row["law"]): row for row in score_list.read_report_28(Path(root))["list"] if not row.get("control")}


def let_through_scoring(index, campaigns, scoring: dict) -> dict:
    from decision_index import json_of
    found = {}
    for row in index.every(campaigns):
        law = str(row["candidate_id"])
        if law not in scoring or row["action"] not in GOING:
            continue
        salted = (json_of(row.get("facts_json")) or {}).get("salted") or []
        if not set(salted) & set(JUDGMENTS):
            continue
        gate = held_by(row, JUDGMENTS)
        if gate is not None:
            found.setdefault(law[:12], {"score": scoring[law]["score"], "gate": gate, "at_n": int(row["at_n"])})
    return found


def core_hours(root: Path, campaigns) -> dict:
    by = defaultdict(float)
    for campaign in campaigns:
        for system in Path(root).glob(f"campaign_{campaign}_reports_*/evidence/system.json"):
            for rung in json.loads(system.read_text(encoding="utf-8")).get("rung_distribution") or []:
                by[int(rung["n"])] += float(rung.get("rung_seconds_total") or 0.0) / 3600.0
    total = sum(by.values())
    return {"total": round(total, 1), "by_size": {str(n): round(h, 1) for n, h in sorted(by.items())},
            "share_at_65536": (by.get(TOP_N, 0.0) / total) if total else None}


def read(root: Path) -> dict:
    from decision_index import DecisionIndex
    import counters_reading
    import study_172_reading as S172
    study, campaigns, states = study_campaigns(root)
    counters = counters_reading.read(root)
    zero = S172.unresolved(root, campaigns)
    gates = gates_held(root)
    with DecisionIndex(root) as index:
        recorded = cut_recorded(index, campaigns)
        p4 = tenth(index, campaigns)
        p5 = stops_at(index, campaigns, 1024, FACTS)
        p6 = stops_at(index, campaigns, 4096, SIX)
        over_4096 = stops_at(index, campaigns, 4096, ("over_budget",))["stopped"]
        over = {str(row["candidate_id"]) for row in index.last_of_each_law(campaigns)
                if row["rule"] == "over_budget" and int(row["at_n"]) < TOP_N}
        cut = cut_laws(index, campaigns)
        scoring = scorers(root)
        lucky = let_through_scoring(index, campaigns, scoring)
    ladder = reached(root, campaigns)
    cost = core_hours(root, campaigns)
    laws = ladder["laws"]
    cut_set = cut.pop("cut_laws")
    scored_cut = len(set(scoring) & cut_set)
    scored_rest = len(set(scoring) - cut_set)
    rate_cut = scored_cut / len(cut_set) if cut_set else None
    rate_rest = scored_rest / (laws - len(cut_set)) if laws - len(cut_set) > 0 else None
    ratio = (rate_cut / rate_rest) if rate_cut is not None and rate_rest else None
    over_share = len(over) / laws if laws else None
    items = {
        "P1": {"holds": counters["C1_replays"] and counters["C2_per_batch_reproduced"],
               "read": {"replay": counters["replay"]["counts"], "learned_decisions": counters["learned_decisions"],
                        "differ": counters["per_batch_differ_count"]}},
        "P2": {"holds": zero["zero_after_the_ceiling"] == 0, "read": zero},
        "P3": {"holds": (not gates["others_holding"] and not gates["facts_before_1024"]
                         and recorded["missing_count"] == 0),
               "read": {**gates, "cut": recorded}},
        "P4": {"holds": p4["holds"], "read": p4},
        "P5": {"holds": _inside(p5["share"], "P5"), "read": p5},
        "P6": {"holds": _inside(p6["share"], "P6"), "read": p6},
        "P7": {"holds": (_inside(ladder["reached"]["16384"], "P7_16384")
                         and _inside(ladder["reached"]["65536"], "P7_65536")), "read": ladder},
        "P8": {"holds": _inside(over_4096, "P8_4096") and _inside(over_share, "P8_share"),
               "read": {"over_budget_at_4096": over_4096, "over_budget_before_65536": len(over),
                        "share": over_share, "laws": laws}},
        "P9": {"holds": _inside(cut["share_cut_again"], "P9"), "read": cut},
        "P10": {"holds": _inside(ratio, "P10"),
                "read": {"cut_laws": len(cut_set), "scoring_cut": scored_cut, "scoring_rest": scored_rest,
                         "rest": laws - len(cut_set), "ratio": ratio}},
        "P11": {"holds": _inside(len(lucky), "P11"), "read": {"let_through_and_scoring": lucky}},
        "P12": {"holds": _inside(cost["total"], "P12") and _inside(cost["share_at_65536"], "P12_top"),
                "read": cost},
    }
    progress = sorted(c for c, state in states.items() if state not in ("done",))
    return {"contract": CONTRACT, "criterion": CRITERION, "bundle": Path(root).name, "study": study,
            "campaigns": campaigns, "states": states, "its_own": study == "173",
            "progress": bool(progress), "items": items}


def _pct(part, whole) -> str:
    return f"{part:,} of {whole:,} ({100 * part / whole:.1f}%)" if whole else f"{part:,} of 0"


def render(found: dict) -> str:
    word = {True: "holds", False: "misses", None: "not read"}
    items = found["items"]
    head = (f"study 173's criterion read ({found['contract']}, {found['criterion']}) on {found['bundle']}, study "
            f"{found['study']}, campaigns {found['states']}")
    if not found["its_own"]:
        head += ": not 173's bundle, so a dry run of the reading"
    elif found["progress"]:
        head += ": a campaign is not done, so this is a progress reading, its predictions reported and not judged"
    lines = [head]
    say = lambda key, text: lines.append(f"{key} {word[items[key]['holds']]}: {text}")
    r = items["P1"]["read"]
    say("P1", f"replay {r['replay']}; {r['differ']} of {r['learned_decisions']:,} learned decisions met other shares")
    r = items["P2"]["read"]
    say("P2", f"zero temperature unresolved after the ceiling {r['zero_after_the_ceiling']}")
    r = items["P3"]["read"]
    say("P3", f"other gates holding {r['others_holding'] or 'none'}; the fact gates before 1,024 "
              f"{r['facts_before_1024'] or 'none'}; cut recorded on {r['cut']['cut_recorded']:,} of "
              f"{r['cut']['buying_with_a_cut_seed']:,} decisions that bought a run with a seed cut at the size"
              + (f", missing on {r['cut']['missing']}" if r["cut"]["missing_count"] else "")
              + (f"; recording gates a budget stopped while they stood against the law, not held by them: "
                 f"{r['recording_gates_priced']}" if r.get("recording_gates_priced") else ""))
    r = items["P4"]["read"]
    say("P4", "; ".join(f"N={int(n):,}: {v['went_on']:,} of {v['held']:,} the six would hold went on"
                        + (f" ({v['share']:.1%})" if v["share"] is not None else "")
                        for n, v in r["by_size"].items())
        + f"; shares at the last decision {r['shares_at_the_last_decision']}")
    r = items["P5"]["read"]
    say("P5", f"the fact gates stopped {_pct(r['stopped'], r['decided'])} at 1,024")
    r = items["P6"]["read"]
    say("P6", f"the six stopped {_pct(r['stopped'], r['decided'])} at 4,096, {r['by_rule']}")
    r = items["P7"]["read"]
    say("P7", f"{r['reached']['16384']:,} laws reached 16,384 and {r['reached']['65536']:,} reached 65,536")
    r = items["P8"]["read"]
    say("P8", f"over_budget {r['over_budget_at_4096']} at 4,096, {_pct(r['over_budget_before_65536'], r['laws'])} "
              "before 65,536")
    r = items["P9"]["read"]
    say("P9", f"of {r['followed_one_size_up']} cut laws followed one size up, {r['cut_again']} cut there too"
              + (f" ({r['share_cut_again']:.0%})" if r["share_cut_again"] is not None else ""))
    r = items["P10"]["read"]
    say("P10", f"{r['scoring_cut']} of {r['cut_laws']} cut laws score, {r['scoring_rest']} of {r['rest']:,} others"
               + (f": {r['ratio']:.1f} times" if r["ratio"] is not None else ""))
    r = items["P11"]["read"]
    say("P11", f"laws let through past starts_alike, starts_apart_by_history or nothing_read that score: "
               f"{r['let_through_and_scoring'] or 'none'}")
    r = items["P12"]["read"]
    say("P12", f"{r['total']:,} core-hours, 65,536 "
               + (f"{r['share_at_65536']:.0%} of it" if r["share_at_65536"] is not None else "none of it")
               + "; by size " + ", ".join(f"N={int(n):,} {h}" for n, h in r["by_size"].items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from read_bundle import scratch_dir, unpacked
    parser = argparse.ArgumentParser(description="tools/study_173_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="a study bundle, unpacked or its .tar.zst")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = unpacked(args.bundle, scratch_dir("gsd_173_"))
    found = read(root)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if all(item["holds"] is not False for item in found["items"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
