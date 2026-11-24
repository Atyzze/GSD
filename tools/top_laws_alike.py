#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402

CONTRACT = "gsd-top-laws-alike-1"
FROZEN = "frozen: no edge changed"
POPULATION_FROM = 4096


def top_law(score: dict) -> bool:
    if not score or (score.get("score") or 0) <= 0:
        return False
    items = score.get("items") or {}
    return any(points >= 2 for points in items.values()) and score.get("by") not in ("frozen", "still")


def laws_of(root: Path, *, rescore: bool = True) -> list[dict]:
    from score_list import chains_of_report, control_bundles
    controls = control_bundles(root)
    out = []
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        if Path(path).parent.name in controls:
            continue
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        body = report.get("body") or {}
        campaign = str(report.get("campaign_id") or Path(path).parent.name.split("_")[1])
        chains = (body.get("every_chain") or {}).get("laws") or {}
        for row in (body.get("law_ledger") or {}).get("rows") or []:
            law = str(row.get("candidate_id"))
            entry = chains.get(law) or {}
            if rescore and entry:
                found_chains, reading = chains_of_report(entry, (body.get("every_chain") or {}).get("value_columns"))
                score = L.score(found_chains, reading, references={})
            else:
                score = entry.get("score") or {}
            out.append({"law": law, "campaign": campaign, "spec": row.get("spec") or {}, "kind": row.get("kind"),
                        "fate": row.get("fate"), "top_n": entry.get("top_n") or max(
                            (int(n) for n in (row.get("mean_degree") or {})), default=0),
                        "score": score})
    return out


def _ops(spec: dict) -> list[tuple[str, int]]:
    out = []
    for op, _k, c0, _scale, _p in spec.get("terms") or []:
        out.append((str(op), 1 if (c0 or 0) > 0 else -1))
    return out


