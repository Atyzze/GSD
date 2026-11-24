#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.scheduling.fleet_halves import EXTENSION_FROM_N  # noqa: E402

CONTRACT = "gsd-fleet-reading-1"

STOPS = ("interrupt: stopping fleet", "deployment provenance fence:")
STARTED = "coordinator backend:"
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z ")
BUILD = re.compile(r"\[supervisor\] build (\d+) \(")
LEFT_FAILED = re.compile(r"repair: (\d+) law\(s\) stay stopped `failed` for failures of their own \(([^)]*)\): (.*)$")
A_LAW = re.compile(r"([0-9a-f]{6,}) \(campaign (\w+), N=(\d+)\)")


def _body(root: Path, campaign: str, name: str) -> dict:
    found = sorted(root.glob(f"campaign_{campaign}_reports_*/{name}"))
    if not found:
        return {}
    data = json.loads(found[0].read_text(encoding="utf-8"))
    return data.get("body", data) if isinstance(data, dict) else {}


def _ladder(hours: list[dict]) -> list[dict]:
    rows, before = [], {}
    for hour in hours:
        rungs = {}
        for rung in hour.get("rungs") or []:
            n = str(int(rung["n"]))
            total = int(rung.get("attempts") or 0)
            rungs[n] = {"attempts": total - before.get(n, 0), "queued": int(rung.get("queued") or 0),
                        "running": int(rung.get("running") or 0),
                        "queued_analyses": int(rung.get("queued_analyses") or 0)}
            before[n] = total
        rows.append({"hour": hour.get("hour"), "rungs": rungs})
    return rows


def _halves(by_n: dict) -> dict:
    base = sum(v for n, v in by_n.items() if int(n) < EXTENSION_FROM_N)
    extension = sum(v for n, v in by_n.items() if int(n) >= EXTENSION_FROM_N)
    return {"base": round(base, 1), "extension": round(extension, 1)}


def _share(halves: dict) -> float | None:
    total = halves["base"] + halves["extension"]
    return round(halves["extension"] / total, 3) if total else None


def _fleet(attempts: dict, wall: dict) -> tuple[dict, dict]:
    total_attempts, total_wall = Counter(), Counter()
    for campaign in attempts:
        total_attempts.update(attempts[campaign])
        total_wall.update(wall[campaign])
    return dict(sorted(total_attempts.items(), key=lambda kv: int(kv[0]))), \
        {n: round(v, 1) for n, v in sorted(total_wall.items(), key=lambda kv: int(kv[0]))}


def supervisor(root: Path) -> dict | None:
    logs = sorted(root.glob("campaign_*_reports_*/evidence/supervisor_tail.log"))
    if not logs:
        return None
    lines = max(logs, key=lambda p: (p.stat().st_size, p.name)).read_text(encoding="utf-8", errors="replace")
    stamped = [(m.group(1) + "Z", line) for line in lines.splitlines() if (m := STAMP.match(line))]
    if not stamped:
        return None
    stops, starts, left, stopped, last = [], [], None, None, None
    for utc, line in stamped:
        if any(word in line for word in STOPS):
            stopped = stopped or utc
        elif STARTED in line:
            if last is not None:
                stops.append({"stopped_utc": stopped or last, "resumed_utc": utc,
                              "how": "a stop the log records" if stopped else "no stop line: from the line before"})
            starts.append({"utc": utc, "build": None})
            stopped = None
        elif (found := BUILD.search(line)) and starts and starts[-1]["build"] is None:
            starts[-1]["build"] = int(found.group(1))
        elif found := LEFT_FAILED.search(line):
            left = {"utc": utc, "laws": int(found.group(1)), "classes": found.group(2),
                    "named": [{"law": m.group(1), "campaign": m.group(2), "n": int(m.group(3))}
                              for m in A_LAW.finditer(found.group(3))]}
        last = utc
    return {"log_from_utc": stamped[0][0], "log_to_utc": stamped[-1][0], "stops": stops, "starts": starts,
            "stopped_since": stopped, "stopped_failed": left}


