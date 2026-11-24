#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import platform
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import contract as C  # noqa: E402
from graph_scale_dynamics.calibration import table as T  # noqa: E402
from graph_scale_dynamics.calibration.cells import plan_cells, plan_extension_cells, suite_families  # noqa: E402

MANIFEST_CONTRACT = "gsd-calibration-collection-1"
THE_ONE_COMMAND = "uv run python tools/probe_calibration.py --whole"
TABLE_MEMBER = "probe_calibration.json"
MANIFEST_MEMBER = "manifest.json"


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _counts(classes: dict) -> dict:
    return {state: len(keys) for state, keys in classes.items()}


def reading(document: dict, root: Path = ROOT) -> dict:
    profile = document.get("profile") or {}
    families = suite_families(profile.get("families") or None)
    gate_plan = plan_cells(families, seeds=int(profile.get("seeds") or C.AUTHORITATIVE_SEEDS),
                           max_nodes=profile.get("max_nodes"))
    extension_plan = plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)
    whole_plan = plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)
    gate = T.classify_cells(document, gate_plan, str(root))
    extension = T.classify_cells(document, extension_plan, str(root))
    whole = T.classify_cells(document, whole_plan, str(root))
    peaks: dict[str, dict] = {}
    for cell in (document.get("cells") or {}).values():
        peak, n = cell.get("peak_rss_bytes"), cell.get("n")
        if isinstance(peak, int) and isinstance(n, int) and cell.get("status") == "ok":
            best = peaks.get(cell.get("family"))
            if best is None or n > best["n"] or (n == best["n"] and peak > best["peak_rss_bytes"]):
                peaks[str(cell.get("family"))] = {"n": n, "peak_rss_bytes": peak}
    return {
        "contract": document.get("contract"), "suite_version": document.get("suite_version"),
        "analysis_version": document.get("analysis_version"), "authoritative": bool(document.get("authoritative")),
        "profile": {key: profile.get(key) for key in ("name", "seeds", "max_nodes")},
        "cells": len(document.get("cells") or {}),
        "gate": _counts(gate),
        "gate_not_current": sorted({t["key"] for t in gate_plan} - set(gate[T.CELL_CURRENT]))[:50],
        "extension": _counts(extension),
        "extension_not_current": sorted({t["key"] for t in extension_plan} - set(extension[T.CELL_CURRENT])),
        "extension_complete": len(extension[T.CELL_CURRENT]) == len(extension_plan),
        "gate_complete": len(gate[T.CELL_CURRENT]) == len(gate_plan),
        "whole_table": {"cells": len(whole_plan), "current": len(whole[T.CELL_CURRENT]),
                        "seeds": C.AUTHORITATIVE_SEEDS},
        "largest_measured_cell_per_family": peaks,
        "fingerprints": {k: document.get(k) for k in ("science_fingerprint", "suite_fingerprint",
                                                      "estimator_fingerprint")},
        "verdict": (document.get("deviation") or {}).get("summary_line"),
    }


NOT_MEASURED_SHOWN = 12


def _number(value) -> str:
    return "nothing" if not isinstance(value, (int, float)) or isinstance(value, bool) else f"{value:g}"


def _failure_in_words(name: str, family: dict, row: dict, channel: str, judged: dict) -> str:
    seeds = int(judged.get("seeds") or 0)
    read = seeds - int(judged.get("seed_refusals") or 0)
    where = f"{name}, {channel} at {int(row['n']):,} nodes"
    held = f"{_number(judged.get('theory'))} is held within {_number(judged.get('tolerance'))}"
    status = judged.get("status")
    if status == "OUT_OF_TOLERANCE":
        return f"{where}: reads {_number(judged.get('measured'))} where {held}"
    if status == "REFUSED":
        return f"{where}: refused on every seed where {held}"
    if status == "REFUSED_MAJORITY":
        return (f"{where}: read on {read} of {seeds} seeds where {held}, fewer than the "
                f"{float(judged.get('availability_floor') or 0.0):.0%} that must read")
    from_nodes = (family.get("refusal_gated_from") or {}).get(channel)
    return (f"{where}: read on {read} of {seeds} seeds ({_number(judged.get('measured'))}) where every probe must "
            f"refuse from {int(from_nodes or 0):,} nodes")


