#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.observability import starts_reading as F  # noqa: E402
from graph_scale_dynamics.observability import two_chains as T  # noqa: E402

CHECK_CONTRACT = "gsd-starts-check-1"
from graph_scale_dynamics.measurements import starts as S  # noqa: E402

CHAINS = tuple((start.name, {S.EMPTY: "empty", S.RANDOM: "given"}.get(start.kind, start.name), start.family)
               for start in S.run())
PROBES = ("d_s", "d_V", "d_B", "d_w")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_graph(n: int, edges, *, seed: int, name: str | None, ended: bool = False) -> dict:
    from graph_scale_dynamics.measurements.curvature_probe import read as curvature
    from graph_scale_dynamics.measurements.structure_census import census
    from graph_scale_dynamics.scaleflow.one_shot import chain_probes
    probes = {} if ended else chain_probes(int(n), edges, seed=int(seed), name=name)
    counted = census(int(n), edges)
    kappa = {} if ended else curvature(int(n), edges)
    out = {"mean_degree": 2.0 * float(counted.get("edges") or 0) / int(n), "energy_per_node": None,
           "triangles_per_node": T._per_node((counted.get("cliques") or {}).get("triangles"), n),
           "squares_per_node": T._per_node(counted.get("squares"), n),
           "giant_fraction": T._per_node((counted.get("largest_component") or {}).get("size"), n),
           "kappa": T._number(kappa.get("mean")) if kappa.get("measured") else None,
           "reach": T._number(probes.get("half_volume_radius")), "ended": bool(ended)}
    for probe in PROBES:
        block = probes.get(probe) or {}
        value = T._number(block.get("value")) if block.get("valid") else None
        refusal = "ENDED_AT_CAP" if ended else (None if value is not None else block.get("refusal"))
        out[probe] = {"value": value, "withheld": None, "refusal": refusal, "read": True}
    return out


NOT_RUN = {**{key: None for key in T.QUANTITIES if key not in PROBES},
           **{probe: {"value": None, "withheld": None, "refusal": None, "read": False} for probe in PROBES},
           "ended": False}


def summary(values: list[dict]) -> dict:
    total = len(values)
    out = {key: (T._probe_summary([v[key] for v in values], total) if key in PROBES
                 else T._summary([v[key] for v in values], total)) for key in T.QUANTITIES}
    out["ended_at_cap"] = {"seeds": sum(1 for v in values if v.get("ended")), "of": total}
    return out


def lattice_edges(family: str, n: int):
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    edges = control_family_edges(family, int(n))
    if edges is None:
        raise SystemExit(f"{family} does not reach N={n}")
    return edges


def _build() -> int | None:
    try:
        return int((ROOT / "BUILD_NUMBER").read_text().strip())
    except (OSError, ValueError):
        return None


def rewired(edges, share: float, seed: int) -> list:
    import random
    rng = random.Random(int(seed))
    edges = [tuple(sorted(e)) for e in edges]
    present = set(edges)
    swaps, done, tries = int(round(share * len(edges) / 2)), 0, 0
    while done < swaps and tries < 100 * max(1, swaps):
        tries += 1
        i, j = rng.randrange(len(edges)), rng.randrange(len(edges))
        (a, b), (c, d) = edges[i], edges[j]
        if rng.random() < 0.5:
            c, d = d, c
        one, two = tuple(sorted((a, c))), tuple(sorted((b, d)))
        if len({a, b, c, d}) < 4 or one in present or two in present:
            continue
        present -= {edges[i], edges[j]}
        present |= {one, two}
        edges[i], edges[j] = one, two
        done += 1
    return edges


def moved_locally(n: int, edges, share: float, seed: int) -> list:
    import random
    rng = random.Random(int(seed))
    adj = {i: set() for i in range(int(n))}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    swaps, done, tries = int(round(share * len(edges) / 2)), 0, 0
    while done < swaps and tries < 200 * max(1, swaps):
        tries += 1
        a = rng.randrange(int(n))
        if not adj[a]:
            continue
        b = rng.choice(sorted(adj[a]))
        two = sorted({c for x in adj[a] for c in adj[x]} - adj[a] - {a})
        if not two:
            continue
        c = rng.choice(two)
        ends = sorted(adj[c] - {a, b} - adj[b])
        if not ends:
            continue
        d = rng.choice(ends)
        adj[a].discard(b), adj[b].discard(a), adj[c].discard(d), adj[d].discard(c)
        adj[a].add(c), adj[c].add(a), adj[b].add(d), adj[d].add(b)
        done += 1
    return sorted({tuple(sorted((u, v))) for u in adj for v in adj[u]})


