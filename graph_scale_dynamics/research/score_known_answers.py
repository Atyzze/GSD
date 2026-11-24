from __future__ import annotations

import json
import math
from pathlib import Path

from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
CRITERION = READINGS / "score_known_answers_criterion_3.json"
MEASURED = READINGS / "score_known_answers_3_measured.json"
JUDGED = READINGS / "score_known_answers_3_judged.json"
PAGE = ROOT / committed.DOCS_READINGS / "score_known_answers_3_judged.md"
TABLE = ROOT / "calibration" / "seed_table.json"
HOLDS = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "table_holds.json"
JUDGED_CONTRACT = "gsd-score-known-answers-1"
CRITERION_4 = READINGS / "score_known_answers_criterion_4.json"
CRITERION_5 = READINGS / "score_known_answers_criterion_5.json"
MEASURED_5 = READINGS / "score_known_answers_5_measured.json"
JUDGED_5 = READINGS / "score_known_answers_5_judged.json"
PAGE_5 = ROOT / committed.DOCS_READINGS / "score_known_answers_5_judged.md"
JUDGED_5_CONTRACT = "gsd-score-known-answers-3"
MEASURED_4 = READINGS / "score_known_answers_4_measured.json"
JUDGED_4 = READINGS / "score_known_answers_4_judged.json"
PAGE_4 = ROOT / committed.DOCS_READINGS / "score_known_answers_4_judged.md"
JUDGED_4_CONTRACT = "gsd-score-known-answers-2"
REACH_CONTRACT = "gsd-score-reach-1"
SCORE_4 = "gsd-law-score-7"
SCORE_5 = "gsd-law-score-8"
IN_FORCE_AT_846 = "gsd-law-score-6"
RING_BELOW = 1.5
FLOOR_FROM = 16384
TRIPLES = ((0, 1, 2), (3, 4, 5), (6, 7, 8))
LEVELS = tuple(n for n in L.LADDER if n > L.RELIED_FROM)
FIRST_LEVEL = LEVELS[0]


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def criterion() -> dict:
    return _json(CRITERION)


def rule() -> dict:
    return criterion()["training"]


def _mean_of_reads(values: list) -> tuple[float | None, int]:
    read = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return (sum(read) / len(read) if read else None), len(read)


def _spread_of(values: list) -> float | None:
    read = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if len(read) < 2:
        return 0.0 if read else None
    mean = sum(read) / len(read)
    return math.sqrt(sum((v - mean) ** 2 for v in read) / (len(read) - 1)) / math.sqrt(len(read))


def _side(values: dict[str, list]) -> dict:
    side = {}
    for probe in L.PROBES:
        mean, read = _mean_of_reads(values.get(probe) or [])
        side[probe] = {"mean": mean, "se": 0.0, "seeds": read, "of": len(values.get(probe) or [])}
    for key in ("reach", "giant_fraction"):
        if key in values:
            mean, read = _mean_of_reads(values[key] or [])
            side[key] = {"mean": mean, "se": _spread_of(values[key] or []), "seeds": read, "of": len(values[key] or [])}
    return side


def _value(side: dict, probe: str) -> float | None:
    return L.reading(side.get(probe))


def _held_in_table(holds: dict, family: str, probe: str, n: int) -> bool:
    block = ((holds.get("with_a_dimension") or {}).get(family) or {}).get(probe) or {}
    return int(n) in {int(size) for size, _width in block.get("bands") or []}


def table_cases(table: dict | None = None, holds: dict | None = None) -> dict:
    table = _json(TABLE) if table is None else table
    holds = _json(HOLDS) if holds is None else holds
    families = sorted((holds.get("with_a_dimension") or {}))
    seeds: dict[tuple[str, int], dict[int, dict]] = {}
    for cell in (table.get("cells") or {}).values():
        if cell.get("family") not in families or cell.get("status") != "ok":
            continue
        channels = cell.get("channels") or {}
        seeds.setdefault((cell["family"], int(cell["n"])), {})[int(cell["seed"])] = {
            **{probe: ((channels.get(probe) or {}).get("value") if (channels.get(probe) or {}).get("valid") else None)
               for probe in L.PROBES}, "reach": cell.get("half_volume_radius")}
    out: dict[str, dict] = {}
    for family in families:
        sizes = sorted(n for f, n in seeds if f == family)
        for index, triple in enumerate(TRIPLES):
            at = [n for n in sizes if all(s in seeds[(family, n)] for s in triple)]
            if not at:
                continue
            out.setdefault(family, {})[index] = {
                n: {"side": _side({p: [seeds[(family, n)][s][p] for s in triple] for p in (*L.PROBES, "reach")}),
                    "held": {p: _held_in_table(holds, family, p, n) for p in L.PROBES}} for n in at}
    return out


def _grid_at_least(value: float, grid: list[float]) -> tuple[float, bool]:
    for allowed in grid:
        if value <= allowed + 1e-12:
            return float(allowed), True
    return float(grid[-1]), False


