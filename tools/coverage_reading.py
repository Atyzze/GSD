#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import gzip
import itertools
import json
import math
import random
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import law_rows as L  # noqa: E402

CONTRACT = "gsd-coverage-reading-1"
DEFAULT_SAMPLE = 100_000
DEFAULT_SEED = 160
THIN_RATIO = 0.8
THICK_RATIO = 1.25
EXTREME_Z = 3.0
MIN_EXPECTED = 20.0
DEEP_SIZES = (16_384, 262_144)
SINGLE_VALUED = ("term count", "temperature", "local move", "locality", "swap share", "beta (finite temperature)")
MAGNITUDE_EDGES = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 2.0001)
BETA_EDGES = (0.1, 0.316, 1.0, 3.16, 10.0, 31.6, 100.0001)
SHARE_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)
ANCHOR_EDGES = (2, 4, 6, 8, 12, 16, 24, 33)
POWER_EDGES = (-2.0, -1.0, 0.0, 1.0, 2.0001)
AGREE_WITHIN = 0.4


def _bin(value, edges) -> str | None:
    if value is None:
        return None
    value = float(value)
    for low, high in zip(edges, edges[1:], strict=False):
        if low <= value < high:
            return f"{low:g} to {round(high, 3):g}"
    return None


def features(compact: dict) -> dict[str, list[str]]:
    terms = compact.get("terms") or []
    ops = sorted({str(term[0]) for term in terms})
    zero_t = bool(compact.get("zero_temperature"))
    out: dict[str, list[str]] = {
        "term count": [str(len(terms))],
        "operator": ops,
        "operator pair": [f"{a} + {b}" for a, b in itertools.combinations(ops, 2)],
        "scale": sorted({str(term[3]) for term in terms}),
        "sign": sorted({"+" if float(term[2] or 0) > 0 else "-" for term in terms}),
        "magnitude": sorted({b for b in (_bin(abs(float(term[2] or 0)), MAGNITUDE_EDGES) for term in terms) if b}),
        "anchor k": sorted({b for b in (_bin(term[1], ANCHOR_EDGES) for term in terms if term[1] is not None) if b}),
        "power exponent": sorted({b for b in (_bin(term[4], POWER_EDGES) for term in terms if term[4] is not None)
                                  if b}),
        "temperature": ["zero" if zero_t else "finite"],
        "local move": [str(compact.get("local_move") or "none")],
        "locality": [b for b in [_bin(compact.get("locality") or 0.0, SHARE_EDGES)] if b],
        "swap share": [b for b in [_bin(compact.get("swap_share") or 0.0, SHARE_EDGES)] if b],
    }
    if not zero_t:
        out["beta (finite temperature)"] = [b for b in [_bin(compact.get("beta"), BETA_EDGES)] if b]
    return out


def stratum(compact: dict) -> str:
    from graph_scale_dynamics.research.strata import stratum_of
    return stratum_of(L.spec_of(compact))


def blind_campaign_spec(study_id: str) -> dict:
    from graph_scale_dynamics.operations import study_design as SD
    design = SD.design_for(ROOT, str(study_id))
    if design is None:
        raise ValueError(f"study {study_id} has no committed design in this tree")
    base = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                       / "campaign_engine_survey.json").read_text(encoding="utf-8"))
    entry = next(e for e in design["campaigns"] if e.get("kind") == SD.BLIND)
    return SD.campaign_spec(design, base, entry, 1)


def measure(spec: dict, size: int, seed: int) -> list[dict]:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.research.law_ledger import compact_spec
    from graph_scale_dynamics.services.proposer.blind import blind_law
    grid = dict(spec["search_policy"]["grid"])
    grid.pop("strata", None)
    whitelist, budget = list(spec["operator_whitelist"]), spec.get("complexity_budget")
    rng = random.Random(seed)
    return [compact_spec(dsl.normalize(blind_law(rng, whitelist, grid, complexity_budget=budget)))
            for _ in range(int(size))]


def conditional_shares(rows: list[dict], strata: list[str]) -> tuple[dict, Counter]:
    counts: dict = defaultdict(lambda: defaultdict(Counter))
    sizes = Counter(strata)
    for row, h in zip(rows, strata, strict=True):
        for axis, values in row.items():
            for value in values:
                counts[h][axis][value] += 1
    return ({h: {axis: {v: n / sizes[h] for v, n in values.items()} for axis, values in axes.items()}
             for h, axes in counts.items()}, sizes)


