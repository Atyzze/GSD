#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

CONTRACT = "gsd-holds-reading-1"
LONGER = ["run_next", "longer_chain"]


def holds(law: dict | None) -> bool:
    return bool(law) and "holds" in (law.get("fates") or {}).values()


def _brief(law: dict | None) -> dict | None:
    if not law:
        return None
    return {"class": law.get("class"), "at_n": law.get("at_n"), "decision": law.get("decision"),
            "held": sorted(k for k, v in (law.get("fates") or {}).items() if v == "holds")}


def _where(then: dict, now: dict) -> str:
    if (now.get("at_n") or 0) > (then.get("at_n") or 0):
        return "at the next size"
    if (then.get("decision") or [])[:2] == LONGER and now.get("decision") != then.get("decision"):
        return "on a longer chain at the same size"
    return "at the same size"


def step(then: dict, now: dict) -> dict:
    lost, gained = [], []
    not_read = sorted(law[:12] for law, record in then.items() if holds(record) and law not in now)
    for law, record in sorted(then.items()):
        if holds(record) and law in now and not holds(now.get(law)):
            lost.append({"law": law[:12], "where": _where(record, now.get(law) or {}),
                         "then": _brief(record), "now": _brief(now.get(law))})
    for law, record in sorted(now.items()):
        if holds(record) and not holds(then.get(law)):
            how = "read for the first time" if law not in then else _where(then[law], record)
            gained.append({"law": law[:12], "where": how, "then": _brief(then.get(law)), "now": _brief(record)})
    finished = {"holders_kept": [], "holders_lost": [], "others_came_to_hold": [], "others_did_not": 0}
    for law, record in then.items():
        if (record.get("decision") or [])[:2] != LONGER or (now.get(law) or {}).get("decision") == record.get(
                "decision") or law not in now:
            continue
        if holds(record):
            finished["holders_kept" if holds(now[law]) else "holders_lost"].append(law[:12])
        elif holds(now[law]):
            finished["others_came_to_hold"].append(law[:12])
        else:
            finished["others_did_not"] += 1
    for key in ("holders_kept", "holders_lost", "others_came_to_hold"):
        finished[key].sort()
    counts = {}
    for item in lost:
        counts[item["where"]] = counts.get(item["where"], 0) + 1
    return {"holders": [sum(1 for r in then.values() if holds(r)), sum(1 for r in now.values() if holds(r))],
            "lost": lost, "lost_by_where": dict(sorted(counts.items())), "gained": gained, "not_read": not_read,
            "longer_chains_finished": finished,
            "holders_waiting_on_a_longer_chain": sum(1 for r in now.values()
                                                     if holds(r) and (r.get("decision") or [])[:2] == LONGER)}


def read(paths: list[Path]) -> dict:
    named = list(zip(paths, [json.loads(p.read_text(encoding="utf-8")) for p in paths], strict=True))
    steps = []
    for (path_a, a), (path_b, b) in zip(named, named[1:], strict=False):
        steps.append({"from": a.get("bundle") or path_a.name, "to": b.get("bundle") or path_b.name,
                      **step(a["laws"], b["laws"])})
    kept = sum(len(s["longer_chains_finished"]["holders_kept"]) for s in steps)
    lost = sum(len(s["longer_chains_finished"]["holders_lost"]) for s in steps)
    return {"contract": CONTRACT, "files": [p.name for p in paths], "steps": steps,
            "totals": {"holders_lost": sum(len(s["lost"]) for s in steps),
                       "holders_gained": sum(len(s["gained"]) for s in steps),
                       "longer_chains_finished_on_holders": kept + lost, "kept": kept, "lost": lost}}


JUDGEMENT = "gsd-holds-judgement-1"