def margins(cases: dict | None = None, rule: dict | None = None) -> dict:
    rule = criterion()["training"] if rule is None else rule
    cases = table_cases() if cases is None else cases
    steps: dict[str, dict[int, list[dict]]] = {p: {lvl: [] for lvl in LEVELS} for p in L.PROBES}
    residuals: list[dict] = []
    for family, triples in sorted(cases.items()):
        for index, by_n in sorted(triples.items()):
            for a, b in L.pairs(by_n):
                for probe in L.PROBES:
                    x, y = _value(by_n[a]["side"], probe), _value(by_n[b]["side"], probe)
                    if x is None or y is None or not (by_n[a]["held"][probe] and by_n[b]["held"][probe]):
                        continue
                    steps[probe][L.level(b)].append({"family": family, "triple": index, "from_n": a, "n": b,
                                                     "step": round(L.step(x, y), 5)})
            for n, entry in sorted(by_n.items()):
                if n < L.RELIED_FROM or not all(entry["held"].values()):
                    continue
                off = L.residual({p: _value(entry["side"], p) for p in L.PROBES})
                if off is not None:
                    residuals.append({"family": family, "triple": index, "n": n, "residual": round(off, 5)})
    relative: dict[str, dict[str, float]] = {}
    above: list[dict] = []
    for probe in L.PROBES:
        chosen: dict[int, float] = {}
        for lvl in LEVELS:
            found = steps[probe][lvl]
            if found:
                worst = max(found, key=lambda s: s["step"])
                chosen[lvl], fits = _grid_at_least(float(rule.get("factor", 1.0)) * worst["step"], rule["margin_grid"])
                above.extend(dict(s, probe=probe) for s in found if s["step"] > chosen[lvl] + 1e-12)
            elif chosen:
                chosen[lvl] = chosen[max(chosen)]
        if not chosen:
            raise ValueError(f"no training step for {probe}")
        lowest = min(chosen)
        for lvl in LEVELS:
            chosen.setdefault(lvl, chosen[lowest])
        relative[probe] = {str(lvl): chosen[lvl] for lvl in LEVELS}
    worst = max(residuals, key=lambda r: r["residual"]) if residuals else None
    if worst is None:
        raise ValueError("no training size holds all four probes")
    tau, _fits = _grid_at_least(worst["residual"], rule["tau_grid"])
    beyond = [r for r in residuals if r["residual"] > tau + 1e-12]
    widest = {probe: {str(lvl): max((s["step"] for s in steps[probe][lvl]), default=None) for lvl in LEVELS}
              for probe in L.PROBES}
    return {"contract": L.MARGINS_CONTRACT,
            "made_by": "python3 tools/score_known_answers.py --write, from the criterion's training rule; never by hand",
            "criterion": CRITERION.relative_to(ROOT).as_posix(),
            "source": {"table": "calibration/seed_table.json", "estimator_fingerprint": _json(TABLE)["estimator_fingerprint"],
                       "holds": "graph_scale_dynamics/resources/calibration/table_holds.json"},
            "relied_from": L.RELIED_FROM, "levels": list(LEVELS), "factor": float(rule.get("factor", 1.0)),
            "relative": relative, "tau": tau,
            "widest_training_step": widest, "widest_training_residual": worst,
            "training_steps": sum(len(v) for p in steps.values() for v in p.values()),
            "training_residuals": len(residuals),
            "does_not_settle": above, "beyond_tau": beyond}


def _as_chain(by_n: dict) -> dict:
    return {"rungs": [{"n": n, "seeds": 3, "empty": entry["side"]} for n, entry in sorted(by_n.items())],
            "every_chain": [{"name": "empty", "key": "empty", "start": "the empty graph"}]}


def judged_cases(rows: list[dict] | None = None, rule: dict | None = None) -> dict:
    rule = criterion() if rule is None else rule
    rows = _json(MEASURED)["rows"] if rows is None else rows
    seeds = rule["seeds"]
    found: dict[tuple[str, int], dict[int, dict]] = {}
    for row in rows:
        if row.get("built"):
            found.setdefault((row["structure"], int(row["size"])), {})[int(row["seed"])] = {
                probe: (row.get("probes") or {}).get(probe, {}).get("value") for probe in L.PROBES}
    out: dict[str, dict] = {}
    for structure in rule["structures"]:
        held = structure.get("held") or {}
        by_n = {}
        for size in structure["sizes"]:
            at = found.get((structure["name"], int(size)))
            if not at or not all(s in at for s in seeds):
                continue
            by_n[int(size)] = {"side": _side({p: [at[s][p] for s in seeds] for p in L.PROBES}),
                               "held": {p: ("refuse" if held.get(p) == "refuse" else
                                            "held" if int(size) in (held.get(p) or []) else "reported")
                                        for p in L.PROBES}}
        if L.pairs(by_n):
            out[structure["name"]] = by_n
    return out


