#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import law_rows as L  # noqa: E402

CONTRACT = "gsd-sample-reading-1"
Z95 = 1.959964
ONE_SAMPLE_P = 0.002
CURVE_SIZES = (1000, 2000, 5000, 10000, 20000)
SCAN_OUTCOMES = 10
POWER = 0.8
ALPHA = 0.05


def _z(count: int, n: int, p: float) -> float:
    return (count / n - p) / math.sqrt(p * (1 - p) / n) if n and 0 < p < 1 else 0.0


def outcome_at_256(row: dict) -> str | None:
    if row.get("fate") is None or row.get("fate_n") is None or int(row["fate_n"]) < 256:
        return None
    if row.get("fate_n") == 256 and row["fate"] in ("empty", "too_dense"):
        return row["fate"]
    return "past 256"


def outcome_at_1024(row: dict) -> str | None:
    n, fate = row.get("fate_n"), row.get("fate")
    if fate is None or n is None or n < 256 or outcome_at_256(row) != "past 256":
        return None
    if n == 1024 and fate in ("empty", "too_dense", "disconnected"):
        return fate
    if n > 1024:
        return "past 1,024"
    return None


def class_at_1024(row: dict) -> str | None:
    value = row.get("class_1024")
    return None if value is None else (value if value in ("forgets", "remembers", "not_read") else "a shape read")


READINGS = {
    "the outcome at 256": (outcome_at_256, "every law with a decision"),
    "the outcome at 1,024": (outcome_at_1024, "every law past 256 whose 1,024 is decided"),
    "the starts' class at 1,024": (class_at_1024, "every law its starts read at 1,024"),
    "a lattice held": (lambda r: ("held" if L.held(r) else "none held") if L.read_by_the_starts(r) else None,
                       "every law its starts read"),
    "a score above 0": (lambda r: ("scores" if (r.get("score") or 0) > 0 else "0") if L.read_by_the_starts(r)
                        else None, "every law its starts read"),
    "the drawn temperature": (lambda r: "zero" if (r.get("spec") or {}).get("zero_temperature") else "finite",
                              "every law drawn"),
}


def campaigns_against_chance(rows: list[dict]) -> dict:
    out = []
    for name, (read, base) in READINGS.items():
        table: dict[str, Counter] = {}
        for row in rows:
            value = read(row)
            if value is not None:
                table.setdefault(row["campaign"], Counter())[value] += 1
        if len(table) < 2:
            continue
        sizes = {c: sum(counts.values()) for c, counts in table.items()}
        total = sum(sizes.values())
        categories = sorted({v for counts in table.values() for v in counts})
        for category in categories:
            hits = sum(counts[category] for counts in table.values())
            p = hits / total
            if not 0 < p < 1:
                continue
            zs = {c: _z(table[c][category], sizes[c], p) for c in table}
            chi = sum(z * z for z in zs.values())
            shares = [table[c][category] / sizes[c] for c in table]
            out.append({"reading": name, "over": base, "category": category, "laws": total, "hits": hits,
                        "pooled": round(p, 6), "lowest": round(min(shares), 6), "highest": round(max(shares), 6),
                        "worst_z": round(max(abs(z) for z in zs.values()), 2),
                        "chi2_per_dof": round(chi / (len(table) - 1), 3),
                        "p": round(float(stats.chi2.sf(chi, len(table) - 1)), 4)})
    lowest = min((r["p"] for r in out), default=None)
    return {"readings": out, "campaigns": len({r["campaign"] for r in rows}), "lowest_p": lowest,
            "one_sample": lowest is None or lowest >= ONE_SAMPLE_P}


