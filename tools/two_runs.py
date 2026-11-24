#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-two-runs-1"
LANE_RULES = ("deep_lane_full", "lane_resumed", "hold_released")
DECISION_TIMING = ("lane", "learned", "standing", "deep_lane_in_flight")
TABLES = {"laws.ndjson.gz": ("campaign_id", "candidate_id"),
          "rungs.ndjson.gz": ("campaign_id", "candidate_id", "n"),
          "draws.ndjson.gz": ("campaign_id", "stream_index", "draw_index"),
          "chains.ndjson.gz": ("campaign_id", "candidate_id", "n", "seed", "replicate", "chain", "audit")}
SEED_TIMING = ("attempts", "simulation_seconds", "cpu_seconds", "peak_memory_bytes", "d_s_seconds", "d_V_seconds",
               "d_B_seconds", "d_w_seconds", "interrupted", "kappa_seconds", "moves_per_cpu_second", "cpu", "die")
APART = 1e-8
SECONDS = ("simulation_seconds", "d_s_seconds", "d_V_seconds", "d_B_seconds", "d_w_seconds", "kappa_seconds")
SHOWN = 20


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _rows(root: Path, name: str):
    path = Path(root) / "tables" / name
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def study_of(root: Path) -> dict:
    return json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))


def campaigns_of(root: Path) -> list[str]:
    return [str(c["campaign_id"]) for c in study_of(root).get("campaigns") or [] if c.get("study_design")]


def table_digests(root: Path, name: str, keys: tuple, campaigns: set[str]) -> tuple[dict, Counter]:
    from study_twice import normal
    found, doubled = {}, Counter()
    for row in _rows(root, name):
        if str(row.get("campaign_id")) not in campaigns:
            continue
        key = json.dumps([row.get(k) for k in keys], default=str)
        digest = _digest(normal(row))
        if key in found:
            doubled[key] += 1
            digest = _digest([found[key], digest])
        found[key] = digest
    return found, doubled


def compare_table(first: Path, second: Path, name: str, keys: tuple, campaigns: set[str], *,
                  whole: bool = True, finished=None) -> dict:
    a, _ = table_digests(first, name, keys, campaigns)
    b, _ = table_digests(second, name, keys, campaigns)
    if finished is not None:
        a = {key: value for key, value in a.items() if finished(key)}
        b = {key: value for key, value in b.items() if finished(key)}
    only_first = sorted(set(a) - set(b))
    only_second = sorted(set(b) - set(a))
    differ = sorted(key for key in set(a) & set(b) if a[key] != b[key])
    return {"rows": [len(a), len(b)], "same": not differ and (not whole or not (only_first or only_second)),
            "only_first": only_first[:SHOWN], "only_second": only_second[:SHOWN], "differ": differ[:SHOWN],
            "counts": {"only_first": len(only_first), "only_second": len(only_second), "differ": len(differ)}}


