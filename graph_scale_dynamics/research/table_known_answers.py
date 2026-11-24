from __future__ import annotations

import statistics

CONTRACT = "gsd-table-known-answers-1"
PROBES = ("d_s", "d_V", "d_B", "d_w")
FOR_ITS_BALLS = ("EXPONENTIAL_GROWTH", "GROWTH_UNDECIDED", "GROWTH_UNEVEN")
BY_THE_TABLE = "this table's own cells"
ITS_SEEDS_MAY_BE_REFUSED_FOR_THEIR_BALLS = ("uniform_random_tree",)
ERROR_FROM_NODES = 1024
ERROR_LEAST_SEEDS = 6
ERROR_TO_SPREAD = (0.5, 2.0)
ERROR_SHARE = 0.9
A4_AND_D4 = ("periodic_a4_lattice", "periodic_d4_lattice")
DENSE_RANDOM = ("erdos_renyi_degree_16", "erdos_renyi_degree_32")
A4_AND_D4_HELD_FROM = {"d_B": 65536}


def band_at(bands, n: int) -> float | None:
    chosen = None
    for nodes, within in bands or ():
        if int(n) >= int(nodes):
            chosen = float(within)
    return chosen


def planned(criterion: dict) -> list[dict]:
    from graph_scale_dynamics.calibration import the_whole_plan
    return the_whole_plan(criterion["plan"]["seeds"], criterion["plan"]["extension_seeds"])


def _reading(cell: dict, probe: str) -> tuple:
    entry = (cell.get("channels") or {}).get(probe) or {}
    value = entry.get("value") if entry.get("valid") else None
    return value, entry.get("se") if value is not None else None, None if value is not None else entry.get("refusal")


def rungs(criterion: dict, table: dict) -> tuple[dict, list[str]]:
    cells = table.get("cells") or {}
    wanted = criterion["measured_by"]["cell_fingerprints"]
    found: dict = {}
    absent = []
    for task in planned(criterion):
        cell = cells.get(task["key"])
        if not isinstance(cell, dict) or cell.get("status") != "ok":
            absent.append(f"{task['key']}: {'not in the table' if not isinstance(cell, dict) else 'failed'}")
            continue
        if str(cell.get("cell_fingerprint")) != wanted[task["family"]]:
            absent.append(f"{task['key']}: measured by other probes ({cell.get('cell_fingerprint')})")
            continue
        rung = found.setdefault(task["family"], {}).setdefault(int(task["n"]), {
            "family": task["family"], "parameter": task["parameter"], "n": int(task["n"]),
            "extension": bool(task.get("extension")), "seeds": []})
        probes = {probe: dict(zip(("value", "se", "refusal"), _reading(cell, probe), strict=True)) for probe in PROBES}
        rung["seeds"].append({"seed": int(task["seed"]), "probes": probes})
    return found, absent


def _values(rung: dict, probe: str) -> list:
    return [seed["probes"][probe]["value"] for seed in rung["seeds"]]


def held_from_the_table(bands, by_n: dict, probe: str) -> int | None:
    banded = sorted(n for n in by_n if band_at(bands, n) is not None)
    held = None
    for n in reversed(banded):
        if not all(value is not None for value in _values(by_n[n], probe)):
            break
        held = n
    return held


def _judged_cell(rung: dict, probe: str, theory: float, within: float, floor: float) -> tuple[dict, str | None]:
    values = _values(rung, probe)
    read = [value for value in values if value is not None]
    mean = sum(read) / len(read) if read else None
    cell = {"probe": probe, "theory": theory, "within": within, "values": values, "mean": mean,
            "read": len(read), "seeds": len(values)}
    if not read:
        return cell, "refused on every seed where it is held"
    if len(read) / len(values) < floor:
        return cell, "read on fewer seeds than the table asks where it is held"
    if abs(mean - theory) > within:
        return cell, "outside its band"
    return cell, None