def judge(table: dict, cases: dict | None = None, *, labels: tuple = ("K1", "K2", "K3", "K4"),
          must_read: bool = True) -> dict:
    cases = judged_cases() if cases is None else cases
    one, two, three, four = labels
    misses, rows, reported = [], [], []
    counts = {label: [0, 0] for label in labels}
    for name, by_n in sorted(cases.items()):
        must_refuse_all = all(by_n[n]["held"][p] == "refuse" for n in by_n for p in L.PROBES)
        fifth = []
        for a, b in L.pairs(by_n):
            found = L.points_at(by_n[a]["side"], by_n[b]["side"], b, table)
            rows.append({"structure": name, "from_n": a, "n": b, **found,
                         "held": {p: [by_n[a]["held"][p], by_n[b]["held"][p]] for p in L.PROBES}})
            reads = {p: _value(by_n[a]["side"], p) is not None and _value(by_n[b]["side"], p) is not None
                     for p in L.PROBES}
            for probe in L.PROBES:
                at = (by_n[a]["held"][probe], by_n[b]["held"][probe])
                if at == ("held", "held"):
                    if must_read and not reads[probe]:
                        reported.append({"structure": name, "probe": probe, "from_n": a, "n": b,
                                         "why": "held, and not read at both sizes"})
                        continue
                    counts[one][1] += 1
                    if probe in found["settled"]:
                        counts[one][0] += 1
                    else:
                        misses.append({"prediction": one, "structure": name, "probe": probe, "from_n": a, "n": b,
                                       "step": (found["steps"].get(probe) or {}).get("step"),
                                       "margin": L.margin(probe, b, table)})
                if "refuse" in at:
                    counts[three][1] += 1
                    if probe not in found["settled"]:
                        counts[three][0] += 1
                    else:
                        misses.append({"prediction": three, "structure": name, "probe": probe, "from_n": a, "n": b})
            if all(by_n[a]["held"][p] == by_n[b]["held"][p] == "held" for p in L.PROBES) and (
                    not must_read or all(reads.values())):
                fifth.append(b)
                counts[two][1] += 1
                if found["points"] == L.PAIR_POINTS:
                    counts[two][0] += 1
                else:
                    misses.append({"prediction": two, "structure": name, "from_n": a, "n": b,
                                   "points": found["points"], "residual": found["residual"]})
        if must_refuse_all or fifth:
            steps = L.pairs(by_n)
            at_pairs = [L.points_at(by_n[a]["side"], by_n[b]["side"], b, table)["points"] for a, b in steps]
            top = at_pairs[-1] if at_pairs else None
            counts[four][1] += 1
            ok = (not any(at_pairs)) if must_refuse_all else (top == L.PAIR_POINTS)
            if ok:
                counts[four][0] += 1
            else:
                values = [round(100.0 * L.depth(b) * points / L.PAIR_POINTS, 2)
                          for (_a, b), points in zip(steps, at_pairs, strict=True)]
                misses.append({"prediction": four, "structure": name, "score": int(round(max(values, default=0.0))),
                               "points_at_top": top})
    return {"counts": {k: {"held": v[0], "of": v[1]} for k, v in counts.items()}, "misses": misses,
            "reported": reported, "pairs": rows, "passes": not misses}


def training_reading(cases: dict, table: dict) -> dict:
    first, below = {}, {}
    for family, triples in sorted(cases.items()):
        by_n = triples.get(0) or {}
        for a, b in L.pairs(by_n):
            if L.points_at(by_n[a]["side"], by_n[b]["side"], b, table)["points"] == L.PAIR_POINTS:
                first[family] = b
                break
        relied = [n for n in sorted(by_n) if n >= L.RELIED_FROM]
        under = [n for n in sorted(by_n) if relied and n * L.STEP_AT_LEAST <= relied[0]]
        if relied and under:
            a, b = under[-1], relied[0]
            found = L.points_at(by_n[a]["side"], by_n[b]["side"], b, table)
            below[family] = {"from_n": a, "n": b, "points": found["points"], "settled": found["settled"]}
    return {"first_five_points": first, "under_4096_kept_not_relied_on": below}


def _training(cases: dict, table: dict) -> dict:
    return {"steps": table["training_steps"], "residuals": table["training_residuals"],
            "widest_step": table["widest_training_step"], "widest_residual": table["widest_training_residual"],
            "does_not_settle": table["does_not_settle"], "beyond_tau": table["beyond_tau"],
            **training_reading(cases, table)}


def run(rows: list[dict] | None = None) -> tuple[dict, dict]:
    rule = criterion()
    table = _json(TABLE)
    cases = table_cases(table)
    trained = margins_in_force(cases)
    judged = judge(trained, judged_cases(rows, rule))
    document = {"contract": JUDGED_CONTRACT, "criterion": rule["contract"], "committed_utc": rule["committed_utc"],
                "table": {"file": TABLE.relative_to(ROOT).as_posix(), "estimator_fingerprint": table.get("estimator_fingerprint")},
                "judged_on": f"seeds {rule['seeds'][0]} to {rule['seeds'][-1]}, built and read for it",
                "margins": {k: trained[k] for k in ("relative", "tau")},
                "training": _training(cases, trained), "judged": judged, "passes": judged["passes"]}
    return trained, document


def _counts(judged: dict) -> str:
    return ", ".join(f"{k} {v['held']} of {v['of']}" for k, v in judged["counts"].items())


def _miss(miss: dict) -> str:
    where = f"{miss['from_n']:,} to {miss['n']:,}" if "from_n" in miss else "its top pair"
    if miss["prediction"] == "K1":
        step = "not read at both sizes" if miss.get("step") is None else f"moves {miss['step']:.3g} of itself"
        return f"{miss['structure']}, {miss['probe']} {where}: {step}, {miss['margin']} allowed"
    if miss["prediction"] == "K2":
        return f"{miss['structure']} {where}: {miss['points']} of 5"
    if miss["prediction"] == "K4":
        return f"{miss['structure']}: score {miss['score']}, {miss['points_at_top']} points at its top pair"
    return f"{miss['structure']}, {miss.get('probe', '')} {where}"


def _margins_table(margins: dict) -> list[str]:
    lines = ["| probe | " + " | ".join(f"{n:,}" for n in LEVELS) + " |", "|---|" + "---|" * len(LEVELS)]
    for probe in L.PROBES:
        lines.append(f"| {probe} | " + " | ".join(f"{margins['relative'][probe][str(n)]:g}" for n in LEVELS) + " |")
    return lines + ["", f"The Einstein relation's tolerance tau: {margins['tau']:g} of d_s."]


