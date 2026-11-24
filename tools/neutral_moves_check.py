#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.measurements import starts as the_starts  # noqa: E402

CONTRACT = "gsd-neutral-moves-run-1"
JUDGEMENT = "gsd-neutral-moves-judgement-1"
GRADIENT = "degree_neighbor_gradient"
MEAN_DEGREE_CAP = 16.0
POINTS = 20
KEPT_FATES = ("holds", "unmoved")
LATTICES = tuple(start.name for start in the_starts.known_lattices())


def law_spec(compact: dict, candidate_id: str | None = None) -> dict:
    from law_rows import spec_of

    from graph_scale_dynamics.dsl.dsl import fingerprint
    spec = spec_of(compact)
    if candidate_id is not None and fingerprint(spec) != candidate_id:
        raise ValueError(f"{candidate_id[:12]}: report 28's compact spec does not rebuild the law")
    return spec


def variant(spec: dict, name: str) -> dict:
    if name == "drawn":
        return spec
    if name == "no_gradient":
        return dict(spec, terms=[t for t in spec["terms"] if t["op"] != GRADIENT])
    raise ValueError(f"no variant {name!r}")


def chain(spec: dict, lattice: str, n: int, multiplier: int, seed: int, shift: float | None) -> dict:
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    from graph_scale_dynamics.observability.starts_reading import NAMED
    from graph_scale_dynamics.services.worker.engine_rs import init_declared, rust_chain_runner
    node_terms, empty_energy, apply_edge = E._energy_model(spec, n)
    dynamics, settings = spec["dynamics"], E._law_dynamics(spec, 0.0)
    mix = dynamics["move_mix"]
    ctx = E.ChainContext(
        n=n, total_moves=int(dynamics["sweeps"]) * int(multiplier) * n, mean_degree_cap=MEAN_DEGREE_CAP,
        proposal_locality=0.0, apply_edge=apply_edge, locality=settings["locality"],
        zero_temperature=settings["zero_temperature"],
        p_add=mix["add"], p_del=mix["delete"], p_swap=mix["swap"], beta=float(dynamics["beta"]),
        max_edges=n * (n - 1) // 2, candidate_spec=spec, deadline_monotonic=None,
        spec_ops={t["op"] for t in spec["terms"]}, node_terms=node_terms, restore_deadline_monotonic=None)
    state = E.GraphState(n)
    state.require_ops(ctx.spec_ops)
    state, start_energy = init_declared(ctx, control_family_edges(NAMED[lattice], n, seed=0), state, empty_energy)
    start_edges = sorted(state.edge_list)
    energy = start_energy if shift is None else float(start_energy) + float(shift)
    started = time.monotonic()
    final, end_energy, _trajectory, attempted, proposed, accepted, _snapshots, _peak, termination = rust_chain_runner(
        ctx, random.Random(seed), state, energy, POINTS, enforce_limits=True)
    return {"start_energy": start_energy, "end_energy_less_start": float(end_energy) - float(energy),
            "attempted": dict(attempted), "proposed": dict(proposed), "accepted": dict(accepted),
            "termination": (termination or {}).get("reason"), "seconds": round(time.monotonic() - started, 2),
            "start_edges": start_edges, "final_edges": sorted(final.edge_list)}


