#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.stats import fisher_exact

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import law_rows as L  # noqa: E402

CONTRACT = "gsd-pattern-scan-1"
JUDGEMENT = "gsd-pattern-judgement-1"
FDR = 0.01
CONFIRM_P = 0.01
MIN_CARRIERS, MIN_HITS = 20, 3
SCALES = ("one", "log_N", "inv_log_N", "inv_sqrt_N", "inv_N", "power")
KINDS = {"degree sequence only": "reads only its degree sequence",
         "degree correlations": "reads its neighbours' degrees", "sees cycles": "sees cycles"}
LATTICE_NAMES = {name: f"the {name} held" for name in L.LATTICES}


def features(rows: list[dict]) -> dict[str, np.ndarray]:
    specs = [r.get("spec") or {} for r in rows]
    terms = [s.get("terms") or [] for s in specs]
    ops = sorted({str(t[0]) for ts in terms for t in ts})
    out: dict[str, np.ndarray] = {}

    def add(name, values):
        out[name] = np.fromiter((bool(v) for v in values), dtype=bool, count=len(rows))

    carried = [{str(t[0]) for t in ts} for ts in terms]
    for op in ops:
        add(f"carries {op}", (op in c for c in carried))
        add(f"{op} rewarded (coupling < 0)", (any(t[0] == op and t[2] < 0 for t in ts) for ts in terms))
        add(f"{op} penalised (coupling > 0)", (any(t[0] == op and t[2] > 0 for t in ts) for ts in terms))
    for a, b in itertools.combinations(ops, 2):
        add(f"carries {a} and {b}", ({a, b} <= c for c in carried))
    for scale in SCALES:
        add(f"a term scaled {scale}", (any(t[3] == scale for t in ts) for ts in terms))
    for kind, name in KINDS.items():
        add(name, (r.get("kind") == kind for r in rows))
    zero = [bool(s.get("zero_temperature")) for s in specs]
    add("zero temperature", zero)
    beta = [float(s.get("beta") or 0.0) for s in specs]
    for low, high in ((0, 1), (1, 10), (10, 101)):
        add(f"finite beta {low} to {high}", (not z and low <= b < high for z, b in zip(zero, beta, strict=True)))
    for k in (1, 2, 3, 4):
        add(f"{k} term{'s' if k > 1 else ''}", (len(ts) == k for ts in terms))
    for axis, label in (("locality", "locality"), ("swap_share", "swap share")):
        values = [float(s.get(axis) or 0.0) for s in specs]
        for low, high in ((0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)):
            add(f"{label} {low} to {min(high, 1)}", (low <= v < high for v in values))
    sweeps = [s.get("sweeps") for s in specs]
    add("sweeps 30", (v == 30 for v in sweeps))
    add("sweeps 120", (v == 120 for v in sweeps))
    add("sweeps otherwise", (v not in (30, 120) for v in sweeps))
    anchors = [L.anchor_degrees(r) for r in rows]
    for low, high in ((2, 3), (3, 4), (4, 6), (6, 7), (7, 8), (8, 9), (9, 17), (17, 33)):
        add(f"an anchor at {low}" if high == low + 1 else f"an anchor at {low} to {high - 1}",
            (any(low <= k < high for k in ks) for ks in anchors))
    return out