def graph_for(spec: str, n: int, seed: int, index: int):
    from graph_scale_dynamics.measurements import random_starts
    from graph_scale_dynamics.measurements.random_starts import _random_wiring
    kind, _, what = spec.partition(":")
    stream = 1000 * (int(seed) + 1) + int(index)
    if kind == "lattice":
        return lattice_edges(F.NAMED[what], n)
    if kind == "random":
        return random_starts.build(int(n), float(what), 1000 * int(seed) + int(index))
    if kind == "melted":
        return _random_wiring(int(n), lattice_edges(F.NAMED[what], n), seed=stream)
    if kind in ("local", "rewired"):
        name, _, share = what.partition(":")
        base = lattice_edges(F.NAMED[name], n)
        return (moved_locally(int(n), base, float(share), stream) if kind == "local"
                else rewired(base, float(share), stream))
    if kind == "empty":
        return []
    if kind == "capped":
        return (random_starts.build(int(n), float(what), 1000 * int(seed) + int(index)), "ended")
    if kind == "skipped":
        return None
    raise SystemExit(f"a case's graph is lattice:, random:, melted:, local:, rewired:, empty, capped: or skipped, "
                     f"not {spec!r}")


def case_chains(case: dict, sizes: list[int], seeds: int, cache: dict, first_seed: int = 0) -> dict:
    rungs = []
    for n in sizes:
        rung = {"n": n, "seeds": seeds, "ends": {"completed": seeds}}
        for index, (name, key, _family) in enumerate(CHAINS):
            spec = ((case.get("at") or {}).get(str(n)) or {}).get(name) or case["chains"][name]
            values = []
            for s in range(int(first_seed), int(first_seed) + seeds):
                cached = (spec, n, s, name)
                if cached not in cache:
                    made = graph_for(spec, n, s, index)
                    if made is None:
                        cache[cached] = dict(NOT_RUN)
                    elif isinstance(made, tuple):
                        cache[cached] = read_graph(n, made[0], seed=s, name=name, ended=True)
                    else:
                        cache[cached] = read_graph(n, made, seed=s, name=name)
                values.append(cache[cached])
            if key in ("empty", "given"):
                rung[key] = summary(values)
            else:
                rung.setdefault("more_given", {})[key] = summary(values)
        rungs.append(rung)
    every = [{"name": name, "key": key, "start": family} for name, key, family in CHAINS]
    return {"rungs": rungs, "every_chain": every}


def expected_at(case: dict, n: int) -> dict:
    return ((case.get("expect_at") or {}).get(str(n))) or case["expect"]


def judge_law(reading: dict, expect: dict | None) -> list[str]:
    failures = []
    if not expect:
        return failures
    if "class" in expect and reading["class"] != expect["class"]:
        failures.append(f"the law reads {reading['class']}, expected {expect['class']}")
    if "at_n" in expect and reading.get("at_n") != expect["at_n"]:
        failures.append(f"the law is read at N={reading.get('at_n')}, expected N={expect['at_n']}")
    return failures


def judge_rung(rung: dict, expect: dict) -> list[str]:
    failures = []
    if rung["class"] != expect["class"]:
        failures.append(f"class {rung['class']}, expected {expect['class']}")
    for name, allowed in (expect.get("fates") or {}).items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        fate = (rung["fates"].get(name) or {}).get("fate")
        if fate not in allowed:
            failures.append(f"{name} {fate}, expected {' or '.join(allowed)}")
    count = len(rung["groups"])
    if "groups" in expect and count != int(expect["groups"]):
        failures.append(f"{count} groups, expected {expect['groups']}")
    if "groups_at_least" in expect and count < int(expect["groups_at_least"]):
        failures.append(f"{count} groups, expected at least {expect['groups_at_least']}")
    for together in expect.get("together") or []:
        if not any(set(together) <= set(group) for group in rung["groups"]):
            failures.append(f"{' and '.join(together)} not in one group")
    return failures


def space_score_on_the_starts(refs: dict) -> dict:
    from graph_scale_dynamics.observability import space_score
    out = {}
    for family, by_n in refs.items():
        rungs = [{"n": int(n), "empty": ref["start"]} for n, ref in sorted(by_n.items())]
        reading = space_score.chain_reading(rungs, "empty")
        out[family] = {"d": reading["d"], "space": reading["space"],
                       "rungs": [[r["n"], r["distance"], r["worst"]] for r in reading["rungs"]]}
    return out


def criterion_of(path: Path) -> dict:
    from graph_scale_dynamics.resources import committed
    return committed.read(path)


def references_of(table: Path | None) -> dict:
    if table is None:
        return F.table_references()
    return F.references_from(json.loads(table.read_text(encoding="utf-8")))