def render(document: dict) -> str:
    lines = ["# What settles means, on known answers", "",
             f"The score's definitions, committed before they were read: `{document['criterion']}` "
             f"({document['committed_utc']}). "
             "A probe settles at two sizes from 4,096, the larger at least three times the smaller, when its relative "
             "step is within its margin at the larger size; all four agree by the Einstein relation when all four settle "
             "and d_s is within tau of 2 d_V / d_w and of 2 d_B / d_w. Each margin is twice the widest step of the "
             "calibration table's exact lattices and fractals, three seeds a mean, on its grid; tau the smallest value "
             "of its grid above every training residual. "
             f"Trained on `{document['table']['file']}`, estimator {document['table']['estimator_fingerprint']}.", "",
             f"## Judged on {document['judged_on']}", "",
             ("**It passes**" if document["passes"] else "**It does not pass**") + f": {_counts(document['judged'])}. "
             "A held probe that did not read at both sizes is the probes' to judge, reported here, not a miss of the "
             "score.", ""]
    lines += _margins_table(document["margins"]) + [""]
    if document["judged"]["misses"]:
        lines += ["What missed:", ""] + [f"* {_miss(m)}" for m in document["judged"]["misses"]] + [""]
    if document["judged"]["reported"]:
        lines += ["Held and not read at both sizes (reported):", ""]
        lines += [f"* {r['structure']}, {r['probe']} {r['from_n']:,} to {r['n']:,}" for r in document["judged"]["reported"]]
        lines += [""]
    training = document["training"]
    lines += ["## Where each exact structure of the table first reaches five points", "",
              "| family | first pair's larger size |", "|---|---|"]
    lines += [f"| {f} | {n:,} |" for f, n in sorted(training["first_five_points"].items())]
    lines += ["", "No table family failed to settle under the margins its own steps set, and none broke tau "
              f"({len(training['does_not_settle'])} steps above a margin, {len(training['beyond_tau'])} residuals "
              f"above tau, of {training['steps']} steps and {training['residuals']} residuals).", "",
              "## Under 4,096 nodes: kept, not relied on", "",
              "What the pair from about 1,024 to 4,096 would have given each table family under the 16,384 margins:", ""]
    lines += [f"* {f}: {r['points']} of 5 ({', '.join(r['settled']) or 'nothing settles'})"
              for f, r in sorted(training["under_4096_kept_not_relied_on"].items())]
    lines += ["", ("The score reads these margins" if document["passes"] else "The margins are not judged fit")
              + " (`graph_scale_dynamics/resources/calibration/score_margins.json`).", ""]
    return "\n".join(lines)


def criterion_4() -> dict:
    return _json(CRITERION_4)


def reach_excess(side_a: dict, side_b: dict, a: int, b: int, rule: dict) -> dict | None:
    free = dict(rule, q=0.0)
    found = L.scale_at(side_a, side_b, a, b, {"reach": free})
    if found.get("off") is None:
        return None
    expected = math.log(int(b) / int(a)) / float(found["d"])
    return {"from_n": a, "n": b, "excess": round(max(0.0, float(found["off"]) - float(found["allowed"])) / expected, 5),
            "growth_d": found["growth_d"], "d": found["d"], "reach": found["reach"]}


def reach_training(cases: dict | None = None, rule: dict | None = None) -> dict:
    rule = criterion_4()["training"] if rule is None else rule
    cases = table_cases() if cases is None else cases
    pairs, unread = [], []
    for family, triples in sorted(cases.items()):
        for index, by_n in sorted(triples.items()):
            for a, b in L.pairs(by_n):
                found = reach_excess(by_n[a]["side"], by_n[b]["side"], a, b,
                                     {"z": rule["z"], "half_step": rule["half_step"]})
                if found is None:
                    unread.append({"family": family, "triple": index, "from_n": a, "n": b})
                else:
                    pairs.append(dict(found, family=family, triple=index))
    if not pairs:
        raise ValueError("no training pair reads a reach")
    widest = max(pairs, key=lambda r: r["excess"])
    q, fits = _grid_at_least(float(rule["factor"]) * widest["excess"], rule["reach_grid"])
    return {"contract": REACH_CONTRACT, "criterion": CRITERION_4.relative_to(ROOT).as_posix(),
            "q": q, "z": float(rule["z"]), "half_step": float(rule["half_step"]), "factor": float(rule["factor"]),
            "widest_training_excess": widest, "training_pairs": len(pairs), "unread_training_pairs": unread,
            "above_grid": [] if fits else [widest]}


def margins_in_force(cases: dict | None = None) -> dict:
    cases = table_cases() if cases is None else cases
    trained = margins(cases, criterion()["training"])
    trained["reach"] = reach_training(cases)
    return trained


def _sides_of(rows: list[dict], structure: dict, seeds: list) -> dict[int, dict]:
    found: dict[int, dict[int, dict]] = {}
    for row in rows:
        if row.get("built") and row["structure"] == structure["name"]:
            found.setdefault(int(row["n"]), {})[int(row["seed"])] = row
    out = {}
    for n, at in sorted(found.items()):
        if not all(s in at for s in seeds):
            continue
        values = {p: [(at[s].get("probes") or {}).get(p, {}).get("value") for s in seeds] for p in L.PROBES}
        values["reach"] = [at[s].get("reach") for s in seeds]
        values["giant_fraction"] = [(at[s].get("component") or 0) / max(1, int(at[s]["n"])) for s in seeds]
        out[n] = _side(values)
    return out


def _size_of(structure: dict, n: int) -> int:
    for size in structure["sizes"]:
        if structure["build"] != "box":
            continue
        across = 1
        for side in structure["sides"]:
            across *= int(size) if side == "n" else int(side)
        if across == int(n):
            return int(size)
    return int(n)