def read(lattice: str, n: int, ran: dict, references: dict) -> dict:
    from graph_scale_dynamics.observability import starts_reading as F
    from graph_scale_dynamics.research import reach as G
    start = {tuple(e) for e in ran["start_edges"]}
    final = {tuple(e) for e in ran["final_edges"]}
    mean_degree = 2 * len(final) / n
    reach = G.half_volume_radius(n, sorted(final))
    ref = (references.get(F.NAMED[lattice]) or {}).get(int(n)) or {}
    at_start = ref.get("start") or {}
    share = G.kept(reach, ref.get("random_reach"), (at_start.get("reach") or {}).get("mean"))
    start_degree = (at_start.get("mean_degree") or {}).get("mean")
    moved = abs(mean_degree - start_degree) / start_degree if start_degree else None
    if ran["termination"] == "mean_degree_cap":
        fate = "dense"
    elif reach is None:
        fate = "fell_apart"
    elif share is None:
        fate = None
    elif share < F.KEPT_AT_LEAST:
        fate = "melted"
    elif share < F.KEPT_HOLDS:
        fate = "partly"
    elif share > F.KEPT_AT_MOST:
        fate = "stretched"
    elif moved is not None and moved > F.DEGREE_WITHIN:
        fate = "changed"
    elif final == start:
        fate = "unmoved"
    else:
        fate = "holds"
    swaps = int(ran["proposed"].get("swap") or 0)
    return {"start_energy": ran["start_energy"], "end_energy_less_start": round(ran["end_energy_less_start"], 9),
            "accepted": ran["accepted"], "proposed_swaps": swaps,
            "swaps_taken_share": round(int(ran["accepted"].get("swap") or 0) / swaps, 6) if swaps else None,
            "start_edges_left": round(len(final & start) / len(start), 6) if start else None,
            "mean_degree": round(mean_degree, 4), "reach": reach, "kept": share, "fate": fate,
            "termination": ran["termination"], "seconds": ran["seconds"]}


def select(rows: list[dict], laws: dict, *, named: str, degree_only: int = 2, cap_n: int = 16384) -> list[dict]:
    from law_rows import anchor_degrees
    by_id = {r["law"]: r for r in rows}
    out = []
    for law, record in sorted(laws.items()):
        row = by_id.get(law)
        held = sorted(k for k, v in (record.get("fates") or {}).items() if v == "holds")
        if row is None or not held:
            continue
        spec = row.get("spec") or {}
        zero = bool(spec.get("zero_temperature"))
        gradient = any(t[0] == GRADIENT and float(t[2]) > 0 for t in spec.get("terms") or [])
        if law.startswith(named):
            kind, sizes = "named", [4096, 16384]
        else:
            kind, sizes = ("zero" if zero else "finite"), [min(int(record["at_n"]), cap_n)]
        out.append({"law": law, "campaign": row["campaign"], "set": kind, "kind": row.get("kind"),
                    "zero_temperature": zero, "lattices": held, "sizes": sizes,
                    "variants": ["no_gradient"] if gradient and zero else [],
                    "fleet": {"at_n": record.get("at_n"), "class": record.get("class"), "fates": record.get("fates")},
                    "spec": spec})
    chosen = [(r, start.name) for r in sorted(rows, key=lambda r: r["law"]) for start in the_starts.lattices_run()
              if r.get("kind") == "degree sequence only" and (r.get("spec") or {}).get("zero_temperature")
              and start.neighbours in anchor_degrees(r)
              and (laws.get(r["law"]) or {}).get("fates", {}).get(start.name) == "melted"]
    for row, lattice in chosen[:degree_only]:
        record = laws[row["law"]]
        out.append({"law": row["law"], "campaign": row["campaign"], "set": "degree_only", "kind": row.get("kind"),
                    "zero_temperature": True, "lattices": [lattice], "sizes": [4096, 16384], "variants": [],
                    "fleet": {"at_n": record.get("at_n"), "class": record.get("class"), "fates": record.get("fates")},
                    "spec": row.get("spec") or {}})
    return out