def rows_judged(document: dict) -> dict:
    from graph_scale_dynamics.calibration.deviation import FAILING_STATUSES
    counted = {"held_and_inside": 0, "refusals_required_and_held": 0, "shown": 0, "waived": 0, "failing": []}
    for name, family in ((document.get("deviation") or {}).get("families") or {}).items():
        required_from = family.get("refusal_gated_from") or {}
        for row in family.get("rows") or []:
            if not row.get("complete"):
                continue
            for channel, judged in sorted((row.get("channels") or {}).items()):
                status = judged.get("status")
                if status in FAILING_STATUSES:
                    counted["failing"].append(_failure_in_words(name, family, row, channel, judged))
                elif status == "WITHIN_TOLERANCE":
                    counted["held_and_inside"] += 1
                elif status == "WAIVED":
                    counted["waived"] += 1
                elif (status == "REFUSED_OK" and channel in required_from
                      and int(row["n"]) >= int(required_from[channel])):
                    counted["refusals_required_and_held"] += 1
                else:
                    counted["shown"] += 1
    return counted


def cells_not_measured(document: dict, root: Path = ROOT) -> list[str]:
    profile = document.get("profile") or {}
    plan = plan_cells(suite_families(profile.get("families") or None),
                      seeds=int(profile.get("seeds") or C.AUTHORITATIVE_SEEDS), max_nodes=profile.get("max_nodes"))
    if profile.get("max_nodes") is None:
        plan = plan + plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)
    classes = T.classify_cells(document, plan, str(root))
    blocked = {str(entry.get("key")): str(entry.get("reason")) for name in ("blocked_cells", "extension_blocked_cells")
               for entry in document.get(name) or [] if isinstance(entry, dict)}
    cells = document.get("cells") or {}
    said = []
    for task in plan:
        key = task["key"]
        if key in classes[T.CELL_FAILED]:
            said.append(f"{key} ({task['n']:,} nodes): failed: {cells[key].get('error') or 'no error recorded'}")
        elif key in classes[T.CELL_STALE] and T.its_probes_are_current(cells[key], str(root)):
            start = cells[key].get("start") if isinstance(cells[key].get("start"), dict) else {}
            said.append(f"{key} ({task['n']:,} nodes): its probes are measured and its reading as a start is not: "
                        + str(start.get("error") or "not read, or read by other code than this tree's"))
        elif key in classes[T.CELL_STALE]:
            said.append(f"{key} ({task['n']:,} nodes): measured by other code than this tree's")
        elif key in classes[T.CELL_MISSING]:
            said.append(f"{key} ({task['n']:,} nodes): " + (f"held back: {blocked[key]}" if key in blocked
                                                            else "not measured"))
    return said


def is_a_rehearsal(profile: dict) -> bool:
    return (profile.get("max_nodes") is not None
            or int(profile.get("seeds") or C.AUTHORITATIVE_SEEDS) < C.AUTHORITATIVE_SEEDS)