def judged_cases_4(rows: list[dict] | None = None, rule: dict | None = None) -> dict:
    rule = criterion_4() if rule is None else rule
    rows = _json(MEASURED_4)["rows"] if rows is None else rows
    out: dict[str, dict] = {"structures": {}, "crossovers": {}}
    for key in ("structures", "crossovers"):
        for structure in rule[key]:
            held = structure.get("held") or {}
            by_n = {}
            for n, side in _sides_of(rows, structure, rule["seeds"]).items():
                size = _size_of(structure, n)
                by_n[n] = {"side": side, "held": {p: ("refuse" if held.get(p) == "refuse" else
                                                      "held" if size in (held.get(p) or []) else "reported")
                                                  for p in L.PROBES}}
            out[key][structure["name"]] = by_n
    return out


def scored_pair(by_n: dict, a: int, b: int, table: dict) -> dict:
    side_a, side_b = by_n[a]["side"], by_n[b]["side"]
    found = L.points_at(side_a, side_b, b, table)
    scale = L.scale_at(side_a, side_b, a, b, table)
    connected = L.piece_holds(side_a, a) and L.piece_holds(side_b, b)
    settled = found["settled"] if scale["holds"] and connected else []
    einstein = bool(found["einstein"] and scale["holds"] and connected)
    return {"from_n": a, "n": b, "settled": settled, "einstein": einstein,
            "points": len(settled) + (1 if einstein else 0), "connected": connected, "scale": scale,
            "steps": found["steps"], "residual": found["residual"], "unscaled_points": found["points"],
            "unscaled_settled": found["settled"]}


def judge_4(table: dict, cases: dict | None = None) -> dict:
    cases = judged_cases_4() if cases is None else cases
    rule = criterion_4()
    misses, rows, reported = [], [], []
    counts = {label: [0, 0] for label in ("K1", "K2", "K3", "K4", "S1", "S2", "S3")}
    for name, by_n in sorted(cases["structures"].items()):
        must_refuse_all = all(by_n[n]["held"][p] == "refuse" for n in by_n for p in L.PROBES)
        fifth, at_pairs = [], []
        for a, b in L.pairs(by_n):
            found = scored_pair(by_n, a, b, table)
            at_pairs.append(found["points"])
            rows.append({"structure": name, **found})
            reads = {p: _value(by_n[a]["side"], p) is not None and _value(by_n[b]["side"], p) is not None
                     for p in L.PROBES}
            for probe in L.PROBES:
                at = (by_n[a]["held"][probe], by_n[b]["held"][probe])
                if at == ("held", "held"):
                    if not reads[probe]:
                        reported.append({"structure": name, "probe": probe, "from_n": a, "n": b,
                                         "why": "held, and not read at both sizes"})
                        continue
                    counts["K1"][1] += 1
                    if probe in found["settled"]:
                        counts["K1"][0] += 1
                    else:
                        misses.append({"prediction": "K1", "structure": name, "probe": probe, "from_n": a, "n": b,
                                       "step": (found["steps"].get(probe) or {}).get("step"),
                                       "margin": L.margin(probe, b, table), "scale": found["scale"]})
                if "refuse" in at:
                    counts["K3"][1] += 1
                    if probe not in found["settled"]:
                        counts["K3"][0] += 1
                    else:
                        misses.append({"prediction": "K3", "structure": name, "probe": probe, "from_n": a, "n": b})
            if all(by_n[a]["held"][p] == by_n[b]["held"][p] == "held" for p in L.PROBES) and all(reads.values()):
                fifth.append(b)
                counts["K2"][1] += 1
                if found["points"] == L.PAIR_POINTS:
                    counts["K2"][0] += 1
                else:
                    misses.append({"prediction": "K2", "structure": name, "from_n": a, "n": b,
                                   "points": found["points"], "residual": found["residual"], "scale": found["scale"]})
        if must_refuse_all or fifth:
            counts["K4"][1] += 1
            score = L.score(_as_chain(by_n), references={}, table=table, next_breaks=False)
            top = at_pairs[-1] if at_pairs else None
            ok = (score["score"] == 0) if must_refuse_all else (top == L.PAIR_POINTS)
            if ok:
                counts["K4"][0] += 1
            else:
                misses.append({"prediction": "K4", "structure": name, "score": score["score"], "points_at_top": top})
    for structure in rule["crossovers"]:
        name = structure["name"]
        by_n = cases["crossovers"].get(name) or {}
        for a, b in L.pairs(by_n):
            found = scored_pair(by_n, a, b, table)
            judged = "judged_from_n" in structure and a >= int(structure["judged_from_n"])
            rows.append({"structure": name, "judged": judged, **found})
            if "judged_from_n" in structure:
                if not judged:
                    reported.append({"structure": name, "from_n": a, "n": b, "why": "a pair from a square or a cube",
                                     "points": found["points"], "scale": found["scale"]})
                    continue
                counts["S1"][1] += 1
                if not found["scale"]["holds"] and not found["settled"] and not found["einstein"]:
                    counts["S1"][0] += 1
                else:
                    misses.append({"prediction": "S1", "structure": name, "from_n": a, "n": b,
                                   "points": found["points"], "scale": found["scale"]})
            elif structure["build"] == "subdivided_random_tree":
                counts["S2"][1] += 1
                d_b = found["scale"].get("d")
                if not found["settled"] or (d_b is not None and d_b >= RING_BELOW):
                    counts["S2"][0] += 1
                else:
                    misses.append({"prediction": "S2", "structure": name, "from_n": a, "n": b, "d": d_b,
                                   "settled": found["settled"]})
            elif structure["build"] == "cycle_soup" and b >= FLOOR_FROM:
                counts["S3"][1] += 1
                if found["points"] == 0:
                    counts["S3"][0] += 1
                else:
                    misses.append({"prediction": "S3", "structure": name, "from_n": a, "n": b,
                                   "points": found["points"]})
    empty = [label for label, (_held, of) in counts.items() if of == 0]
    misses += [{"prediction": label, "structure": "none", "why": "no case judged"} for label in empty]
    return {"counts": {k: {"held": v[0], "of": v[1]} for k, v in counts.items()}, "misses": misses,
            "reported": reported, "pairs": rows, "passes": not misses}


