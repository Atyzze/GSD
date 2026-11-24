#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import coverage_reading as C  # noqa: E402
import history_reading as H  # noqa: E402
import law_rows as L  # noqa: E402

from graph_scale_dynamics.research import dimension_rule as R  # noqa: E402
from graph_scale_dynamics.research import dimension_test as T  # noqa: E402

CONTRACT = "gsd-dimension-reading-1"
GROWN, LATTICES, KEPT_FATES, LINE_BELOW = R.GROWN, R.LATTICES, R.KEPT_FATES, R.LINE_BELOW
KINDS, calibration, judged_chain, kind_of = R.KINDS, R.calibration, R.judged_chain, R.kind_of


def why_dropped(cell: dict, rule: T.Rule = T.RULE) -> str | None:
    degree, piece = T._value(cell, "mean_degree"), T._value(cell, "giant_fraction")
    if degree is None or piece is None:
        return "not read"
    found = (["in pieces"] if piece < rule.piece_at_least else []) + (
        ["degree off the window"] if degree <= rule.degree_above or degree >= rule.degree_below else [])
    return " and ".join(found) or None


def dropped_above(rows: list, columns: list, judged: dict, rule: T.Rule = T.RULE) -> list[dict]:
    if not judged["sizes"]:
        return []
    out = []
    for cell in sorted((dict(zip(columns, row, strict=False)) for row in rows or []), key=lambda c: int(c["n"])):
        if int(cell["n"]) > judged["sizes"][-1]:
            out.append({"n": int(cell["n"]), "why": why_dropped(cell, rule),
                        "degree": R._round(cell.get("mean_degree"), 3),
                        "piece": R._round(cell.get("giant_fraction"), 3)})
    return out


def law_entry(law: str, chained: dict, columns: list, ledger: dict, ended: tuple[str, str], campaign: str,
              cal: dict) -> dict:
    starts = chained.get("starts_reading") or {}
    fates = {name: (value or [None])[0] for name, value in (starts.get("fates") or {}).items()}
    chains = {name: R.mark(name, judged_chain(rows, columns), fates.get(name), cal)
              for name, rows in (chained.get("values") or {}).items()}
    for name, rows in (chained.get("values") or {}).items():
        below = dropped_above(rows, columns, chains[name])
        if below:
            chains[name]["dropped_above"] = below
    spec = ledger.get("spec") or {}
    fate = list(ledger.get("fate") or [None, None]) + [None, None]
    return {"law": law, "campaign": campaign, "class": starts.get("class") or "not_read", "state": ended[0],
            "ended": ended[1], "fate": fate[0], "fate_n": fate[1], "top_n": chained.get("top_n"),
            "zero_t": bool(spec.get("zero_temperature")), "stratum": C.stratum(spec) if spec else None,
            "operators": sorted({str(t[0]) for t in spec.get("terms") or []}),
            "kinds": sorted({c["kind"] for c in chains.values() if c["kind"]}, key=KINDS.index), "chains": chains}


def entries_of(root: Path, cal: dict) -> list[dict]:
    ended = H.ended_by(root)
    out = []
    for part in L.campaigns(root):
        engine = L.body(root / str(part.get("bundle") or ""))
        every = engine.get("every_chain") or {}
        columns = every.get("value_columns") or list(H.COLUMNS)
        ledger = {str(r.get("candidate_id")): r for r in (engine.get("law_ledger") or {}).get("rows") or []}
        campaign = str(part.get("campaign_id"))
        for law, chained in (every.get("laws") or {}).items():
            if law in ledger:
                out.append(law_entry(law, chained, columns, ledger[law], ended.get(law, ("", "")), campaign, cal))
        del engine, every, ledger
        gc.collect()
    return out


def _pick(entry: dict, kind: str) -> list[tuple[str, dict]]:
    return [(name, c) for name, c in entry["chains"].items() if c["kind"] == kind]


def below_top(entries: list[dict]) -> dict:
    chains = sorted(({"law": e["law"], "campaign": e["campaign"], "chain": GROWN.get(name, name),
                      "verdict": c["verdict"], "kind": c["kind"], "d": c["d"], "sizes": c["sizes"],
                      "top_n": c["top_n"], "dropped": c["dropped_above"], "state": e["state"], "ended": e["ended"]}
                     for e in entries for name, c in e["chains"].items() if c.get("dropped_above")),
                    key=lambda c: (KINDS.index(c["kind"]) if c["kind"] else len(KINDS), c["law"], c["chain"]))
    return {"chains": len(chains), "laws": len({c["law"] for c in chains}),
            "by_kind": dict(Counter(c["kind"] or "not dimensional" for c in chains).most_common()),
            "by_why_at_the_next_size": dict(Counter(c["dropped"][0]["why"] for c in chains).most_common()),
            "dimensional_by_why_at_the_next_size": dict(Counter(c["dropped"][0]["why"] for c in chains
                                                                if c["kind"]).most_common()),
            "entries": [c for c in chains if c["kind"]],
            "not_dimensional": {f"{c['law'][:12]} {c['chain']}": _one_line(c) for c in chains if not c["kind"]}}


