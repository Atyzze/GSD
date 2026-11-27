from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-dex-1"
NAME, CHAINS, RUNGS, README = "dex.json", "chains.ndjson.gz", "rungs.ndjson.gz", "README.json"
STUDY, LAWS, FOCUS = "study.json", "tables/laws.ndjson.gz", "focus.json"
BUNDLE_CHAINS, BUNDLE_RUNGS = "tables/chains.ndjson.gz", "tables/rungs.ndjson.gz"
DEX_FILES = (NAME, CHAINS, RUNGS)
BUNDLE_FILES = (STUDY, LAWS, FOCUS, BUNDLE_CHAINS, BUNDLE_RUNGS)
SEEDING_FILES = (NAME, STUDY, LAWS, FOCUS)
PREFIX = "dex_"
ARCHIVE_ENDINGS = (".tar.zst", "_tar.zst")
TOP = 100
FOLDER = "export"
EVERY_SECONDS = 3600.0
NEW_GAP_SECONDS = 600.0
LOOK_SECONDS = 60.0
KEPT_ID = 16
FLAG = "dex_written"
DEX, BUNDLE, OWN = "dex", "study bundle", "folder"
RUN_AGAIN = ("moves", "accepted_moves", "final_edges", "peak_edges", "max_degree", "work_units", "termination")
CHAIN_KEPT = ("n", "seed", "replicate", "chain", "init", "ran", "ended_at_cap", "termination", "final_edges",
              "final_mean_degree", "peak_edges", "peak_mean_degree", "max_degree", "moves", "accepted_moves",
              "work_units", "work_parts", "seconds", "seed_peak_memory_bytes", "sweeps_multiplier", "campaign_id")
RUNG_DROPPED = ("candidate_id",)
ZSTD_LEVEL = 9
_TRIED: dict[str, list] = {}


def _dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        found = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        found = None
    return found if isinstance(found, dict) else {}


def name_of(path) -> str:
    return Path(str(path)).name.removesuffix(".tar.zst").removesuffix("_tar.zst")


def _root_of(path: Path) -> Path:
    if (path / NAME).is_file() or (path / STUDY).is_file():
        return path
    inner = [p.parent for p in path.glob(f"*/{NAME}")] + [p.parent for p in path.glob(f"*/{STUDY}")]
    if len(inner) != 1:
        raise ValueError(f"{path} holds {len(inner)} dexes or study bundles: name one")
    return inner[0]