def run_4(rows: list[dict] | None = None) -> tuple[dict, dict]:
    rule = criterion_4()
    table = _json(TABLE)
    cases = table_cases(table)
    trained = margins_in_force(cases)
    judged = judge_4(trained, judged_cases_4(rows, rule))
    measured = _json(MEASURED_4) if rows is None else {"seconds": None}
    document = {"contract": JUDGED_4_CONTRACT, "criterion": rule["contract"], "committed_utc": rule["committed_utc"],
                "score": SCORE_4,
                "table": {"file": TABLE.relative_to(ROOT).as_posix(), "estimator_fingerprint": table.get("estimator_fingerprint")},
                "judged_on": f"seeds {rule['seeds'][0]} to {rule['seeds'][-1]}, built and read for it",
                "measured_seconds": measured.get("seconds"),
                "reach": {k: trained["reach"][k] for k in ("q", "z", "half_step", "factor", "widest_training_excess",
                                                         "training_pairs")},
                "judged": judged, "passes": judged["passes"]}
    return trained, document


def _scale_words(scale: dict) -> str:
    if scale.get("growth_d") is None:
        return "no growth of the reach"
    return (f"reach {scale['reach'][0]:g} to {scale['reach'][1]:g}, grows as d {scale['growth_d']:g} against "
            f"d {scale['d']:g} read")


def render_4(document: dict) -> str:
    judged = document["judged"]
    reach = document["reach"]
    lines = ["# The score's scale, its floor and its counted seeds, on known answers", "",
             f"Committed before any crossover was built or read: `{document['criterion']}` ({document['committed_utc']}). "
             f"The score judged is `{document['score']}`. A seed counts only where its chain stopped changing; a chain is "
             "read at a size only on a piece of at least 4,096 nodes and half the graph; a pair holds its scale when the "
             "reach grows as the d the score reads at the larger size, within q of that growth plus half a step of the "
             "reach at each size and two standard errors of the seeds' reach. Only a pair that holds its scale lets a "
             "probe settle or the Einstein relation hold.", "",
             f"q = {reach['q']:g}, twice the widest training excess ({reach['widest_training_excess']['excess']:g}, "
             f"{reach['widest_training_excess']['family']} from {reach['widest_training_excess']['from_n']:,} to "
             f"{reach['widest_training_excess']['n']:,}) on its grid, over {reach['training_pairs']} training pairs of "
             f"`{document['table']['file']}`.", "",
             f"## Judged on {document['judged_on']}", "",
             ("**It passes**" if document["passes"] else "**It does not pass**") + ": "
             + ", ".join(f"{k} {v['held']} of {v['of']}" for k, v in judged["counts"].items()) + ".", ""]
    if judged["misses"]:
        lines += ["What missed:", ""]
        for miss in judged["misses"]:
            where = f" {miss['from_n']:,} to {miss['n']:,}" if "from_n" in miss else ""
            extra = f", {_scale_words(miss['scale'])}" if miss.get("scale") else ""
            lines.append(f"* {miss['prediction']}: {miss['structure']}{where}"
                         + (f", {miss['probe']}" if miss.get("probe") else "") + extra)
        lines.append("")
    lines += ["## The crossovers, pair by pair", "",
              "| structure | pair | judged | reach and d | points now | points without scale or floor |",
              "|---|---|---|---|---|---|"]
    names = {s["name"] for s in criterion_4()["crossovers"]}
    for row in judged["pairs"]:
        if row["structure"] not in names:
            continue
        lines.append(f"| {row['structure']} | {row['from_n']:,} to {row['n']:,} | "
                     f"{'yes' if row.get('judged') else 'reported'} | {_scale_words(row['scale'])}"
                     f"{'' if row['connected'] else ', largest piece under half the graph'} | {row['points']} | "
                     f"{row['unscaled_points']} |")
    lines += ["", "## Criterion 3's structures under the scale", "",
              "| structure | pair | reach and d | points now | points without scale or floor |", "|---|---|---|---|---|"]
    for row in judged["pairs"]:
        if row["structure"] in names:
            continue
        lines.append(f"| {row['structure']} | {row['from_n']:,} to {row['n']:,} | {_scale_words(row['scale'])} | "
                     f"{row['points']} | {row['unscaled_points']} |")
    if judged["reported"]:
        lines += ["", "Reported, not judged:", ""]
        for r in judged["reported"]:
            lines.append(f"* {r['structure']} {r['from_n']:,} to {r['n']:,}: {r['why']}"
                         + (f", {r['points']} points, {_scale_words(r['scale'])}" if r.get("scale") else ""))
    lines += ["", ("The score reads q from" if document["passes"] else "q is not judged fit")
              + " `graph_scale_dynamics/resources/calibration/score_margins.json` (its reach block).", ""]
    return "\n".join(lines)


def criterion_5() -> dict:
    return _json(CRITERION_5)


def _giant_at(side: dict) -> float | None:
    return L.reading((side or {}).get("giant_fraction"))