def judge(criterion: dict, table: dict, against: dict | None = None) -> dict:
    found, absent = rungs(criterion, table)
    floor = float(criterion["availability_floor"])
    held_from_nodes = int(criterion["verdict_held_from_nodes"])
    families, misses, holds = {}, [], {}
    for family, by_n in sorted(found.items()):
        rows = []
        if family in criterion["without_a_dimension"]:
            for n, rung in sorted(by_n.items()):
                read = {probe: sum(1 for v in _values(rung, probe) if v is not None) for probe in PROBES}
                status = "shown" if n < held_from_nodes else (
                    "refused as required" if not any(read.values()) else "read where no dimension exists")
                rows.append({"n": n, "parameter": rung["parameter"], "seeds": len(rung["seeds"]),
                             "read": read, "status": status})
                if status == "read where no dimension exists":
                    misses.append({"family": family, "n": n, "probe": ", ".join(p for p in PROBES if read[p]),
                                   "miss": status})
            families[family] = {"kind": "without a dimension", "rows": rows}
            continue
        spec = criterion["with_a_dimension"].get(family)
        if spec is None:
            continue
        held = {}
        for probe, want in sorted(spec["probes"].items()):
            if spec["held_from"] == BY_THE_TABLE:
                start = held_from_the_table(want["bands"], by_n, probe)
                if start is None:
                    misses.append({"family": family, "n": max(n for n in by_n if band_at(want["bands"], n) is not None),
                                   "probe": probe, "miss": "not read on every seed at its largest size with a band"})
                    continue
                bands = [[start, band_at(want["bands"], start)]] + [
                    [int(nodes), float(within)] for nodes, within in want["bands"] if int(nodes) > start]
            else:
                start, bands = int(want["bands"][0][0]), [[int(a), float(b)] for a, b in want["bands"]]
            held[probe] = {"theory": float(want["theory"]), "from_nodes": int(start), "bands": bands}
        holds[family] = held
        for n, rung in sorted(by_n.items()):
            row = {"n": n, "parameter": rung["parameter"], "seeds": len(rung["seeds"]), "probes": {}}
            for probe in PROBES:
                hold = held.get(probe)
                within = band_at(hold["bands"], n) if hold and n >= hold["from_nodes"] else None
                values = _values(rung, probe)
                if within is None:
                    row["probes"][probe] = {"probe": probe, "values": values, "status": "shown"}
                    continue
                cell, miss = _judged_cell(rung, probe, hold["theory"], within, floor)
                cell["status"] = miss or "inside"
                row["probes"][probe] = cell
                if miss:
                    misses.append({"family": family, "n": n, "probe": probe, "miss": miss, "mean": cell["mean"]})
            rows.append(row)
        families[family] = {"kind": "with a dimension", "held_from": spec["held_from"], "held": held, "rows": rows}
    whole = not absent
    return {"contract": CONTRACT, "criterion": criterion["contract"],
            "criterion_committed_utc": criterion["committed_utc"],
            "table": {key: table.get(key) for key in ("build_number", "written_utc", "estimator_fingerprint",
                                                       "analysis_version", "science_fingerprint")},
            "whole": whole, "not_counted": absent, "families": families, "holds": holds, "misses": misses,
            "passes": whole and not misses, "predictions": predictions(criterion, found, holds, against, table)}


def _the_same(table_cell: dict, seed_cell: dict) -> list[str]:
    differ = []
    for probe in PROBES:
        new, old = _reading(table_cell, probe), _reading(seed_cell, probe)
        if new[0] != old[0] or new[2] != old[2]:
            differ.append(f"{probe}: {old[0] if old[0] is not None else old[2]} then "
                          f"{new[0] if new[0] is not None else new[2]}")
    return differ


def _the_same_readings(table: dict | None, against: dict | None) -> dict:
    if against is None or table is None:
        return {"judged": False, "why": "no seed to compare with was given"}
    old, new = against.get("cells") or {}, table.get("cells") or {}
    compared, missing, differ = 0, [], []
    for key, seed_cell in sorted(old.items()):
        if seed_cell.get("status") != "ok":
            continue
        cell = new.get(key)
        if not isinstance(cell, dict) or cell.get("status") != "ok":
            missing.append(key)
            continue
        compared += 1
        differ += [f"{key} {line}" for line in _the_same(cell, seed_cell)]
    return {"judged": True, "compared": compared, "missing": missing, "differ": differ,
            "true": compared > 0 and not missing and not differ}