def in_plain_words(document: dict, root: Path = ROOT) -> list[str]:
    here = reading(document, root)
    profile = document.get("profile") or {}
    seeds = int(profile.get("seeds") or C.AUTHORITATIVE_SEEDS)
    is_the_whole_table = here["whole_table"]["current"] == here["whole_table"]["cells"]
    reduced = is_a_rehearsal(profile)
    missing = cells_not_measured(document, root)
    core_hours = sum(float(cell.get("elapsed_seconds") or 0.0)
                     for cell in (document.get("cells") or {}).values() if isinstance(cell, dict)) / 3600.0
    ladders, past = here["gate"].get(T.CELL_CURRENT, 0), here["extension"].get(T.CELL_CURRENT, 0)
    if missing:
        lines = [f"The table is not whole: {len(missing):,} of its cells are not measured:"]
        lines += [f"    {line}" for line in missing[:NOT_MEASURED_SHOWN]]
        if len(missing) > NOT_MEASURED_SHOWN:
            lines.append(f"    and {len(missing) - NOT_MEASURED_SHOWN:,} more")
    elif reduced:
        lines = [f"A rehearsal's table, whole as a rehearsal: {ladders:,} cells at {seeds} seed(s), every ladder to "
                 f"{int(profile.get('max_nodes') or C.MAX_NODES):,} nodes, nothing past the ladders, "
                 f"{core_hours:.1f} core-hours of measuring. It is not the table a study reads."]
    else:
        lines = [f"The table is whole: {ladders:,} cells on the ladders and {past:,} past them, "
                 f"{core_hours:.1f} core-hours of measuring."]
        if not is_the_whole_table:
            lines.append(f"It is not this tree's whole table: {here['whole_table']['current']:,} of its "
                         f"{here['whole_table']['cells']:,} cells are current here.")
    judged = rows_judged(document)
    if judged["failing"]:
        lines.append(f"The gate does not pass, in {len(judged['failing']):,} place(s):")
        lines += [f"    {line}" for line in judged["failing"]]
        lines.append("The table is kept as measured: no cell is measured again, and nothing in it is changed.")
    elif missing:
        lines.append("Nothing measured so far fails the gate; the gate's verdict needs the table whole.")
    else:
        lines.append(f"The gate passes: {judged['held_and_inside']:,} readings are held to a band and every one is "
                     f"inside it, {judged['refusals_required_and_held']:,} refusals are required and every one is "
                     f"held, and {judged['shown']:,} readings are shown and held to nothing.")
    if judged["waived"]:
        lines.append(f"{judged['waived']:,} failing reading(s) are waived by this folder's waivers file.")
    return lines


def collect(root: Path = ROOT, out_dir: Path | None = None, *, table_path: Path | None = None) -> Path:
    table_path = table_path or C.durable_artifact_path(root)
    document = T.load(table_path)
    if document is None:
        raise SystemExit(f"no calibration table at {table_path}: nothing to collect")
    try:
        build = int((root / "BUILD_NUMBER").read_text().strip())
    except (OSError, ValueError):
        build = None
    manifest = {"contract": MANIFEST_CONTRACT, "collected_utc": _utc(), "host": platform.node(),
                "folder": str(root), "build": build, "table": str(table_path), **reading(document, root),
                "in_plain_words": in_plain_words(document, root)}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = (out_dir or root) / f"calibration_{platform.node() or 'host'}_{stamp}.zip"
    partial = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.write(table_path, TABLE_MEMBER)
        bundle.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2, sort_keys=True))
    partial.replace(target)
    return target


BUNDLE_MEMBER_SUFFIX = "evidence/probe_calibration.json"


def _from_bundle(path: Path) -> dict:
    import shutil
    import subprocess
    import tarfile
    zstd = shutil.which("zstd")
    if not zstd:
        raise SystemExit("reading a .tar.zst bundle needs the zstd executable; extract "
                         f"{BUNDLE_MEMBER_SUFFIX} from it and pass that file instead")
    with subprocess.Popen([zstd, "-dc", str(path)], stdout=subprocess.PIPE) as unzstd:
        with tarfile.open(fileobj=unzstd.stdout, mode="r|") as archive:
            for member in archive:
                if member.isfile() and member.name.endswith(BUNDLE_MEMBER_SUFFIX):
                    return json.loads(archive.extractfile(member).read().decode("utf-8"))
    raise SystemExit(f"{path.name} carries no {BUNDLE_MEMBER_SUFFIX}: the "
                     "table was not in force when it was made")


def _load_collected(path: Path) -> tuple[dict, dict | None]:
    if path.name.endswith(".tar.zst"):
        return _from_bundle(path), None
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8")), None
    with zipfile.ZipFile(path) as bundle:
        document = json.load(io.TextIOWrapper(bundle.open(TABLE_MEMBER), encoding="utf-8"))
        manifest = json.loads(bundle.read(MANIFEST_MEMBER)) if MANIFEST_MEMBER in bundle.namelist() else None
    return document, manifest


