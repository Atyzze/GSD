#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402
from graph_scale_dynamics.research import finds as FN  # noqa: E402

CONTRACT = "gsd-score-list-1"
CHAIN = "the chain from empty: a bundle's rung rows carry it, where the decision engine reads it"


def chains_of(law: dict) -> dict:
    rungs = []
    for n, rung in sorted((law.get("rungs") or {}).items(), key=lambda kv: int(kv[0])):
        seeds = int(rung.get("seeds") or 0)
        side = {p: {"mean": rung.get(p), "se": 0.0, "seeds": seeds, "of": seeds} for p in L.PROBES}
        side["giant_fraction"] = {"mean": rung.get("connected_fraction")}
        rungs.append({"n": int(n), "seeds": seeds, "empty": side})
    return {"rungs": rungs}


COLUMNS = ("n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction")


def chains_of_report(entry: dict, columns=None, moved: dict | None = None) -> tuple[dict, dict]:
    values = entry.get("values") or {}
    names = [name for name in values if name not in ("empty", "given")]
    at = list(columns).index("moved") if columns and "moved" in columns else None
    rungs: dict[int, dict] = {}
    for name, rows in values.items():
        for row in rows:
            side = {key: {"mean": value} for key, value in zip(COLUMNS[1:], row[1:len(COLUMNS)], strict=False)}
            found = ((moved or {}).get(name) or {}).get(int(row[0]))
            if found is None and at is not None and at < len(row):
                found = row[at]
            if found is not None:
                side["moved"] = {"median": found}
            rungs.setdefault(int(row[0]), {"n": int(row[0]), "more_given": {}})
            if name in ("empty", "given"):
                rungs[int(row[0])][name] = side
            else:
                rungs[int(row[0])]["more_given"][name] = side
    given = entry.get("given") or "given"
    family = entry.get("given_family")
    if family is None and not entry.get("given"):
        family = "a control's own start"
    every = ([{"name": "empty", "key": "empty", "start": "the empty graph"},
              {"name": given, "key": "given", **({"family": family} if family else {})}]
             + [{"name": name, "key": name} for name in names])
    fates = {name: {"fate": fate} for name, (fate, _kept) in ((entry.get("starts_reading") or {}).get("fates") or {}).items()}
    five = {"rungs": [{"n": n, "fates": fates} for n in rungs]}
    return {"rungs": [rungs[n] for n in sorted(rungs)], "every_chain": every, "given_name": given}, five


def _why(found: dict) -> str:
    entry = found["sizes"][[s["n"] for s in found["sizes"]].index(found["to_n"])]["chains"][found["chain"]]
    return f"{entry['how']}, from N={entry['from_n']:,} to {found['to_n']:,}"


def read(record: dict) -> dict:
    laws, listed = record.get("laws") or {}, []
    relied = scored = five = 0
    for law_id, law in sorted(laws.items()):
        found = L.score(chains_of(law), references={})
        if found["sizes"]:
            relied += 1
        if found["score"] > 0:
            scored += 1
            five += int(found["points"] == L.POINTS)
            top = found["sizes"][-1]["chains"].get(found["chain"]) or {"how": "not read at the top"}
            listed.append({"law": law_id, "score": found["score"], "points": found["points"], "to_n": found["to_n"],
                           "by": found["by"], "chain": found["chain"], "d": found["d"],
                           "mean_degree": found["mean_degree"], "top_n": law.get("top_n"), "decision": [law.get("action"), law.get("rule"), law.get("at_n")],
                           "why": _why(found), "at_its_top": top["how"],
                           "readings_at_to_n": {p: (law["rungs"].get(str(found["to_n"])) or {}).get(p) for p in L.PROBES}})
    listed.sort(key=lambda row: (-row["score"], -row["to_n"], row["law"]))
    return {"contract": CONTRACT, "score_contract": L.CONTRACT, "bundle": record.get("bundle"),
            "built_on": record.get("build_number"), "chain": CHAIN, "laws": len(laws),
            "with_two_sizes_from_4096": relied, "scored": scored, "full_points": five, "list": listed,
            "margins": {k: L.margins()[k] for k in ("relative", "tau")}}


def control_bundles(root: Path) -> set[str]:
    study = Path(root) / "study.json"
    if not study.is_file():
        return set()
    found = json.loads(study.read_text(encoding="utf-8"))
    return {str(row.get("bundle")) for row in found.get("campaigns") or [] if row.get("controls") is not None}


