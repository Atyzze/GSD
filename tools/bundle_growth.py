#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-bundle-growth-1"
READERS = ("read_bundle", "replay_bundle", "counters_reading", "study_172_reading", "cap_reading", "budget_reading")
SANDBOX_BYTES = 7 * 1024 ** 3
TARGETS = (10_000, 100_000)
EARLIER = ROOT / "tests" / "fixtures" / "bundle_growth_171.json"


POLL_SECONDS = 0.1


def high_water(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def measured_child(command: list[str], *, cwd: Path = ROOT) -> dict:
    started, peak = time.monotonic(), 0
    with open(os.devnull, "wb") as quiet:
        child = subprocess.Popen(command, cwd=cwd, stdout=quiet, stderr=quiet)
        while child.poll() is None:
            peak = max(peak, high_water(child.pid) or 0)
            time.sleep(POLL_SECONDS)
    return {"seconds": round(time.monotonic() - started, 1), "peak_bytes": peak, "exit": child.returncode}


def _json(path: Path) -> dict:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _controller(system: dict) -> dict | None:
    for service in system.get("services") or []:
        if isinstance(service, dict) and service.get("role") == "controller":
            try:
                said = json.loads(service.get("last_message") or "{}")
            except ValueError:
                said = {}
            return {key: said.get(key) for key in ("pass_seconds", "passes_total", "passes_idle", "rest_seconds")}
    return None


def sizes(root: Path) -> dict:
    root = Path(root)
    study = _json(root / "study.json")
    tables = {}
    for path in sorted((root / "tables").glob("*.ndjson.gz")):
        with gzip.open(path, "rb") as handle:
            rows, raw = 0, 0
            for line in handle:
                rows += 1
                raw += len(line)
        tables[path.name] = {"bytes": path.stat().st_size, "raw_bytes": raw, "rows": rows}
    parts = {}
    for manifest in sorted(root.glob("*/manifest.json")):
        folder = manifest.parent
        found = _json(manifest)
        parts[folder.name] = {"bytes": sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()),
                              "cycle_seconds": found.get("cycle_seconds"),
                              "controller": _controller(_json(folder / "evidence" / "system.json"))}
    laws = tables.get("laws.ndjson.gz", {}).get("rows")
    return {"study_id": study.get("study_id"), "build_number": study.get("build_number"),
            "built_utc": study.get("built_utc"), "read_utc": {k: v for k, v in (study.get("read_utc") or {}).items()
                                                              if k != "reading"},
            "bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()), "laws": laws,
            "tables": tables, "parts": parts}


def readers(bundle: Path, names=READERS) -> dict:
    found = {}
    for name in names:
        found[name] = measured_child([sys.executable, str(ROOT / "tools" / f"{name}.py"), str(bundle)])
    return found


def quantities(found: dict) -> dict:
    out = {"bytes": found.get("bytes"),
           "decisions_raw_bytes": (found.get("tables", {}).get("decisions.ndjson.gz") or {}).get("raw_bytes")}
    for name, reader in (found.get("readers") or {}).items():
        out[f"{name}.seconds"] = reader.get("seconds")
        out[f"{name}.peak_bytes"] = reader.get("peak_bytes")
    return out


def projected(laws: float, value: float, target: int, earlier: dict | None, key: str) -> tuple[float, str]:
    before = (earlier or {}).get("quantities", {}).get(key) if earlier else None
    then = (earlier or {}).get("laws")
    if before is not None and then and then != laws:
        slope = (value - before) / (laws - then)
        return max(value, value + slope * (target - laws)), "a line through two bundles"
    return value * target / laws, "in proportion to the laws, an upper bound"


def scaled(found: dict, targets=TARGETS, earlier: dict | None = None) -> dict:
    laws = found.get("laws") or 0
    if not laws:
        return {}
    now = quantities(found)
    out = {}
    for target in targets:
        row, how = {"ratio": round(target / laws, 2), "readers": {}}, set()
        for key, value in now.items():
            if value is None:
                continue
            guess, method = projected(laws, float(value), target, earlier, key)
            how.add(method)
            if "." in key:
                name, field = key.split(".", 1)
                reader = row["readers"].setdefault(name, {})
                reader[field] = round(guess, 1) if field == "seconds" else int(guess)
                if field == "peak_bytes":
                    reader["fits_the_sandbox"] = guess < SANDBOX_BYTES
            else:
                row[key] = int(guess)
        row["how"] = sorted(how)
        out[str(target)] = row
    return out


def _mb(value) -> str:
    return "-" if value is None else f"{value / 1e6:,.1f} MB"


def render(found: dict) -> str:
    against = found.get("against") or {}
    lines = [f"what grows with the study ({found['contract']}), study {found.get('study_id')}, build "
             f"{found.get('build_number')}, made {found.get('built_utc')}: {found.get('laws')} laws, the bundle "
             f"{_mb(found.get('bytes'))} unpacked"
             + (f"; against study {against['study_id']}'s {against['laws']} laws" if against.get("laws") else ""),
             f"  read_utc {found.get('read_utc')}"]
    for name, table in found["tables"].items():
        lines.append(f"  {name}: {table['rows']:,} rows, {_mb(table['bytes'])} ({_mb(table['raw_bytes'])} unpacked)")
    for name, part in found["parts"].items():
        lines.append(f"  {name}: {_mb(part['bytes'])}, report cycle {part['cycle_seconds']} s, controller "
                     f"{part['controller']}")
    for name, reader in (found.get("readers") or {}).items():
        lines.append(f"  {name}: {reader['seconds']} s, peak {_mb(reader['peak_bytes'])}, exit {reader['exit']}")
    for target, row in (found.get("scaled") or {}).items():
        heavy = {name: f"{_mb(r['peak_bytes'])}{'' if r['fits_the_sandbox'] else ' (past the sandbox)'}"
                 for name, r in row["readers"].items()}
        lines.append(f"  at {int(target):,} laws (x{row['ratio']}, {' and '.join(row['how'])}): bundle {_mb(row['bytes'])}, "
                     f"decisions {_mb(row['decisions_raw_bytes'])} unpacked; readers' peaks {heavy}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from read_bundle import unpacked, scratch_dir
    parser = argparse.ArgumentParser(description="tools/bundle_growth.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--readers", nargs="*", default=list(READERS), help="the readers to time; none for none")
    parser.add_argument("--against", type=Path, default=EARLIER,
                        help="an earlier bundle's --json, the second point of each line (171's by default)")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    root = unpacked(args.bundle, scratch_dir("gsd_growth_"))
    found = {"contract": CONTRACT, **sizes(root)}
    names = [name for name in args.readers if name != "none"]
    found["readers"] = readers(args.bundle, names) if names else {}
    found["quantities"] = quantities(found)
    earlier = _json(args.against) if args.against else {}
    found["against"] = {"study_id": earlier.get("study_id"), "laws": earlier.get("laws")} if earlier else None
    found["scaled"] = scaled(found, earlier=earlier or None)
    text = render(found)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        args.md.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