def halves(rows: list[dict]) -> dict:
    ordered = sorted((r for r in rows if r.get("drawn")), key=lambda r: r["drawn"])
    middle = len(ordered) // 2
    parts = {"first": ordered[:middle], "second": ordered[middle:]}
    out = []
    for name in ("the outcome at 256", "the starts' class at 1,024"):
        read = READINGS[name][0]
        counts = {half: Counter(v for v in map(read, laws) if v is not None) for half, laws in parts.items()}
        sizes = {half: sum(c.values()) for half, c in counts.items()}
        if not all(sizes.values()):
            continue
        for category in sorted(set(counts["first"]) | set(counts["second"])):
            a, b = counts["first"][category], counts["second"][category]
            p = (a + b) / (sizes["first"] + sizes["second"])
            se = math.sqrt(p * (1 - p) * (1 / sizes["first"] + 1 / sizes["second"])) if 0 < p < 1 else 0.0
            diff = a / sizes["first"] - b / sizes["second"]
            out.append({"reading": name, "category": category, "first": round(a / sizes["first"], 6),
                        "second": round(b / sizes["second"], 6), "standard_errors": round(diff / se, 2) if se else 0.0,
                        "laws": [sizes["first"], sizes["second"]]})
    worst = max((abs(r["standard_errors"]) for r in out), default=0.0)
    return {"split_at": ordered[middle]["drawn"] if ordered else None, "readings": out, "worst": worst}


def what_more_laws_buy(rows: list[dict], budget: int, drawn: int | None = None) -> dict:
    drawn = int(drawn) if drawn else len(rows)
    scale = budget / drawn if drawn else 1.0
    read = [r for r in rows if L.read_by_the_starts(r)]
    decided = [r for r in rows if outcome_at_256(r) is not None]

    def width(p: float, n: float) -> float:
        return round(100 * Z95 * math.sqrt(p * (1 - p) / n), 3) if n and 0 < p < 1 else None

    empty = sum(1 for r in decided if outcome_at_256(r) == "empty") / max(1, len(decided))
    remembers = sum(1 for r in read if r.get("class") == "remembers") / max(1, len(read))
    common = [{"share": "empty at 256", "of": "laws decided", "value": round(empty, 6),
               "plus_minus_points_now": width(empty, len(decided)),
               "plus_minus_points_at_budget": width(empty, len(decided) * scale)},
              {"share": "remembers", "of": "laws read", "value": round(remembers, 6),
               "plus_minus_points_now": width(remembers, len(read)),
               "plus_minus_points_at_budget": width(remembers, len(read) * scale)}]
    rare = []
    for name, test in (("a lattice held", L.held), ("a score above 0", lambda r: (r.get("score") or 0) > 0),
                       ("a score of 17 or more", lambda r: (r.get("score") or 0) >= 17),
                       ("a start without a shape reaching one (grows, one_space)",
                        lambda r: r.get("class") in ("grows", "one_space"))):
        k = sum(1 for r in read if test(r))
        rare.append({"class": name, "laws_now": k, "laws_at_budget": round(k * scale),
                     "relative_error_now": round(1 / math.sqrt(k), 3) if k else None,
                     "relative_error_at_budget": round(1 / math.sqrt(k * scale), 3) if k else None})
    two_sizes = [r for r in read if (r.get("top_n") or 0) >= 4096]
    geometry = sum(1 for r in two_sizes if r.get("score_by") in ("empty", "random"))
    absence = {"laws_read_at_two_sizes": len(two_sizes), "from_empty_or_random_a_geometry": geometry,
               "rarer_than_one_in_now": round(len(two_sizes) / 3) if not geometry else None,
               "rarer_than_one_in_at_budget": round(len(two_sizes) * scale / 3) if not geometry else None}
    return {"drawn": drawn, "budget": budget, "decided": len(decided), "read": len(read), "common": common,
            "rare": rare, "absence": absence}


def signature(row: dict, lattices: tuple) -> str:
    fates = row.get("fates") or {}
    return "|".join([str(row.get("class"))] + [str(fates.get(name) or "-") for name in lattices]
                    + ["scores" if (row.get("score") or 0) > 0 else "0"])


def _rarefied(counts: list[int], n: int, m: int) -> float:
    from scipy.special import gammaln
    total = 0.0
    for c in counts:
        if n - c < m:
            total += 1.0
        else:
            total += 1.0 - math.exp(gammaln(n - c + 1) - gammaln(n - c - m + 1) - gammaln(n + 1) + gammaln(n - m + 1))
    return total