def read_report_28(root: Path) -> dict:
    listed, laws = [], 0
    relied = scored = five = 0
    controls = control_bundles(root)
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        control = Path(path).parent.name in controls
        body = json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}
        decided = {str(r.get("candidate_id")): r for r in body.get("laws") or [] if isinstance(r, dict)}
        ledger = {str(r.get("candidate_id")): r for r in ((body.get("law_ledger") or {}).get("rows") or [])
                  if isinstance(r, dict)}
        columns = (body.get("every_chain") or {}).get("value_columns")
        for law_id, entry in sorted(((body.get("every_chain") or {}).get("laws") or {}).items()):
            laws += 1
            chains, reading = chains_of_report(entry, columns)
            found = L.score(chains, reading, references={})
            relied += int(bool(found["sizes"]))
            if found["score"] <= 0:
                continue
            scored += 1
            five += int(found["points"] == L.POINTS)
            own = decided.get(law_id) or {}
            top = found["sizes"][-1]["chains"].get(found["chain"]) or {"how": "not read at the top"}
            listed.append({"law": law_id, "score": found["score"], "points": found["points"], "to_n": found["to_n"],
                           "by": found["by"], "chain": found["chain"], "d": found["d"],
                           "mean_degree": found["mean_degree"], "top_n": entry.get("top_n"),
                           "scales_with_n": FN.scales_with_n((ledger.get(law_id) or {}).get("spec")),
                           "decision": [own.get("action"), own.get("rule"), own.get("at_n")], "why": _why(found),
                           "at_its_top": top["how"], "control": control})
    listed.sort(key=lambda row: (-row["score"], -row["to_n"], row["law"]))
    return {"contract": CONTRACT, "score_contract": L.CONTRACT, "bundle": Path(root).name, "built_on": None,
            "chain": "every chain of every law, from report 28's values and its starts' reading's fates",
            "laws": laws, "with_two_sizes_from_4096": relied, "scored": scored, "full_points": five,
            "list": listed, "margins": {k: L.margins()[k] for k in ("relative", "tau")}}


def render(found: dict) -> str:
    lines = [f"# The score's first list, on {found['bundle']} (build {found['built_on']})", "",
             f"The score ({found['score_contract']}) read on the {found['laws']} laws of the pilot "
             f"record, {found['chain']}. {found['with_two_sizes_from_4096']} laws have two sizes from 4,096, which a "
             f"probe needs to settle; {found['scored']} score above zero, {found['full_points']} of them with every point "
             "(each probe and the Einstein relation settled twice). Every other start's chain is not in the record: the list on "
             "all eight starts is read from a pilot's whole bundle."
             + (f" {sum(1 for row in found['list'] if row.get('control'))} of the laws that score are the study's "
                "standing controls, marked so: laws whose answer is known, not drawn."
                if any(row.get("control") for row in found["list"]) else ""), "",
             f"d is the median of the four probes on the scoring chain at its top; below {L.RING_BELOW} it is a ring "
             "(one-dimensional), marked so.", "",
             "N is which of the law's terms scale with the size of the graph, as its law ledger row keeps them; "
             "free of N is a law every node can follow without knowing the size.", "",
             "| law | score | d | mean degree | N | chain | points | at N | top N | decision | why |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in found["list"]:
        decision = " ".join(str(x) for x in row["decision"] if x is not None)
        d = row.get("d")
        shown = "" if d is None else f"{d:g}" + (" (ring)" if L.is_ring(d) else "")
        degree = row.get("mean_degree")
        mark = " (a standing control)" if row.get("control") else ""
        lines.append(f"| `{row['law'][:12]}`{mark} | {row['score']} | {shown} | {'' if degree is None else degree} | "
                     f"{FN.n_text(row.get('scales_with_n'))} | {row['chain']} ({row['by']}) | {row['points']} of {L.POINTS} | {row['to_n']:,} | "
                     f"{(row['top_n'] or 0):,} | {decision} | {row['why']}; at its top: {row['at_its_top']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the score's list, read on a pilot's record or bundle")
    parser.add_argument("source", help="a pilot record (.json, as tools/pilot_difference.py --record writes) or a study bundle")
    parser.add_argument("--json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if source.suffix == ".json":
        from pilot_difference import load
        found = read(load(source))
    else:
        from read_bundle import scratch_dir, unpacked
        found = read_report_28(unpacked(source, scratch_dir("gsd-score-list-")) if source.is_file() else source)
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(found), encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
