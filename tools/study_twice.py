#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-study-twice-1"
STUDY = "172"
LAWS = 4
SIZES = (64, 256, 1024)
SEEDS = 3
WALL = 3600
POLL_SECONDS = 20
QUIET_POLLS = 2
REQUEST = "study-twice"
HOST_KEY = re.compile(r"(^|_)(utc|seconds|elapsed|wall|pid|host|hostname|bytes|rss|pss|uss|memory|timing|timings|"
                      r"started|finished|written|built|cpu|io|cost|costs|load|path|folder|root|request_id)($|_)"
                      r"|_at$")
HOST_FIELDS = ("created_utc", "decision_id", "job_id", "seed_peak_memory_bytes", "queue_order", "jobs_seen",
               "rows_changed", "released_hold", "queue_depth", "bundle", "cycle_id", "report_cycle_id",
               "bundle_revision", "source_revision", "heavy_source_revision", "replication_source_revision",
               "checksums", "snapshot_parts", "compute_by_regime", "revision")
HOST_MEMBERS = ("14-compute.json", "25-fleet-and-host.json")
TABLE_KEYS = {"rungs.ndjson.gz": ("campaign_id", "candidate_id", "n"),
              "laws.ndjson.gz": ("campaign_id", "candidate_id"),
              "draws.ndjson.gz": ("campaign_id", "stream_index", "draw_index"),
              "decisions.ndjson.gz": ("campaign_id", "candidate_id", "at_n", "action", "rule", "next_n"),
              "chains.ndjson.gz": ("campaign_id", "candidate_id", "n", "seed", "replicate", "chain", "audit")}
JSON_TEXT = ("facts_json", "inputs_json", "context_json")
PART = re.compile(r"^(campaign_[^/_]+)_reports_[^/]+")


def host_key(key: str, extra: tuple[str, ...] = ()) -> bool:
    return key in HOST_FIELDS or key in extra or HOST_KEY.search(str(key).lower()) is not None


def _host_columns(value: dict, extra: tuple[str, ...]) -> dict:
    columns = value["columns"]
    keep = [i for i, name in enumerate(columns) if not (isinstance(name, str) and host_key(name, extra))]
    rows = [[row[i] for i in keep] if isinstance(row, list) and len(row) == len(columns) else row
            for row in value["rows"]]
    return dict(value, columns=[columns[i] for i in keep], rows=rows)


def normal(value, extra: tuple[str, ...] = ()):
    if isinstance(value, dict) and isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
        value = _host_columns(value, extra)
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if host_key(str(key), extra):
                continue
            if key in JSON_TEXT and isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    pass
            out[key] = normal(inner, extra)
        return out
    if isinstance(value, list):
        inner = [normal(item, extra) for item in value]
        if inner and all(isinstance(item, dict) and "candidate_id" in item for item in inner):
            inner.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return inner
    if isinstance(value, float):
        return float(f"{value:.12g}")
    return value


def _key(row: dict, fields: tuple[str, ...]) -> str:
    return json.dumps([row.get(f) for f in fields], sort_keys=True, default=str)