def judge(criterion: dict, laws: dict, bundle: str | None = None) -> dict:
    rows = []
    for w in criterion["waiting"]:
        now = laws.get(w["law"])
        finished = bool(now) and now.get("decision") != w["decision"]
        rows.append({"law": w["law"][:12], "held_then": w["held"], "finished": finished,
                     "held_now": sorted(k for k, v in ((now or {}).get("fates") or {}).items() if v == "holds"),
                     "decision_now": (now or {}).get("decision")})
    done = [r for r in rows if r["finished"]]
    needed = int(criterion["judged_when"]["finished_at_least"])
    ready = len(done) >= needed
    out = []
    for p in criterion["predictions"]:
        rule = p["rule"]
        lattice = rule.get("lattice")
        pool = [r for r in done if lattice is None or lattice in r["held_then"]]
        kept = [r for r in pool if (r["held_now"] if lattice is None else lattice in r["held_now"])]
        share = round(len(kept) / len(pool), 3) if pool else None
        if share is None:
            word = "nothing to measure yet"
        elif "kept_share_below" in rule:
            word = "held" if share < rule["kept_share_below"] else "missed"
        else:
            word = "held" if share <= rule["kept_share_at_most"] else "missed"
        verdict = word if ready and share is not None else f"reported, not judged: {word}"
        out.append({"id": p["id"], "claim": p["claim"], "finished": len(pool), "kept": len(kept), "share": share,
                    "verdict": verdict})
    return {"contract": JUDGEMENT, "criterion": criterion["contract"], "bundle": bundle, "finished": len(done),
            "waiting": len(rows), "needed": needed, "judged": ready, "laws": rows, "predictions": out}


def render_judgement(result: dict) -> str:
    state = "judged" if result["judged"] else f"reported, not judged (needs {result['needed']} finished)"
    out = [f"# The holds criterion, in {result['bundle']}", "",
           f"{result['finished']} of the {result['waiting']} holders waiting on a longer chain have finished it: "
           f"{state}.", "", "| id | claim | finished | kept | share | verdict |", "|---|---|---:|---:|---:|---|"]
    out += [f"| {p['id']} | {p['claim']} | {p['finished']} | {p['kept']} | {p['share']} | {p['verdict']} |"
            for p in result["predictions"]]
    out += ["", "| law | held then | finished | held now | decision now |", "|---|---|---|---|---|"]
    out += [f"| `{r['law']}` | {', '.join(r['held_then'])} | {'yes' if r['finished'] else 'not yet'} | "
            f"{', '.join(r['held_now']) or 'none'} | {' '.join(str(x) for x in (r['decision_now'] or []))} |"
            for r in result["laws"]]
    return "\n".join(out) + "\n"


def render(result: dict) -> str:
    t = result["totals"]
    out = [f"# Which holds survive, {result['steps'][0]['from']} to {result['steps'][-1]['to']}" if result["steps"]
           else "# Which holds survive", "",
           f"{CONTRACT}, from the starts' law files. Over every step: {t['holders_lost']} holds lost, "
           f"{t['holders_gained']} gained; of the {t['longer_chains_finished_on_holders']} holders whose size was run "
           f"again with a longer chain and finished, {t['kept']} kept their lattice and {t['lost']} lost it.", ""]
    for s in result["steps"]:
        f = s["longer_chains_finished"]
        out += [f"## {s['from']} to {s['to']}", "",
                f"Holders {s['holders'][0]:,} then, {s['holders'][1]:,} now; lost {len(s['lost'])} ("
                + ", ".join(f"{v} {k}" for k, v in s["lost_by_where"].items()) + f"), gained {len(s['gained'])}. "
                f"Longer chains finished: on holders {len(f['holders_kept'])} kept and {len(f['holders_lost'])} lost; "
                f"on other laws {len(f['others_came_to_hold'])} came to hold and {f['others_did_not']} did not. "
                f"Holders waiting on a longer chain: {s['holders_waiting_on_a_longer_chain']}.", ""]
        rows = [("lost", item) for item in s["lost"]] + [("gained", item) for item in s["gained"]]
        if rows:
            out += ["| law | | where | then | now |", "|---|---|---|---|---|"]
            for kind, item in rows:
                then = item["then"] or {}
                now = item["now"] or {}
                fmt = (lambda r: f"{r.get('class')} at {r.get('at_n')}, held {', '.join(r.get('held') or []) or 'none'}"
                       f", {' '.join(str(x) for x in (r.get('decision') or []))}" if r else "not read")
                out.append(f"| `{item['law']}` | {kind} | {item['where']} | {fmt(then)} | {fmt(now)} |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/holds_reading.py: see docs/TOOLS.md")
    parser.add_argument("laws", nargs="+", help="the starts' law files, oldest first")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    parser.add_argument("--judge", help="a committed holds criterion, read in the newest law file")
    args = parser.parse_args(argv)
    if args.judge:
        newest = json.loads(Path(args.laws[-1]).read_text(encoding="utf-8"))
        result = judge(json.loads(Path(args.judge).read_text(encoding="utf-8")), newest["laws"],
                       newest.get("bundle") or Path(args.laws[-1]).name)
        page = render_judgement(result)
    else:
        result = read([Path(p) for p in args.laws])
        page = render(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    if not args.json and not args.md:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
