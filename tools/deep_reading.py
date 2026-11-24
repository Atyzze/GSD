#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

CONTRACT = "gsd-deep-reading-1"
DEEP_FROM = 65_536
SHAPED = ("holds", "selects", "grows")
CHAINS = ("empty", "given", *L.LATTICES)
SHOWN = ("mean_degree", "giant_fraction", "reach", "d_s", "d_V", "d_B", "d_w", "kappa")


def _round(value):
    return round(float(value), 3) if isinstance(value, (int, float)) else None


def top_cells(values: dict) -> dict:
    out = {}
    for name in CHAINS:
        rows = values.get(name) or []
        if rows:
            last = max(rows, key=lambda row: int(row[0]))
            cell = dict(zip(H.COLUMNS, last, strict=False))
            out[H.NAMES.get(name, name)] = {"n": int(cell["n"]), **{k: _round(cell.get(k)) for k in SHOWN},
                                            "probes_read": sum(1 for k in H.PROBES if cell.get(k) is not None),
                                            "readable": H.readable(cell)}
    return out


def deep_entry(law: str, chained: dict, ended: tuple[str, str], row: dict) -> dict | None:
    top = int(chained.get("top_n") or row.get("top_n") or 0)
    if top < DEEP_FROM:
        return None
    starts = chained.get("starts_reading") or {}
    return {"law": law, "campaign": row["campaign"], "top_n": top, "class": starts.get("class") or "not_read",
            "state": ended[0], "ended": ended[1], "trend": starts.get("trend"),
            "fates": {k: (v or [None])[0] or "not read" for k, v in (starts.get("fates") or {}).items()},
            "pattern": H.pattern(((starts.get("by_n") or {}).get(str(starts.get("at_n"))) or [None, []])[1]),
            "zero_t": bool(row["spec"].get("zero_temperature")), "stratum": C.stratum(row["spec"]),
            "operators": sorted(L.operators(row)), "chains": top_cells(chained.get("values") or {})}


def entries_of(root: Path) -> list[dict]:
    ended = H.ended_by(root)
    rows = {row["law"]: row for row in L.rows(root)}
    out = []
    for part in L.campaigns(root):
        engine = L.body(root / str(part.get("bundle") or ""))
        for law, chained in ((engine.get("every_chain") or {}).get("laws") or {}).items():
            if law in rows:
                entry = deep_entry(law, chained, ended.get(law, ("", "")), rows[law])
                if entry is not None:
                    out.append(entry)
    return sorted(out, key=lambda e: (-e["top_n"], e["class"], e["law"]))


def summarize(entries: list[dict]) -> dict:
    nothing = [e for e in entries if e["class"] not in SHAPED]
    sizes = Counter(e["top_n"] for e in entries)
    return {"deep": len(entries), "by_size": {str(n): k for n, k in sorted(sizes.items())},
            "by_class": dict(Counter(e["class"] for e in entries).most_common()),
            "by_class_and_state": {c: dict(Counter(f"{H.STATES.get(e['state'], e['state'])}: {e['ended']}"
                                                   for e in entries if e["class"] == c).most_common())
                                   for c in sorted({e["class"] for e in entries})},
            "holding_nothing": len(nothing),
            "holding_nothing_zero_t": sum(e["zero_t"] for e in nothing),
            "holding_nothing_with_a_readable_chain": sum(1 for e in nothing
                                                         if any(c["readable"] for c in e["chains"].values())),
            "laws": nothing}


def reading(root: Path) -> dict:
    return {"contract": CONTRACT, "bundle": root.name, "rules": {"deep_from": DEEP_FROM, "shaped": list(SHAPED),
                                                                "one_piece": H.ONE_PIECE,
                                                                "probes_read": H.PROBES_READ},
            **summarize(entries_of(root))}


def _cell(value) -> str:
    return "" if value is None else f"{value:g}"


def render(result: dict) -> str:
    lines = [f"# The deep laws that hold nothing, from {result['bundle']}", "",
             f"{result['deep']:,} blind laws reached {result['rules']['deep_from']:,} nodes or more "
             f"({', '.join(f'{int(n):,}: {k:,}' for n, k in result['by_size'].items())}). "
             f"{result['deep'] - result['holding_nothing']:,} of them hold, select or grow a shape at their largest "
             f"size read; {result['holding_nothing']:,} hold none ({result['contract']}). Recorded, never judged.", "",
             "## Every deep law by its class and how it stands", "", "| class | laws | state: decision |",
             "|---|---:|---|"]
    for c, states in result["by_class_and_state"].items():
        lines.append(f"| {c} | {result['by_class'][c]:,} | " + "; ".join(f"{k} {n:,}" for k, n in states.items())
                     + " |")
    lines += ["", f"## The {result['holding_nothing']:,} that hold nothing", "",
              f"{result['holding_nothing_zero_t']:,} at zero temperature; "
              f"{result['holding_nothing_with_a_readable_chain']:,} with a start whose graph is one piece and read by "
              "two probes or more at the largest size. Each start at its largest size:", ""]
    for e in result["laws"]:
        lines += [f"### `{e['law'][:12]}`, campaign {e['campaign']}, {e['top_n']:,} nodes", "",
                  f"{e['class']}, {e['trend'] or 'no'} trend; {H.STATES.get(e['state'], e['state'])}: {e['ended']}; "
                  f"{'zero' if e['zero_t'] else 'finite'} temperature; {e['stratum']}; terms "
                  f"{', '.join(e['operators'])}. Groups: {e['pattern']}. Lattice fates: "
                  + ", ".join(f"{k} {v}" for k, v in sorted(e["fates"].items())) + ".", "",
                  "| start | degree | one piece | reach | d_s | d_V | d_B | d_w | kappa |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, c in e["chains"].items():
            lines.append(f"| {name}{' (read)' if c['readable'] else ''} | {_cell(c['mean_degree'])} | "
                         f"{_cell(c['giant_fraction'])} | {_cell(c['reach'])} | {_cell(c['d_s'])} | "
                         f"{_cell(c['d_V'])} | "
                         f"{_cell(c['d_B'])} | {_cell(c['d_w'])} | {_cell(c['kappa'])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/deep_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-deep-") as scratch:
        result = reading(unpacked(Path(args.bundle), Path(scratch)))
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = render(result)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text[:7000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