def read(root: Path) -> dict:
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    campaigns = [str(c["campaign_id"]) for c in study.get("campaigns") or []]
    attempts, wall, analyses, queued, ladder, home = {}, {}, {}, Counter(), [], None
    standing, census = {}, {}
    for campaign in campaigns:
        rows = _body(root, campaign, "16-efficiency.json").get("cost_by_n") or []
        attempts[campaign] = {str(int(r["n"])): int(r.get("attempts") or 0) for r in rows}
        wall[campaign] = {str(int(r["n"])): round(float(r.get("wall_seconds") or 0.0), 1) for r in rows}
        now = _body(root, campaign, "14-compute.json").get("analysis_queue_now") or {}
        queue = now.get("raw_counts") or {}
        analyses[campaign] = int(queue.get("queued") or 0)
        if now.get("standing_failures"):
            standing[campaign] = now["standing_failures"]
        cost = _body(root, campaign, "14-compute.json").get("census_cost")
        if cost:
            census[campaign] = cost
        fleet = _body(root, campaign, "25-fleet-and-host.json")
        if not queued:
            for row in fleet.get("live_compute_by_campaign") or []:
                queued.update({str(int(n)): int(v) for n, v in (row.get("queued_by_n") or {}).items()})
        hours = (fleet.get("fleet_ladder_by_hour") or {}).get("hours") or []
        if hours and not ladder:
            ladder, home = _ladder(hours), campaign
    fleet_attempts, fleet_wall = _fleet(attempts, wall)
    halves = {"attempts": _halves(fleet_attempts), "wall_seconds": _halves(fleet_wall)}
    result = {"contract": CONTRACT, "bundle": root.name, "built_utc": study.get("built_utc"),
              "build_number": study.get("build_number"), "extension_from_n": EXTENSION_FROM_N,
              "laws": sum(int(c.get("laws") or 0) for c in study.get("campaigns") or []),
              "attempts": attempts, "wall_seconds": wall, "fleet_attempts": fleet_attempts,
              "fleet_wall_seconds": fleet_wall,
              "halves": dict(halves, extension_share_of_wall=_share(halves["wall_seconds"])),
              "queued_seeds": dict(sorted(queued.items(), key=lambda kv: int(kv[0]))),
              "queued_analyses": analyses, "ladder_campaign": home, "ladder": ladder,
              "campaigns": campaigns,
              "missing": [str((m or {}).get("campaign_id") if isinstance(m, dict) else m)
                          for m in study.get("missing") or []]}
    log = supervisor(root)
    if log:
        result["supervisor"] = log
    if standing:
        result["standing_failures"] = standing
        result["raw_lost"] = raw_lost(standing, result.get("supervisor"))
    if census:
        result["census_cost"] = census
    return result


def _parse(utc: str) -> datetime:
    return datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")


def _hours(first: str, second: str) -> float:
    return (_parse(second) - _parse(first)).total_seconds() / 3600.0


def stood(log: dict | None, start: str, end: str) -> dict | None:
    if not log:
        return None
    t0, t1 = _parse(start), _parse(end)
    spans = [(s["stopped_utc"], s["resumed_utc"]) for s in log.get("stops") or []]
    if log.get("stopped_since"):
        spans.append((log["stopped_since"], end))
    hours, overlapping = 0.0, []
    for a, b in spans:
        lo, hi = max(_parse(a), t0), min(_parse(b), t1)
        if hi > lo:
            hours += (hi - lo).total_seconds() / 3600.0
            overlapping.append([a, b])
    return {"hours": round(hours, 2), "seconds": round(hours * 3600.0), "stops": overlapping,
            "log_from_utc": log.get("log_from_utc"), "whole": log.get("log_from_utc", end) <= start}


RAW_LOST = "TRANSIENT_RAW_LOST"
NEAR_A_STOP_MINUTES = 30