def scored_pair_5(by_n: dict, a: int, b: int, table: dict) -> dict:
    sides = {n: entry["side"] for n, entry in by_n.items()}
    side_a, side_b = sides[a], sides[b]
    found = L.points_at(side_a, side_b, b, table)
    scale = L.scale_kept(sides, a, b, table)
    connected = L.piece_holds(side_a, a) and L.piece_holds(side_b, b)
    settled = found["settled"] if scale["holds"] and connected else []
    einstein = bool(found["einstein"] and scale["holds"] and connected)
    alone = L.scale_at(side_a, side_b, a, b, table)["holds"]
    return {"from_n": a, "n": b, "settled": settled, "einstein": einstein,
            "points": len(settled) + (1 if einstein else 0), "connected": connected, "scale": scale,
            "d": L.dimension_read(side_b), "giant": _giant_at(side_b), "steps": found["steps"],
            "residual": found["residual"],
            "points_without_next_step": (len(found["settled"]) + (1 if found["einstein"] else 0)
                                         if alone and connected else 0),
            "unscaled_points": found["points"]}


def judge_5(table: dict, cases: dict | None = None) -> dict:
    rule = criterion_5()
    cases = judged_cases_4(None, rule) if cases is None else cases
    misses, rows, reported = [], [], []
    counts = {label: [0, 0] for label in ("K1", "K2", "K3", "K4", "S1", "S2", "S3")}
    for name, by_n in sorted(cases["structures"].items()):
        must_refuse_all = all(by_n[n]["held"][p] == "refuse" for n in by_n for p in L.PROBES)
        fifth, at_pairs = [], []
        for a, b in L.pairs(by_n):
            found = scored_pair_5(by_n, a, b, table)
            at_pairs.append(found["points"])
            rows.append({"structure": name, **found})
            reads = {p: _value(by_n[a]["side"], p) is not None and _value(by_n[b]["side"], p) is not None
                     for p in L.PROBES}
            for probe in L.PROBES:
                at = (by_n[a]["held"][probe], by_n[b]["held"][probe])
                if at == ("held", "held"):
                    if not reads[probe]:
                        reported.append({"structure": name, "probe": probe, "from_n": a, "n": b,
                                         "why": "held, and not read at both sizes"})
                        continue
                    counts["K1"][1] += 1
                    if probe in found["settled"]:
                        counts["K1"][0] += 1
                    else:
                        misses.append({"prediction": "K1", "structure": name, "probe": probe, "from_n": a, "n": b,
                                       "step": (found["steps"].get(probe) or {}).get("step"),
                                       "margin": L.margin(probe, b, table), "scale": found["scale"]})
                if "refuse" in at:
                    counts["K3"][1] += 1
                    if probe not in found["settled"]:
                        counts["K3"][0] += 1
                    else:
                        misses.append({"prediction": "K3", "structure": name, "probe": probe, "from_n": a, "n": b})
            if all(by_n[a]["held"][p] == by_n[b]["held"][p] == "held" for p in L.PROBES) and all(reads.values()):
                fifth.append(b)
                counts["K2"][1] += 1
                if found["points"] == L.PAIR_POINTS:
                    counts["K2"][0] += 1
                else:
                    misses.append({"prediction": "K2", "structure": name, "from_n": a, "n": b,
                                   "points": found["points"], "residual": found["residual"], "scale": found["scale"]})
        if must_refuse_all or fifth:
            counts["K4"][1] += 1
            score = L.score(_as_chain(by_n), references={}, table=table)
            top = at_pairs[-1] if at_pairs else None
            ok = (score["score"] == 0) if must_refuse_all else (top == L.PAIR_POINTS)
            if ok:
                counts["K4"][0] += 1
            else:
                misses.append({"prediction": "K4", "structure": name, "score": score["score"], "points_at_top": top})
    for structure in rule["crossovers"]:
        name = structure["name"]
        by_n = cases["crossovers"].get(name) or {}
        for a, b in L.pairs(by_n):
            found = scored_pair_5(by_n, a, b, table)
            read_as = bool(found["settled"] or found["einstein"])
            judged = "judged_from_n" in structure and a >= int(structure["judged_from_n"])
            rows.append({"structure": name, "judged": judged, **found})
            if "judged_from_n" in structure:
                if not judged:
                    reported.append({"structure": name, "from_n": a, "n": b, "why": "a pair from a square or a cube",
                                     "points": found["points"], "scale": found["scale"]})
                    continue
                counts["S1"][1] += 1
                if not read_as or (found["d"] is not None and found["d"] < RING_BELOW):
                    counts["S1"][0] += 1
                else:
                    misses.append({"prediction": "S1", "structure": name, "from_n": a, "n": b, "d": found["d"],
                                   "points": found["points"], "scale": found["scale"]})
            elif structure["build"] == "subdivided_random_tree":
                rows[-1]["judged"] = True
                counts["S2"][1] += 1
                if not read_as or (found["d"] is not None and found["d"] >= RING_BELOW):
                    counts["S2"][0] += 1
                else:
                    misses.append({"prediction": "S2", "structure": name, "from_n": a, "n": b, "d": found["d"],
                                   "settled": found["settled"], "scale": found["scale"]})
            elif structure["build"] == "cycle_soup":
                giant = found["giant"]
                if giant is None or giant >= L.CONNECTED_AT_LEAST:
                    reported.append({"structure": name, "from_n": a, "n": b, "points": found["points"],
                                     "why": "its largest piece is half the graph or more at the larger size",
                                     "scale": found["scale"]})
                    continue
                rows[-1]["judged"] = True
                counts["S3"][1] += 1
                if found["points"] == 0:
                    counts["S3"][0] += 1
                else:
                    misses.append({"prediction": "S3", "structure": name, "from_n": a, "n": b,
                                   "points": found["points"]})
    empty = [label for label, (_held, of) in counts.items() if of == 0]
    misses += [{"prediction": label, "structure": "none", "why": "no case judged"} for label in empty]
    return {"counts": {k: {"held": v[0], "of": v[1]} for k, v in counts.items()}, "misses": misses,
            "reported": reported, "pairs": rows, "passes": not misses}