def neutral_share(spec: dict, lattice: str, n: int, samples: int, seed: int) -> dict:
    from graph_scale_dynamics.dsl.dsl import coefficient
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    from graph_scale_dynamics.observability.starts_reading import NAMED
    ops = {t["op"] for t in spec["terms"]} - set(E._NODE_FUNCTIONALS)
    weight = {}
    for t in spec["terms"]:
        if t["op"] in ops:
            weight[t["op"]] = weight.get(t["op"], 0.0) + coefficient(t, n)
    state = E.GraphState(n)
    state.require_ops({t["op"] for t in spec["terms"]})
    for u, v in control_family_edges(NAMED[lattice], n, seed=0):
        if v not in state.adj[u]:
            state.apply(u, v, True, state.op_deltas(u, v, True))
    rng = random.Random(seed)
    edges = sorted(state.edges)
    counts = {"sampled": 0, "neutral": 0, "raise": 0, "lower": 0}
    while counts["sampled"] < samples:
        i = rng.randrange(len(edges))
        j = rng.randrange(len(edges) - 1)
        j += j >= i
        (a, b), (c, d) = edges[i], edges[j]
        if len({a, b, c, d}) != 4:
            continue
        if rng.random() < 0.5:
            n1, n2 = state._edge(a, c), state._edge(b, d)
        else:
            n1, n2 = state._edge(a, d), state._edge(b, c)
        if n1 == n2 or n1 in state.edges or n2 in state.edges:
            continue
        total = dict.fromkeys(ops, 0.0)
        done = []
        for (x, y), adding in (((a, b), False), ((c, d), False), (n1, True), (n2, True)):
            deltas = state.op_deltas(x, y, adding)
            state.apply(x, y, adding, deltas)
            done.append(((x, y), adding))
            for op in ops:
                total[op] += deltas[op]
        for (x, y), adding in reversed(done):
            state.apply(x, y, not adding, state.op_deltas(x, y, not adding))
        counts["sampled"] += 1
        change = sum(weight[op] * total[op] for op in ops)
        if all(total[op] == 0 for op in ops):
            counts["neutral"] += 1
        elif change > 0:
            counts["raise"] += 1
        else:
            counts["lower"] += 1
    return dict(counts, share=round(counts["neutral"] / counts["sampled"], 4))


def cells(criterion: dict) -> list[dict]:
    out = []
    shifts = [float(s) for s in criterion["chain"]["shifts"]]
    for entry in criterion["laws"]:
        for lattice in entry["lattices"]:
            for n in entry["sizes"]:
                for name in ["drawn", *entry.get("variants", [])]:
                    for shift in [None, *(shifts if name == "drawn" else [])]:
                        for seed in criterion["chain"]["seeds"]:
                            out.append({"law": entry["law"], "set": entry["set"],
                                        "zero_temperature": bool(entry["zero_temperature"]), "lattice": lattice,
                                        "n": int(n), "variant": name, "shift": shift, "seed": int(seed)})
    return out


def _run_cell(args: tuple) -> dict:
    cell, compact, law, multiplier, samples = args
    from graph_scale_dynamics.observability.starts_reading import table_references
    spec = variant(law_spec(compact, law), cell["variant"])
    ran = chain(spec, cell["lattice"], cell["n"], multiplier, cell["seed"], cell["shift"])
    row = dict(cell, law=law[:12], **read(cell["lattice"], cell["n"], ran, table_references()))
    if cell["shift"] is None:
        row["swaps_at_the_start"] = neutral_share(spec, cell["lattice"], cell["n"], samples, cell["seed"])
    return row