def _a4_and_d4(found: dict, holds: dict) -> dict:
    said = {}
    true = True
    for family in A4_AND_D4:
        by_n = found.get(family) or {}
        held = holds.get(family) or {}
        first = min((n for n in by_n if n >= ERROR_FROM_NODES), default=None)
        above = sorted(n for n in by_n if n > 262144)
        want = {"d_s": first, "d_V": first, "d_B": A4_AND_D4_HELD_FROM["d_B"], "d_w": above[0] if above else None}
        for probe, at_most in want.items():
            given = (held.get(probe) or {}).get("from_nodes")
            ok = given is not None and at_most is not None and (
                given <= at_most if probe == "d_B" else given == at_most)
            said[f"{family} {probe}"] = {"held_from": given, "predicted": at_most, "true": ok}
            true = true and ok
    return {"judged": True, "cells": said, "true": true}


def _dense_random(found: dict) -> dict:
    read = []
    for family in DENSE_RANDOM:
        for n, rung in sorted((found.get(family) or {}).items()):
            for probe in PROBES:
                count = sum(1 for value in _values(rung, probe) if value is not None)
                if count:
                    read.append(f"{family} at {n:,}: {probe} on {count} of {len(rung['seeds'])}")
    return {"judged": all(family in found for family in DENSE_RANDOM), "read": read,
            "true": all(family in found for family in DENSE_RANDOM) and not read}


def _d_s_error(criterion: dict, found: dict) -> dict:
    from graph_scale_dynamics.calibration import the_same_graph_on_every_seed
    cells = []
    for family, by_n in sorted(found.items()):
        if family in criterion["without_a_dimension"] or not the_same_graph_on_every_seed(family):
            continue
        for n, rung in sorted(by_n.items()):
            if n < ERROR_FROM_NODES:
                continue
            read = [seed["probes"]["d_s"] for seed in rung["seeds"] if seed["probes"]["d_s"]["value"] is not None]
            values = [entry["value"] for entry in read]
            if len(read) < ERROR_LEAST_SEEDS or max(values) == min(values):
                continue
            errors = [entry["se"] for entry in read if entry["se"] is not None]
            if not errors:
                continue
            ratio = statistics.median(errors) / statistics.stdev(values)
            cells.append({"family": family, "n": n, "read": len(read), "ratio": ratio,
                          "inside": ERROR_TO_SPREAD[0] <= ratio <= ERROR_TO_SPREAD[1]})
    inside = sum(1 for cell in cells if cell["inside"])
    return {"judged": bool(cells), "cells": cells, "inside": inside, "of": len(cells),
            "true": bool(cells) and inside >= ERROR_SHARE * len(cells)}


def _for_their_balls(criterion: dict, found: dict) -> dict:
    said = []
    for family, by_n in sorted(found.items()):
        if family not in criterion["with_a_dimension"]:
            continue
        for n, rung in sorted(by_n.items()):
            if n < int(criterion["verdict_held_from_nodes"]):
                continue
            refused = [seed["seed"] for seed in rung["seeds"]
                       if any(seed["probes"][probe]["refusal"] in FOR_ITS_BALLS for probe in PROBES)]
            if not refused:
                continue
            allowed = family in ITS_SEEDS_MAY_BE_REFUSED_FOR_THEIR_BALLS and 2 * len(refused) < len(rung["seeds"])
            said.append({"family": family, "n": n, "seeds": refused, "allowed": allowed})
    return {"judged": True, "refused": said, "true": all(entry["allowed"] for entry in said)}


def predictions(criterion: dict, found: dict, holds: dict, against: dict | None, table: dict | None = None) -> dict:
    return {"the_same_readings": _the_same_readings(table, against),
            "a4_and_d4_read_four": _a4_and_d4(found, holds),
            "the_dense_random_graphs_are_refused": _dense_random(found),
            "d_s_error_is_its_seeds_spread": _d_s_error(criterion, found),
            "no_geometry_refused_for_its_balls": _for_their_balls(criterion, found)}


def _number(value) -> str:
    return "" if value is None else f"{value:.3f}"


def _shown(cell: dict) -> str:
    values = cell.get("values") or []
    read = [value for value in values if value is not None]
    if cell.get("status") == "shown":
        return "refused" if not read else f"{sum(read) / len(read):.3f}" + (
            "" if len(read) == len(values) else f" on {len(read)} of {len(values)}")
    mark = "" if cell["status"] == "inside" else " MISS"
    some = "" if cell["read"] == cell["seeds"] else f" on {cell['read']} of {cell['seeds']}"
    return f"**{_number(cell['mean'])}**{some}{mark}"