def run_5(rows: list[dict] | None = None) -> tuple[dict, dict]:
    rule = criterion_5()
    table = _json(TABLE)
    cases = table_cases(table)
    trained = margins_in_force(cases)
    measured = _json(MEASURED_5) if rows is None else {"rows": rows, "seconds": None}
    judged = judge_5(trained, judged_cases_4(measured["rows"], rule))
    document = {"contract": JUDGED_5_CONTRACT, "criterion": rule["contract"], "committed_utc": rule["committed_utc"],
                "score": SCORE_5,
                "table": {"file": TABLE.relative_to(ROOT).as_posix(), "estimator_fingerprint": table.get("estimator_fingerprint")},
                "judged_on": f"seeds {rule['seeds'][0]} to {rule['seeds'][-1]}, built and read for it",
                "measured_seconds": measured.get("seconds"),
                "reach": {k: trained["reach"][k] for k in ("q", "z", "half_step", "factor", "widest_training_excess",
                                                         "training_pairs")},
                "judged": judged, "passes": judged["passes"]}
    return trained, document


def _next_words(scale: dict) -> str:
    after = scale.get("broken_after")
    if not after:
        return ""
    grown = (f"grows as d {after['growth_d']:g} against d {after['d']:g}"
             if after.get("growth_d") is not None and after.get("d") is not None else "does not grow")
    return f"; to {after['n']:,} its reach {grown}, so the step breaks"


def render_5(document: dict) -> str:
    judged = document["judged"]
    reach = document["reach"]
    lines = ["# The score's next step, on known answers written fresh", "",
             f"Committed before any of its structures was built or read: `{document['criterion']}` "
             f"({document['committed_utc']}), after criterion 4 missed (`docs/readings/score_known_answers_4_judged.md`). "
             f"The score judged is `{document['score']}`: criterion 4's counted seeds, connected piece and scale, and a "
             "pair whose next step breaks its scale settles nothing, because the dimension it read was a crossover on its "
             "way. A strip or a tube may settle only as the line it is at that size.", "",
             f"q = {reach['q']:g}, trained as criterion 4 trained it, over {reach['training_pairs']} training pairs of "
             f"`{document['table']['file']}`.", "",
             f"## Judged on {document['judged_on']}", "",
             ("**It passes**" if document["passes"] else "**It does not pass**") + ": "
             + ", ".join(f"{k} {v['held']} of {v['of']}" for k, v in judged["counts"].items()) + ".", ""]
    if judged["misses"]:
        lines += ["What missed:", ""]
        for miss in judged["misses"]:
            where = f" {miss['from_n']:,} to {miss['n']:,}" if "from_n" in miss else ""
            extra = (f", d {miss['d']:g}" if miss.get("d") is not None else "") + (
                f", {_scale_words(miss['scale'])}{_next_words(miss['scale'])}" if miss.get("scale") else "")
            lines.append(f"* {miss['prediction']}: {miss['structure']}{where}"
                         + (f", {miss['probe']}" if miss.get("probe") else "") + extra)
        lines.append("")
    lines += ["## The crossovers, pair by pair", "",
              "| structure | pair | judged | d read | reach and d | points now | without the next step | "
              "without scale or floor |", "|---|---|---|---|---|---|---|---|"]
    names = {s["name"] for s in criterion_5()["crossovers"]}
    for row in judged["pairs"]:
        if row["structure"] not in names:
            continue
        lines.append(f"| {row['structure']} | {row['from_n']:,} to {row['n']:,} | "
                     f"{'yes' if row.get('judged') else 'reported'} | {row['d'] if row['d'] is not None else 'none'} | "
                     f"{_scale_words(row['scale'])}{_next_words(row['scale'])}"
                     f"{'' if row['connected'] else ', largest piece under half the graph'} | {row['points']} | "
                     f"{row['points_without_next_step']} | {row['unscaled_points']} |")
    lines += ["", "## Criterion 3's structures, on seeds 61 to 63", "",
              "| structure | pair | reach and d | points now | without the next step | without scale or floor |",
              "|---|---|---|---|---|---|"]
    for row in judged["pairs"]:
        if row["structure"] in names:
            continue
        lines.append(f"| {row['structure']} | {row['from_n']:,} to {row['n']:,} | "
                     f"{_scale_words(row['scale'])}{_next_words(row['scale'])} | {row['points']} | "
                     f"{row['points_without_next_step']} | {row['unscaled_points']} |")
    if judged["reported"]:
        lines += ["", "Reported, not judged:", ""]
        for r in judged["reported"]:
            lines.append(f"* {r['structure']} {r['from_n']:,} to {r['n']:,}: {r['why']}"
                         + (f", {r['points']} points, {_scale_words(r['scale'])}" if r.get("scale") else ""))
    lines += ["", (f"It passes, so the candidate may be put in force in place of {IN_FORCE_AT_846}" if document["passes"]
                   else f"It misses, so the score in force stays {IN_FORCE_AT_846}, and the candidate is read beside it") + ".", ""]
    return "\n".join(lines)