def check(criterion_path: Path, out: Path | None, *, first_seed: int = 0, sizes: list[int] | None = None,
          before: list | None = None, table: Path | None = None) -> dict:
    criterion = criterion_of(criterion_path)
    refs = references_of(table)
    if not refs:
        raise SystemExit("no references: the calibration table holds no current cell of a lattice start with its "
                         "reading as a start; a fleet measures them with its table at its first start "
                         "(`python3 main.py run`), and --table names another table")
    held_out = bool(first_seed) or sizes is not None
    sizes = [int(n) for n in (sizes or criterion["sizes"])]
    seeds = int(criterion["seeds"])
    cache: dict = {}
    result = {"contract": CHECK_CONTRACT, "written_utc": _utc(), "build": _build(),
              "criterion": {"path": criterion_path.relative_to(ROOT).as_posix() if criterion_path.is_absolute()
                            and ROOT in criterion_path.parents else str(criterion_path),
                            "sha256": hashlib.sha256(criterion_path.read_bytes()).hexdigest()},
              "references_sha256": hashlib.sha256(json.dumps(refs, sort_keys=True).encode("utf-8")).hexdigest(),
              "references_from": "the calibration table's cells of the lattice starts" if table is None else str(table),
              "reading_contract": F.CONTRACT, "rule": F.rule(), "first_seed": int(first_seed), "sizes": sizes,
              "held_out": held_out, "cases": []}
    if before is not None:
        result["runs_before"] = before
    for case in criterion["cases"]:
        started = time.monotonic()
        case_sizes = [n for n in sizes if not case.get("sizes") or n in case["sizes"] or held_out]
        reading = F.law_reading(case_chains(case, case_sizes, seeds, cache, first_seed), references=refs)
        rows, passed = {}, True
        for rung in reading["rungs"]:
            failures = judge_rung(rung, expected_at(case, rung["n"]))
            passed = passed and not failures
            rows[str(rung["n"])] = {
                "class": rung["class"], "groups": rung["groups"], "spread": rung["spread"],
                "fates": {name: [f.get("fate"), f.get("kept"), f.get("degree_moved")]
                          for name, f in rung["fates"].items()},
                "distances": rung["distances"], "worst": rung["worst"], "failures": failures}
        law = {"class": reading["class"], "at_n": reading.get("at_n"), "top_dense": reading.get("top_dense"),
               "failures": judge_law(reading, case.get("law"))}
        passed = passed and not law["failures"] and len(rows) == len(case_sizes)
        result["cases"].append({"id": case["id"], "name": case["name"], "passed": passed, "sizes": rows,
                                "law": law})
        print(f"{case['id']} {case['name']}: {'passed' if passed else 'MISSED'}  [{time.monotonic() - started:.1f} s]",
              flush=True)
        for n, row in rows.items():
            fates = ", ".join(f"{name} {v[0]} (kept {v[1]})" for name, v in row["fates"].items())
            print(f"    N={n}: {row['class']}; groups {row['groups']}; {fates}"
                  + (f"; MISSED: {'; '.join(row['failures'])}" if row["failures"] else ""), flush=True)
        print(f"    the law: {law['class']} at N={law['at_n']}"
              + (f"; MISSED: {'; '.join(law['failures'])}" if law["failures"] else ""), flush=True)
    result["passed"] = all(c["passed"] for c in result["cases"])
    result["space_score_on_the_starts"] = space_score_on_the_starts(refs)
    for family, reading in result["space_score_on_the_starts"].items():
        print(f"space score on the exact {family}: d {reading['d']}, a space {reading['space']}, "
              + ", ".join(f"{n}: {d} ({w})" for n, d, w in reading["rungs"]), flush=True)
    if out is not None:
        out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/starts_check.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("check", help="read the criterion's cases and judge them")
    run.add_argument("--judge", type=Path, default=ROOT / "graph_scale_dynamics" / "resources" / "readings" / "starts_known_answers_criterion.json")
    run.add_argument("--out", type=Path)
    run.add_argument("--first-seed", type=int, default=0, help="read every graph on seeds from this one (held out)")
    run.add_argument("--sizes", help="sizes other than the criterion's (held out)")
    run.add_argument("--before", type=Path, help="a JSON list of this criterion's runs before this one")
    run.add_argument("--table", type=Path, help="a calibration table other than this folder's, for its references")
    args = parser.parse_args(argv)
    sizes = [int(n) for n in str(args.sizes).split(",") if n.strip()] if args.sizes else None
    before = json.loads(args.before.read_text(encoding="utf-8")) if args.before else None
    return 0 if check(args.judge, args.out, first_seed=args.first_seed, sizes=sizes, before=before,
                      table=args.table)["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