def kinds(rows: list[dict], budget: int, drawn: int | None = None) -> dict:
    read = [r for r in rows if L.read_by_the_starts(r)]
    lattices = L.lattices_given(r.get("fates") for r in read)
    counts = Counter(signature(r, lattices) for r in read)
    n, s = len(read), len(counts)
    f1 = sum(1 for c in counts.values() if c == 1)
    f2 = sum(1 for c in counts.values() if c == 2)
    if not n:
        return {"laws_read": 0, "kinds": 0}
    f0 = (n - 1) / n * (f1 * f1 / (2 * f2) if f2 else f1 * (f1 - 1) / 2)
    more = n * (budget / (int(drawn) if drawn else len(rows)) - 1) if rows else 0.0
    expected = s + (f0 * (1 - (1 - f1 / (n * f0 + f1)) ** more) if f0 > 0 else 0.0)
    curve = {str(m): round(_rarefied(list(counts.values()), n, m), 1) for m in (1000, 2000, 5000, 10000, 20000)
             if m < n}
    return {"laws_read": n, "kinds": s, "seen_once": f1, "seen_twice": f2, "missing_mass": round(f1 / n, 5),
            "chao1": round(s + f0, 1), "expected_at_budget": round(expected, 1), "rarefied": curve,
            "rarest": [{"kind": k, "laws": c} for k, c in sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))[:12]]}


def _cases_needed(ratio: float, comparisons: int) -> float:
    lam = 0.05
    alpha = ALPHA / comparisons
    while lam < 1e6:
        crit = stats.poisson.isf(alpha, lam) + 1
        if stats.poisson.sf(crit - 1, ratio * lam) >= POWER:
            return lam
        lam *= 1.02
    return float("inf")


def cells(rows: list[dict]) -> dict:
    drawn = len(rows)
    read = [r for r in rows if L.read_by_the_starts(r)]
    ops = sorted({op for r in rows for op in L.operators(r)})
    per_op = {op: sum(1 for r in rows if op in L.operators(r)) for op in ops}
    pairs = {f"{a}+{b}": sum(1 for r in rows if {a, b} <= L.operators(r)) for a, b in itertools.combinations(ops, 2)}
    if not drawn or not pairs:
        return {}
    op_share = float(np.median(list(per_op.values()))) / drawn
    pair_share = float(np.median(list(pairs.values()))) / drawn
    read_share = len(read) / drawn
    base = sum(1 for r in read if L.held(r)) / max(1, len(read))
    comparisons = len(pairs) * SCAN_OUTCOMES
    needs = [{"claim": "any share to 1 point either way", "laws_drawn": round(3.84 * 0.21 / 0.01 ** 2)},
             {"claim": "each operator's share to 1 point", "laws_drawn": round(3.84 * 0.21 / 0.01 ** 2 / op_share)},
             {"claim": "each pair's share to 2 points", "laws_drawn": round(3.84 * 0.21 / 0.02 ** 2 / pair_share)}]
    if base > 0:
        for ratio in (5.0, 3.0, 2.0):
            lam = _cases_needed(ratio, comparisons)
            needs.append({"claim": f"holding {ratio:g} times as likely in a pair",
                          "laws_drawn": round(lam / base / pair_share / read_share)})
    return {"operators": per_op, "median_operator_share": round(op_share, 4), "pairs": len(pairs),
            "laws_per_pair": {"min": min(pairs.values()), "median": float(np.median(list(pairs.values()))),
                              "max": max(pairs.values())},
            "median_pair_share": round(pair_share, 4), "comparisons": comparisons,
            "holding_base_rate": round(base, 5), "needs": needs}


def sample(root: Path) -> dict:
    rows = L.rows(root)
    total = L.budget(root)
    return {"contract": CONTRACT, "bundle": root.name, "laws": len(rows), "budget": total,
            "campaigns": campaigns_against_chance(rows), "halves": halves(rows),
            "what_more_laws_buy": what_more_laws_buy(rows, total, L.drawn(root)), "kinds": kinds(rows, total, L.drawn(root)),
            "cells": cells(rows)}