def _differences(a, b, prefix: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        found = []
        for key in sorted(set(a) | set(b)):
            here = f"{prefix}.{key}" if prefix else str(key)
            if key not in a or key not in b:
                found.append(here)
            else:
                found.extend(_differences(a[key], b[key], here))
        return found
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        found = []
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            found.extend(sorted(set(_differences(x, y, f"{prefix}[]")) - set(found)))
        return found
    return [] if a == b else [prefix]


def compare_rows(name: str, first: list[dict], second: list[dict], extra: tuple[str, ...] = ()) -> dict:
    fields = TABLE_KEYS.get(name, ())
    a = [normal(row, extra) for row in first]
    b = [normal(row, extra) for row in second]
    same = sorted(json.dumps(r, sort_keys=True, default=str) for r in a) == sorted(
        json.dumps(r, sort_keys=True, default=str) for r in b)
    out = {"rows": [len(a), len(b)], "same": same}
    if same:
        return out
    by_a, by_b = {}, {}
    for row in a:
        by_a.setdefault(_key(row, fields), []).append(row)
    for row in b:
        by_b.setdefault(_key(row, fields), []).append(row)
    fields_differ, only_a, only_b, example = {}, [], [], None
    for key in sorted(set(by_a) | set(by_b)):
        left, right = by_a.get(key, []), by_b.get(key, [])
        if not right:
            only_a.append(key)
            continue
        if not left:
            only_b.append(key)
            continue
        for x, y in zip(sorted(left, key=lambda r: json.dumps(r, sort_keys=True, default=str)),
                        sorted(right, key=lambda r: json.dumps(r, sort_keys=True, default=str)), strict=False):
            for field in _differences(x, y):
                fields_differ[field] = fields_differ.get(field, 0) + 1
                if example is None:
                    example = {"key": key, "field": field, "first": _at(x, field), "second": _at(y, field)}
    out.update(fields_differ=dict(sorted(fields_differ.items(), key=lambda kv: -kv[1])), only_first=only_a[:10],
               only_second=only_b[:10], example=example)
    return out


def _at(row: dict, dotted: str):
    node = row
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    text = json.dumps(node, sort_keys=True, default=str)
    return text if len(text) <= 300 else text[:300] + "..."


def members(bundle: Path) -> dict[str, bytes]:
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd is needed to read a study bundle")
    raw = subprocess.run([zstd, "-dc", str(bundle)], capture_output=True, check=True).stdout
    found = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for info in archive.getmembers():
            if info.isfile():
                name = info.name.split("/", 1)[1] if "/" in info.name else info.name
                found[PART.sub(r"\1", name)] = archive.extractfile(info).read()
    return found


def ndjson(payload: bytes) -> list[dict]:
    return [json.loads(line) for line in gzip.decompress(payload).decode("utf-8").splitlines() if line.strip()]


def compare_bundles(first: dict[str, bytes], second: dict[str, bytes], extra: tuple[str, ...] = ()) -> dict:
    names = sorted(set(first) | set(second))
    out = {"contract": CONTRACT, "members": [len(first), len(second)],
           "only_first": sorted(set(first) - set(second)), "only_second": sorted(set(second) - set(first)),
           "tables": {}, "documents": {}, "pages": 0, "host_reports": 0}
    for name in names:
        if name not in first or name not in second:
            continue
        if name.endswith(".ndjson.gz"):
            out["tables"][name] = compare_rows(Path(name).name, ndjson(first[name]), ndjson(second[name]), extra)
        elif Path(name).name in HOST_MEMBERS:
            out["host_reports"] += 1
        elif name.endswith(".json"):
            a, b = normal(json.loads(first[name]), extra), normal(json.loads(second[name]), extra)
            out["documents"][name] = {"same": a == b} if a == b else {
                "same": False, "fields_differ": _differences(a, b)[:20]}
        else:
            out["pages"] += 1
    out["same"] = (not out["only_first"] and not out["only_second"]
                   and all(t["same"] for t in out["tables"].values())
                   and all(d["same"] for d in out["documents"].values()))
    out["host_fields"] = {"named": list(HOST_FIELDS) + list(extra), "pattern": HOST_KEY.pattern,
                          "members": list(HOST_MEMBERS),
                          "reading": ("left out before comparing: when a thing happened, how long it took, how much "
                                      "memory it held, which process, core or folder did it, the database's own row "
                                      "ids and revisions, how deep the queue was, and the host's two reports (14, "
                                      "compute; 25, the fleet and the host); a table's host columns go with them, "
                                      "and a list of laws is compared as a set; every other field of every table "
                                      "and document is compared")}
    return out


def short_design(design: dict, *, laws: int = LAWS, sizes=SIZES, seeds: int = SEEDS) -> dict:
    short = copy.deepcopy(design)
    sizes = [int(n) for n in sizes]
    budgets = {int(n): int(units) for n, units in design["ladder"].get("budgets") or []}
    short["ladder"] = dict(design["ladder"], base=sizes, deep=[], seeds=int(seeds),
                           budgets=[[n, budgets[n]] for n in sizes if n in budgets])
    short["law_budget"] = int(laws)
    return short


def _env(schema: str) -> dict:
    return dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=schema, PYTHONDONTWRITEBYTECODE="1")


def _main_py(var: Path, schema: str, *args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "main.py", "--var", str(var), *args], cwd=ROOT, env=_env(schema),
                          capture_output=True, text=True, timeout=timeout)


def _step(var: Path, schema: str, step: str, *args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), "--step", step, "--var", str(var), *args],
                          cwd=ROOT, env=_env(schema), capture_output=True, text=True, timeout=timeout)


def _must(done: subprocess.CompletedProcess, what: str) -> str:
    if done.returncode != 0:
        raise RuntimeError(f"{what} failed ({done.returncode}):\n{(done.stdout or '')[-3000:]}\n"
                           f"{(done.stderr or '')[-3000:]}")
    return done.stdout