def raw_lost(standing: dict | None, log: dict | None) -> dict | None:
    lost = [dict(f, campaign=c) for c, fs in (standing or {}).items() for f in fs
            if str(f.get("error") or "").startswith(RAW_LOST)]
    if not lost:
        return None
    timed = [f for f in lost if f.get("failed_utc")]
    out = {"lost": len(lost), "laws": len({f["law"] for f in lost}), "timed": len(timed),
           "by_size": {str(n): sum(1 for f in lost if f["n"] == n) for n in sorted({f["n"] for f in lost})}}
    if not timed or not log:
        return out
    spans = [(s["stopped_utc"], s["resumed_utc"]) for s in log.get("stops") or []]
    pad = timedelta(minutes=NEAR_A_STOP_MINUTES)
    at_stop = 0
    hours: dict = {}
    for f in timed:
        t = _parse(str(f["failed_utc"])[:19] + "Z")
        if any(_parse(a) - pad <= t <= _parse(b) + pad for a, b in spans):
            at_stop += 1
        hours[t.strftime("%Y-%m-%dT%H")] = hours.get(t.strftime("%Y-%m-%dT%H"), 0) + 1
    return out | {"at_a_stop": at_stop, "while_running": len(timed) - at_stop, "by_hour": dict(sorted(hours.items()))}


def between(first: dict, second: dict) -> dict:
    if "campaigns" in first and "campaigns" in second and sorted(first["campaigns"]) != sorted(second["campaigns"]):
        raise ValueError(f"the readings cover different campaigns ({sorted(first['campaigns'])} against "
                         f"{sorted(second['campaigns'])}; missing {first.get('missing') or []} and "
                         f"{second.get('missing') or []}): read them over the same campaigns")
    hours = _hours(first["built_utc"], second["built_utc"])
    sizes = sorted(set(first["fleet_attempts"]) | set(second["fleet_attempts"]), key=int)
    attempts = {n: second["fleet_attempts"].get(n, 0) - first["fleet_attempts"].get(n, 0) for n in sizes}
    wall = {n: round(second["fleet_wall_seconds"].get(n, 0.0) - first["fleet_wall_seconds"].get(n, 0.0), 1)
            for n in sizes}
    per_hour = (lambda v: round(v / hours, 1)) if hours > 0 else (lambda v: None)
    halves = {"attempts": _halves(attempts), "wall_seconds": _halves(wall)}
    found = {"earlier": first["bundle"], "earlier_built_utc": first["built_utc"], "hours": round(hours, 2),
             "attempts": attempts, "attempts_per_hour": {n: per_hour(v) for n, v in attempts.items()},
             "wall_seconds": wall, "workers": {n: (round(v / 3600.0 / hours, 2) if hours > 0 else None)
                                               for n, v in wall.items()},
             "halves": dict(halves, extension_share_of_wall=_share(halves["wall_seconds"])),
             "laws": second["laws"] - first["laws"], "laws_per_hour": per_hour(second["laws"] - first["laws"]),
             "queued_seeds": {n: [first["queued_seeds"].get(n, 0), second["queued_seeds"].get(n, 0)]
                              for n in sorted(set(first["queued_seeds"]) | set(second["queued_seeds"]), key=int)}}
    still = stood(second.get("supervisor"), first["built_utc"], second["built_utc"])
    if still is not None:
        running = hours - still["seconds"] / 3600.0
        ran = (lambda v: round(v / running, 1)) if running > 0 else (lambda v: None)
        found.update({"stood": still, "running_hours": round(running, 2),
                      "attempts_per_running_hour": {n: ran(v) for n, v in attempts.items()},
                      "laws_per_running_hour": ran(found["laws"])})
    return found


def _n(value) -> str:
    return f"{int(value):,}"


def _by_size(counts: dict) -> list:
    return sorted(counts.items(), key=lambda kv: int(kv[0]))