def _one_line(chain: dict) -> str:
    return (f"campaign {chain['campaign']}; judged on {', '.join(f'{n:,}' for n in chain['sizes'])}; top "
            f"{chain['top_n']:,}; " + "; ".join(f"{d['n']:,} {d['why']}" for d in chain["dropped"]))


def summarize(entries: list[dict], cal: dict) -> dict:
    by_chain = Counter()
    for e in entries:
        for name, c in e["chains"].items():
            by_chain[f"{GROWN.get(name, name)}: {c['verdict']}"] += 1
    listed = {}
    for kind in ("grown", "changed"):
        laws = [e for e in entries if kind in e["kinds"]]
        chains = [c for e in laws for _, c in _pick(e, kind)]
        best = [min((0 if not c["beyond_checked"] and not c["line"] else 1 if c["beyond_checked"] else 2)
                    for _, c in _pick(e, kind)) for e in laws]
        listed[kind] = {
            "laws": len(laws), "chains": len(chains),
            "laws_inside": best.count(0), "laws_beyond": best.count(1), "laws_lines": best.count(2),
            "lines": sum(c["line"] for c in chains),
            "beyond_checked": sum(c["beyond_checked"] and not c["line"] for c in chains),
            "inside_checked": sum(not c["beyond_checked"] and not c["line"] for c in chains),
            "by_class": dict(Counter(e["class"] for e in laws).most_common()),
            "by_decision": dict(Counter(f"{H.STATES.get(e['state'], e['state'])}: {e['ended']}"
                                        for e in laws).most_common()),
            "zero_t": sum(e["zero_t"] for e in laws),
            "entries": sorted(({k: e[k] for k in ("law", "campaign", "class", "state", "ended", "fate", "fate_n",
                                                  "top_n", "zero_t", "stratum", "operators")}
                               | {"chains": {GROWN.get(n, n): c for n, c in _pick(e, kind)}} for e in laws),
                              key=lambda x: (min(c["beyond_checked"] or c["line"] for c in x["chains"].values()),
                                             -max(c["sizes"][-1] for c in x["chains"].values()), x["law"]))}
    kept = [e for e in entries if e["kinds"] == ["kept_d"]]
    return {"laws": len(entries), "chains_by_verdict": dict(sorted(by_chain.items())), "grown": listed["grown"],
            "changed": listed["changed"], "judged_below_top": below_top(entries),
            "kept_d_only": {"laws": len(kept),
                            "whose_lattice_does_not_hold": sum(
                                any(c["kind"] == "kept_d" and c["fate"] not in KEPT_FATES
                                    for c in e["chains"].values()) for e in kept),
                            "by_state": dict(Counter(H.STATES.get(e["state"], e["state"])
                                                     for e in kept).most_common())}}


def reading(root: Path) -> dict:
    cal = calibration()
    entries = entries_of(root, cal)
    return {"contract": CONTRACT, "bundle": root.name, "test": T.DIMENSION_TEST_CONTRACT, "calibration": cal,
            "line_below": LINE_BELOW, "kept_fates": list(KEPT_FATES), **summarize(entries, cal)}


def _n(value) -> str:
    return "" if value is None else f"{value:g}"


def _above(dropped: list[dict] | None) -> str:
    if not dropped:
        return ""
    return " (not " + ", ".join(f"{d['n']:,}: {d['why']}" for d in dropped) + ")"


def _below_top_lines(part: dict) -> list[str]:
    lines = ["## Chains judged below their top size", "",
             f"The test reads a chain only at the sizes it can use (from {T.RULE.from_n:,}, one piece of at least "
             f"{T.RULE.piece_at_least:.0%}, a mean degree above {T.RULE.degree_above:g} and below "
             f"{T.RULE.degree_below:g}), so a chain whose larger sizes fell apart or left that window is judged at its "
             f"last usable size. {part['chains']:,} chains of {part['laws']:,} laws are: "
             + ", ".join(f"{kind.replace('_', ' ')} {count:,}" for kind, count in part["by_kind"].items())
             + ". Why the size after the last one judged was dropped: "
             + ", ".join(f"{why} {count:,}" for why, count in part["by_why_at_the_next_size"].items())
             + "; of the dimensional ones, "
             + (", ".join(f"{why} {count:,}" for why, count in part["dimensional_by_why_at_the_next_size"].items())
                or "none") + ". The dimensional ones are named here, every one in the JSON (`judged_below_top`).",
             ""]
    shown = part["entries"]
    if shown:
        lines += ["| law | campaign | start | kind | d | judged on | top | the sizes dropped |",
                  "|---|---|---|---|---:|---|---:|---|"]
        lines += [f"| `{c['law'][:12]}` | {c['campaign']} | {c['chain']} | {c['kind'].replace('_', ' ')} | "
                  f"{c['d']:.2f} | {', '.join(f'{n:,}' for n in c['sizes'])} | {c['top_n']:,} | "
                  + "; ".join(f"{d['n']:,} {d['why']} (degree {_n(d['degree'])}, one piece {_n(d['piece'])})"
                              for d in c["dropped"]) + " |" for c in shown]
    return lines + [""]