def step_start(var: Path, laws: int, sizes, seeds: int) -> int:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design
    design = study_design.design_for(ROOT, STUDY)
    short = short_design(design, laws=laws, sizes=sizes, seeds=seeds)
    with Repo(f"folder-schema:{os.environ['GSD_TEST_SCHEMA']}") as repo:
        first = study_design.start(repo, short, control.shipped_spec(), var=var, tree=ROOT, log=lambda *_: None)
    print(f"CAMPAIGN {first}")
    return 0


def step_done() -> int:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES
    from graph_scale_dynamics.operations import study as S
    with Repo(f"folder-schema:{os.environ['GSD_TEST_SCHEMA']}") as repo:
        campaigns = [str(row["campaign_id"]) for row in repo.all_campaigns()]
        waiting = []
        for campaign in campaigns:
            budget = S.budget_state(repo, campaign)
            states = [c["state"] for c in repo.candidates(campaign)]
            if budget is not None and budget["state"] != S.DONE:
                waiting.append(f"{campaign}: {budget['laws_held']} of {budget['law_budget']} laws, "
                               f"{'in flight' if budget['reached'] else 'drawing'}")
            elif not states or any(state not in TERMINAL_CANDIDATE_STATES for state in states) \
                    or repo.campaign_pending_work(campaign):
                waiting.append(f"{campaign}: {sum(st not in TERMINAL_CANDIDATE_STATES for st in states)} laws going")
    print("DONE" if campaigns and not waiting else "WAITING " + "; ".join(waiting or ["no campaign yet"]))
    return 0