def _share(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def _median(values: list) -> float | None:
    kept = [float(v) for v in values if v is not None]
    return round(statistics.median(kept), 4) if kept else None


def enrichment(top: list[dict], population: list[dict]) -> list[dict]:
    rows = []
    names = sorted({name for law in top + population for name, _ in _ops(law["spec"])})
    for name in names:
        def having(laws, sign=None):
            return sum(1 for law in laws if any(n == name and (sign is None or s == sign) for n, s in _ops(law["spec"])))
        in_top, in_all = having(top), having(population)
        rows.append({"term": name, "top": in_top, "top_share": _share(in_top, len(top)),
                     "population": in_all, "population_share": _share(in_all, len(population)),
                     "ratio": (round((in_top / len(top)) / (in_all / len(population)), 2)
                               if top and in_all else None),
                     "top_positive": having(top, 1), "top_negative": having(top, -1),
                     "population_positive": having(population, 1), "population_negative": having(population, -1)})
    rows.sort(key=lambda r: (-(r["ratio"] or 0), r["term"]))
    return rows


def dynamics(laws: list[dict]) -> dict:
    specs = [law["spec"] for law in laws]
    finite = [s for s in specs if not s.get("zero_temperature")]
    return {"laws": len(specs), "zero_temperature": _share(sum(1 for s in specs if s.get("zero_temperature")), len(specs)),
            "beta_finite_median": _median([s.get("beta") for s in finite]),
            "locality_median": _median([s.get("locality") for s in specs]),
            "swap_share_median": _median([s.get("swap_share") for s in specs]),
            "terms_median": _median([len(s.get("terms") or []) for s in specs]),
            "kinds": dict(Counter(str(law.get("kind")) for law in laws).most_common())}


def term_sets(top: list[dict], population: list[dict]) -> list[dict]:
    def key(law):
        return " + ".join(sorted({name for name, _ in _ops(law["spec"])}))
    reached = Counter(key(law) for law in population)
    rows = []
    for name, laws in sorted(_group(top, key).items(), key=lambda kv: (-len(kv[1]), kv[0])):
        rows.append({"terms": name, "top": len(laws), "population": reached.get(name, 0),
                     "chains": dict(Counter(law["score"].get("chain") for law in laws).most_common()),
                     "d": sorted(law["score"].get("d") for law in laws if law["score"].get("d") is not None),
                     "signs": dict(Counter(" ".join(f"{n}{'+' if s > 0 else '-'}" for n, s in sorted(_ops(law["spec"])))
                                           for law in laws).most_common()),
                     "laws": sorted(law["law"][:12] for law in laws)})
    return rows


def _group(laws: list[dict], key) -> dict:
    out: dict = {}
    for law in laws:
        out.setdefault(key(law), []).append(law)
    return out


def by_dimension(top: list[dict]) -> list[dict]:
    rows = []
    for band, laws in sorted(_group(top, lambda law: _band(law["score"].get("d"))).items()):
        ops = Counter(name for law in laws for name in {n for n, _ in _ops(law["spec"])})
        rows.append({"d": band, "laws": len(laws), "chains": dict(Counter(law["score"].get("chain") for law in laws)),
                     "terms": dict(ops.most_common()), "dynamics": dynamics(laws)})
    return rows


def _band(d) -> str:
    if d is None:
        return "none"
    if L.is_ring(d):
        return "below 1.5 (a ring)"
    return f"about {int(round(float(d)))}"


def read(root: Path, *, rescore: bool = True) -> dict:
    laws = laws_of(root, rescore=rescore)
    top = [law for law in laws if top_law(law["score"])]
    population = [law for law in laws if int(law["top_n"] or 0) >= POPULATION_FROM]
    return {"contract": CONTRACT, "score_contract": L.CONTRACT if rescore else "as the bundle carries it",
            "bundle": Path(root).name, "laws": len(laws), "population_from_n": POPULATION_FROM,
            "population": len(population), "top": len(top),
            "rule": ("a top law is a drawn law (no standing control) the score settles: it scores above zero with at "
                     "least one probe or the Einstein relation settled, and its scoring start is not frozen"),
            "enrichment": enrichment(top, population), "term_sets": term_sets(top, population),
            "by_dimension": by_dimension(top),
            "dynamics": {"top": dynamics(top), "population": dynamics(population), "every_law": dynamics(laws)},
            "top_laws": [{"law": law["law"], "campaign": law["campaign"], "score": law["score"].get("score"),
                          "chain": law["score"].get("chain"), "d": law["score"].get("d"),
                          "to_n": law["score"].get("to_n"), "terms": _ops(law["spec"]), "spec": law["spec"]}
                         for law in sorted(top, key=lambda x: -(x["score"].get("score") or 0))]}


def render(found: dict) -> str:
    lines = [f"# What the top laws share, on {found['bundle']}", "",
             f"{found['top']} top laws of {found['laws']} ({found['rule']}; the score {found['score_contract']}), beside "
             f"the {found['population']} laws that reached {found['population_from_n']:,}, the laws that could have "
             "scored. A ratio is a term's share among the top laws over its share among those.", "",
             "## Terms", "", "| term | top laws | share | reached 4,096 | share | ratio | top + / - |",
             "|---|---|---|---|---|---|---|"]
    for row in found["enrichment"]:
        lines.append(f"| {row['term']} | {row['top']} | {row['top_share']} | {row['population']} | "
                     f"{row['population_share']} | {row['ratio']} | {row['top_positive']} / {row['top_negative']} |")
    lines += ["", "## Term sets of the top laws", "", "| terms | top laws | reached 4,096 | chains | d | signs |",
              "|---|---|---|---|---|---|"]
    for row in found["term_sets"]:
        lines.append(f"| {row['terms']} | {row['top']} | {row['population']} | "
                     f"{', '.join(f'{k} {v}' for k, v in row['chains'].items())} | "
                     f"{', '.join(f'{d:g}' for d in row['d'])} | "
                     f"{'; '.join(f'{k} ({v})' for k, v in row['signs'].items())} |")
    lines += ["", "## By the dimension read", ""]
    for row in found["by_dimension"]:
        dyn = row["dynamics"]
        lines.append(f"* d {row['d']}: {row['laws']} laws; chains "
                     + ", ".join(f"{k} {v}" for k, v in row["chains"].items()) + "; terms "
                     + ", ".join(f"{k} {v}" for k, v in row["terms"].items())
                     + f"; zero temperature {dyn['zero_temperature']}, locality {dyn['locality_median']}, "
                     f"swap share {dyn['swap_share_median']}")
    lines += ["", "## Dynamics", "", "| laws | count | zero temperature | beta (finite T) | locality | swap share | terms |",
              "|---|---|---|---|---|---|---|"]
    for name, dyn in found["dynamics"].items():
        lines.append(f"| {name.replace('_', ' ')} | {dyn['laws']} | {dyn['zero_temperature']} | "
                     f"{dyn['beta_finite_median']} | {dyn['locality_median']} | {dyn['swap_share_median']} | "
                     f"{dyn['terms_median']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="what the laws the score settles share, read on a study's bundle")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its folder")
    parser.add_argument("--as-carried", action="store_true", help="the scores the bundle carries, not the score in force")
    parser.add_argument("--json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)
    source = Path(args.bundle)
    if source.is_file():
        from read_bundle import scratch_dir, unpacked
        source = unpacked(source, scratch_dir("gsd-top-laws-"))
    found = read(source, rescore=not args.as_carried)
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(found), encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