def tally(rows: list[dict], strata: list[str], weights: list[float]) -> dict:
    out = {"weight": defaultdict(float), "weight2": defaultdict(float), "observed": defaultdict(float),
           "within": defaultdict(float), "laws": Counter()}
    for row, h, w in zip(rows, strata, weights, strict=True):
        out["weight"][h] += w
        out["weight2"][h] += w * w
        for axis, values in row.items():
            for value in values:
                out["observed"][(axis, value)] += w
                out["within"][(h, axis, value)] += w
                out["laws"][(axis, value)] += 1
    return out


def judged(observed: float, expected: float, var: float) -> dict:
    z = (observed - expected) / math.sqrt(var) if var > 0 else None
    ratio = observed / expected if expected > 0 else None
    enough = expected >= MIN_EXPECTED and ratio is not None and z is not None
    return {"expected": round(expected, 1), "drawn": round(observed, 1),
            "ratio": round(ratio, 3) if ratio is not None else None, "z": round(z, 2) if z is not None else None,
            "thin": bool(enough and ratio < THIN_RATIO and z < -EXTREME_Z),
            "thick": bool(enough and ratio > THICK_RATIO and z > EXTREME_Z)}


def compare(measure_rows: list[dict], measure_strata: list[str], run_rows: list[dict], run_strata: list[str],
            weights: list[float] | None = None, tops: list[int | None] | None = None) -> dict:
    weights = weights if weights is not None else [1.0] * len(run_rows)
    tops = tops if tops is not None else [None] * len(run_rows)
    shares, sizes = conditional_shares(measure_rows, measure_strata)
    m_total = sum(sizes.values())
    drawn = tally(run_rows, run_strata, weights)
    run = tally(run_rows, run_strata, [1.0] * len(run_rows))
    reached: dict = defaultdict(Counter)
    for row, top in zip(run_rows, tops, strict=True):
        for axis, values in row.items():
            for value in values:
                for n in DEEP_SIZES:
                    if top is not None and int(top) >= n:
                        reached[(axis, value)][n] += 1
    keys = {(axis, v) for h in shares.values() for axis, values in h.items() for v in values}
    keys |= set(drawn["observed"])

    def expect(t: dict, axis: str, value: str) -> tuple[float, float]:
        mean = var = 0.0
        for h, w in t["weight"].items():
            p = shares.get(h, {}).get(axis, {}).get(value, 0.0)
            mean += w * p
            var += t["weight2"][h] * p * (1 - p) + (w * w * p * (1 - p) / sizes[h] if sizes.get(h) else 0.0)
        return mean, var

    axes: dict = defaultdict(list)
    for axis, value in sorted(keys):
        p = sum(sizes[h] * shares[h].get(axis, {}).get(value, 0.0) for h in shares) / m_total
        run_expected, _ = expect(run, axis, value)
        laws = run["laws"].get((axis, value), 0)
        axes[axis].append({"value": value, "measure": round(p, 6),
                           **judged(drawn["observed"].get((axis, value), 0.0), *expect(drawn, axis, value)),
                           "laws": laws, "run_ratio": round(laws / run_expected, 3) if run_expected > 0 else None,
                           **{f"reached_{n}": reached[(axis, value)][n] for n in DEEP_SIZES}})
    within = []
    for h, w in sorted(drawn["weight"].items()):
        for axis, value in sorted(keys):
            p = shares.get(h, {}).get(axis, {}).get(value, 0.0)
            var = drawn["weight2"][h] * p * (1 - p) + (w * w * p * (1 - p) / sizes[h] if sizes.get(h) else 0.0)
            row = judged(drawn["within"].get((h, axis, value), 0.0), w * p, var)
            if row["thin"] or row["thick"]:
                within.append({"stratum": h, "axis": axis, "value": value, **row})
    total_drawn = sum(drawn["weight"].values())
    out = {}
    for axis, rows in axes.items():
        tv = None
        if axis in SINGLE_VALUED and total_drawn:
            tv = round(0.5 * sum(abs(r["drawn"] - r["expected"]) for r in rows) / total_drawn, 4)
        out[axis] = {"rows": rows, "total_variation": tv}
    return {"axes": out, "within_strata": within, "strata_unmeasured": sorted(set(run_strata) - set(sizes)),
            "strata": {h: {"measure": round(sizes[h] / m_total, 4), "laws": int(run["weight"].get(h, 0)),
                           "drawn": round(drawn["weight"].get(h, 0.0), 1)}
                       for h in sorted(set(sizes) | set(run_strata))}}


def _round(x):
    return None if x is None else round(float(x), 3)


