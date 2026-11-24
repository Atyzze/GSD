#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import numpy as np  # noqa: E402

import law_rows as L  # noqa: E402
from graph_scale_dynamics.measurements import starts as the_starts  # noqa: E402

CONTRACT = "gsd-cluster-reading-2"
LATTICES_RUN = tuple(start.name for start in the_starts.lattices_run())
CHAINS = ("empty", "given", *LATTICES_RUN)
NAMES = {"empty": "empty", "given": "random"}
QUANTITIES = ("mean_degree", "giant_fraction", "triangles_per_node", "squares_per_node", "reach", "d_s", "d_V",
              "d_B", "d_w")
PROBES = ("d_s", "d_V", "d_B", "d_w")
FIRST, SECOND = 1024, 4096
K_FROM, K_TO = 4, 16
SAMPLE = 3000
SEED = 736
MOSTLY = 0.8


def _value(name: str, value, n: int) -> float | None:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    value = float(value)
    if name in ("mean_degree", "triangles_per_node", "squares_per_node"):
        return math.log1p(max(value, 0.0))
    if name == "reach":
        return math.log(max(value, 1.0)) / math.log(n)
    return value


def _at(values: dict, columns: list, chain: str, n: int) -> dict | None:
    for row in values.get(chain) or []:
        if int(row[0]) == n:
            cells = dict(zip(columns, row, strict=False))
            return {q: _value(q, cells.get(q), n) for q in QUANTITIES}
    return None


def features(values: dict, columns: list) -> list[float | None] | None:
    first = {chain: _at(values, columns, chain, FIRST) for chain in CHAINS}
    if not all(first.values()):
        return None
    second = {chain: _at(values, columns, chain, SECOND) for chain in CHAINS}
    out: list[float | None] = []
    for chain in CHAINS:
        out += [first[chain][q] for q in QUANTITIES]
        out += [1.0 if first[chain][p] is None else 0.0 for p in PROBES]
    reached = all(second.values())
    for chain in CHAINS:
        for q in QUANTITIES:
            a, b = first[chain][q], (second[chain] or {}).get(q)
            out.append(b - a if reached and a is not None and b is not None else 0.0)
    out.append(1.0 if reached else 0.0)
    return out


def feature_names() -> list[str]:
    names = [f"{NAMES.get(c, c)} {q} at {FIRST}" for c in CHAINS for q in QUANTITIES + tuple(f"{p} unread" for p in PROBES)]
    names += [f"{NAMES.get(c, c)} {q} change to {SECOND}" for c in CHAINS for q in QUANTITIES]
    return names + [f"reached {SECOND}"]


def entries(root: Path) -> list[dict]:
    from graph_scale_dynamics.research import dimension_rule as R
    cal = R.calibration()
    out = []
    for part in L.campaigns(root):
        engine = L.body(root / str(part.get("bundle") or ""))
        every = engine.get("every_chain") or {}
        columns = list(every.get("value_columns") or [])
        ledger = {str(r.get("candidate_id")): r for r in (engine.get("law_ledger") or {}).get("rows") or []}
        for law, chained in (every.get("laws") or {}).items():
            values = chained.get("values") or {}
            row = features(values, columns)
            if row is None or law not in ledger:
                continue
            starts = chained.get("starts_reading") or {}
            fates = {name: (v or [None])[0] for name, v in (starts.get("fates") or {}).items()}
            kinds = sorted({R.mark(name, R.judged_chain(rows, columns), fates.get(name), cal)["kind"] or "none"
                            for name, rows in values.items()} - {"none"}, key=R.KINDS.index)
            fate = list(ledger[law].get("fate") or [None, None])
            spec = ledger[law].get("spec") or {}
            out.append({"law": law, "campaign": str(part.get("campaign_id")), "features": row,
                        "class": starts.get("class") or "not_read", "kind": kinds[0] if kinds else "none",
                        "fate": fate[0] or "open", "top_n": chained.get("top_n"),
                        "zero_t": bool(spec.get("zero_temperature")), "fates": fates})
        del engine, every, ledger
        gc.collect()
    return out


def matrix(rows: list[dict]) -> tuple[np.ndarray, list[int]]:
    raw = np.array([[np.nan if v is None else float(v) for v in r["features"]] for r in rows], dtype=float)
    mean = np.nanmean(raw, axis=0)
    filled = np.where(np.isnan(raw), mean, raw)
    sd = filled.std(axis=0)
    kept = [i for i, s in enumerate(sd) if s > 1e-9]
    return (filled[:, kept] - filled[:, kept].mean(axis=0)) / sd[kept], kept


