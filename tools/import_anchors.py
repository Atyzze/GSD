#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.db.repo import Repo, connect  # noqa: E402
from graph_scale_dynamics.research import anchors  # noqa: E402

def read_env(folder: Path) -> dict[str, str]:
    env = folder / ".env.postgres"
    if not env.is_file():
        raise SystemExit(f"{folder} has no .env.postgres: not a GSD folder, or its database was removed")
    values = {}
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def dsn_for(values: dict[str, str]) -> str:
    query = urlencode({"host": str(Path(values["POSTGRES_SOCKET"]).expanduser().resolve())})
    return (f"postgresql://{quote(values['POSTGRES_USER'], safe='')}:{quote(values['POSTGRES_PASSWORD'], safe='')}@/"
            f"{quote(values['POSTGRES_DB'], safe='')}?{query}")


def instance(folder: Path, action: str) -> int:
    helper = folder / "tools" / "postgres_instance.py"
    if not helper.is_file():
        raise SystemExit(f"{folder} has no tools/postgres_instance.py")
    return subprocess.run([sys.executable, str(helper), action], cwd=folder,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def picks(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    return list((json.loads(path.read_text(encoding="utf-8")) or {}).get("picks") or [])


def gather(conn, chosen: list[dict], origin: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for pick in chosen:
        prefix = str(pick.get("candidate_prefix") or "").strip()
        if len(prefix) < 6:
            continue
        for row in conn.execute("SELECT campaign_id, candidate_id FROM candidates WHERE candidate_id LIKE ?",
                                (prefix + "%",)).fetchall():
            reason = {"rule": "operator", "note": str(pick.get("note") or "")}
            found[str(row["candidate_id"])] = {"campaign_id": str(row["campaign_id"]), "reason": reason,
                                               "note": str(pick.get("note") or "")}
    out = []
    kept = stored(conn)
    for law, entry in found.items():
        if law in kept:
            continue
        out.append(anchors.make_anchor(
            candidate_id=law, campaign_id=entry["campaign_id"],
            spec=anchors.law_spec(conn, entry["campaign_id"], law),
            readings=anchors.law_readings(conn, entry["campaign_id"], law),
            reason=entry["reason"], origin=origin, note=entry.get("note", "")))
    for law, anchor in kept.items():
        out.append(dict(anchor, origin=dict(anchor.get("origin") or {}, **origin)))
    return out


def stored(conn) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sql, column, args in (("SELECT document FROM anchors", "document", ()),
                              ("SELECT value FROM control WHERE key LIKE ?", "value", (anchors.KEY_PREFIX + "%",))):
        try:
            rows = conn.execute(sql, args).fetchall()
        except Exception:  # noqa: BLE001
            if hasattr(conn, "rollback_if_open"):
                conn.rollback_if_open()
            continue
        for row in rows:
            try:
                anchor = json.loads(row[column])
            except (TypeError, ValueError):
                continue
            if isinstance(anchor, dict) and anchor.get("candidate_id"):
                out.setdefault(str(anchor["candidate_id"]), anchor)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/import_anchors.py: see docs/TOOLS.md")
    parser.add_argument("folder", help="the other GSD folder, the one to import anchors from")
    parser.add_argument("--picks", default=None,
                        help="a file of laws the operator names, {\"picks\": [...]} (default: none)")
    args = parser.parse_args(argv)
    folder = Path(args.folder).expanduser().resolve()
    if folder == ROOT.resolve():
        raise SystemExit("that is this folder; name the one to import from")
    values = read_env(folder)
    build = (folder / "BUILD_NUMBER").read_text().strip() if (folder / "BUILD_NUMBER").is_file() else None
    origin = {"folder": str(folder), "build": build, "imported_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    started = instance(folder, "status") != 0
    if started and instance(folder, "up") != 0:
        raise SystemExit(f"could not start the database of {folder}")
    try:
        conn = connect(dsn_for(values))
        try:
            conn.execute("SET default_transaction_read_only = on")
            imported = gather(conn, picks(None if args.picks is None else Path(args.picks)), origin)
        finally:
            conn.close()
    finally:
        if started:
            instance(folder, "down")
    added = kept = 0
    with Repo("folder") as repo:
        for anchor in imported:
            if anchors.get(repo, anchor["candidate_id"]) is not None:
                kept += 1
                continue
            anchors.put(repo, anchor)
            added += 1
    out_dir = ROOT / "var" / "anchors"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"import_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out.write_text(json.dumps({"origin": origin, "anchors": imported}, indent=1, sort_keys=True), encoding="utf-8")
    incomplete = sum(1 for a in imported if not a.get("spec_complete"))
    print(f"{len(imported)} anchor(s) found in {folder}: {added} added, {kept} already here"
          + (f", {incomplete} with an incomplete spec" if incomplete else ""))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