def structure(root: Path) -> dict:
    fitted = {}
    laws_table = root / "tables" / "laws.ndjson.gz"
    if laws_table.is_file():
        with gzip.open(laws_table, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                fitted[str(row.get("candidate_id"))] = (row.get("d_s"), row.get("d_s_n"))
    laws = []
    given_only = 0
    for report in sorted(glob.glob(str(root / "campaign_*_reports_*" / "28-decision-engine.json"))):
        campaign = int(Path(report).parent.name.split("_")[1])
        body = json.loads(Path(report).read_text(encoding="utf-8")).get("body") or {}
        record = (body.get("the_record") or {}).get("structure_by_the_committed_rule") or {}
        given_only += len(record.get("given_only_finite") or [])
        for entry in record.get("finite") or []:
            three = entry.get("three_readings") or {}
            law = str(entry.get("candidate_id"))
            gap = three.get("gap_implied_d_s", entry.get("implied_spectral_dimension"))
            d_s, d_s_n = fitted.get(law, (None, None))
            laws.append({"law": law[:12], "campaign": campaign, "gap_implied_d_s": _round(gap),
                         "local_d_s": _round(three.get("local_d_s")), "local_d_s_at_n": three.get("local_d_s_at_n"),
                         "fitted_d_s": _round(d_s), "fitted_d_s_at_n": d_s_n,
                         "local_agrees": three.get("local_agrees_with_gap"),
                         "fitted_agrees": (abs(float(d_s) - float(gap)) <= AGREE_WITHIN
                                           if d_s is not None and gap is not None else None),
                         "all_three": three.get("agree")})
    read = [r for r in laws if r["local_agrees"] is not None]
    return {"finite_by_the_committed_rule": len(laws), "finite_on_the_given_chain_only": given_only,
            "agree_within": AGREE_WITHIN, "local_read": len(read),
            "local_agrees": sum(1 for r in read if r["local_agrees"]),
            "fitted_read": sum(1 for r in laws if r["fitted_agrees"] is not None),
            "fitted_agrees": sum(1 for r in laws if r["fitted_agrees"]),
            "fitted_is_local": sum(1 for r in laws if r["fitted_d_s"] is not None and r["fitted_d_s"] == r["local_d_s"]
                                   and r["fitted_d_s_at_n"] == r["local_d_s_at_n"]),
            "all_three": sum(1 for r in laws if r["all_three"]),
            "laws": sorted(laws, key=lambda r: (r["campaign"], r["law"]))}


def reading(root: Path, *, sample: int = DEFAULT_SAMPLE, seed: int = DEFAULT_SEED, workers: int = 2) -> dict:
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    study_id = str(study.get("study_id"))
    spec = blind_campaign_spec(study_id)
    blind = sorted(int(record["campaign_id"]) for record in L.campaigns(root))
    rows = [row for row in L.rows(root) if row.get("spec")]
    run_compact = [row["spec"] for row in rows]
    weights = [1.0] * len(rows)
    drawn = measure(spec, sample, seed)
    result = compare([features(c) for c in drawn], [stratum(c) for c in drawn],
                     [features(c) for c in run_compact], [stratum(c) for c in run_compact],
                     weights, [row.get("top_n") for row in rows])
    flagged = [{"axis": axis, **row} for axis, body in result["axes"].items() for row in body["rows"]]
    return {"contract": CONTRACT, "bundle": root.name, "study": study_id, "campaigns": blind,
            "laws_run": len(rows), "laws_drawn": round(sum(weights), 1),
            "measure_sample": int(sample), "measure_seed": int(seed),
            "thresholds": {"thin_ratio": THIN_RATIO, "thick_ratio": THICK_RATIO, "z": EXTREME_Z,
                           "min_expected": MIN_EXPECTED},
            "thin": sorted((r for r in flagged if r["thin"]), key=lambda r: r["ratio"]),
            "thick": sorted((r for r in flagged if r["thick"]), key=lambda r: -r["ratio"]),
            "structure": structure(root), **result}


def _pct(x) -> str:
    return "" if x is None else f"{100 * float(x):.1f}%"


def _at(value, n) -> str:
    return "" if value is None else f"{value} ({n:,})" if n else f"{value}"


def _flag_table(rows: list[dict], limit: int) -> list[str]:
    lines = ["| axis | value | measure | expected | drawn | ratio | z | ran | ran / expected |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    lines += [f"| {r['axis']} | {r['value']} | {_pct(r['measure'])} | {r['expected']:,.0f} | {r['drawn']:,.0f} | "
              f"{r['ratio']} | {r['z']} | {r['laws']:,} | {r['run_ratio']} |" for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"\nand {len(rows) - limit} more in the JSON.")
    return lines


def render(result: dict) -> str:
    t = result["thresholds"]
    lines = [f"# How evenly study {result['study']} covered its space, from {result['bundle']}", "",
             f"{result['laws_run']:,} laws ran in the blind campaigns {result['campaigns']}, read against "
             f"{result['measure_sample']:,} laws drawn from the study's own measure (seed {result['measure_seed']}), "
             "within each stratum, so the strata's designed allocation is not counted as unevenness "
             f"({result['contract']}). Recorded, never judged.", "",
             f"Thin: as drawn under {t['thin_ratio']} of what the measure expects and more than {t['z']:g} standard "
             f"errors below it. Thick: over {t['thick_ratio']} and more than {t['z']:g} above. Only where at least "
             f"{t['min_expected']:g} laws were expected.", "",
             "## Where the drawing is thin", ""]
    lines += _flag_table(result["thin"], 60) if result["thin"] else ["Nowhere."]
    lines += ["", "## Where the drawing is thick", ""]
    lines += _flag_table(result["thick"], 40) if result["thick"] else ["Nowhere."]
    within = result.get("within_strata") or []
    lines += ["", "## Within one stratum", ""]
    if within:
        lines += ["| stratum | axis | value | expected | drawn | ratio | z | |", "|---|---|---|---:|---:|---:|---:|---|"]
        lines += [f"| {r['stratum']} | {r['axis']} | {r['value']} | {r['expected']:,.0f} | {r['drawn']:,.0f} | "
                  f"{r['ratio']} | {r['z']} | {'thin' if r['thin'] else 'thick'} |"
                  for r in sorted(within, key=lambda r: r["ratio"])[:60]]
    else:
        lines.append("Nothing more: no value is thin or thick inside a stratum that is not already above.")
    lines += ["", "## The strata", "", "| stratum | measure | ran | as drawn |", "|---|---:|---:|---:|"]
    lines += [f"| {h} | {_pct(s['measure'])} | {s['laws']:,} | {s['drawn']:,.0f} |"
              for h, s in result["strata"].items()]
    s = result["structure"]
    lines += ["", "## The gap's d_s against the measured d_s", "",
              f"{s['finite_by_the_committed_rule']} laws are finite by the committed rule on the chain from empty "
              f"({s['finite_on_the_given_chain_only']} more on the given chain only). The local d_s is within {s['agree_within']} "
              f"of the gap's for {s['local_agrees']} of the {s['local_read']} it was read for; the laws table's d_s at "
              f"the top rung is the same reading for {s['fitted_is_local']} of {s['fitted_read']} and agrees for "
              f"{s['fitted_agrees']}; all three readings of the rule agree for {s['all_three']}.", "",
              "| law | campaign | gap's d_s | local d_s (N) | within 0.4 | all three |",
              "|---|---:|---:|---:|---|---|"]
    lines += [f"| {r['law']} | {r['campaign']} | {r['gap_implied_d_s']} | {_at(r['local_d_s'], r['local_d_s_at_n'])} | "
              f"{'' if r['local_agrees'] is None else 'yes' if r['local_agrees'] else 'no'} | "
              f"{'yes' if r['all_three'] else 'no' if r['all_three'] is False else 'not read'} |" for r in s["laws"]]
    lines += ["", "## Each axis, with how far its laws reached", ""]
    for axis, body in result["axes"].items():
        if axis == "operator pair":
            continue
        tv = body["total_variation"]
        lines += [f"### {axis}" + (f" (total variation {tv})" if tv is not None else ""), "",
                  "| value | measure | expected | drawn | ratio | z | ran | ran / expected | reached 16,384 | "
                  "reached 262,144 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        lines += [f"| {r['value']} | {_pct(r['measure'])} | {r['expected']:,.0f} | {r['drawn']:,.0f} | {r['ratio']} | "
                  f"{r['z']} | {r['laws']:,} | {r['run_ratio']} | {r['reached_16384']:,} | {r['reached_262144']:,} |"
                  for r in body["rows"]]
        lines.append("")
    pairs = [r for r in result["axes"].get("operator pair", {}).get("rows") or [] if r["expected"] >= MIN_EXPECTED]
    if pairs:
        lines += ["### operator pairs, the fifteen least drawn", "",
                  "| pair | expected | drawn | ratio | z | ran | reached 16,384 |", "|---|---:|---:|---:|---:|---:|---:|"]
        lines += [f"| {r['value']} | {r['expected']:,.0f} | {r['drawn']:,.0f} | {r['ratio']} | {r['z']} | "
                  f"{r['laws']:,} | {r['reached_16384']:,} |" for r in sorted(pairs, key=lambda r: r["ratio"])[:15]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/coverage_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-coverage-") as scratch:
        root = unpacked(Path(args.bundle), Path(scratch))
        result = reading(root, sample=args.sample, seed=args.seed, workers=args.workers)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = render(result)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