def _render_census(census: dict | None) -> list[str]:
    if not census:
        return []
    lines = ["## The census's gap at the deep sizes (report 14, 614)", "",
             "| campaign | size | gap by | reads | median, s | 90%, s | most, s |",
             "|---|---:|---|---:|---:|---:|---:|"]
    for campaign, cost in _by_size(census):
        for n, methods in _by_size(cost.get("by_size_and_method") or {}):
            for method, v in sorted(methods.items()):
                lines.append(f"| {campaign} | {_n(n)} | {method} | {_n(v['reads'])} | {v['median_seconds']} | "
                             f"{v['p90_seconds']} | {v['max_seconds']} |")
    slow = sorted((dict(r, campaign=c) for c, cost in census.items() for r in cost.get("slowest") or []),
                  key=lambda r: (-(r.get("seconds") or 0), r["law"], r["n"], str(r["seed"]), r["chain"]))[:12]
    before = [dict(r, campaign=c) for c, cost in _by_size(census) for r in cost.get("failed_laws_before") or []]
    for title, rows in (("The slowest reads", slow), ("The laws whose analysis failure stands, at the size before",
                                                      before)):
        if rows:
            lines += ["", f"{title}:", "", "| campaign | law | size | seed | chain | gap by | s | giant | diameter, "
                      "bound |", "|---|---|---:|---:|---|---|---:|---:|---:|"]
            lines += [f"| {r['campaign']} | `{r['law']}` | {_n(r['n'])} | {r['seed']} | {r['chain']} | {r['method']} | "
                      f"{r.get('seconds')} | {r.get('giant')} | {r.get('diameter_lower_bound')} |" for r in rows]
    return lines + [""]


def _render_supervisor(log: dict | None, standing: dict | None, lost: dict | None = None) -> list[str]:
    lines = []
    if log:
        lines += ["## The supervisor's starts", "",
                  f"Its log from {log['log_from_utc']} to {log['log_to_utc']}: {len(log['starts'])} starts, "
                  f"{len(log['stops'])} stops before them.", "",
                  "| stopped | started again | hours stood | build started |", "|---|---|---:|---:|"]
        builds = {s["utc"]: s["build"] for s in log["starts"]}
        for stop in log["stops"]:
            hours = _hours(stop["stopped_utc"], stop["resumed_utc"])
            note = "" if stop["how"] == "a stop the log records" else " (no stop line)"
            lines.append(f"| {stop['stopped_utc']}{note} | {stop['resumed_utc']} | {hours:.2f} | "
                         f"{builds.get(stop['resumed_utc'])} |")
        if log.get("stopped_since"):
            lines.append(f"| {log['stopped_since']} | not in the log | | |")
        lines.append("")
        left = log.get("stopped_failed")
        if left:
            lines += [f"Left stopped `failed` for failures of their own by the start of {left['utc']}: {left['laws']} "
                      f"laws ({left['classes']}): " + ", ".join(f"`{x['law']}` (campaign {x['campaign']}, "
                                                                f"{_n(x['n'])})" for x in left["named"]) + ".", ""]
    if lost:
        lines += ["## Simulations whose raw output was lost (621)", "",
                  f"{lost['lost']} analyses on {lost['laws']} laws stand because their simulation's raw output was lost "
                  "before it was read, the simulation queued again (" + ", ".join(
                      f"{_n(int(n))}: {c}" for n, c in lost["by_size"].items()) + ")."]
        if not lost["timed"]:
            lines.append("The bundle carries no time on them, so they cannot be set beside the "
                         "fleet's stops.")
        elif "at_a_stop" in lost:
            lines.append(f"Of the {lost['timed']} timed, {lost['at_a_stop']} at a stop of the fleet (within "
                         f"{NEAR_A_STOP_MINUTES} minutes of it, or while it stood) and {lost['while_running']} while "
                         "it ran; by hour: " + ", ".join(f"{h}Z {c}" for h, c in lost["by_hour"].items()) + ".")
        lines.append("")
    if standing:
        lines += ["## Analyses that failed and still stand (report 14, 612)", "",
                  "| campaign | law | size | seed | class | attempt started | wall, s | peak, GiB | ceiling, GiB |",
                  "|---|---|---:|---:|---|---|---:|---:|---:|"]
        for campaign, failures in _by_size(standing):
            for f in failures:
                for t in f["tries"] or [{}]:
                    lines.append(f"| {campaign} | `{f['law']}` | {_n(f['n'])} | {f['seed']} | "
                                 f"{t.get('class') or f['class']} | {t.get('started_utc') or ''} | "
                                 f"{t.get('wall_seconds', '')} | {t.get('peak_rss_gib') or ''} | "
                                 f"{t.get('ceiling_gib') or ''} |")
        lines.append("")
    return lines


