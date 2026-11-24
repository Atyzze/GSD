from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.decisions import steady_chain as SC  # noqa: E402
from graph_scale_dynamics.observability import starts_reading as SR  # noqa: E402
from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS  # noqa: E402

CONTRACT = "gsd-pilot-reading-1"
COLUMNS = list(VALUE_COLUMNS)
LATTICES = set(SR.NAMED)
HELD = ("holds", "unmoved")
THINNED = ("melted", "partly", "fell_apart", "stretched", "no_reach")
FROZEN_SHARE = 0.001
SAME_COUNT = 2.5
ONLY_DEGREES = ("degree sequence only", "degree correlations")
KINDS = ("a ring", "no edge changed", "reshaped the same per node", "thinning", "irregular")


def _body(path: Path) -> dict:
    body = json.loads(path.read_text(encoding="utf-8"))
    return body.get("body", body)


def _study_campaigns(root: Path) -> set:
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    return {str(c.get("campaign_id")) for c in study.get("campaigns") or []
            if "control" not in str(c.get("name") or c.get("label") or "").lower()}


def laws_of(root: Path) -> dict:
    wanted, out = _study_campaigns(root), {}
    for path in sorted(root.glob("campaign_*_reports_*/28-decision-engine.json")):
        campaign = path.parent.name.split("_")[1]
        if campaign not in wanted:
            continue
        body = _body(path)
        every = (body.get("every_chain") or {}).get("laws") or {}
        ledger = {r["candidate_id"]: r for r in (body.get("law_ledger") or {}).get("rows") or []}
        decided = {r["candidate_id"]: r for r in body.get("laws") or []}
        seeds = body.get("seeds") or {}
        names, ids = seeds.get("columns") or [], seeds.get("laws") or []
        by_law = defaultdict(list)
        for row in seeds.get("rows") or []:
            seed = dict(zip(names, row, strict=True))
            by_law[ids[seed["law"]] if isinstance(seed["law"], int) else seed["law"]].append(seed)
        for law in set(ledger) | set(every):
            entry = every.get(law) or {}
            out[(campaign, law)] = {"campaign": campaign, "law": law, "ledger": ledger.get(law) or {},
                                    "decided": decided.get(law) or {}, "values": entry.get("values") or {},
                                    "score": entry.get("score") or {}, "starts": entry.get("starts_reading") or {},
                                    "seeds": by_law.get(law, [])}
    return out


def _value(law: dict, chain: str, n: int, column: str):
    for row in law["values"].get(chain) or ():
        if int(row[0]) == int(n):
            value = row[COLUMNS.index(column)]
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _key(law: dict, chain: str | None) -> str | None:
    if chain in law["values"]:
        return chain
    return next((k for k in ("given", "random") if chain in ("given", "random") and k in law["values"]), None)


def _start(chain: str, n: int, refs: dict) -> float | None:
    ref = (refs.get(SR.NAMED.get(chain)) or {}).get(int(n)) or {}
    value = ((ref.get("start") or {}).get("mean_degree") or {}).get("mean")
    return float(value) if isinstance(value, (int, float)) else None


def _fate(law: dict, chain: str, n: int, refs: dict) -> str | None:
    side = {name: {"mean": _value(law, chain, n, name)} for name in COLUMNS[1:]}
    return SR.lattice_fate(side, SR.NAMED[chain], int(n), refs).get("fate")


def score_of(law: dict) -> float:
    return float(law["score"].get("score") or 0)


def d_of(law: dict) -> float | None:
    chain, n = _key(law, law["score"].get("chain")), law["score"].get("to_n")
    if chain is None or n is None:
        return None
    probes = [_value(law, chain, int(n), p) for p in ("d_s", "d_V", "d_B", "d_w")]
    probes = [p for p in probes if p is not None]
    return statistics.median(probes) if probes else None


def kind(law: dict, refs: dict) -> str | None:
    if score_of(law) <= 0:
        return None
    d = d_of(law)
    if d is not None and d < 1.5:
        return "a ring"
    chain = law["score"].get("chain")
    if chain not in LATTICES or chain not in law["values"]:
        return "irregular"
    sizes = sorted({int(r[0]) for r in law["values"][chain] if int(r[0]) >= SC.FROM_N})
    degrees = [_value(law, chain, n, "mean_degree") for n in sizes]
    starts = [_start(chain, n, refs) for n in sizes]
    if None in degrees or None in starts or not sizes:
        return "irregular"
    changed = [(k - k0) / 2.0 * n for k, k0, n in zip(degrees, starts, sizes, strict=True)]
    frozen = [abs(c) <= FROZEN_SHARE * k0 / 2.0 * n for c, k0, n in zip(changed, starts, sizes, strict=True)]
    if all(frozen):
        return "no edge changed"
    at = _value(law, chain, SC.AT_N, "mean_degree")
    if not frozen[-1] and at is not None and all(abs(k - at) <= SC.DEGREE_WITHIN * at for k in degrees):
        return "reshaped the same per node"
    last, before = changed[-1], changed[-2] if len(changed) > 1 else None
    same_count = (before is not None and last * before > 0
                  and 1.0 / SAME_COUNT <= last / before <= SAME_COUNT)
    if same_count or any(_fate(law, chain, n, refs) in THINNED for n in (SC.FROM_N, SC.AT_N) if n in sizes):
        return "thinning"
    return "irregular"