def _silhouette(x: np.ndarray, labels: np.ndarray) -> float:
    from scipy.spatial.distance import cdist
    d = cdist(x, x)
    found = np.unique(labels)
    if len(found) < 2:
        return -1.0
    a = np.zeros(len(x))
    b = np.full(len(x), np.inf)
    for k in found:
        inside = labels == k
        mean = d[:, inside].sum(axis=1) / np.maximum(inside.sum() - inside.astype(int), 1)
        a = np.where(inside, mean, a)
        b = np.where(inside, b, np.minimum(b, d[:, inside].mean(axis=1)))
    s = (b - a) / np.maximum(np.maximum(a, b), 1e-12)
    return float(np.mean(s))


def cluster(x: np.ndarray) -> dict:
    from scipy.cluster.vq import kmeans2
    rng = np.random.default_rng(SEED)
    sample = rng.choice(len(x), size=min(SAMPLE, len(x)), replace=False)
    tried = {}
    best = None
    for k in range(K_FROM, min(K_TO, len(x) - 1) + 1):
        centres, labels = kmeans2(x, k, minit="++", seed=SEED + k)
        score = _silhouette(x[sample], labels[sample])
        tried[k] = round(score, 4)
        if best is None or score > best[0]:
            best = (score, k, centres, labels)
    return {"k": best[1], "silhouette": round(best[0], 4), "tried": tried, "centres": best[2], "labels": best[3],
            "searched": [min(tried), max(tried)], "at_edge": edge_of(best[1], tried)}


def edge_of(k: int, tried: dict) -> str | None:
    if len(tried) < 2:
        return None
    return "lowest" if k == min(tried) else "highest" if k == max(tried) else None


def imputed(rows: list[dict], names: list[str]) -> dict:
    probes = {f"{NAMES.get(c, c)} {p} at {FIRST}" for c in CHAINS for p in PROBES}
    at = [i for i, name in enumerate(names) if name in probes]
    with_probe = sum(any(r["features"][i] is None for i in at) for r in rows)
    with_any = sum(any(v is None for v in r["features"]) for r in rows)
    return {"laws_with_a_probe_imputed": with_probe, "share_with_a_probe_imputed": round(with_probe / len(rows), 4),
            "laws_with_any_value_imputed": with_any, "share_with_any_value_imputed": round(with_any / len(rows), 4),
            "share_of_probe_values_imputed": round(sum(r["features"][i] is None for r in rows for i in at)
                                                   / (len(rows) * len(at)), 4)}


def _share(count: Counter, total: int) -> dict:
    return {key: {"laws": n, "share": round(n / total, 4)} for key, n in count.most_common()}


def describe(rows: list[dict], x_raw: np.ndarray, labels: np.ndarray, names: list[str]) -> list[dict]:
    out = []
    for k in sorted(set(labels.tolist()), key=lambda k: -int((labels == k).sum())):
        inside = [r for r, label in zip(rows, labels, strict=True) if label == k]
        block = x_raw[labels == k]
        medians = {name: (None if np.all(np.isnan(block[:, i])) else round(float(np.nanmedian(block[:, i])), 3))
                   for i, name in enumerate(names) if name.endswith(f"at {FIRST}") and "unread" not in name}
        unread = {name: round(float(np.nanmean(block[:, i])), 3) for i, name in enumerate(names) if "unread" in name}
        lattices = {lattice: dict(Counter(r["fates"].get(lattice) or "not read" for r in inside).most_common(3))
                    for lattice in LATTICES_RUN}
        classes = Counter(r["class"] for r in inside)
        top, top_n = classes.most_common(1)[0]
        out.append({"cluster": int(k), "laws": len(inside), "classes": _share(classes, len(inside)),
                    "mostly": top if top_n / len(inside) >= MOSTLY else None,
                    "kinds": _share(Counter(r["kind"] for r in inside), len(inside)),
                    "fates": _share(Counter(r["fate"] for r in inside), len(inside)),
                    "zero_temperature": round(sum(r["zero_t"] for r in inside) / len(inside), 4),
                    "reached_4096": round(sum(r["features"][-1] for r in inside) / len(inside), 4),
                    "lattice_fates": lattices, "medians": medians, "unread_share": unread,
                    "examples": sorted(r["law"][:12] for r in inside)[:8]})
    return out