PREDICTION_WORDS = {
    "the_same_readings": "Every value and refusal of the seed's cells repeated, bit for bit",
    "a4_and_d4_read_four": "A4 and D4 held from the predicted sizes",
    "the_dense_random_graphs_are_refused": "The random graphs of mean degree 16 and 32 refused everywhere",
    "d_s_error_is_its_seeds_spread": "d_s's error within 0.5 to 2 of its seeds' spread in nine cells of ten",
    "no_geometry_refused_for_its_balls": "No geometry refused for its balls from 4,096 nodes",
}


def _prediction_line(name: str, said: dict) -> str:
    words = PREDICTION_WORDS[name]
    if not said.get("judged"):
        return f"* {words}: not judged ({said.get('why') or 'nothing to judge'})."
    detail = ""
    if name == "the_same_readings":
        detail = (f": {said['compared']:,} cells compared, {len(said['differ'])} readings differ, "
                  f"{len(said['missing'])} cells missing")
    elif name == "d_s_error_is_its_seeds_spread":
        detail = f": {said['inside']} of {said['of']} cells inside"
    elif name == "the_dense_random_graphs_are_refused":
        detail = "" if not said["read"] else ": read in " + "; ".join(said["read"][:12])
    elif name == "no_geometry_refused_for_its_balls":
        detail = "" if not said["refused"] else ": " + "; ".join(
            f"{entry['family']} at {entry['n']:,} on seeds {entry['seeds']}" for entry in said["refused"][:12])
    elif name == "a4_and_d4_read_four":
        detail = ": " + "; ".join(f"{key} from {value['held_from']} ({value['predicted']} predicted)"
                                  for key, value in said["cells"].items() if not value["true"]) if not said[
            "true"] else ""
    return f"* {words}: {'true' if said['true'] else 'false'}{detail}."


def render(judged: dict) -> str:
    lines = ["# The calibration table's known answers on the final probes", "",
             f"Judged against `table_known_answers_criterion.json`, committed {judged['criterion_committed_utc']} "
             f"before the table was read. {'It passes' if judged['passes'] else 'It does not pass'}: "
             f"{len(judged['misses'])} judged cells are not as the criterion says"
             + ("" if judged["whole"] else f", and {len(judged['not_counted'])} planned cells do not count") + ".",
             "", "A bold reading is held to its band (the mean over the seeds that read); the rest are shown. "
             "A family without a dimension is held to no value from 4,096 nodes.", ""]
    for family, entry in judged["families"].items():
        if entry["kind"] == "without a dimension":
            said = ", ".join(f"{row['n']:,} {row['status']}" for row in entry["rows"])
            lines += [f"## {family}, without a dimension", "", said + ".", ""]
            continue
        held = "; ".join(f"{probe} {hold['theory']:.3g} from {hold['from_nodes']:,}"
                         for probe, hold in sorted(entry["held"].items()))
        lines += [f"## {family} ({held or 'nothing held'}; held from {entry['held_from']})", "",
                  "| nodes | " + " | ".join(PROBES) + " |", "|---:|" + "---|" * len(PROBES)]
        for row in entry["rows"]:
            lines.append(f"| {row['n']:,} | " + " | ".join(_shown(row["probes"][probe]) for probe in PROBES) + " |")
        lines.append("")
    lines += ["## Not as the criterion says", ""]
    lines += [f"* {miss['family']} at {miss['n']:,}, {miss['probe']}: {miss['miss']}"
              + (f", {miss['mean']:.3f}" if isinstance(miss.get("mean"), float) else "") + "."
              for miss in judged["misses"]] or ["Nothing."]
    if judged["not_counted"]:
        lines += ["", f"Not counted: {len(judged['not_counted'])} planned cells, first "
                  + "; ".join(judged["not_counted"][:12]) + "."]
    lines += ["", "## The predictions", ""]
    lines += [_prediction_line(name, said) for name, said in judged["predictions"].items()]
    lines.append("")
    return "\n".join(lines)