def run_fleet(var: Path, schema: str, campaign: str, *, workers: int, wall: int, log=print) -> dict:
    out_path = var / "study_twice_fleet.log"
    with open(out_path, "wb") as out:
        fleet = subprocess.Popen([sys.executable, "main.py", "--var", str(var), "run", "--campaign", campaign,
                                  "--workers", str(workers), "--wall", str(wall), "--no-dashboard", "--no-browser",
                                  "--no-power-telemetry"], cwd=ROOT, env=_env(schema), stdout=out,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        deadline, quiet, asked = time.monotonic() + wall + 900, 0, None
        while fleet.poll() is None:
            time.sleep(POLL_SECONDS)
            said = _step(var, schema, "done", timeout=600).stdout or ""
            quiet = quiet + 1 if re.search(r"^DONE$", said, re.M) else 0
            if quiet >= QUIET_POLLS or time.monotonic() > deadline:
                asked = "every campaign done" if quiet >= QUIET_POLLS else "past its wall"
                fleet.send_signal(signal.SIGTERM)
                break
        code = fleet.wait(timeout=900)
    tail = out_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    if not (code == 0 or (code == 130 and asked == "every campaign done")):
        raise RuntimeError(f"the fleet ended {code} ({asked or 'by itself'}):\n{tail}")
    log(f"the fleet stopped: {asked or 'it had no work'}")
    return {"exit": code, "stopped": asked or "it had no work"}


def step_bundle(var: Path) -> int:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.reporting import study_bundle
    database = f"folder-schema:{os.environ['GSD_TEST_SCHEMA']}"
    base = var / "reports"
    runs = base / "study" / "runs" / REQUEST
    runs.mkdir(parents=True, exist_ok=True)
    with Repo(database) as repo:
        campaigns = sorted((str(row["campaign_id"]) for row in repo.all_campaigns()), key=lambda c: (len(c), c))
    for campaign in campaigns:
        done = subprocess.run([sys.executable, "-m", "graph_scale_dynamics.services.reporter.study_run", "--worker",
                               "--campaign", campaign, "--db", database, "--base", str(base), "--progress-dir",
                               str(runs), "--request-id", REQUEST, "--workers", "1", "--memory-budget",
                               str(2 * 1024 ** 3)], cwd=ROOT, env=dict(os.environ), capture_output=True, text=True,
                              timeout=3600)
        if done.returncode != 0:
            print(f"campaign {campaign}'s report cycle", (done.stdout or "")[-3000:], (done.stderr or "")[-3000:],
                  sep="\n")
            return done.returncode
    with Repo(database) as repo:
        entry = study_bundle.build(base, repo, campaigns, request_id=REQUEST, finished=campaigns)
    print(f"BUNDLE {study_bundle.bundles_dir(base) / entry['filename']}")
    return 0


def run_once(tag: str, out: dict, *, laws: int, sizes, seeds: int, workers: int, wall: int, log=print) -> dict:
    from graph_scale_dynamics.db.connection import connect_database
    schema = f"gsd_twice_{tag}_{uuid.uuid4().hex[:10]}"
    var = ROOT / f".study_twice_{tag}_{uuid.uuid4().hex[:8]}"
    out.update(folder=var.name, schema=schema)
    admin = connect_database("folder")
    try:
        admin.execute(f"CREATE SCHEMA {schema}")
    finally:
        admin.close()
    started = time.monotonic()
    _must(_main_py(var, schema, "init", timeout=900), "init")
    _must(_main_py(var, schema, "benchmark", timeout=1800), "benchmark")
    campaign = re.search(r"^CAMPAIGN (\S+)$", _must(_step(var, schema, "start", "--laws", str(laws), "--sizes",
                                                         ",".join(str(n) for n in sizes), "--seeds", str(seeds),
                                                         timeout=900), "the study's start"), re.M).group(1)
    log(f"{tag}: study started in {var.name}, campaign {campaign}")
    out["fleet"] = run_fleet(var, schema, campaign, workers=workers, wall=wall, log=lambda line: log(f"{tag}: {line}"))
    out["fleet_seconds"] = round(time.monotonic() - started, 1)
    log(f"{tag}: {out['fleet_seconds']} s to here")
    bundle = re.search(r"^BUNDLE (.+)$", _must(_step(var, schema, "bundle", "--campaign", campaign, timeout=3900),
                                               "the bundle"), re.M).group(1)
    out.update(campaign=campaign, bundle=bundle, seconds=round(time.monotonic() - started, 1))
    log(f"{tag}: bundle {Path(bundle).name}")
    return out


def drop(run: dict) -> None:
    from graph_scale_dynamics.db.connection import connect_database
    shutil.rmtree(ROOT / run["folder"], ignore_errors=True)
    admin = connect_database("folder")
    try:
        admin.execute(f"DROP SCHEMA IF EXISTS {run['schema']} CASCADE")
    finally:
        admin.close()


def render(found: dict) -> str:
    lines = [f"study twice ({found['contract']}): " + ("the same bundle" if found["same"] else "the bundles differ"),
             f"  members {found['members'][0]} and {found['members'][1]}; pages not compared {found['pages']}, the "
             f"host's reports not compared {found.get('host_reports', 0)}"]
    for name, table in found["tables"].items():
        lines.append(f"  {name}: rows {table['rows'][0]} and {table['rows'][1]}, "
                     + ("the same" if table["same"] else f"differ in {table.get('fields_differ')}"))
    differ = [name for name, doc in found["documents"].items() if not doc["same"]]
    lines.append(f"  documents: {len(found['documents']) - len(differ)} of {len(found['documents'])} the same"
                 + (f"; differ: {', '.join(differ[:8])}" if differ else ""))
    for name in differ[:8]:
        lines.append(f"    {name}: {found['documents'][name]['fields_differ'][:6]}")
    if found["only_first"] or found["only_second"]:
        lines.append(f"  only in the first: {found['only_first'][:6]}; only in the second: {found['only_second'][:6]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/study_twice.py: see docs/TOOLS.md")
    parser.add_argument("--laws", type=int, default=LAWS)
    parser.add_argument("--sizes", default=",".join(str(n) for n in SIZES))
    parser.add_argument("--seeds", type=int, default=SEEDS)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--wall", type=int, default=WALL)
    parser.add_argument("--keep", action="store_true", help="keep both folders and schemas")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path, metavar="BUNDLE", help="compare two bundles already made")
    parser.add_argument("--step", choices=("start", "done", "bundle"), help=argparse.SUPPRESS)
    parser.add_argument("--var", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--campaign", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    sizes = [int(n) for n in str(args.sizes).split(",") if n]
    if args.step == "start":
        return step_start(args.var, args.laws, sizes, args.seeds)
    if args.step == "done":
        return step_done()
    if args.step == "bundle":
        return step_bundle(args.var)
    if args.compare:
        found = compare_bundles(members(args.compare[0]), members(args.compare[1]))
    else:
        runs = []
        try:
            for tag in ("a", "b"):
                runs.append({})
                run_once(tag, runs[-1], laws=args.laws, sizes=sizes, seeds=args.seeds, workers=args.workers,
                                     wall=args.wall, log=lambda line: print(line, flush=True))
            found = compare_bundles(members(Path(runs[0]["bundle"])), members(Path(runs[1]["bundle"])))
            found["runs"] = runs
            found["design"] = {"study": STUDY, "laws": args.laws, "sizes": sizes, "seeds": args.seeds,
                               "workers": args.workers}
            if args.json:
                for run in runs:
                    shutil.copy2(run["bundle"], args.json.parent / f"study_twice_{run['folder']}.tar.zst")
        finally:
            if not args.keep:
                for run in runs:
                    if run.get("schema"):
                        drop(run)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if found["same"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