def _cpu(law: dict) -> dict:
    out = defaultdict(float)
    for seed in law["seeds"]:
        out[int(seed["n"])] += float(seed.get("cpu_seconds") or 0.0)
    return out


def _squares(law: dict, chain: str, n: int) -> float:
    return _value(law, chain, n, "squares_per_node") or 0.0


def certified_at(law: dict, n: int) -> bool:
    seeds = [seed for seed in law["seeds"] if int(seed["n"]) == int(n) and seed.get("attempts")]
    return bool(seeds) and all(seed.get("ended") == "completed" for seed in seeds)


def _class(law: dict, n: int) -> str | None:
    row = (law["starts"].get("by_n") or {}).get(str(n))
    return row[0] if row else None


def predictions(laws: dict, refs: dict) -> dict:
    scorers = {k: v for k, v in laws.items() if score_of(v) > 0}
    kinds = {k: kind(v, refs) for k, v in scorers.items()}
    out = {}
    named = [k for k, v in scorers.items() if v["score"].get("chain") not in LATTICES and kinds[k] != "a ring"]
    out["K1"] = {"named": sum(1 for v in scorers.values() if v["score"].get("chain") not in LATTICES),
                 "breaks": [k[1][:12] for k in named]}
    degrees = [k for k, v in laws.items() if v["ledger"].get("kind") in ONLY_DEGREES]
    out["K2"] = {"named": len(degrees), "breaks": [k[1][:12] for k in degrees if k in scorers and kinds[k] != "a ring"]}
    alike = [k for k, v in laws.items() if _class(v, 4096) == "forgets" or _class(v, 1024) == "forgets"]
    out["K3"] = {"named": len(alike), "breaks": [k[1][:12] for k in alike if k in scorers and kinds[k] != "a ring"]}
    gated, through, kept = [], Counter(), Counter()
    for k, v in laws.items():
        if SC.AT_N not in _cpu(v):
            continue
        found = SC.block(v["values"], COLUMNS, refs)
        if found and found["moved"]:
            kept[kinds.get(k) or "no score"] += 1
            continue
        gated.append(k)
        through[kinds.get(k) or "no score"] += 1
    reshaped_unsteady = [k[1][:12] for k, kd in kinds.items() if kd == "reshaped the same per node"
                         and not ((SC.block(laws[k]["values"], COLUMNS, refs) or {}).get("moved"))]
    out["K4"] = {"named": len(gated), "kinds_of_the_named": dict(through), "kinds_of_the_kept": dict(kept),
                 "breaks": sorted(set([k[1][:12] for k in gated if kinds.get(k) == "reshaped the same per node"]
                                      + reshaped_unsteady))}
    over = []
    for k, v in scorers.items():
        chain = _key(v, v["score"].get("chain"))
        if chain and any(_squares(v, chain, n) > SC.SQUARES_A_NODE_AT_MOST for n in (256, 1024)):
            over.append(k[1][:12])
    out["K5"] = {"named": len(scorers), "breaks": over}
    uncertified = [k for k, v in laws.items() if SC.AT_N in _cpu(v) and not certified_at(v, SC.AT_N)]
    out["K8"] = {"named": len(uncertified),
                 "breaks": [k[1][:12] for k in uncertified if kinds.get(k) == "reshaped the same per node"],
                 "kinds_of_the_named": dict(Counter(kinds.get(k) or "no score" for k in uncertified))}
    for item in out.values():
        if "breaks" in item:
            item["holds"] = not item["breaks"]
    return {"predictions": out, "scorers": {f"{k[0]}:{k[1]}": {"score": score_of(v), "kind": kinds[k],
                                                               "chain": v["score"].get("chain"), "d": d_of(v)}
                                            for k, v in sorted(scorers.items(), key=lambda kv: -score_of(kv[1]))}}


def render(name: str, found: dict) -> str:
    lines = [f"# {name}: the pilot's predictions", "",
             f"Read with `tools/pilot_reading.py` ({CONTRACT}). A prediction holds only if no law breaks it.", "",
             "| prediction | named | breaks | holds |", "|---|---:|---|---|"]
    for key, item in found["predictions"].items():
        breaks = ", ".join(f"`{b}`" for b in item.get("breaks") or []) or "none"
        lines.append(f"| {key} | {item.get('named')} | {breaks} | {item.get('holds')} |")
    lines += ["", "| scorer | score | kind | chain | d |", "|---|---:|---|---|---:|"]
    for law, s in found["scorers"].items():
        d = "" if s["d"] is None else f"{s['d']:.2f}"
        lines.append(f"| `{law.split(':')[1][:12]}` | {s['score']:g} | {s['kind']} | {s['chain']} | {d} |")
    counts = Counter(s["kind"] for s in found["scorers"].values())
    lines += ["", "Scorers by kind: " + ", ".join(f"{counts.get(k, 0)} {k}" for k in KINDS) + "."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="a pilot's predictions and its scorers by kind, read from its bundle")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    found = {"contract": CONTRACT, "bundle": args.bundle.name,
             **predictions(laws_of(args.bundle), SR.table_references())}
    text = render(args.bundle.name, found)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