def render(result: dict) -> str:
    halves = result["halves"]
    lines = [f"# The fleet, from {result['bundle']}", "",
             f"Made on build {result['build_number']} at {result['built_utc']}; {_n(result['laws'])} laws. Extension is "
             f"every size from {_n(result['extension_from_n'])} (`scheduling/fleet_halves.py`, 607).", "",
             "## Since the study started", "",
             "| size | attempts | wall, hours |", "|---:|---:|---:|"]
    for n, count in _by_size(result["fleet_attempts"]):
        lines.append(f"| {_n(n)} | {_n(count)} | {result['fleet_wall_seconds'][n] / 3600:.1f} |")
    share = halves["extension_share_of_wall"]
    lines += ["", f"Base exploration {_n(halves['attempts']['base'])} attempts, extension "
              f"{_n(halves['attempts']['extension'])}; extension's share of the simulation wall "
              + (f"{share:.0%}." if share is not None else "none."), ""]
    found = result.get("against")
    if found:
        share = found["halves"]["extension_share_of_wall"]
        lines += [f"## Since {found['earlier']} ({found['hours']} hours)", "",
                  "| size | attempts | an hour | workers' time |", "|---:|---:|---:|---:|"]
        for n, count in _by_size(found["attempts"]):
            lines.append(f"| {_n(n)} | {_n(count)} | {found['attempts_per_hour'][n]} | {found['workers'][n]} |")
        lines += ["", "Extension's share of the simulation wall between the two: "
                  + (f"{share:.0%}" if share is not None else "none")
                  + f". Laws: {_n(found['laws'])} more, {found['laws_per_hour']} an hour. Seeds queued, then and now: "
                  + "; ".join(f"{_n(n)}: {_n(a)} to {_n(b)}" for n, (a, b) in _by_size(found["queued_seeds"])) + ".", ""]
        still = found.get("stood")
        if still and still["hours"] > 0:
            spans = "; ".join(f"{a} to {b}" for a, b in still["stops"])
            ran = found["attempts_per_running_hour"]
            lines += [f"The fleet stood {still['hours']} of these hours ({spans}, the supervisor's log"
                      + ("" if still["whole"] else f", which reaches back only to {still['log_from_utc']}")
                      + f"): over the {found['running_hours']} hours it ran, {found['laws_per_running_hour']} laws an "
                      "hour, and per size " + "; ".join(f"{_n(n)}: {v}" for n, v in _by_size(ran))
                      + " attempts an hour.", ""]
        elif still:
            lines += ["The supervisor's log records no stop between the two.", ""]
    lines += ["## Queued at the bundle", "",
              "Seeds: " + "; ".join(f"{_n(n)}: {_n(v)}" for n, v in _by_size(result["queued_seeds"])) + ". Analyses, by "
              "campaign: " + "; ".join(f"{c}: {_n(v)}" for c, v in _by_size(result["queued_analyses"])) + ".", ""]
    lines += _render_supervisor(result.get("supervisor"), result.get("standing_failures"), result.get("raw_lost"))
    lines += _render_census(result.get("census_cost"))
    if result["ladder"]:
        sizes = sorted({n for hour in result["ladder"] for n in hour["rungs"]}, key=int)
        lines += [f"## Campaign {result['ladder_campaign']}'s ladder by hour", "",
                  "Each size: attempts that hour / queued / analyses waiting, at the hour's snapshot.", "",
                  "| hour | " + " | ".join(_n(n) for n in sizes) + " |", "|---|" + "---:|" * len(sizes)]
        for hour in result["ladder"]:
            cells = []
            for n in sizes:
                rung = hour["rungs"].get(n)
                cells.append(f"{rung['attempts']} / {rung['queued']} / {rung['queued_analyses']}" if rung else "-")
            lines.append(f"| {hour['hour']} | " + " | ".join(cells) + " |")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/fleet_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--against", help="an earlier study bundle, or this tool's .json of one")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    args = parser.parse_args(argv)
    from read_bundle import unpacked

    def reading_of(path: Path) -> dict:
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="gsd_fleet_") as scratch:
            return read(unpacked(path, Path(scratch)))

    result = reading_of(Path(args.bundle))
    if args.against:
        earlier = reading_of(Path(args.against))
        result["against"] = between(earlier, result)
    page = render(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