def _chain_rows(entry: dict) -> list[str]:
    out = []
    for name, c in entry["chains"].items():
        a = c["at_d"]
        note = "a line" if c["line"] else ("beyond what the test was checked on" if c["beyond_checked"] else "")
        sizes = ", ".join(f"{n:,}" for n in c["sizes"]) + _above(c.get("dropped_above"))
        out.append(f"| {name} | {c['d']:.2f} | {sizes} | {c['reach_exponent']:.2f} | "
                   f"{c['growth_gap']:.2f} | {_n(a['mean_degree'])} | {_n(a['giant_fraction'])} | {_n(a['reach'])} | "
                   f"{_n(a['d_s'])} | {_n(a['d_V'])} | {_n(a['d_B'])} | {_n(a['d_w'])} | "
                   f"{_n(a['triangles_per_node'])} | {_n(a['squares_per_node'])} | {c['fate'] or ''} | {note} |")
    return out


def render(result: dict) -> str:
    cal = result["calibration"]
    lines = [f"# The study read with the dimension test, from {result['bundle']}", "",
             f"Every chain of every law the bundle reports from 1,024 nodes, judged by `research/dimension_test.py` "
             f"as frozen at 729 ({result['test']}; {result['contract']}), offline, no rerun. Recorded, never judged: "
             "it is what the dimension rule extends.", "",
             f"{result['laws']:,} laws. A chain is **grown** when it starts from empty or from the random graph and "
             "reads dimensional; a lattice chain has **changed** its dimension when it reads dimensional outside "
             "the band the criterion gives its lattice ("
             + ", ".join(f"{k} {v[0]} to {v[1]}" for k, v in cal["lattice_bands"].items())
             + ") and further than half that band from what the instrument reads on the exact lattice at the same "
             "size (the training reading), so a lattice the instrument under-reads at a small size is not counted "
             "as changed. The test's training geometries read a d of at most "
             f"{cal['d_checked_up_to']} with a reach growing as N to {cal['reach_exponent_checked_down_to']} or "
             "more; a chain with a higher d or a slower reach passes the rule but is **beyond what the test was "
             f"checked on**, where a slow small world and a high dimension are not yet told apart. A chain whose d "
             f"reads below {result['line_below']} is **a line** (a path or a ring).", "",
             "| chain: verdict | chains |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k, v in result["chains_by_verdict"].items()]
    below = result["judged_below_top"]
    lines += ["", f"{below['chains']:,} chains ({below['by_kind'].get('not dimensional', 0):,} of them not "
              f"dimensional) are judged below their top size, their larger sizes dropped by the test "
              "(\"Chains judged below their top size\")."]
    lines += ["", f"{result['kept_d_only']['laws']:,} laws read dimensional only on a lattice start that kept its "
              f"lattice's dimension; on {result['kept_d_only']['whose_lattice_does_not_hold']:,} of them the five "
              "starts do not call that lattice held or unmoved: the dimension stays while the lattice does not. How "
              "their last decisions left them: "
              + ", ".join(f"{k} {v:,}" for k, v in result["kept_d_only"]["by_state"].items()) + ".", ""]
    for kind, title in (("grown", "Grown from empty or from the random graph"),
                        ("changed", "A lattice start that changed its dimension")):
        part = result[kind]
        lines += [f"## {title}", "",
                  f"{part['laws']:,} laws, {part['chains']:,} chains: {part['inside_checked']:,} inside what the test "
                  f"was checked on and not a line, {part['beyond_checked']:,} beyond it, {part['lines']:,} lines. By "
                  f"each law's best chain: {part['laws_inside']:,} inside, {part['laws_beyond']:,} beyond, "
                  f"{part['laws_lines']:,} lines. "
                  f"{part['zero_t']:,} of the laws at zero temperature. Their starts' classes: "
                  + ", ".join(f"{k} {v:,}" for k, v in part["by_class"].items()) + ". Their last decisions: "
                  + "; ".join(f"{k} {v:,}" for k, v in part["by_decision"].items()) + ".", ""]
        for e in part["entries"]:
            at = "" if e["fate_n"] is None else f" at {int(e['fate_n']):,}"
            lines += [f"### `{e['law'][:12]}`, campaign {e['campaign']}", "",
                      f"{e['class']}; {H.STATES.get(e['state'], e['state'])}: {e['ended']}{at}; "
                      f"{'zero' if e['zero_t'] else 'finite'} temperature; {e['stratum']}; terms "
                      f"{', '.join(e['operators'])}.", "",
                      "| start | d | sizes | reach exp. | growth gap | degree | one piece | reach | d_s | d_V | d_B | "
                      "d_w | triangles | squares | fate | note |",
                      "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
            lines += _chain_rows(e) + [""]
    lines += _below_top_lines(result["judged_below_top"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/dimension_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-dimension-") as scratch:
        result = reading(unpacked(Path(args.bundle), Path(scratch)))
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = render(result)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