def alike(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(alike(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(alike(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=APART, abs_tol=1e-15)
    return a == b


def acting_shares(inputs, timing: Counter):
    policy = inputs.get("policy") if isinstance(inputs, dict) else None
    if not isinstance(policy, dict) or not policy.get("salt_shares"):
        return inputs
    acting = [share for share in policy["salt_shares"] if float(share[-1]) < 1.0]
    if len(acting) != len(policy["salt_shares"]):
        timing["inputs.policy.salt_shares recording"] += 1
    return dict(inputs, policy=dict(policy, salt_shares=acting))


def verdicts(rows: list[dict]) -> tuple[list, Counter]:
    from study_twice import normal
    from decision_index import json_of
    kept, timing = [], Counter()
    for row in rows:
        if row.get("rule") in LANE_RULES or row.get("released_hold"):
            timing["lane rows"] += 1
            continue
        facts = json_of(row.get("facts_json")) or {}
        inputs = json_of(row.get("inputs_json")) or {}
        for key in DECISION_TIMING:
            if key in facts:
                timing[f"facts.{key}"] += 1
            if key in inputs:
                timing[f"inputs.{key}"] += 1
        facts = {k: v for k, v in facts.items() if k not in DECISION_TIMING} if isinstance(facts, dict) else facts
        inputs = {k: v for k, v in inputs.items() if k not in DECISION_TIMING} if isinstance(inputs, dict) else inputs
        inputs = acting_shares(inputs, timing)
        kept.append([row.get("at_n"), row.get("action"), row.get("rule"), row.get("next_n"), row.get("reason"),
                     normal(facts), normal(inputs)])
    return kept, timing


def decided_at(rows: list[dict], campaign: str, law: str, out: dict) -> None:
    for row in rows:
        if row.get("at_n") is None or row.get("rule") in LANE_RULES:
            continue
        key = (str(campaign), str(law), int(row["at_n"]))
        if key not in out or str(row.get("created_utc") or "") < out[key]["when"]:
            out[key] = {"when": str(row.get("created_utc") or ""), "final": False}
        if row.get("action") in ("stop", "done"):
            out[key]["final"] = True


def compare_decisions(first: Path, second: Path, campaigns: set[str], whole: bool = True) -> dict:
    from decision_index import DecisionIndex
    laws_differ, only_first, only_second, where, last_digits = [], [], [], Counter(), []
    timing = {"first": Counter(), "second": Counter()}
    decided = {"first": {}, "second": {}}
    compared = 0
    with DecisionIndex(first) as a, DecisionIndex(second) as b:
        left, right = a.by_law(campaigns), b.by_law(campaigns)
        x, y = next(left, None), next(right, None)
        while x is not None or y is not None:
            if y is None or (x is not None and x[0] < y[0]):
                only_first.append(x[0][1][:12])
                decided_at(x[1], *x[0], decided["first"])
                x = next(left, None)
                continue
            if x is None or y[0] < x[0]:
                only_second.append(y[0][1][:12])
                decided_at(y[1], *y[0], decided["second"])
                y = next(right, None)
                continue
            compared += 1
            decided_at(x[1], *x[0], decided["first"])
            decided_at(y[1], *y[0], decided["second"])
            one, t1 = verdicts(x[1])
            two, t2 = verdicts(y[1])
            if not whole:
                one, two = one[:min(len(one), len(two))], two[:min(len(one), len(two))]
            timing["first"].update(t1)
            timing["second"].update(t2)
            if one != two and alike(one, two):
                last_digits.append(x[0][1][:12])
            elif one != two:
                laws_differ.append(x[0][1][:12])
                for i, (p, q) in enumerate(zip(one, two, strict=False)):
                    if not alike(p, q):
                        part = next(name for name, u, v in zip(("at_n", "action", "rule", "next_n", "reason",
                                                                "facts", "inputs"), p, q, strict=True)
                                    if not alike(u, v))
                        where[f"N={p[0]} {part}"] += 1
                        break
                else:
                    where["one run has more decisions"] += 1
            x, y = next(left, None), next(right, None)
    return {"laws_compared": compared, "decided": decided,
            "same": not laws_differ and (not whole or not (only_first or only_second)),
            "laws_differ": laws_differ[:SHOWN], "laws_differ_count": len(laws_differ), "first_difference": dict(where),
            "last_digits": last_digits[:SHOWN], "last_digits_count": len(last_digits),
            "only_first": only_first[:SHOWN], "only_second": only_second[:SHOWN],
            "timing_left_out": {run: dict(sorted(c.items())) for run, c in timing.items()}}


def seed_table(root: Path, campaigns: set[str]) -> dict:
    found = {}
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        campaign = Path(path).parent.name.split("_reports_")[0].replace("campaign_", "")
        if campaign not in campaigns:
            continue
        seeds = (json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}).get("seeds") or {}
        columns, laws = list(seeds.get("columns") or []), list(seeds.get("laws") or [])
        for row in seeds.get("rows") or []:
            entry = dict(zip(columns, row, strict=False))
            key = (campaign, str(laws[entry.pop("law")]), int(entry["n"]), int(entry["seed"]))
            found[key] = entry
    return found


def compare_seeds(a: dict, b: dict) -> dict:
    differ, fields = [], Counter()
    for key in sorted(set(a) & set(b)):
        x = {k: v for k, v in a[key].items() if k not in SEED_TIMING}
        y = {k: v for k, v in b[key].items() if k not in SEED_TIMING}
        if x != y:
            differ.append(f"{key[1][:12]} N={key[2]} seed {key[3]}")
            fields.update(k for k in set(x) | set(y) if x.get(k) != y.get(k))
    only = {"first": len(set(a) - set(b)), "second": len(set(b) - set(a))}
    return {"seeds": [len(a), len(b)], "same": not differ and not any(only.values()), "differ": differ[:SHOWN],
            "differ_count": len(differ), "fields": dict(fields), "only": only}


def _utc(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def wall_hours(root: Path, campaigns: set[str]) -> dict:
    created = [_utc(c.get("created_utc")) for c in study_of(root).get("campaigns") or []
               if str(c.get("campaign_id")) in campaigns]
    last = None
    for row in _rows(root, "decisions.ndjson.gz"):
        if str(row.get("campaign_id")) in campaigns and row.get("created_utc"):
            when = _utc(row["created_utc"])
            last = when if last is None or (when and when > last) else last
    start = min(t for t in created if t) if any(created) else None
    hours = (last - start).total_seconds() / 3600.0 if start and last else None
    return {"from": start.isoformat() if start else None, "to": last.isoformat() if last else None,
            "hours": round(hours, 3) if hours is not None else None}


def in_window(seeds: dict, decided: dict, start: str | None, hours: float | None) -> dict:
    by = defaultdict(int)
    begin = _utc(start) if start else None
    if begin is None or hours is None:
        return {}
    for (campaign, law, n), when in decided.items():
        moment = _utc(when["when"])
        if moment is None or (moment - begin).total_seconds() > hours * 3600.0:
            continue
        for seed in range(16):
            row = seeds.get((campaign, law, n, seed))
            if row is None:
                break
            by[n] += int(row.get("work_units") or 0)
    return dict(sorted(by.items()))


def speed(first: dict, second: dict, wall: dict, decided: dict | None = None) -> dict:
    by_size = defaultdict(lambda: {"seeds": 0, "first_hours": 0.0, "second_hours": 0.0, "ratios": []})
    for key in sorted(set(first) & set(second)):
        a = sum(float(first[key].get(name) or 0.0) for name in SECONDS)
        b = sum(float(second[key].get(name) or 0.0) for name in SECONDS)
        cell = by_size[key[2]]
        cell["seeds"] += 1
        cell["first_hours"] += a / 3600.0
        cell["second_hours"] += b / 3600.0
        if a > 0 and b > 0:
            cell["ratios"].append(b / a)
    sizes = {}
    for n, cell in sorted(by_size.items()):
        ratios = sorted(cell.pop("ratios"))
        sizes[str(n)] = dict({k: round(v, 3) if isinstance(v, float) else v for k, v in cell.items()},
                             slowdown_median=round(statistics.median(ratios), 3) if ratios else None,
                             slowdown_p90=round(ratios[int(0.9 * (len(ratios) - 1))], 3) if ratios else None)
    totals = {run: round(sum(s[f"{run}_hours"] for s in sizes.values()), 2) for run in ("first", "second")}
    hours = {run: wall[run]["hours"] for run in ("first", "second")}
    busy = {run: (round(totals[run] / hours[run], 2) if hours[run] else None) for run in ("first", "second")}
    gain = (hours["first"] / hours["second"]) if hours["first"] and hours["second"] else None
    window = min(hours["first"], hours["second"]) if hours["first"] and hours["second"] else None
    done = {run: in_window(seeds, (decided or {}).get(run, {}), wall[run]["from"], window)
            for run, seeds in (("first", first), ("second", second))}
    work = {run: sum(done[run].values()) for run in done}
    window_gain = (work["second"] / work["first"]) if work["first"] else None
    return {"wall": wall, "worker_hours": totals, "workers_busy_on_average": busy,
            "gain": round(gain, 3) if gain is not None else None, "by_size": sizes,
            "window": {"hours": round(window, 3) if window is not None else None, "work_units": work,
                       "by_size": {str(n): [done["first"].get(n, 0), done["second"].get(n, 0)]
                                   for n in sorted(set(done["first"]) | set(done["second"]))},
                       "gain": round(window_gain, 3) if window_gain is not None else None}}


def occupancy(root: Path, campaigns: set[str]) -> dict | None:
    home = min(campaigns, key=lambda c: (len(c), c)) if campaigns else None
    found = sorted(glob.glob(str(Path(root) / f"campaign_{home}_reports*" / "evidence" / "performance.json")))
    if not found:
        return None
    series = json.loads(Path(found[-1]).read_text(encoding="utf-8")).get("occupancy_series") or []
    if not series:
        return None
    busy = [int(x.get("active_simulations") or 0) + int(x.get("active_analyses") or 0) for x in series]
    mean = lambda name: round(statistics.mean(float(x.get(name) or 0.0) for x in series), 1)
    return {"from": series[0].get("utc"), "to": series[-1].get("utc"), "samples": len(series),
            "busy": round(statistics.mean(busy), 1), "busy_most": max(busy),
            "simulations": mean("active_simulations"), "analyses": mean("active_analyses"),
            "cpu_percent": mean("cpu_percent")}


def reached(decided: dict, wall: dict) -> dict:
    begin = {run: _utc(wall[run]["from"]) for run in ("first", "second")}
    if not decided or None in begin.values():
        return {}
    both = sorted(set(decided.get("first") or {}) & set(decided.get("second") or {}))
    hours = {run: {key: (_utc(decided[run][key]["when"]) - begin[run]).total_seconds() / 3600.0 for key in both}
             for run in ("first", "second")}

    def marks(keys: list) -> dict:
        out = {}
        for run in ("first", "second"):
            times = sorted(hours[run][key] for key in keys)
            out[run] = {share: round(times[max(0, int(share * len(times)) - 1)], 3) for share in (0.5, 0.9, 1.0)}
        return out
    by_size = defaultdict(list)
    for key in both:
        by_size[int(key[2])].append(key)
    return {"decisions": len(both), "marks": marks(both) if both else {},
            "by_size": {str(n): dict(marks(keys), decisions=len(keys)) for n, keys in sorted(by_size.items())}}


def states_of(root: Path, campaigns: set[str]) -> dict:
    return {str(c["campaign_id"]): str(c.get("state")) for c in study_of(root).get("campaigns") or []
            if str(c["campaign_id"]) in campaigns}


def read(first: Path, second: Path) -> dict:
    a_campaigns, b_campaigns = campaigns_of(first), campaigns_of(second)
    campaigns = set(a_campaigns) & set(b_campaigns)
    studies = [str(study_of(first).get("study_id")), str(study_of(second).get("study_id"))]
    states = {"first": states_of(first, campaigns), "second": states_of(second, campaigns)}
    whole = all(state == "done" for run in states.values() for state in run.values())
    decisions = compare_decisions(first, second, campaigns, whole)
    decided = decisions.pop("decided")
    past = {run: defaultdict(int) for run in decided}
    for run, found in decided.items():
        for campaign, law, n in found:
            past[run][(campaign, law)] = max(past[run][(campaign, law)], n)
    settled = lambda run, key: decided[run][key]["final"] or past[run][key[:2]] > key[2]
    both = {key for key in set(decided["first"]) & set(decided["second"])
            if settled("first", key) and settled("second", key)}
    final = {key[:2] for key in both if decided["first"][key]["final"] and decided["second"][key]["final"]}
    sized = lambda key: (lambda k: (k[0], k[1], int(k[2])) in both)(json.loads(key))
    lawed = lambda key: tuple(json.loads(key)) in final
    chained = lambda key: (lambda k: (k[0], k[1], int(k[2])) in both)(json.loads(key))
    chosen = {"laws.ndjson.gz": lawed, "rungs.ndjson.gz": sized, "chains.ndjson.gz": chained}
    tables = {name: compare_table(first, second, name, keys, campaigns, whole=whole,
                                  finished=None if whole else chosen.get(name))
              for name, keys in TABLES.items()}
    seeds_a, seeds_b = seed_table(first, campaigns), seed_table(second, campaigns)
    if not whole:
        seeds_a = {key: row for key, row in seeds_a.items() if key[:3] in both}
        seeds_b = {key: row for key, row in seeds_b.items() if key[:3] in both}
    seeds = compare_seeds(seeds_a, seeds_b)
    wall = {"first": wall_hours(first, campaigns), "second": wall_hours(second, campaigns)}
    same = all(t["same"] for t in tables.values()) and decisions["same"] and seeds["same"]
    every_a, every_b = seed_table(first, campaigns), seed_table(second, campaigns)
    return {"contract": CONTRACT, "bundles": [Path(first).name, Path(second).name], "studies": studies,
            "campaigns": sorted(campaigns), "states": states,
            "compared": "the whole of both runs" if whole else "what both runs had finished",
            "same": same and studies[0] == studies[1], "tables": tables,
            "decisions": decisions, "seeds": seeds,
            "speed": dict(speed(every_a, every_b, wall, decided), reached=reached(decided, wall),
                          slots={"first": occupancy(first, campaigns), "second": occupancy(second, campaigns)}),
            "reading": ("Two runs of one design, the second against the first. The same: every law, rung, draw and "
                        "chain row with what is the host's own left out (tools/study_twice.normal: when, how long, "
                        "how much memory, which process or folder, the database's ids); every law's decisions in "
                        "order, the deep lane's holds and releases and what records only when a decision was made "
                        "(the lane, what the law learned from and waited for) left out and counted apart; every "
                        "seed of report 28 with its timing left out. The speed: the wall time from the campaign's "
                        "creation to its last decision; the seed-hours, every compared seed's evolve and probe seconds "
                        "summed; slots, from each bundle's occupancy series (its last samples, the span given): the "
                        "slots busy, simulations and analyses together, and the host's CPU; reached, the hour from "
                        "its start at which each run had made half, nine tenths and all of the decisions both made, "
                        "the same laws in the same order, so the same work; gain the first run's wall time over the "
                        "second's, only when both are done; by size, each seed's seconds in the second run over the "
                        "first (slowdown, matched seed by seed). When either run is not done, what both had finished "
                        "is compared (a law's laws row where both ended it, a rung, its chains and its seeds where both "
                        "were past it, the law ended there or decided at a larger size, so a longer chain still to come "
                        "at that size cannot change it; each law's decisions as far as the shorter goes), and the "
                        "speed is the work of "
                        "the rungs each run decided in the same window from its start, the shorter run's length: "
                        "window.gain is the second run's over the first's.")}


def render(found: dict) -> str:
    lines = [f"two runs of one design ({found['contract']}): {found['bundles'][1]} against {found['bundles'][0]}, "
             f"studies {found['studies']}, campaigns {found['campaigns']}, {found['compared']}: "
             + ("the same, law by law" if found["same"] else "not the same")]
    for name, table in found["tables"].items():
        counts = table["counts"]
        lines.append(f"  {name}: {table['rows'][0]:,} and {table['rows'][1]:,} rows, "
                     + ("the same" if table["same"] else
                        f"{counts['differ']} differ {table['differ'][:3]}, {counts['only_first']} only in the first, "
                        f"{counts['only_second']} only in the second"))
    d = found["decisions"]
    lines.append(f"  decisions: {d['laws_compared']:,} laws compared, "
                 + ("every law's decisions the same" if d["same"] else
                    f"{d['laws_differ_count']} laws differ {d['laws_differ'][:5]}, first at {d['first_difference']}")
                 + (f"; {d['last_digits_count']} laws the same but for readings within {APART:g} of each other "
                    f"(the order of a sum) {d['last_digits'][:5]}" if d.get("last_digits_count") else "")
                 + f"; left out as timing: first {d['timing_left_out']['first']}, second "
                 f"{d['timing_left_out']['second']}")
    s = found["seeds"]
    lines.append(f"  seeds: {s['seeds'][0]:,} and {s['seeds'][1]:,}, "
                 + ("the same" if s["same"] else f"{s['differ_count']} differ in {s['fields']} {s['differ'][:3]}"))
    sp = found["speed"]
    lines.append(f"speed: wall {sp['wall']['first']['hours']} h and {sp['wall']['second']['hours']} h"
                 + (f", gain {sp['gain']}" if found["compared"] == "the whole of both runs" else "")
                 + f"; seed-hours of the seeds compared {sp['worker_hours']['first']} and "
                 f"{sp['worker_hours']['second']}")
    for run in ("first", "second"):
        slot = (sp.get("slots") or {}).get(run)
        if slot:
            lines.append(f"  slots, {run} run ({slot['samples']} samples, {slot['from']} to {slot['to']}): "
                         f"{slot['busy']} busy on average, {slot['busy_most']} at most ({slot['simulations']} "
                         f"simulations, {slot['analyses']} analyses), host CPU {slot['cpu_percent']}%")
    got = sp.get("reached") or {}
    if got.get("decisions"):
        mark = lambda m: f"half by {m[0.5]} h, nine tenths by {m[0.9]} h, all by {m[1.0]} h"
        lines.append(f"  the {got['decisions']:,} decisions both made: first run {mark(got['marks']['first'])}; "
                     f"second run {mark(got['marks']['second'])}")
        lines.append("  by size, all of them by: " + ", ".join(
            f"N={int(n):,} ({cell['decisions']:,}) {cell['first'][1.0]} h and {cell['second'][1.0]} h"
            for n, cell in got["by_size"].items()))
    window = sp["window"]
    if window["hours"]:
        lines.append(f"in the first {window['hours']} h of each: work done {window['work_units']['first']:,} and "
                     f"{window['work_units']['second']:,} units, gain {window['gain']}; by size "
                     + ", ".join(f"N={int(n):,} {a:,} and {b:,}" for n, (a, b) in window["by_size"].items()))
    lines += ["| size | seeds | worker-hours, first | second | a seed's slowdown, median | p90 |",
              "|---:|---:|---:|---:|---:|---:|"]
    for n, cell in sp["by_size"].items():
        lines.append(f"| {int(n):,} | {cell['seeds']:,} | {cell['first_hours']} | {cell['second_hours']} | "
                     f"{cell['slowdown_median']} | {cell['slowdown_p90']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from read_bundle import scratch_dir, unpacked
    parser = argparse.ArgumentParser(description="tools/two_runs.py: see docs/TOOLS.md")
    parser.add_argument("first", type=Path, help="the first run's bundle, unpacked or its .tar.zst")
    parser.add_argument("second", type=Path, help="the second run's, of the same design")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    first = unpacked(args.first, scratch_dir("gsd_first_"))
    second = unpacked(args.second, scratch_dir("gsd_second_"))
    found = read(first, second)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if found["same"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
