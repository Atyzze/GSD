#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.measurements import starts as the_starts  # noqa: E402
from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS  # noqa: E402
import starts_check as C  # noqa: E402

CONTRACT = "gsd-disordered-reading-1"
RULE = {"from_n": 4096, "one_piece": 0.98, "probes_at_least": 2, "d_s_at_least": 1.5, "dimension_at_least": 1.5,
        "spread_at_most": 1.0, "reach_ratio_at_most": 1.5, "degree_moved_at_most": 0.05}
RULE_2 = {**RULE, "reach_over_random_at_least": 1.3}
RULES = {"1": RULE, "2": RULE_2}
PROBES = ("d_s", "d_V", "d_B")
KIND = {"empty": "empty", "given": "random", "random": "random",
        **{start.name: "lattice" for start in the_starts.known_lattices()}}


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def features(row: dict, before: dict | None) -> dict:
    probes = {p: _num(row.get(p)) for p in PROBES}
    read = [v for v in probes.values() if v is not None]
    out = {"n": int(row["n"]), "probes": len(read), "d_s": probes["d_s"],
           "d": round(statistics.median(read), 4) if read else None,
           "spread": round(max(read) - min(read), 4) if len(read) >= 2 else None,
           "piece": _num(row.get("giant_fraction")), "d_w": _num(row.get("d_w"))}
    reach, degree = _num(row.get("reach")), _num(row.get("mean_degree"))
    if reach and degree and degree > 2.0:
        out["reach_over_random"] = round(reach / (math.log(out["n"]) / math.log(degree - 1.0)), 4)
    if before is not None:
        out["n_before"], out["piece_before"] = int(before["n"]), _num(before.get("giant_fraction"))
        reach, reach_before = _num(row.get("reach")), _num(before.get("reach"))
        if reach and reach_before and reach > reach_before:
            out["d_reach"] = round(math.log(out["n"] / out["n_before"]) / math.log(reach / reach_before), 4)
        degree, degree_before = _num(row.get("mean_degree")), _num(before.get("mean_degree"))
        if degree is not None and degree_before:
            out["degree_moved"] = round(abs(degree - degree_before) / degree_before, 4)
    return out


def counted(f: dict, rule: dict = RULE) -> tuple[bool, str]:
    if f["n"] < rule["from_n"] or "n_before" not in f:
        return False, "not judged"
    if any(p is None or p < rule["one_piece"] for p in (f["piece"], f.get("piece_before"))):
        return False, "in pieces"
    if f["probes"] < rule["probes_at_least"] or f["d_s"] is None:
        return False, "probes refused"
    if f["d_s"] < rule["d_s_at_least"] or f["d"] < rule["dimension_at_least"]:
        return False, "under two dimensions"
    if f["spread"] > rule["spread_at_most"]:
        return False, "probes disagree"
    if f.get("d_reach") is None:
        return False, "reach does not grow"
    if abs(math.log(f["d_reach"] / f["d"])) > math.log(rule["reach_ratio_at_most"]):
        return False, "reach grows as no space of its dimension"
    if f.get("degree_moved") is None or f["degree_moved"] > rule["degree_moved_at_most"]:
        return False, "degree moving"
    floor = rule.get("reach_over_random_at_least")
    if floor is not None and (f.get("reach_over_random") is None or f["reach_over_random"] < floor):
        return False, "reaches no further than a random wiring"
    return True, "a disordered geometry"


def chain_reading(rows: list[dict], rule: dict = RULE) -> dict:
    rows = sorted((r for r in rows if r.get("n") is not None), key=lambda r: int(r["n"]))
    sizes, before = {}, None
    for row in rows:
        if int(row["n"]) >= 1024:
            f = features(row, before)
            ok, why = counted(f, rule)
            sizes[str(f["n"])] = {**f, "counted": ok, "why": why}
            before = row
    counted_at = [int(n) for n, s in sizes.items() if s["counted"]]
    judged = [int(n) for n, s in sizes.items() if s["why"] != "not judged"]
    held = any(a in counted_at and b in counted_at for a, b in zip(judged, judged[1:], strict=False))
    return {"counted_at": counted_at, "held": held, "sizes": sizes}


def rows_of(values: list[list], columns=VALUE_COLUMNS) -> list[dict]:
    return [dict(zip(columns, row, strict=True)) for row in values or []]


def summary_row(n: int, side: dict) -> dict:
    return {"n": int(n), **{key: (side.get(key) or {}).get("mean") for key in VALUE_COLUMNS[1:]}}


CHAINS = C.CHAINS


INDEX = {name: i for i, (name, _key, _family) in enumerate(CHAINS)}


NEUTRAL = {"empty": "random:6", "random": "random:6",
           **{start.name: f"melted:{start.name}" for start in the_starts.known_lattices()}}


HELD = "local:{name}:0.01"


READERS = ("alone", "beside", "as_start")


def read_key(spec: str, n: int, seed: int, index: int) -> str:
    return f"{spec}|{int(n)}|{int(seed)}|{int(index)}"


def replicates(criterion: dict, case: dict) -> dict:
    table = criterion["held_replicates"] if str(case["planted"]).startswith("held:") else criterion["replicates"]
    return {int(n): int(r) for n, r in table.items()}