def outcomes(rows: list[dict]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    n = len(rows)
    read = np.fromiter((L.read_by_the_starts(r) for r in rows), dtype=bool, count=n)
    decided = np.fromiter((r.get("fate") is not None for r in rows), dtype=bool, count=n)
    at_256 = np.fromiter((r.get("fate") is not None and (r.get("fate_n") or 0) >= 256 for r in rows), dtype=bool,
                         count=n)

    def flag(test):
        return np.fromiter((bool(test(r)) for r in rows), dtype=bool, count=n)

    out = {"a lattice held": (flag(L.held), read)}
    for lattice, name in LATTICE_NAMES.items():
        out[name] = (flag(lambda r, lattice=lattice: L.held(r, lattice)), read)
    out["remembers"] = (flag(lambda r: r.get("class") == "remembers"), read)
    out["scores above 0"] = (flag(lambda r: (r.get("score") or 0) > 0), read)
    out["empty at 256"] = (flag(lambda r: r.get("fate") == "empty" and r.get("fate_n") == 256), at_256)
    out["too dense at 256"] = (flag(lambda r: r.get("fate") == "too_dense" and r.get("fate_n") == 256), at_256)
    out["disconnected"] = (flag(lambda r: r.get("fate") == "disconnected"), decided)
    out["read from 1,024"] = (read, decided)
    return out


def _table(x: np.ndarray, y: np.ndarray, base: np.ndarray) -> list[int]:
    return [int((x & y & base).sum()), int((x & ~y & base).sum()), int((~x & y & base).sum()),
            int((~x & ~y & base).sum())]


def _rates(t: list[int]) -> tuple[float | None, float | None]:
    a, b, c, d = t
    return (a / (a + b) if a + b else None), (c / (c + d) if c + d else None)


def _ratio(t: list[int]) -> float | None:
    with_, without = _rates(t)
    if with_ is None or not without:
        return None
    return round(with_ / without, 3)


def halves_of(rows: list[dict], finding: list[str] | None = None) -> tuple[list[str], list[str]]:
    ids = sorted({r["campaign"] for r in rows}, key=lambda c: int(c) if str(c).isdigit() else str(c))
    first = finding or ids[: len(ids) // 2]
    return list(first), [c for c in ids if c not in first]


def scan(rows: list[dict], finding: list[str] | None = None) -> dict:
    feats, outs = features(rows), outcomes(rows)
    first, second = halves_of(rows, finding)
    camp = np.array([r["campaign"] for r in rows])
    in_first, in_second = np.isin(camp, first), np.isin(camp, second)
    tested = []
    for oname, (y, base) in outs.items():
        for fname, x in feats.items():
            t1 = _table(x, y, base & in_first)
            if t1[0] + t1[1] < MIN_CARRIERS or t1[0] + t1[2] < MIN_HITS:
                continue
            ratio, p = fisher_exact([[t1[0], t1[1]], [t1[2], t1[3]]])
            tested.append({"outcome": oname, "feature": fname, "finding": t1,
                           "checking": _table(x, y, base & in_second), "all": _table(x, y, base),
                           "odds_finding": None if not np.isfinite(ratio) else round(float(ratio), 3),
                           "p_finding": float(p)})
    m = len(tested)
    ranked = sorted(range(m), key=lambda i: tested[i]["p_finding"])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = ranked[rank - 1]
        running = min(running, tested[i]["p_finding"] * m / rank)
        q[i] = running
    found = []
    for i, entry in enumerate(tested):
        if q[i] >= FDR:
            continue
        a, b, c, d = entry["finding"]
        up = a * d > b * c
        ca, cb, cc, cd = entry["checking"]
        _, p2 = fisher_exact([[ca, cb], [cc, cd]], alternative="greater" if up else "less")
        with_, without = _rates(entry["all"])
        found.append({**entry, "q_finding": round(q[i], 6), "p_checking": float(p2), "up": up,
                      "repeated": bool(p2 < CONFIRM_P), "rate_with": with_, "rate_without": without,
                      "ratio": _ratio(entry["all"])})
    found.sort(key=lambda e: (e["outcome"], e["p_checking"]))
    return {"finding": first, "checking": second, "comparisons": m, "found": len(found),
            "repeated": sum(1 for e in found if e["repeated"]), "patterns": found}


def read_patterns(root: Path) -> dict:
    rows = L.rows(root)
    return {"contract": CONTRACT, "bundle": root.name, "laws": len(rows), **scan(rows)}


def _measure(prediction: dict, feats: dict, outs: dict, mask: np.ndarray) -> dict:
    pairs = prediction.get("pairs") or [[prediction["feature"], prediction["outcome"]]]
    totals = np.zeros(4, dtype=np.int64)
    for fname, oname in pairs:
        y, base = outs[oname]
        totals += np.array(_table(feats[fname], y, base & mask))
    t = [int(v) for v in totals]
    with_, without = _rates(t)
    return {"table": t, "rate_with": with_, "rate_without": without, "ratio": _ratio(t), "carriers": t[0] + t[1],
            "with_the_outcome": t[0] + t[2]}


def _unbounded(t: list[int]) -> bool:
    a, b, c, d = t
    return a > 0 and c == 0 and d > 0


def _holds(rule: dict, t: list[int], ratio: float | None) -> bool | None:
    if "positives_at_most" in rule:
        return t[0] <= rule["positives_at_most"]
    if ratio is None:
        if not _unbounded(t):
            return None
        return "rate_ratio_at_least" in rule
    if "rate_ratio_at_least" in rule:
        return ratio >= rule["rate_ratio_at_least"]
    return ratio <= rule["rate_ratio_at_most"]


def judge(rows: list[dict], criterion: dict) -> dict:
    after = str(criterion["drawn_after"])
    later = [r for r in rows if str(r.get("drawn") or "") > after]
    feats, outs = features(later), outcomes(later)
    read = sum(1 for r in later if L.read_by_the_starts(r))
    needed = int((criterion.get("judged_when") or {}).get("laws_read_at_least") or 0)
    ready = read >= needed
    mask = np.ones(len(later), dtype=bool)
    out = []
    for prediction in criterion["predictions"]:
        if not later:
            out.append({"id": prediction["id"], "verdict": "not judged: no law drawn after " + after})
            continue
        try:
            numbers = _measure(prediction, feats, outs, mask)
        except KeyError as missing:
            out.append({"id": prediction["id"], "verdict": f"not judged: {missing} is not in the scan"})
            continue
        holds = _holds(prediction["rule"], numbers["table"], numbers["ratio"])
        if ready:
            verdict = "not judged: nothing to measure" if holds is None else ("held" if holds else "missed")
        else:
            word = "nothing to measure yet" if holds is None else ("held" if holds else "missed")
            verdict = f"reported, not judged: {word}"
        out.append({"id": prediction["id"], "claim": prediction["claim"], **numbers, "verdict": verdict})
    return {"contract": JUDGEMENT, "drawn_after": after, "laws_after": len(later), "laws_read_after": read,
            "needed": needed, "judged": ready, "predictions": out}


def render(result: dict) -> str:
    out = [f"# What the readers do not look for, from {result['bundle']}", "",
           f"{result['laws']:,} laws ({CONTRACT}). Found on campaigns {', '.join(result['finding'])}, checked on "
           f"{', '.join(result['checking'])}: {result['comparisons']:,} comparisons, {result['found']:,} found at a "
           f"false discovery rate under {FDR:.0%}, {result['repeated']:,} repeated by the other half "
           f"(one-sided p under {CONFIRM_P}), {result['found'] - result['repeated']:,} not. Recorded, never judged; "
           "a pattern is a finding only once a criterion committed before a bundle judges it.", ""]
    by_outcome: dict[str, list] = {}
    for p in result["patterns"]:
        by_outcome.setdefault(p["outcome"], []).append(p)
    for outcome, patterns in by_outcome.items():
        kept = [p for p in patterns if p["repeated"]]
        out += [f"## {outcome}", "",
                f"{len(patterns)} found, {len(kept)} repeated. The repeated, strongest first:", "",
                "| feature | with | without | ratio | laws with it | p, checking half |",
                "|---|---:|---:|---:|---:|---:|"]
        kept.sort(key=lambda p: float("inf") if p["ratio"] == 0 else abs(np.log(p["ratio"])) if p["ratio"] else 0.0,
                  reverse=True)
        for p in kept[:15]:
            a, b, _, _ = p["all"]
            out.append(f"| {p['feature']} | {p['rate_with']:.4f} | {p['rate_without']:.4f} | {p['ratio']} | "
                       f"{a + b:,} | {p['p_checking']:.2g} |")
        out.append("")
    return "\n".join(out) + "\n"


def render_judgement(result: dict) -> str:
    state = "judged" if result["judged"] else f"reported, not judged (needs {result['needed']:,} laws read)"
    out = [f"# The patterns' criterion, on the laws drawn after {result['drawn_after']}", "",
           f"{result['laws_after']:,} laws drawn after it, {result['laws_read_after']:,} read from 1,024: {state}.", "",
           "| id | verdict | with | without | ratio | laws with it | laws with the outcome |",
           "|---|---|---:|---:|---:|---:|---:|"]
    rate = (lambda v: "" if v is None else f"{v:.4f}")
    for p in result["predictions"]:
        if "table" not in p:
            out.append(f"| {p['id']} | {p['verdict']} | | | | | |")
            continue
        ratio = p["ratio"] if p["ratio"] is not None else ("unbounded" if _unbounded(p["table"]) else "")
        outcome = p["table"][0] + p["table"][2]
        out.append(f"| {p['id']} | {p['verdict']} | {rate(p['rate_with'])} | {rate(p['rate_without'])} | "
                   f"{ratio} | {p['carriers']:,} | {outcome:,} |")
    out += ["", "A ratio needs laws with the feature, laws without it and the outcome among them; until the outcome "
            "comes there is nothing to measure, which is neither a hit nor a miss. An absence is read as it is "
            "written. Each rate is a share of the laws its outcome is read over (for a lattice or a class, the laws "
            "read from 1,024)."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/pattern_scan.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    parser.add_argument("--judge", help="a committed criterion of patterns, read on the laws drawn after it")
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-pattern-scan-") as scratch:
        root = unpacked(Path(args.bundle), Path(scratch))
        if args.judge:
            criterion = json.loads(Path(args.judge).read_text(encoding="utf-8"))
            result = judge(L.rows(root), criterion)
            page = render_judgement(result)
        else:
            result = read_patterns(root)
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