def install_seed(source: Path, root: Path = ROOT, *, partial: bool = False,
                 target: Path | None = None) -> tuple[Path, dict]:
    document, _manifest = _load_collected(source)
    if document.get("contract") != C.CONTRACT:
        raise SystemExit(f"not a {C.CONTRACT} table: {document.get('contract')!r}")
    if int(document.get("suite_version") or 0) != C.SUITE_VERSION:
        raise SystemExit(f"a suite {document.get('suite_version')} table; this tree runs suite {C.SUITE_VERSION}")
    here = reading(document, root)
    problems = []
    if not here["gate_complete"]:
        problems.append(f"gate cells not current here: {here['gate']}")
    elif here["whole_table"]["current"] < here["whole_table"]["cells"]:
        problems.append(f"a reduced table: {here['whole_table']['current']:,} of the whole table's "
                        f"{here['whole_table']['cells']:,} cells ({C.AUTHORITATIVE_SEEDS} seeds on every ladder) "
                        "are current here")
    if not here["extension_complete"]:
        problems.append(f"extension cells not current here: {here['extension']} "
                        f"({', '.join(here['extension_not_current'][:6])}...)")
    if problems and not partial:
        raise SystemExit("refusing a partial seed (pass --partial to ship it anyway): " + "; ".join(problems))
    document.setdefault("origin", {})["seeded_from"] = {"source": source.name, "installed_utc": _utc(),
                                                        "reading": {k: here[k] for k in ("gate", "extension")}}
    target = target or (root / C.DURABLE_DIR / C.SEED_TABLE_NAME)
    if target.name == C.DURABLE_NAME:
        raise SystemExit(f"never {C.DURABLE_NAME}: an archive carrying the live table overwrites a host's (353)")
    T.write(document, target)
    return target, here


def _say(summary: dict) -> str:
    gate, ext = summary["gate"], summary["extension"]
    on_the_ladders = f"{summary['cells']} cells; gate {gate.get('current', 0)} current of {sum(gate.values())}"
    if is_a_rehearsal(summary.get("profile") or {}):
        return on_the_ladders + "; a rehearsal measures nothing past the ladders"
    return (on_the_ladders + f"; extension {ext.get('current', 0)} current of {sum(ext.values())}"
            + (" (complete)" if summary["extension_complete"] else
               f", {sum(ext.values()) - ext.get('current', 0)} to go"))


def say_collected(target: Path) -> list[str]:
    with zipfile.ZipFile(target) as bundle:
        summary = json.loads(bundle.read(MANIFEST_MEMBER))
    if is_a_rehearsal(summary.get("profile") or {}):
        closing = "A rehearsal has nothing to send. Its file, made as the whole table's is:"
    elif summary["gate_complete"] and summary["extension_complete"]:
        closing = "Send this one file, and start nothing else:"
    else:
        closing = (f"`{THE_ONE_COMMAND}` measures what is missing. If it has ended here twice, send this one file "
                   "as it is, and start nothing else:")
    return [f"calibration table: {_say(summary)}", *summary.get("in_plain_words", []), closing, str(target)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/collect_calibration.py: see docs/TOOLS.md")
    parser.add_argument("--install-seed", type=Path, metavar="ZIP",
                        help="write calibration/seed_table.json from a collected zip, a report bundle (.tar.zst) "
                             "or the table itself (the build sandbox's step)")
    parser.add_argument("--partial", action="store_true", help="with --install-seed: accept an incomplete table")
    parser.add_argument("--out", type=Path, default=None, help="where the zip goes (default: the tree)")
    args = parser.parse_args(argv)
    if args.install_seed:
        target, summary = install_seed(args.install_seed, partial=args.partial)
        print(f"wrote {target.relative_to(ROOT)}: {_say(summary)}")
        return 0
    target = collect(out_dir=args.out)
    for line in say_collected(target):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