def seeds_of(criterion: dict, replicate: int) -> list[int]:
    per = int(criterion["seeds_per_replicate"])
    first = int(criterion["first_seed"]) + per * int(replicate)
    return list(range(first, first + per))


def chain_specs(case: dict, reader: str) -> dict | None:
    planted = (case["planted"], 0)
    specs = {name: (NEUTRAL[name], INDEX[name]) for name in INDEX}
    if reader == "alone":
        specs["empty"] = planted
    elif reader == "beside":
        if not case.get("beside"):
            return None
        specs["empty"] = planted
        specs[case["beside"]] = (HELD.format(name=case["beside"]), INDEX[case["beside"]])
    elif reader == "as_start":
        if not case.get("slot"):
            return None
        specs[case["slot"]] = planted
    return specs


def plan(criterion: dict) -> list[dict]:
    units = []
    for case in criterion["cases"]:
        reps = replicates(criterion, case)
        for reader in READERS:
            specs = chain_specs(case, reader)
            if specs is None:
                continue
            for r in range(max(reps.values())):
                sizes = [n for n in criterion["sizes"] if r < reps.get(int(n), 0)]
                if len(sizes) < 2:
                    continue
                units.append({"case": case["id"], "reader": reader, "replicate": r, "sizes": sizes,
                              "seeds": seeds_of(criterion, r), "specs": specs})
    return units


def unit_chains(unit: dict, reads: dict) -> dict:
    rungs = []
    for n in unit["sizes"]:
        rung = {"n": int(n), "seeds": len(unit["seeds"]), "ends": {"completed": len(unit["seeds"])}}
        for name, key, _family in CHAINS:
            spec, index = unit["specs"][name]
            values = [reads[read_key(spec, n, s, index)]["values"] for s in unit["seeds"]]
            if key in ("empty", "given"):
                rung[key] = C.summary(values)
            else:
                rung.setdefault("more_given", {})[key] = C.summary(values)
        rungs.append(rung)
    return {"rungs": rungs, "every_chain": [{"name": name, "key": key, "start": family}
                                            for name, key, family in CHAINS]}


