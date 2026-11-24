#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import catalogue as K  # noqa: E402
from graph_scale_dynamics.observability import law_score as L  # noqa: E402

CONTRACT = "gsd-catalogue-reading-2"
EARLY = (1024, 4096)
DEEP_FROM = 16384
SETTLE_FROM = K.SETTLE_FROM
SHOWN = 5


def moves_of(root: Path, full_share: float) -> dict[tuple[str, str, int], dict]:
    path = Path(root) / "tables" / "chains.ndjson.gz"
    if not path.is_file():
        return {}
    moved: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    capped: dict[tuple[str, str, int], list[bool]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key = (str(row["candidate_id"]), str(row["chain"]), int(row["n"]))
            capped[key].append(bool(row.get("ended_at_cap")))
            if row.get("final_edges"):
                moved[key].append(row["accepted_moves"] / row["final_edges"])
    return {key: {"moved": round(statistics.median(moved[key]), 6) if moved.get(key) else None,
                  "full": sum(flags) / len(flags) >= full_share}
            for key, flags in capped.items()}


def values_of(root: Path) -> dict[str, dict]:
    out = {}
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        body = report.get("body") or {}
        columns = list((body.get("every_chain") or {}).get("value_columns") or ())
        decided = {str(r.get("candidate_id")): r for r in body.get("laws") or [] if isinstance(r, dict)}
        for law, entry in ((body.get("every_chain") or {}).get("laws") or {}).items():
            own = decided.get(str(law)) or {}
            out[str(law)] = {"campaign": str(report.get("campaign_id")), "folder": Path(path).parent.name, "raw": entry,
                             "columns": columns,
                             "decision": [own.get("action"), own.get("rule"), own.get("at_n")],
                             "chains": {name: {int(row[0]): dict(zip(columns, row, strict=False)) for row in rows}
                                        for name, rows in (entry.get("values") or {}).items()}}
    return out


def views(law: str, entry: dict, moves: dict) -> dict[int, dict[str, dict]]:
    out: dict[int, dict[str, dict]] = defaultdict(dict)
    for name, rows in entry["chains"].items():
        for n, row in rows.items():
            seen = moves.get((law, name, n)) or {}
            out[n][name] = {"d": K.d_of(row), "mean_degree": row.get("mean_degree"), "reach": row.get("reach"),
                            "giant": row.get("giant_fraction"), "moved": seen.get("moved"),
                            "full": bool(seen.get("full"))}
    return dict(out)


def twin_points(found: dict, twins: list[str]) -> dict[int, dict]:
    out = {}
    for size in found.get("sizes") or []:
        if not size.get("n"):
            continue
        probes = {f"{name}:{probe}": points for name, info in (size.get("chains") or {}).items() if name in twins
                  for probe, points in ((info or {}).get("items") or {}).items() if probe != "einstein"}
        out[int(size["n"])] = {"points": max(probes.values(), default=0),
                               "probes": {k: v for k, v in sorted(probes.items()) if v >= 2}}
    return out


value_settles = K.value_settles


def early_table(laws: dict, n: int) -> dict:
    deep = [law for law in laws.values() if law["deepest"] >= DEEP_FROM and n in law["kinds"]]
    pairs = Counter((law["kinds"][n], law["kind"]) for law in deep)
    called, held, became, caught = Counter(), Counter(), Counter(), Counter()
    for (early, late), count in pairs.items():
        called[early] += count
        became[late] += count
        if early == late:
            held[early] += count
            caught[late] += count
    return {"laws": len(deep),
            "pairs": [{"early": a, "deep": b, "laws": c} for (a, b), c in sorted(pairs.items(), key=lambda kv: -kv[1])],
            "held": {k: [held[k], called[k]] for k in sorted(called)},
            "caught": {k: [caught[k], became[k]] for k in sorted(became)}}


def chain_stills(laws: dict, given: dict) -> dict:
    out = {}
    tracks = [(name, track) for law in laws.values() for name, track in law["tracks"].items()
              if name in given["lattice_degrees"]]
    for n in EARLY:
        called = [track for _name, track in tracks if track.get(n) and any(m > n for m in track)]
        kept = sum(1 for track in called if all(track[m] for m in track if m > n))
        deep = [track for _name, track in tracks if max(track) >= DEEP_FROM and track[max(track)]]
        early = sum(1 for track in deep if track.get(n))
        out[str(n)] = {"still_with_a_deeper_size": len(called), "still_at_every_deeper_size": kept,
                       "still_from_16384": len(deep), "of_them_still_already": early}
    return out


def moved_by_chain(law: str, moves: dict) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for (law_id, name, n), seen in moves.items():
        if law_id == law and seen.get("moved") is not None:
            out[name][n] = seen["moved"]
    return dict(out)


def scores_in_force(laws: dict) -> dict:
    rows = []
    for law_id, law in laws.items():
        found = law["score"]
        if found["score"] <= 0:
            continue
        rows.append({"law": law_id, "chain": found["chain"], "to_n": found["to_n"], "score": found["score"],
                     "by": found["by"], "still": found["by"] in L.LOWEST, "kind": law.get("kind"),
                     "kept_score": found["kept_score"]})
    rows.sort(key=lambda r: (-r["score"], -r["to_n"], r["law"]))
    return {"score": L.CONTRACT, "scored": len(rows), "still": sum(1 for r in rows if r["still"]), "rows": rows}



def read(root: Path, *, scores: bool = True) -> dict:
    import score_list
    given = K.rule()
    moves = moves_of(root, float(given["full_share"]))
    controls = score_list.control_bundles(root)
    relative = L.margins()["relative"]
    laws, held_back = {}, 0
    for law, entry in values_of(root).items():
        if entry["folder"] in controls:
            held_back += 1
            continue
        seen = views(law, entry, moves)
        sizes = sorted(seen)
        if not sizes:
            continue
        found = L.score(*score_list.chains_of_report(entry["raw"], entry["columns"], moved_by_chain(law, moves)),
                        references={})
        twin = twin_points(found, given["twin_starts"])
        settles = value_settles(entry["chains"], given["twin_starts"], relative)
        kinds = {n: K.kind(seen[n], given, max((settles.get(n) or {}).values(), default=0), before=seen.get(n // 4), n=n)
                 for n in sizes}
        tracks: dict[str, dict[int, bool]] = defaultdict(dict)
        for n in sizes:
            for name, chain in seen[n].items():
                if chain.get("mean_degree") is not None:
                    tracks[name][n] = K.still(name, chain, given)
        deep_twin = {"sizes": max((settles.get(sizes[-1]) or {}).values(), default=0),
                     "probes": settles.get(sizes[-1]) or {},
                     "score_points": (twin.get(sizes[-1]) or {}).get("probes") or {}}
        score = {"score": found["score"], "by": found["by"], "chain": found["chain"], "to_n": found["to_n"],
                 "kept_score": L.score(*score_list.chains_of_report(entry["raw"]), references={})["score"]}
        laws[law] = {"campaign": entry["campaign"], "decision": entry["decision"], "kinds": kinds, "twin": deep_twin,
                     "score": score,
                     "deepest": sizes[-1], "kind": kinds[sizes[-1]], "views": seen, "tracks": dict(tracks)}
    tally = Counter(law["kind"] for law in laws.values())
    shown = {k: [law_id for law_id, law in sorted(laws.items(), key=lambda kv: (-kv[1]["deepest"], kv[0]))
                 if law["kind"] == k][:SHOWN] for k in tally}
    out = {"contract": CONTRACT, "catalogue": K.CONTRACT, "bundle": Path(root).name, "rule": given,
           "laws": len(laws), "controls": held_back, "kinds": {k: tally[k] for k in K.kinds() if tally[k]}, "examples": shown,
           "deepest_sizes": dict(sorted(Counter(law["deepest"] for law in laws.values()).items())),
           "early": {str(n): early_table(laws, n) for n in EARLY}, "chains": chain_stills(laws, given),
           "twins": {"settled": {law_id: law["twin"] for law_id, law in sorted(laws.items())
                                 if law["twin"]["sizes"] >= given["twin_settled_at_least"]},
                     "settling": {law_id: law["twin"] for law_id, law in sorted(laws.items())
                                  if 2 <= law["twin"]["sizes"] < given["twin_settled_at_least"]}},
           "by_law": {law_id: {"kind": law["kind"], "deepest": law["deepest"],
                               "kinds": {str(n): k for n, k in law["kinds"].items()}}
                      for law_id, law in laws.items()}}
    if scores:
        out["score"] = scores_in_force(laws)
    return out


def render(found: dict) -> str:
    names = K.names()
    lines = [f"# The catalogue of behaviours, on {found['bundle']}", "",
             f"{found['laws']} laws placed, each at its deepest size read by report 28; {found['controls']} laws of "
             f"control campaigns left out. {found['rule']['words']}", "",
             "| kind | name | laws at their deepest size | deepest of them |", "|---|---|---|---|"]
    for k, count in found["kinds"].items():
        lines.append(f"| {k} | {names.get(k, k)} | {count:,} | "
                     + ", ".join(f"`{law[:12]}`" for law in found["examples"].get(k, [])) + " |")
    for n, table in found["early"].items():
        lines += ["", f"## Known at {int(n):,}, of the {table['laws']:,} laws read from {DEEP_FROM:,}", "",
                  "Called at this size, and the share that was the same kind at the deepest size (held); each deepest "
                  "kind, and the share already called at this size (caught).", "",
                  "| kind | held | caught |", "|---|---|---|"]
        for k in K.kinds():
            held, caught = table["held"].get(k), table["caught"].get(k)
            if not held and not caught:
                continue
            lines.append(f"| {k} | {'-' if not held else f'{held[0]} of {held[1]}'} | "
                         f"{'-' if not caught else f'{caught[0]} of {caught[1]}'} |")
    twins = found["twins"]
    lines += ["", "## Settled from empty or random", "",
              "A probe on a twin start whose value steps within the score's margin from 4,096 on, by its value alone "
              f"(the score in force's own points beside it): three sizes in a row, {len(twins['settled'])} laws; two "
              f"sizes, the third not read or not settled, {len(twins['settling'])} laws.", ""]
    for label, rows in (("three sizes", twins["settled"]), ("two sizes", twins["settling"])):
        for law, twin in list(rows.items())[:25]:
            lines.append(f"* {label}: `{law[:12]}` " + ", ".join(f"{k} {v} sizes" for k, v in twin["probes"].items())
                         + "; the score in force: " + (", ".join(f"{k} {v} points" for k, v in twin["score_points"].items())
                                                       or "no probe settled"))
    lines += ["", "## Still lattice chains", "", "| size | still, with a deeper size | still at every deeper size | "
              f"still from {DEEP_FROM:,} | of them already still |", "|---|---|---|---|---|"]
    for n, row in found["chains"].items():
        lines.append(f"| {int(n):,} | {row['still_with_a_deeper_size']} | {row['still_at_every_deeper_size']} | "
                     f"{row['still_from_16384']} | {row['of_them_still_already']} |")
    if "score" in found:
        score = found["score"]
        lines += ["", f"## The score in force ({score['score']}), the still lattice scored lowest", "",
                  f"{score['scored']} laws score; {score['still']} of them score {L.FROZEN_SCORE}, their best chain a "
                  "frozen or still lattice. The ten first, beside what each scored with no lattice read as still:", "",
                  "| law | chain | to N | kind | score | no chain still |", "|---|---|---|---|---|---|"]
        for row in score["rows"][:10]:
            lines.append(f"| `{row['law'][:12]}` | {row['chain']} | {int(row['to_n']):,} | {row['kind']} | "
                         f"{row['score']:g} | {row['kept_score']:g} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="every law of a bundle placed in the catalogue of behaviours")
    parser.add_argument("bundle", help="a study's bundle (.tar.zst) or its folder")
    parser.add_argument("--json")
    parser.add_argument("--md")
    parser.add_argument("--no-scores", action="store_true")
    args = parser.parse_args(argv)
    source = Path(args.bundle)
    if source.is_file():
        from read_bundle import scratch_dir, unpacked
        source = unpacked(source, scratch_dir("gsd-catalogue-reading-"))
    found = read(source, scores=not args.no_scores)
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(found), encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