def reading(root: Path) -> dict:
    rows = entries(root)
    if len(rows) < K_TO + 2:
        return {"contract": CONTRACT, "bundle": root.name, "laws": len(rows), "reading": "too few laws to cluster"}
    names = feature_names()
    x, kept = matrix(rows)
    found = cluster(x)
    raw = np.array([[np.nan if v is None else float(v) for v in r["features"]] for r in rows], dtype=float)
    raw[:, [i for i, n in enumerate(names) if "change to" in n]] = np.where(
        raw[:, [-1]] > 0, raw[:, [i for i, n in enumerate(names) if "change to" in n]], np.nan)
    clusters = describe(rows, raw, found["labels"], names)
    by_class: dict = {}
    for r, label in zip(rows, found["labels"], strict=True):
        by_class.setdefault(r["class"], Counter())[int(label)] += 1
    spread = {c: {"laws": sum(v.values()), "clusters": len(v),
                  "largest_share": round(max(v.values()) / sum(v.values()), 4)}
              for c, v in sorted(by_class.items(), key=lambda kv: -sum(kv[1].values()))}
    return {"contract": CONTRACT, "bundle": root.name, "laws": len(rows), "features": len(names),
            "features_used": len(kept), "k": found["k"], "silhouette": found["silhouette"],
            "silhouette_by_k": found["tried"], "k_searched": found["searched"], "k_at_edge": found["at_edge"],
            "imputed": imputed(rows, names), "clusters": clusters, "classes_across_clusters": spread,
            "reading": ("every law read at 1,024 on every chain it runs, each a vector of its "
                        "chains' readings at 1,024 (degree, one piece, triangles and squares a node, the reach's "
                        "exponent, the four probes, which probes were unread) and their change to 4,096 where it "
                        "reached it, standardised; k-means for k of 4 to 16, k chosen by the silhouette on a fixed "
                        f"sample of {SAMPLE}; the starts' classes and the dimension test's kinds are not among "
                        "the features and are read against the clusters after. Recorded, never judged.")}


def _edge(result: dict) -> str:
    edge, searched = result.get("k_at_edge"), result.get("k_searched")
    if not edge:
        return ""
    side = "smaller" if edge == "lowest" else "larger"
    return (f" The chosen k is the {edge} searched ({searched[0]} to {searched[1]}): the silhouette may rise further "
            f"at a {side} k, which was not tried, so k is a bound of the search, not a finding.")


def _imputed(found: dict | None) -> str:
    if not found:
        return ""
    return (f"Imputed (an unread value given its feature's mean over the laws, its probe's unread flag kept beside it): "
            f"{found['laws_with_a_probe_imputed']:,} laws ({found['share_with_a_probe_imputed']:.1%}) have a probe "
            f"imputed on some chain at {FIRST:,}, {found['share_of_probe_values_imputed']:.1%} of all probe values; "
            f"{found['laws_with_any_value_imputed']:,} ({found['share_with_any_value_imputed']:.1%}) have any value "
            "imputed.")


def render(result: dict) -> str:
    if "clusters" not in result:
        return f"# The study's laws clustered\n\n{result['reading']}.\n"
    lines = [f"# The study's laws clustered, from {result['bundle']}", "", result["reading"], "",
             f"{result['laws']:,} laws, {result['features_used']} features; k = {result['k']} "
             f"(silhouette {result['silhouette']}; by k: {result['silhouette_by_k']}).{_edge(result)}", "",
             _imputed(result.get("imputed")), "",
             "## The clusters", "", "| cluster | laws | classes | dimension kinds | fates | zero T | reached 4,096 |",
             "|---|---:|---|---|---|---:|---:|"]
    for c in result["clusters"]:
        def top(block, n=3):
            return ", ".join(f"{k} {v['share']:.0%}" for k, v in list(block.items())[:n])
        lines.append(f"| {c['cluster']} | {c['laws']:,} | {top(c['classes'])} | {top(c['kinds'])} | {top(c['fates'])} "
                     f"| {c['zero_temperature']:.0%} | {c['reached_4096']:.0%} |")
    lines += ["", "## What each cluster reads at 1,024 (medians)", ""]
    keys = [f"{NAMES.get(c, c)} {q} at {FIRST}" for c in ("empty", "given") for q in
            ("mean_degree", "giant_fraction", "reach", "d_s", "d_V", "d_B")]
    lines += ["| cluster | " + " | ".join(k.replace(f" at {FIRST}", "") for k in keys) + " | lattices |",
              "|---|" + "---|" * (len(keys) + 1)]
    for c in result["clusters"]:
        cells = []
        for key in keys:
            value = c["medians"].get(key)
            if value is not None and "mean_degree" in key:
                value = round(math.expm1(value), 2)
            cells.append("" if value is None else str(value))
        fates = "; ".join(f"{name} {next(iter(f))}" for name, f in c["lattice_fates"].items())
        lines.append(f"| {c['cluster']} | " + " | ".join(cells) + f" | {fates} |")
    lines += ["", "Degree is the mean degree; one piece the largest component's share; reach the exponent of the reach "
              "in N (log reach over log N); the probes' medians over the laws that read them.", "",
              "## Each class across the clusters", "", "| class | laws | clusters it falls in | its largest cluster's share |",
              "|---|---:|---:|---:|"]
    for name, row in result["classes_across_clusters"].items():
        lines.append(f"| {name} | {row['laws']:,} | {row['clusters']} | {row['largest_share']:.0%} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/cluster_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-clusters-") as scratch:
        result = reading(unpacked(Path(args.bundle), Path(scratch)))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    page = render(result)
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    if not args.json and not args.md:
        print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