def calibrate(run_path: Path, criterion_path: Path, rule: dict = RULE) -> dict:
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    criterion = json.loads(Path(criterion_path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in criterion["cases"]}
    reads = {k: {"values": v} for k, v in run["values"].items()}
    table: dict = {}
    why: dict = {}
    for unit in plan(criterion):
        if unit["reader"] != "alone":
            continue
        chains = unit_chains(unit, reads)
        for key, case, kind in (("empty", unit["case"], cases[unit["case"]]["kind"]),):
            reading = chain_reading([summary_row(r["n"], r[key]) for r in chains["rungs"]], rule)
            for n, s in reading["sizes"].items():
                if int(n) < rule["from_n"]:
                    continue
                cell = table.setdefault(kind, {}).setdefault(case, {}).setdefault(n, [0, 0])
                cell[0] += int(s["counted"])
                cell[1] += 1
                if not s["counted"]:
                    why.setdefault(case, {}).setdefault(s["why"], 0)
                    why[case][s["why"]] += 1
    totals = {kind: {n: [sum(c[n][0] for c in by_case.values() if n in c), sum(c[n][1] for c in by_case.values()
                                                                                if n in c)]
                     for n in sorted({n for c in by_case.values() for n in c}, key=int)}
              for kind, by_case in table.items()}
    return {"contract": CONTRACT, "rule": rule, "run": Path(run_path).name, "criterion": Path(criterion_path).name,
            "by_case": table, "totals": totals, "why_not": why}


def _campaigns(root: Path) -> list[Path]:
    return sorted(p for p in Path(root).iterdir() if p.is_dir() and "_reports_" in p.name)


def study_campaigns(root: Path) -> set[str] | None:
    path = Path(root) / "study.json"
    if not path.is_file():
        return None
    study = json.loads(path.read_text(encoding="utf-8"))
    return {str(c["campaign_id"]) for c in study.get("campaigns") or [] if c.get("study_design")} or None


def read_bundle(root: Path, rule: dict = RULE) -> dict:
    out = {"contract": CONTRACT, "rule": rule, "bundle": Path(root).name, "campaigns": {}, "counted": [],
           "by_kind": {}, "left_out": []}
    ours = study_campaigns(root)
    for folder in _campaigns(root):
        campaign = folder.name.split("_reports_")[0].replace("campaign_", "")
        if ours is not None and campaign not in ours:
            out["left_out"].append(campaign)
            continue
        report = json.loads((folder / "28-decision-engine.json").read_text(encoding="utf-8"))
        every_chain = (report.get("body") or {}).get("every_chain") or {}
        laws = every_chain.get("laws") or {}
        columns = tuple(every_chain.get("value_columns") or VALUE_COLUMNS)
        with_values = {law: entry for law, entry in laws.items() if isinstance(entry.get("values"), dict)}
        source = "report 28 values" if with_values else "report 05 specimens"
        chains_read = 0
        if with_values:
            for law, entry in with_values.items():
                for chain, values in entry["values"].items():
                    reading = chain_reading(rows_of(values, columns), rule)
                    chains_read += 1
                    _count(out, campaign, law, chain, reading)
        else:
            phen = json.loads((folder / "05-phenotypes.json").read_text(encoding="utf-8"))
            for specimen in (phen.get("body") or {}).get("specimens") or []:
                per_n = (specimen.get("phenotype") or {}).get("per_n") or {}
                per_n = {**per_n, **((specimen.get("phenotype") or {}).get("extension_per_n") or {})}
                rows = [{"n": int(n), "d_s": v.get("d_s"), "d_V": v.get("d_V"), "d_B": v.get("d_B"),
                         "d_w": v.get("d_w"), "reach": v.get("half_volume_radius"),
                         "mean_degree": v.get("mean_degree"), "giant_fraction": v.get("connected_fraction")}
                        for n, v in per_n.items() if isinstance(v, dict)]
                reading = chain_reading(rows, rule)
                chains_read += 1
                _count(out, campaign, str(specimen.get("candidate_id")), "empty", reading)
        out["campaigns"][campaign] = {"source": source, "laws": len(with_values) if with_values else None,
                                      "chains_read": chains_read}
    return out


def _count(out: dict, campaign: str, law: str, chain: str, reading: dict) -> None:
    kind = KIND.get(chain, "lattice")
    tally = out["by_kind"].setdefault(kind, {"chains": 0, "judged": 0, "counted": 0, "held": 0, "why_not": {}})
    tally["chains"] += 1
    judged = [s for s in reading["sizes"].values() if s["why"] != "not judged"]
    if judged:
        tally["judged"] += 1
        top = judged[-1]
        if not top["counted"]:
            tally["why_not"][top["why"]] = tally["why_not"].get(top["why"], 0) + 1
    if reading["counted_at"]:
        tally["counted"] += 1
        tally["held"] += int(reading["held"])
        out["counted"].append({"campaign": campaign, "law": law, "chain": chain, "kind": kind,
                               "counted_at": reading["counted_at"], "held": reading["held"],
                               "sizes": reading["sizes"]})


def render(found: dict) -> str:
    lines = [f"# Disordered geometry read in {found['bundle']} (rule {found.get('rule_name', '?')})", "",
             f"`{CONTRACT}`; the rule: " + ", ".join(f"{k} {v}" for k, v in found["rule"].items()) + ".", "",
             "| campaign | read from | chains read |", "|---|---|---|"]
    for campaign, c in sorted(found["campaigns"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        lines.append(f"| {campaign} | {c['source']} | {c['chains_read']:,} |")
    if found.get("left_out"):
        lines += ["", "Left out, not the study's laws (its design names them not; the standing controls): campaign "
                  + ", ".join(found["left_out"]) + "."]
    lines += ["", "| who started the chain | chains | judged from 4,096 | counted at a size | at two sizes in a row | "
              "why not, at its largest size judged |", "|---|---|---|---|---|---|"]
    for kind, t in found["by_kind"].items():
        why = ", ".join(f"{k} {v:,}" for k, v in sorted(t["why_not"].items(), key=lambda kv: -kv[1]))
        lines.append(f"| {kind} | {t['chains']:,} | {t['judged']:,} | {t['counted']:,} | {t['held']:,} | {why} |")
    lines += ["", f"## The chains counted ({len(found['counted'])})", ""]
    for c in found["counted"][:200]:
        sizes = "; ".join(f"{n}: d {s['d']}, reach's {s.get('d_reach')}, d_w {s.get('d_w')}" for n, s in c["sizes"].items()
                          if s["counted"])
        lines.append(f"* campaign {c['campaign']}, `{c['law'][:12]}`, {c['chain']} ({c['kind']}): {sizes}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/disordered_reading.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="command", required=True)
    cal = sub.add_parser("calibrate", help="the rule on a detection run's graphs")
    cal.add_argument("--run", type=Path, required=True)
    cal.add_argument("--criterion", type=Path, required=True)
    cal.add_argument("--json", type=Path)
    cal.add_argument("--rule", choices=sorted(RULES), default="2")
    bun = sub.add_parser("bundle", help="every chain of a study bundle, unpacked")
    bun.add_argument("root", type=Path)
    bun.add_argument("--json", type=Path)
    bun.add_argument("--md", type=Path)
    bun.add_argument("--rule", choices=sorted(RULES), default="2")
    args = parser.parse_args(argv)
    if args.command == "calibrate":
        found = dict(calibrate(args.run, args.criterion, RULES[args.rule]), rule_name=args.rule)
        for kind, by_n in found["totals"].items():
            print(kind, ", ".join(f"{n}: {c}/{t}" for n, (c, t) in by_n.items()))
        if args.json:
            args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    found = dict(read_bundle(args.root, RULES[args.rule]), rule_name=args.rule)
    for kind, t in found["by_kind"].items():
        print(f"{kind}: {t['counted']} counted ({t['held']} at two sizes in a row) of {t['judged']} judged "
              f"({t['chains']} chains)")
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.md:
        args.md.write_text(render(found), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