def _from_archive(path: Path, wanted) -> dict[str, bytes]:
    zstd = shutil.which("zstd")
    if not zstd:
        raise ValueError("reading a .tar.zst needs the zstd executable; give the unpacked folder instead")
    wanted, found = set(wanted), {}
    with subprocess.Popen([zstd, "-dc", str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as unzip:
        with tarfile.open(fileobj=unzip.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                parts = member.name.split("/", 1)
                name = parts[1] if len(parts) == 2 else parts[0]
                if name in wanted and name not in found:
                    handle = archive.extractfile(member)
                    found[name] = handle.read() if handle is not None else b""
                if NAME in found and all(n in found for n in DEX_FILES if n in wanted):
                    break
                if STUDY in found and all(n in found for n in wanted if n not in DEX_FILES):
                    break
        unzip.stdout.close()
        unzip.kill()
    return found


def files(path, wanted=DEX_FILES + BUNDLE_FILES) -> dict[str, bytes]:
    path = Path(str(path or "").strip()).expanduser()
    if not str(path) or not path.exists():
        raise ValueError(f"nothing at {path}: give a dex or a study bundle, its .tar.zst or its folder")
    if path.is_dir():
        root = _root_of(path)
        return {name: (root / name).read_bytes() for name in wanted if (root / name).is_file()}
    return _from_archive(path, wanted)


def is_dex(found: dict) -> bool:
    return NAME in found


def _rows(raw: bytes | None):
    if not raw:
        return
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _fingerprint_ok(law: str, spec: dict) -> bool:
    from graph_scale_dynamics.dsl import dsl
    try:
        return dsl.fingerprint(dsl.normalize(spec)) == law
    except Exception:  # noqa: BLE001
        return False


def _seen(source: str, study, code, score, top_n, science: str | None, campaign=None) -> dict:
    return {"source": source, "study": None if study in (None, "") else str(study), "code": code,
            "score": None if score is None else int(score), "top_n": None if top_n is None else int(top_n),
            "science": science, "campaign": None if campaign is None else str(campaign)}


def _entry(law: str, spec: dict) -> dict:
    return {"law": law, "spec": spec, "codes": [], "seen": [], "verified": []}


def _add_seen(entry: dict, seen: dict) -> None:
    from graph_scale_dynamics.operations import law_code as LC
    if seen.get("code"):
        seen = dict(seen, code=LC.upgraded(seen["code"], seen.get("study")))
    if seen.get("code") and seen["code"] not in entry["codes"]:
        entry["codes"].append(seen["code"])
    key = (seen.get("source"), seen.get("code"), seen.get("score"), seen.get("science"))
    if all((s.get("source"), s.get("code"), s.get("score"), s.get("science")) != key for s in entry["seen"]):
        entry["seen"].append(seen)


def _chain(row: dict, law: str, source: str, science: str | None, study) -> dict:
    kept = {key: row.get(key) for key in CHAIN_KEPT}
    return dict(kept, law=law, source=source, science=science, study=None if study in (None, "") else str(study))


def _rung(row: dict, law: str, source: str, science: str | None, study) -> dict:
    kept = {key: value for key, value in row.items() if key not in RUNG_DROPPED}
    return dict(kept, law=law, source=source, science=science, study=None if study in (None, "") else str(study))


def _regions_of(focus: dict, study, keep: set[str], source: str) -> list[dict]:
    from graph_scale_dynamics.operations import law_code as LC
    out = []
    for region in focus.get("regions") or []:
        holders = [str(law) for law in region.get("laws") or [] if str(law) in keep]
        if not holders:
            continue
        origin = region.get("seeded_from") or {}
        out.append(dict({k: v for k, v in region.items() if k not in ("sources",)}, holders=holders,
                        study=str(origin.get("study") or study or ""),
                        number=int(origin.get("number") or region.get("number") or 0),
                        labels=[LC.upgraded(label, study) for label in region.get("labels") or []],
                        source=source))
    return out


def part_of_bundle(found: dict, name: str) -> dict:
    meta = json.loads(found[STUDY])
    study = str(meta.get("study_id") or meta.get("study") or "")
    science = _dict(meta.get("science"))
    sha = science.get("sha256")
    focus = _dict(found.get(FOCUS, b"null").decode("utf-8")) if found.get(FOCUS) else {}
    laws: dict[str, dict] = {}
    specs: dict[str, dict] = {}
    for row in _rows(found.get(LAWS)):
        law, spec = str(row["candidate_id"]), _dict(row.get("spec"))
        if spec:
            specs.setdefault(law, spec)
        score = int(_dict(row.get("law_score")).get("score") or 0)
        if score > 0 and spec and _fingerprint_ok(law, spec):
            entry = laws.setdefault(law, _entry(law, spec))
            _add_seen(entry, _seen(name, study, row.get("code"), score, row.get("top_n"), sha, row.get("campaign_id")))
    for record in focus.get("seeded") or []:
        if record.get("selected") is False:
            continue
        for law, earlier in (record.get("laws") or {}).items():
            spec = specs.get(str(law))
            if not spec or not _fingerprint_ok(str(law), spec):
                continue
            entry = laws.setdefault(str(law), _entry(str(law), spec))
            _add_seen(entry, _seen(str(record.get("bundle") or ""), record.get("study"), earlier.get("code"),
                                   earlier.get("score"), None, record.get("science"), record.get("campaign")))
    chains = [_chain(row, str(row["candidate_id"]), name, sha, study)
              for row in _rows(found.get(BUNDLE_CHAINS)) if str(row.get("candidate_id")) in laws]
    rungs = [_rung(row, str(row["candidate_id"]), name, sha, study)
             for row in _rows(found.get(BUNDLE_RUNGS)) if str(row.get("candidate_id")) in laws]
    return {"name": name, "kind": BUNDLE, "study": study, "build": meta.get("build_number"),
            "made_utc": meta.get("built_utc"), "science": science, "laws": laws,
            "regions": _regions_of(focus, study, set(laws), name), "chains": chains, "rungs": rungs,
            "sources": [{"name": name, "kind": BUNDLE, "study": study, "build": meta.get("build_number"),
                         "made_utc": meta.get("built_utc"), "science": sha, "laws": len(laws),
                         "sha256": hashlib.sha256(found[LAWS]).hexdigest()}]}


def part_of_dex(found: dict, name: str) -> dict:
    dex = json.loads(found[NAME])
    if dex.get("contract") != CONTRACT:
        raise ValueError(f"{name} is not a dex of contract {CONTRACT}")
    laws = {}
    for entry in dex.get("laws") or []:
        law, spec = str(entry.get("law")), _dict(entry.get("spec"))
        if spec and _fingerprint_ok(law, spec):
            laws[law] = dict(entry, spec=spec, codes=list(entry.get("codes") or []),
                             seen=list(entry.get("seen") or []), verified=list(entry.get("verified") or []))
    return {"name": name, "kind": DEX, "study": (dex.get("made_by") or {}).get("study"),
            "build": (dex.get("made_by") or {}).get("build"), "made_utc": dex.get("made_utc"),
            "science": _dict(dex.get("science")), "laws": laws, "regions": list(dex.get("regions") or []),
            "verify_to": level_of(dex.get("verify_to")),
            "chains": [row for row in _rows(found.get(CHAINS)) if str(row.get("law")) in laws],
            "rungs": [row for row in _rows(found.get(RUNGS)) if str(row.get("law")) in laws],
            "sources": list(dex.get("sources") or []) + [{"name": name, "kind": DEX, "made_utc": dex.get("made_utc"),
                                                         "study": (dex.get("made_by") or {}).get("study"),
                                                         "science": _dict(dex.get("science")).get("sha256"),
                                                         "laws": len(laws), "sha256": dex_sha256(dex)}]}


def level_of(value) -> int | None:
    try:
        found = int(value)
    except (TypeError, ValueError):
        return None
    return found if found > 0 else None


def read_part(path) -> dict:
    found = files(path)
    name = name_of(path)
    if is_dex(found):
        return part_of_dex(found, name)
    if STUDY not in found or LAWS not in found:
        raise ValueError(f"{path} is neither a dex ({NAME}) nor a study bundle with its laws table")
    return part_of_bundle(found, name)


def dex_sha256(dex: dict) -> str:
    laws = sorted((str(e.get("law")), sorted(str(c) for c in e.get("codes") or [])) for e in dex.get("laws") or [])
    return hashlib.sha256(json.dumps(laws, separators=(",", ":")).encode("utf-8")).hexdigest()


def standing(entry: dict, science: str | None) -> int | None:
    scores = [int(s["score"]) for s in entry.get("seen") or [] if s.get("score") is not None
              and (science is None or s.get("science") == science)]
    return max(scores) if scores else None


def best_score(entry: dict) -> int:
    return max((int(s["score"]) for s in entry.get("seen") or [] if s.get("score") is not None), default=0)


def ranked(laws: dict[str, dict], science: str | None) -> list[str]:
    def key(law: str):
        here = standing(laws[law], science)
        return (here is None, -(here or 0), -best_score(laws[law]), law)
    return sorted(laws, key=key)


def merge(parts: list[dict], *, science: dict, made_by: dict, verify_to=None) -> dict:
    from graph_scale_dynamics.operations import law_code as LC
    sha = science.get("sha256")
    laws: dict[str, dict] = {}
    chains: dict[tuple, dict] = {}
    rungs: dict[tuple, dict] = {}
    regions: dict[tuple, dict] = {}
    sources: dict[str, dict] = {}
    for part in parts:
        for law, entry in part["laws"].items():
            held = laws.setdefault(law, _entry(law, entry["spec"]))
            for code in entry.get("codes") or []:
                code = LC.upgraded(code, None)
                if code and code not in held["codes"]:
                    held["codes"].append(code)
            for seen in entry.get("seen") or []:
                _add_seen(held, dict(seen))
            for check in entry.get("verified") or []:
                if check not in held["verified"]:
                    held["verified"].append(check)
        for row in part.get("chains") or []:
            chains.setdefault(like(row) + (row.get("science"),) + tuple(str(row.get(k)) for k in RUN_AGAIN), row)
        for row in part.get("rungs") or []:
            rungs.setdefault((row.get("law"), row.get("n"), row.get("source"), row.get("campaign_id")), row)
        for region in part.get("regions") or []:
            regions.setdefault((str(region.get("study") or ""), int(region.get("number") or 0)), region)
        for source in part.get("sources") or []:
            sources.setdefault(str(source.get("name")), source)
    order = ranked(laws, sha)
    sizes: dict[str, set] = {}
    for row in chains.values():
        if row.get("n"):
            sizes.setdefault(str(row.get("law")), set()).add(int(row["n"]))
    for place, law in enumerate(order):
        laws[law]["score"] = standing(laws[law], sha)
        laws[law]["rank"] = place + 1
        laws[law]["sizes"] = sorted(sizes.get(law) or ())
    levels = [v for v in [level_of(verify_to)] + [level_of(part.get("verify_to")) for part in parts] if v]
    return {"contract": CONTRACT, "made_utc": utc_now(), "made_by": made_by, "science": science,
            **({"verify_to": max(levels)} if levels else {}),
            "sources": list(sources.values()), "laws": [laws[law] for law in order],
            "top": [law for law in order if laws[law]["score"]][:TOP], "regions": list(regions.values()),
            "chains": list(chains.values()), "rungs": list(rungs.values())}


def like(row: dict) -> tuple:
    return (str(row.get("law")), row.get("n"), row.get("seed"), row.get("replicate"), row.get("chain"), row.get("init"),
            row.get("moves"))


def verify(recorded_rows: list[dict], own_chains: list[dict], *, by: str, science: str | None) -> dict[str, dict]:
    recorded: dict[tuple, dict] = {}
    starts: set[tuple] = set()
    for row in recorded_rows:
        if row.get("science") == science and row.get("source") != by and row.get("ran"):
            recorded.setdefault(like(row), row)
            starts.add(like(row)[:6])
    found: dict[str, dict] = {}
    for row in own_chains:
        if not row.get("ran"):
            continue
        earlier = recorded.get(like(row))
        if earlier is None:
            if like(row)[:6] in starts:
                check = found.setdefault(str(row["law"]), _check(by))
                check["other_length"] += 1
            continue
        check = found.setdefault(str(row["law"]), _check(by))
        same = all(row.get(k) == earlier.get(k) for k in RUN_AGAIN)
        check["agree" if same else "differ"] += 1
        if int(row["n"]) not in check["sizes"]:
            check["sizes"].append(int(row["n"]))
        if str(earlier.get("source")) not in check["against"]:
            check["against"].append(str(earlier.get("source")))
        if not same and "first_differ" not in check:
            check["first_differ"] = {"n": row.get("n"), "seed": row.get("seed"), "chain": row.get("chain"),
                                     **{k: [earlier.get(k), row.get(k)] for k in RUN_AGAIN
                                        if row.get(k) != earlier.get(k)}}
    for check in found.values():
        check["sizes"].sort()
    return {law: check for law, check in found.items() if check["agree"] or check["differ"]}


def _check(by: str) -> dict:
    return {"by": by, "at": utc_now(), "agree": 0, "differ": 0, "other_length": 0, "sizes": [], "against": []}


def _gz(rows) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n")
    return buffer.getvalue()


def document(dex: dict) -> dict:
    return {key: value for key, value in dex.items() if key not in ("chains", "rungs")} | {
        "counts": {"laws": len(dex["laws"]), "top": len(dex["top"]), "regions": len(dex["regions"]),
                   "chains": len(dex["chains"]), "rungs": len(dex["rungs"]), "sources": len(dex["sources"]),
                   "verified": sum(1 for e in dex["laws"] if any(int(v.get("agree") or 0) and not int(v.get("differ") or 0)
                                                                 for v in e.get("verified") or [])),
                   "differs": sum(1 for e in dex["laws"] if any(int(v.get("differ") or 0)
                                                                for v in e.get("verified") or []))}}


def readme() -> dict:
    return {"contract": CONTRACT, "files": {
        NAME: ("every law the dex holds, best first: its spec (whose fingerprint is its id), every code it was known by, "
               "every reading of its score with the study, the source and the science that read it (`seen`), its "
               "score under the dex's own science (`score`, null where no part of that science read it), the sizes "
               "its chains reach, and every run again checked against the chains recorded for it (`verified`); `top` "
               "the first hundred that score; `regions` the mapped regions; `sources` every dex, study bundle and "
               "folder merged into it"),
        CHAINS: ("one row per law, size, seed and start from every source: what a run again on the same science must "
                 "reproduce to the bit (moves, accepted moves, edges, largest degree, work), and its seconds and the "
                 "seed's peak memory"),
        RUNGS: "one row per law, size and source: the probes' readings and the rung's means"},
        "reading": "data only: no report, no page; read by operations/dex.py, merged into the next dex"}


def members(dex: dict, top: str) -> list[tuple[str, bytes]]:
    return [(f"{top}/{NAME}", json.dumps(document(dex), sort_keys=True, indent=1, default=str).encode("utf-8")),
            (f"{top}/{CHAINS}", _gz(dex["chains"])), (f"{top}/{RUNGS}", _gz(dex["rungs"])),
            (f"{top}/{README}", json.dumps(readme(), indent=1, sort_keys=True).encode("utf-8"))]


def write(dex: dict, folder: Path, label: str) -> Path:
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    top = f"{PREFIX}{label}_{stamp}"
    target = Path(folder) / f"{top}.tar.zst"
    zstd = shutil.which("zstd")
    if not zstd:
        raise ValueError("writing a dex needs the zstd executable")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, payload in members(dex, top):
            info = tarfile.TarInfo(name)
            info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = 0, 0o644, 0, 0, "", ""
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    done = subprocess.run([zstd, f"-{ZSTD_LEVEL}", "-q", "-f", "-o", str(partial)], input=buffer.getvalue(),
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if done.returncode != 0:
        partial.unlink(missing_ok=True)
        raise ValueError(f"zstd failed writing the dex: {done.stderr.decode('utf-8', 'replace').strip()[:200]}")
    partial.replace(target)
    return target


def seeding(part: dict) -> dict:
    from graph_scale_dynamics.operations import law_code as LC
    sha = (part.get("science") or {}).get("sha256")
    order = ranked(part["laws"], sha)
    specs = {law: part["laws"][law]["spec"] for law in order}
    codes = {law: (part["laws"][law].get("codes") or [law[:10]])[0] for law in order}
    scoring, laws_only = [], []
    for place, law in enumerate(order):
        here = standing(part["laws"][law], sha)
        if here:
            scoring.append({"law": law, "campaign": "0", "score": int(here), "number": place, "code": codes[law]})
        else:
            laws_only.append(law)
    regions = []
    for region in part.get("regions") or []:
        holders = [law for law in region.get("holders") or region.get("laws") or [] if law in specs]
        if holders:
            regions.append(dict(region, holders=holders,
                                labels=[LC.upgraded(label, region.get("study")) for label in region.get("labels") or []]))
    return {"name": part["name"], "kind": part["kind"], "built_utc": part.get("made_utc"), "build": part.get("build"),
            "study": str(part.get("study") or ""), "science": part.get("science") or {}, "specs": specs,
            "scoring": scoring, "laws_only": laws_only, "regions": regions, "codes": codes,
            "verify_to": level_of(part.get("verify_to")),
            "sha256": dex_sha256({"laws": list(part["laws"].values())})}


def study_campaigns(repo, study: str) -> list[str]:
    out = []
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if str(design.get("study")) == str(study):
            out.append(str(campaign["campaign_id"]))
    return sorted(out, key=lambda c: (not c.isdigit(), int(c) if c.isdigit() else 0, c))


def own_part(repo, *, study: str, blobs: Path | None, science: dict, state: dict | None = None) -> dict:
    from graph_scale_dynamics.operations import study_seed
    from graph_scale_dynamics.reporting import study_tables as T
    sha = science.get("sha256")
    name = f"study {study}'s folder"
    campaigns = study_campaigns(repo, study)
    points: dict = {}
    rung_rows = list(T.rung_rows(repo, campaigns, points))
    laws: dict[str, dict] = {}
    specs: dict[str, dict] = {}
    for row in T.law_rows(repo, campaigns, points):
        law, spec = str(row["candidate_id"]), _dict(row.get("spec"))
        if spec:
            specs.setdefault(law, spec)
        score = int(_dict(row.get("law_score")).get("score") or 0)
        if score > 0 and spec:
            entry = laws.setdefault(law, _entry(law, spec))
            _add_seen(entry, _seen(name, study, row.get("code"), score, row.get("top_n"), sha, row.get("campaign_id")))
    for record in study_seed.records(state):
        if not study_seed.selected(record):
            continue
        for law, earlier in (record.get("laws") or {}).items():
            spec = specs.get(str(law))
            if not spec:
                continue
            entry = laws.setdefault(str(law), _entry(str(law), spec))
            _add_seen(entry, _seen(str(record.get("bundle") or ""), record.get("study"), earlier.get("code"),
                                   earlier.get("score"), None, record.get("science")))
        for law in record.get("laws_only") or []:
            spec = specs.get(str(law))
            if spec:
                entry = laws.setdefault(str(law), _entry(str(law), spec))
                _add_seen(entry, _seen(str(record.get("bundle") or ""), record.get("study"),
                                       (record.get("codes") or {}).get(str(law)), None, None, record.get("science")))
    chains = []
    if blobs is not None and Path(blobs).is_dir() and laws:
        from graph_scale_dynamics.artifact_store.blobstore import BlobStore
        chains = [_chain(row, str(row["candidate_id"]), name, sha, study)
                  for row in T.chain_rows(repo, campaigns, BlobStore(Path(blobs)), laws=set(laws))
                  if row.get("candidate_id") is not None]
    rungs = [_rung(row, str(row["candidate_id"]), name, sha, study) for row in rung_rows
             if str(row["candidate_id"]) in laws]
    regions = _regions_of({"regions": (state or {}).get("regions") or []}, study, set(laws), name)
    return {"name": name, "kind": OWN, "study": study, "made_utc": utc_now(), "science": science, "laws": laws,
            "regions": regions, "chains": chains, "rungs": rungs,
            "sources": [{"name": name, "kind": OWN, "study": study, "made_utc": utc_now(), "science": sha,
                         "laws": len(laws)}]}


def imported_parts(state: dict | None, import_folder: Path | None) -> list[dict]:
    from graph_scale_dynamics.operations import imports, study_seed
    if import_folder is None or not Path(import_folder).is_dir():
        return []
    wanted = {str(r.get("bundle")) for r in study_seed.records(state) if study_seed.selected(r)}
    out = []
    for path in sorted(Path(import_folder).iterdir(), key=lambda p: p.name):
        if imports.is_bundle(path) and name_of(path) in wanted:
            try:
                out.append(read_part(path))
            except (OSError, ValueError, KeyError):
                continue
    return out


def of_folder(repo, *, blobs: Path | None, import_folder: Path | None, build=None) -> dict:
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.reporting import science_contract
    state = focus.load(repo)
    study = str((state or {}).get("study") or "")
    if not study:
        found = focus.studies(repo)
        study = str(found[0]["study"]) if len(found) == 1 else ""
    if not study:
        raise ValueError("this folder holds no single study to write a dex of")
    science = science_contract.science()[0]
    own = own_part(repo, study=study, blobs=blobs, science=science, state=state)
    parts = imported_parts(state, import_folder)
    dex = merge(parts + [own], science=science, made_by={"study": study, "build": build, "folder": own["name"]})
    checks = verify([row for part in parts for row in part.get("chains") or []], own["chains"], by=own["name"],
                     science=science.get("sha256"))
    for entry in dex["laws"]:
        check = checks.get(entry["law"])
        if check is not None:
            entry["verified"] = [v for v in entry["verified"] if v.get("by") != own["name"]] + [check]
    return dex


def held_now(state: dict | None) -> dict:
    return {"regions": len((state or {}).get("regions") or []),
            "confirmed": int((((state or {}).get("dex_check") or {}).get("counts") or {}).get("confirmed") or 0)}


def write_folder(repo, root: Path, *, blobs: Path | None, build=None, why: str | None = None) -> Path:
    from graph_scale_dynamics.operations import focus, imports
    root = Path(root)
    state = focus.load(repo)
    dex = of_folder(repo, blobs=blobs, import_folder=root / imports.FOLDER, build=build)
    path = write(dex, root / FOLDER, str(dex["made_by"]["study"]))
    counts = document(dex)["counts"]
    repo.set_flag(FLAG, json.dumps({"at": time.time(), "utc": utc_now(), "path": str(path), "counts": counts,
                                    "why": why or "written on the Map page", **held_now(state),
                                    "laws": sorted(str(e["law"])[:KEPT_ID] for e in dex["laws"])}, sort_keys=True))
    return path


def scoring_here(repo, study: str) -> set[str]:
    from graph_scale_dynamics.observability import score_board
    from graph_scale_dynamics.operations import focus
    out = set()
    for campaign_id in focus.own_campaigns(repo, str(study)):
        for law, score in (score_board.board(repo, campaign_id).get("scores") or {}).items():
            if int(score.get("score") or 0) > 0:
                out.add(str(law))
    return out


def news(repo, state: dict, last: dict) -> str | None:
    known = set(last.get("laws") or [])
    new = {law[:KEPT_ID] for law in scoring_here(repo, str(state.get("study") or ""))} - known
    if new:
        return f"{len(new)} law{'' if len(new) == 1 else 's'} scoring here that the last dex does not hold"
    now = held_now(state)
    if now["regions"] > int(last.get("regions") or 0):
        more = now["regions"] - int(last.get("regions") or 0)
        return f"{more} zone{'' if more == 1 else 's'} mapped since the last dex"
    if now["confirmed"] > int(last.get("confirmed") or 0):
        more = now["confirmed"] - int(last.get("confirmed") or 0)
        return f"{more} law{'' if more == 1 else 's'} of the dex verified here since the last dex"
    return None


_LOOKED: dict[str, float] = {}


def written(repo) -> dict:
    try:
        found = json.loads(repo.get_flag(FLAG, "") or "null")
    except (TypeError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def keep(repo, root: Path, *, blobs: Path | None, now: float | None = None, build=None) -> Path | None:
    from graph_scale_dynamics.operations import focus
    state = focus.load(repo)
    if state is None:
        return None
    clock = time.time() if now is None else float(now)
    last = written(repo)
    since = clock - float(last.get("at") or 0.0)
    if since >= EVERY_SECONDS:
        return write_folder(repo, root, blobs=blobs, build=build, why="an hour since the last")
    if since < NEW_GAP_SECONDS or clock - _LOOKED.get(str(root), -1e18) < LOOK_SECONDS:
        return None
    _LOOKED[str(root)] = clock
    why = news(repo, state, last)
    return None if why is None else write_folder(repo, root, blobs=blobs, build=build, why=why)


def is_dex_path(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.is_file():
        return path.name.startswith(PREFIX) and path.name.endswith(ARCHIVE_ENDINGS)
    return path.is_dir() and ((path / NAME).is_file() or len(list(path.glob(f"*/{NAME}"))) == 1)


def absorb(repo, import_folder: Path | None) -> list[dict]:
    from graph_scale_dynamics.operations import focus, study_seed
    if import_folder is None or not Path(import_folder).is_dir():
        return []
    state = focus.load(repo)
    if state is None:
        return []
    known = {str(r.get("bundle")) for r in study_seed.records(state)}
    done = []
    for path in sorted(Path(import_folder).iterdir(), key=lambda p: p.name):
        if not is_dex_path(path) or name_of(path) in known:
            continue
        stamp = [path.stat().st_size, path.stat().st_mtime_ns]
        if _TRIED.get(str(path)) == stamp:
            continue
        _TRIED[str(path)] = stamp
        try:
            done.append(study_seed.seed(repo, path))
        except ValueError as exc:
            done.append({"bundle": name_of(path), "refused": str(exc)[:300]})
    return done


__all__ = ["CONTRACT", "FOLDER", "NAME", "TOP", "absorb", "files", "held_now", "is_dex_path", "keep", "level_of",
           "like", "merge", "news", "of_folder", "own_part", "part_of_bundle", "part_of_dex", "read_part",
           "scoring_here", "seeding", "standing", "verify", "write", "write_folder", "written"]