def run(criterion: dict, workers: int = 1, progress=None) -> dict:
    by_law = {entry["law"]: entry for entry in criterion["laws"]}
    multipliers = {int(k): int(v) for k, v in criterion["chain"]["multiplier"].items()}
    samples = int(criterion["chain"]["neutral_samples"])
    tasks = [(cell, by_law[cell["law"]]["spec"], cell["law"], multipliers[cell["n"]], samples)
             for cell in cells(criterion)]
    made = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.monotonic()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = []
            for row in pool.map(_run_cell, tasks):
                rows.append(row)
                if progress:
                    progress(len(rows), len(tasks), row)
    else:
        rows = []
        for task in tasks:
            rows.append(_run_cell(task))
            if progress:
                progress(len(rows), len(tasks), rows[-1])
    return {"contract": CONTRACT, "criterion": criterion["contract"], "criterion_committed_utc": criterion.get(
        "committed_utc"), "made_utc": made, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chain": criterion["chain"], "rows": rows, "seconds": round(time.monotonic() - started, 1)}


def _key(row: dict) -> tuple:
    return (row["law"][:12], row["lattice"], int(row["n"]), row["variant"], int(row["seed"]))


def groups(rows: list[dict]) -> dict:
    out: dict = {}
    for row in rows:
        out.setdefault(_key(row), {})["fleet" if row["shift"] is None else float(row["shift"])] = row
    return out


def _kept(row: dict | None) -> bool | None:
    return None if row is None or row.get("fate") is None else row["fate"] in KEPT_FATES


def turns(group: dict) -> bool | None:
    fleet = _kept(group.get("fleet"))
    others = [_kept(r) for k, r in group.items() if k != "fleet"]
    if fleet is None or not others or any(o is None for o in others):
        return None
    return any(o != fleet for o in others)


def _share(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _neutral(group: dict) -> float | None:
    return ((group.get("fleet") or {}).get("swaps_at_the_start") or {}).get("share")


def _matches(rule: dict, key: tuple, group: dict) -> bool:
    first = group.get("fleet") or next(iter(group.values()))
    neutral = _neutral(group)
    return ((not rule.get("sets") or first["set"] in rule["sets"])
            and (not rule.get("law") or key[0] == rule["law"][:12])
            and (not rule.get("n") or key[2] == int(rule["n"]))
            and rule.get("variant", "drawn") in ("*", key[3])
            and ("zero_temperature" not in rule or bool(first["zero_temperature"]) == bool(rule["zero_temperature"]))
            and ("neutral_at_least" not in rule or (neutral is not None and neutral >= rule["neutral_at_least"]))
            and ("neutral_at_most" not in rule or (neutral is not None and neutral <= rule["neutral_at_most"]))
            and (not rule.get("proposes_swaps") or int((group.get("fleet") or {}).get("proposed_swaps") or 0) > 0))


def judge(criterion: dict, run_result: dict) -> dict:
    by = groups(run_result["rows"])
    out = []
    for p in criterion["predictions"]:
        rule = p["rule"]
        kind = rule["kind"]
        chosen = [(k, g) for k, g in sorted(by.items(), key=lambda kv: kv[0]) if _matches(rule, k, g)]
        counted = len(chosen)
        if kind == "fleet_fate":
            fates = [g["fleet"]["fate"] for _, g in chosen if "fleet" in g]
            ok = bool(fates) and all(f in rule["fates"] for f in fates)
            read_as = {"fates": fates}
        elif kind == "fleet_swaps_taken_at_most":
            shares = [g["fleet"]["swaps_taken_share"] for _, g in chosen if "fleet" in g]
            ok = bool(shares) and all(s is not None and s <= rule["share"] for s in shares)
            read_as = {"swaps_taken_shares": shares}
        elif kind == "every_way_fate":
            fates = [r["fate"] for _, g in chosen for r in g.values()]
            ok = bool(fates) and all(f in rule["fates"] for f in fates)
            read_as = {"fates": fates}
        elif kind == "some_shift_not_kept":
            flags = [any(_kept(r) is False for s, r in g.items() if s != "fleet") for _, g in chosen]
            ok = bool(flags) and all(flags)
            read_as = {"not_kept_under_a_shift": flags}
        elif kind in ("turn_share_at_least", "turn_share_at_most"):
            reproduced = [g for _, g in chosen if _kept(g.get("fleet")) is True]
            flags = [t for t in (turns(g) for g in reproduced) if t is not None]
            share = _share(flags)
            counted = len(flags)
            ok = share is not None and (share >= rule["share"] if kind == "turn_share_at_least"
                                        else share <= rule["share"])
            read_as = {"groups": len(chosen), "reproduced": len(reproduced), "turned": sum(flags), "share": share,
                       "turned_laws": sorted({k[0] for k, g in chosen if _kept(g.get("fleet")) is True and turns(g)})}
        elif kind == "no_toggle_taken":
            taken = [int(r["accepted"].get("add") or 0) + int(r["accepted"].get("delete") or 0)
                     for _, g in chosen for r in g.values()]
            ok = bool(taken) and not any(taken)
            read_as = {"toggles_taken": sum(taken), "chains": len(taken)}
        elif kind == "some_way_kept":
            kept = [_kept(r) for _, g in chosen for r in g.values()]
            ok = any(k is True for k in kept)
            read_as = {"kept": sum(k is True for k in kept), "chains": len(kept)}
        elif kind == "variant_not_kept_share_at_least":
            drawn_rule = dict(rule, variant="drawn")
            kept_drawn = {(k[0], k[1], k[2], k[4]) for k, g in by.items()
                          if _matches(drawn_rule, k, g) and _kept(g.get("fleet")) is True}
            flags = [_kept(g.get("fleet")) is False for k, g in sorted(by.items(), key=lambda kv: kv[0])
                     if k[3] == rule["variant"] and (k[0], k[1], k[2], k[4]) in kept_drawn and "fleet" in g]
            share = _share(flags)
            counted = len(flags)
            ok = share is not None and share >= rule["share"]
            read_as = {"held_as_drawn": len(flags), "not_kept_in_the_variant": sum(flags), "share": share}
        else:
            raise ValueError(f"no rule {kind!r}")
        enough = counted >= int(rule.get("needs_at_least") or 1)
        out.append({"id": p["id"], "claim": p["claim"], "counted": counted, "read": read_as,
                    "verdict": ("held" if ok else "missed") if enough else "nothing to measure"})
    return {"contract": JUDGEMENT, "criterion": criterion["contract"], "run": run_result.get("contract"),
            "predictions": out}


def neutral_class(share: float | None) -> str | None:
    if share is None:
        return None
    return "neutral" if share >= 0.9 else "changes" if share <= 0.01 else "between"


def summary(rows: list[dict]) -> dict:
    table: dict = {}
    by_law: dict = {}
    for key, group in sorted(groups(rows).items(), key=lambda kv: kv[0]):
        if key[3] != "drawn" or "fleet" not in group:
            continue
        fleet = group["fleet"]
        kind = neutral_class((fleet.get("swaps_at_the_start") or {}).get("share"))
        cell = table.setdefault(f"{fleet['set']}, {'zero' if fleet['zero_temperature'] else 'finite'}, {kind}",
                                {"groups": 0, "fleet_kept": 0, "every_way_kept": 0, "none_kept": 0,
                                 "a_shift_changes": 0, "same_moves": 0})
        kept = [_kept(r) for r in group.values()]
        cell["groups"] += 1
        cell["fleet_kept"] += _kept(fleet) is True
        cell["every_way_kept"] += all(k is True for k in kept)
        cell["none_kept"] += all(k is False for k in kept)
        cell["a_shift_changes"] += len(set(kept)) > 1
        cell["same_moves"] += len({(json.dumps(r["accepted"], sort_keys=True), r["proposed_swaps"],
                                    r["start_edges_left"]) for r in group.values()}) == 1
        if fleet["set"] in ("zero", "finite", "named"):
            by_law.setdefault(key[0], set()).add(kind)
    return {"groups": table,
            "holders": {"laws": len(by_law),
                        "a_lattice_whose_swaps_change_their_terms": sum("changes" in k for k in by_law.values()),
                        "only_lattices_whose_swaps_change_nothing": sum(k == {"neutral"} for k in by_law.values())}}


def scorers(run_result: dict, scores: list[dict], laws: dict, specs: dict, samples: int = 1000,
            seed: int = 101) -> list[dict]:
    by = {}
    for key, group in groups(run_result["rows"]).items():
        if key[3] == "drawn" and "fleet" in group:
            by.setdefault((key[0], key[1]), []).append(group)
    out = []
    for s in sorted(scores, key=lambda s: (-int(s["score"]), s["law"])):
        law, chain = s["law"], s["chain"]
        record = laws.get(law) or {}
        found = by.get((law[:12], chain))
        if found:
            group = max(found, key=lambda g: int(g["fleet"]["n"]))
            kept = [_kept(r) for r in group.values()]
            share = group["fleet"]["swaps_at_the_start"]["share"]
            ran = ("kept under every start energy" if all(kept) else "kept under none" if not any(kept)
                   else "changed with the shift")
        else:
            n = min(int(record.get("at_n") or 16384), 16384)
            share = neutral_share(law_spec(specs[law], law), chain, n, samples, seed)["share"]
            ran = "not run: its fate there is " + str((record.get("fates") or {}).get(chain))
        out.append({"law": law[:12], "score": s["score"], "chain": chain, "to_n": s.get("to_n"),
                    "zero_temperature": bool((specs[law] or {}).get("zero_temperature")), "neutral_share": share,
                    "swaps": neutral_class(share), "run": ran})
    return out


MARK = "gsd-holds-marked-1"
LABELS = {"blind": "no term of the law sees its swaps", "resists": "its swaps raise the law's energy",
          "drives": "its swaps lower the law's energy", "between": "some of its swaps change nothing"}


def label(share: dict) -> str:
    kind = neutral_class(share["share"])
    if kind == "neutral":
        return "blind"
    if kind == "changes":
        return "resists" if share["raise"] >= share["lower"] else "drives"
    return "between"


def bundle_scores(root: Path) -> list[dict]:
    from law_rows import body as report_28, campaigns
    found = []
    for record in campaigns(root):
        body = report_28(root / str(record.get("bundle") or ""))
        for law, chain in ((body.get("every_chain") or {}).get("laws") or {}).items():
            score = chain.get("score") or {}
            if (score.get("score") or 0) > 0:
                found.append({"law": law, **{k: score.get(k) for k in ("score", "by", "chain", "to_n")}})
        del body
    return found


def mark(laws: dict, specs: dict, scores: list[dict], *, bundle: str | None = None, samples: int = 1000,
         seed: int = 101, cap_n: int = 16384) -> dict:
    holds, scored = [], []
    for law, record in sorted(laws.items()):
        held = sorted(k for k, v in (record.get("fates") or {}).items() if v == "holds")
        if not held or law not in specs:
            continue
        spec = law_spec(specs[law], law)
        n = min(int(record.get("at_n") or cap_n), cap_n)
        for lattice in held:
            share = neutral_share(spec, lattice, n, samples, seed)
            holds.append({"law": law[:12], "lattice": lattice, "n": n, "at_n": record.get("at_n"),
                          "zero_temperature": bool(specs[law].get("zero_temperature")), "neutral_share": share,
                          "label": label(share)})
    for s in sorted(scores, key=lambda s: (-int(s["score"]), s["law"])):
        law, chain = s["law"], s["chain"]
        if law not in specs or chain not in LATTICES:
            continue
        record = laws.get(law) or {}
        n = min(int(record.get("at_n") or cap_n), cap_n)
        share = neutral_share(law_spec(specs[law], law), chain, n, samples, seed)
        scored.append({"law": law[:12], "score": s["score"], "chain": chain, "to_n": s.get("to_n"), "n": n,
                       "zero_temperature": bool(specs[law].get("zero_temperature")),
                       "fate_there": (record.get("fates") or {}).get(chain), "neutral_share": share,
                       "label": label(share)})
    by_holder: dict = {}
    for h in holds:
        by_holder.setdefault((h["law"], h["zero_temperature"]), set()).add(h["label"])
    holders = {}
    for (_law, zero), labels in by_holder.items():
        key = "zero" if zero else "finite"
        cell = holders.setdefault(key, {"holders": 0, "a_lattice_it_resists": 0, "only_blind_lattices": 0})
        cell["holders"] += 1
        cell["a_lattice_it_resists"] += "resists" in labels
        cell["only_blind_lattices"] += labels == {"blind"}
    def count(rows: list[dict]) -> dict:
        return {k: sum(r["label"] == k for r in rows) for k in LABELS}
    return {"contract": MARK, "bundle": bundle, "samples": samples, "cap_n": cap_n,
            "holds": holds, "holds_by_label": count(holds), "holders": dict(sorted(holders.items())),
            "scored": scored, "scored_by_label": count(scored)}


def render_marks(result: dict) -> str:
    out = [f"# Every hold, marked by what its law sees, in {result['bundle']}", "",
           f"{MARK} (617). Of {result['samples']:,} swaps the engine would propose at each lattice start, at the size "
           f"its law was read (at most {result['cap_n']:,}), the share that change none of the law's terms. "
           + "; ".join(f"`{k}`: {v}" for k, v in LABELS.items())
           + ". A hold marked `blind` is not the law's: the law cannot keep that lattice's wiring against swaps "
             "(`tools/neutral_moves_check.py`, 615).", "",
           "| holds by label | " + " | ".join(LABELS) + " |", "|---|" + "---:|" * len(LABELS),
           "| holds | " + " | ".join(str(result["holds_by_label"][k]) for k in LABELS) + " |",
           "| scoring laws' lattices | " + " | ".join(str(result["scored_by_label"][k]) for k in LABELS) + " |", ""]
    for key, cell in result["holders"].items():
        out.append(f"Holders at {'zero temperature' if key == 'zero' else 'a finite temperature'}: {cell['holders']}; "
                   f"{cell['a_lattice_it_resists']} hold a lattice whose swaps raise their energy, "
                   f"{cell['only_blind_lattices']} only lattices no term of theirs sees a swap on.")
    out += ["", "## The holds", "",
            "| law | lattice | read at | temperature | change nothing | raise | lower | label |",
            "|---|---|---:|---|---:|---:|---:|---|"]
    out += [f"| `{h['law']}` | {h['lattice']} | {h['n']:,} | {'zero' if h['zero_temperature'] else 'finite'} | "
            f"{h['neutral_share']['share']} | {h['neutral_share']['raise']} | {h['neutral_share']['lower']} | "
            f"{h['label']} |" for h in result["holds"]]
    out += ["", "## The scoring laws' lattices", "",
            "| law | score | lattice | its fate there | temperature | change nothing | label |",
            "|---|---:|---|---|---|---:|---|"]
    out += [f"| `{r['law']}` | {r['score']} | {r['chain']} | {r['fate_there']} | "
            f"{'zero' if r['zero_temperature'] else 'finite'} | {r['neutral_share']['share']} | {r['label']} |"
            for r in result["scored"]]
    return "\n".join(out) + "\n"


def _shift(value) -> str:
    return "fleet" if value is None or value == "fleet" else f"{float(value):+g}"


def render(run_result: dict) -> str:
    rows = run_result["rows"]
    neutral = {_key(r): (r.get("swaps_at_the_start") or {}).get("share") for r in rows if r["shift"] is None}
    out = ["# Is a hold the law's, or the rounding's (615)", "",
           f"{CONTRACT}: {len(rows)} chains in {run_result['seconds']:,} s, each the law's sweeps times the fleet's "
           f"first multiplier ({', '.join(f'{k}: {v}' for k, v in run_result['chain']['multiplier'].items())}) on the "
           "Rust engine, from the start energy the fleet computes (`fleet`) and from it shifted by a constant. "
           "`neutral` is the share of a thousand swaps proposed at the start that change none of the law's terms; "
           "`left` the share of the start's edges still there at the end; `kept` the starts' reading's share.", ""]
    told = summary(rows)
    out += ["## Each law as drawn, by temperature and by what its lattice's swaps change", "",
            "| set, temperature, swaps | groups | the fleet's start keeps | every start keeps | none keeps | "
            "a shift changes | the same moves |", "|---|---:|---:|---:|---:|---:|---:|"]
    out += [f"| {k} | {v['groups']} | {v['fleet_kept']} | {v['every_way_kept']} | {v['none_kept']} | "
            f"{v['a_shift_changes']} | {v['same_moves']} |" for k, v in told["groups"].items()]
    h = told["holders"]
    changing = h["a_lattice_whose_swaps_change_their_terms"]
    out += ["", f"Kept is holds or unmoved. Of the {h['laws']} holders, {changing} "
            "hold a lattice whose swaps change their law's terms and "
            f"{h['only_lattices_whose_swaps_change_nothing']} hold only lattices whose swaps change none of them.", "",
            "## Every chain", "",
            "| law | set | lattice | N | variant | neutral | start energy | swaps taken | left | kept | fate | "
            "other moves taken |", "|---|---|---|---:|---|---:|---|---:|---:|---:|---|---|"]
    for r in rows:
        others = ", ".join(f"{k} {v:,}" for k, v in sorted(r["accepted"].items()) if k != "swap" and v)
        taken = "none proposed" if r["swaps_taken_share"] is None else (
            f"{r['accepted'].get('swap', 0):,} of {r['proposed_swaps']:,}")
        out.append(f"| `{r['law']}` | {r['set']} | {r['lattice']} | {r['n']:,} | {r['variant']} | "
                   f"{neutral.get(_key(r))} | {_shift(r['shift'])} | {taken} | {r['start_edges_left']} | "
                   f"{r['kept']} | {r['fate']} | {others or 'none'} |")
    return "\n".join(out) + "\n"


def render_judgement(result: dict) -> str:
    out = ["# The neutral moves' criterion, judged (615)", "", "| id | claim | counted | read | verdict |",
           "|---|---|---:|---|---|"]
    for p in result["predictions"]:
        out.append(f"| {p['id']} | {p['claim']} | {p['counted']} | {json.dumps(p['read'])[:300]} | {p['verdict']} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/neutral_moves_check.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--criterion", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--md")
    r.add_argument("--workers", type=int, default=1)
    j = sub.add_parser("judge")
    j.add_argument("run")
    j.add_argument("--criterion", required=True)
    j.add_argument("--json")
    j.add_argument("--md")
    c = sub.add_parser("scorers", help="the study's scoring laws beside a run, read after it")
    c.add_argument("run")
    c.add_argument("--bundle", required=True)
    c.add_argument("--laws", required=True)
    c.add_argument("--out", required=True)
    m = sub.add_parser("mark", help="every hold of a bundle, and every scoring law's lattice, by what its law sees")
    m.add_argument("--bundle", required=True, help="the study bundle (.tar.zst) or its unpacked folder")
    m.add_argument("--laws", required=True)
    m.add_argument("--json")
    m.add_argument("--md")
    s = sub.add_parser("select", help="the criterion's laws by its rule, from a bundle and its starts' law file")
    s.add_argument("--bundle", required=True, help="the study's unpacked bundle (the folder with study.json)")
    s.add_argument("--laws", required=True, help="the starts' law file of the same bundle")
    s.add_argument("--named", default="ec7c97587eb5")
    s.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "mark":
        from law_rows import rows as law_rows
        from read_bundle import _unpack
        root = _unpack(Path(args.bundle))
        file = json.loads(Path(args.laws).read_text(encoding="utf-8"))
        result = mark(file["laws"], {r["law"]: r["spec"] for r in law_rows(root)}, bundle_scores(root),
                      bundle=file.get("bundle") or root.name)
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        if args.md:
            Path(args.md).write_text(render_marks(result), encoding="utf-8")
        if not args.json and not args.md:
            print(render_marks(result))
        return 0
    if args.command == "scorers":
        from law_rows import rows as law_rows
        root = Path(args.bundle)
        found = bundle_scores(root)
        specs = {r["law"]: r["spec"] for r in law_rows(root)}
        laws = json.loads(Path(args.laws).read_text(encoding="utf-8"))["laws"]
        result = scorers(json.loads(Path(args.run).read_text(encoding="utf-8")), found, laws, specs)
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        return 0
    if args.command == "select":
        from law_rows import rows as law_rows
        laws = json.loads(Path(args.laws).read_text(encoding="utf-8"))["laws"]
        chosen = select(law_rows(Path(args.bundle)), laws, named=args.named)
        Path(args.out).write_text(json.dumps(chosen, indent=1) + "\n", encoding="utf-8")
        counts: dict = {}
        for entry in chosen:
            counts[entry["set"]] = counts.get(entry["set"], 0) + 1
        print(json.dumps(counts))
        return 0
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    if args.command == "run":
        def progress(done, total, row):
            print(f"{done}/{total} {row['law']} {row['lattice']} {row['n']} {row['variant']} {_shift(row['shift'])}: "
                  f"{row['fate']} ({row['seconds']} s)", flush=True)
        result = run(criterion, args.workers, progress)
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        if args.md:
            Path(args.md).write_text(render(result), encoding="utf-8")
        return 0
    result = judge(criterion, json.loads(Path(args.run).read_text(encoding="utf-8")))
    page = render_judgement(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    if not args.json and not args.md:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