def _n(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def render(result: dict) -> str:
    out = [f"# What more laws buy, from {result['bundle']}", "",
           f"{result['laws']:,} laws of the study's own campaigns, of a budget of {result['budget']:,} "
           f"({CONTRACT}). Read from the bundle alone; nothing here is judged.", ""]
    c = result["campaigns"]
    verdict = ("one sample: every reading's campaigns agree as chance allows" if c["one_sample"]
               else "not one sample: a reading departs from chance (below)")
    out += ["## The campaigns against chance", "",
            f"{c['campaigns']} campaigns; {verdict} (the lowest p {c['lowest_p']}; a p under {ONE_SAMPLE_P} departs).",
            "", "| reading | category | laws | pooled | lowest | highest | worst SE | chi2/dof | p |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in c["readings"]:
        out.append(f"| {r['reading']} | {r['category']} | {r['laws']:,} | {r['pooled']:.4f} | {r['lowest']:.4f} | "
                   f"{r['highest']:.4f} | {r['worst_z']} | {r['chi2_per_dof']} | {r['p']} |")
    h = result["halves"]
    out += ["", "## The halves in the order drawn, on what both have reached", "",
            f"Split at the law drawn {h['split_at']}; the worst difference {h['worst']} standard errors.", "",
            "| reading | category | first | second | standard errors |", "|---|---|---:|---:|---:|"]
    for r in h["readings"]:
        out.append(f"| {r['reading']} | {r['category']} | {r['first']:.4f} | {r['second']:.4f} | "
                   f"{r['standard_errors']} |")
    w = result["what_more_laws_buy"]
    out += ["", "## What more laws buy", "",
            f"{w['drawn']:,} drawn of {w['budget']:,}; {w['decided']:,} decided at least once; {w['read']:,} read by "
            "their starts.", "", "| share | of | now | 95% now, points | 95% at the budget |",
            "|---|---|---:|---:|---:|"]
    for r in w["common"]:
        out.append(f"| {r['share']} | {r['of']} | {r['value']:.4f} | {r['plus_minus_points_now']} | "
                   f"{r['plus_minus_points_at_budget']} |")
    out += ["", "| rare class | laws now | at the budget | relative error now | at the budget |",
            "|---|---:|---:|---:|---:|"]
    for r in w["rare"]:
        out.append(f"| {r['class']} | {r['laws_now']:,} | {r['laws_at_budget']:,} | {r['relative_error_now']} | "
                   f"{r['relative_error_at_budget']} |")
    a = w["absence"]
    out += ["", f"Laws read at two sizes from 1,024: {a['laws_read_at_two_sizes']:,}; a geometry from empty or the "
                f"random start among them: {a['from_empty_or_random_a_geometry']}. By the rule of three such a law is "
                f"rarer than 1 in {_n(a['rarer_than_one_in_now'])} now, 1 in {_n(a['rarer_than_one_in_at_budget'])} "
                "at the budget (95%)."]
    k = result["kinds"]
    if k.get("laws_read"):
        out += ["", "## The kinds of outcome", "",
                f"{k['kinds']} kinds (class, each lattice's fate, a score) among {k['laws_read']:,} laws read; "
                f"{k['seen_once']} seen once, {k['seen_twice']} twice. The missing mass {k['missing_mass']}: the "
                f"chance the next law read is a kind not seen. Chao's estimate of all kinds {k['chao1']}; expected by "
                f"the budget {k['expected_at_budget']}. Kinds among fewer laws: "
                + ", ".join(f"{_n(int(m))}: {v}" for m, v in k["rarefied"].items()) + "."]
    cl = result.get("cells") or {}
    if cl:
        lp = cl["laws_per_pair"]
        out += ["", "## The cells and the laws a claim needs", "",
                f"{len(cl['operators'])} operators, each carried by {min(cl['operators'].values()):,} to "
                f"{max(cl['operators'].values()):,} laws; {cl['pairs']} pairs, carried by {lp['min']:,} to "
                f"{lp['max']:,} (median {lp['median']:,.0f}). A pattern is read against "
                f"{cl['comparisons']:,} comparisons; a lattice held by {cl['holding_base_rate']:.3%} of the laws read.",
                "", "| claim | laws drawn |", "|---|---:|"]
        out += [f"| {n['claim']} | {n['laws_drawn']:,} |" for n in cl["needs"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/sample_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-sample-reading-") as scratch:
        root = unpacked(Path(args.bundle), Path(scratch))
        result = sample(root)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    page = render(result)
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    if not args.json and not args.md:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
