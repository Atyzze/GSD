from __future__ import annotations

import gzip
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-study-seed-1"
KIND = "seed"
STUDY, LAWS, FOCUS = "study.json", "tables/laws.ndjson.gz", "focus.json"
WANTED = (STUDY, LAWS, FOCUS)
MAPPED = "mapped"


def _from_folder(path: Path) -> dict[str, bytes]:
    roots = [path] if (path / STUDY).is_file() else sorted(p.parent for p in path.glob(f"*/{STUDY}"))
    if len(roots) != 1:
        raise ValueError(f"{path} holds {len(roots)} study bundles: name one")
    return {name: (roots[0] / name).read_bytes() for name in WANTED if (roots[0] / name).is_file()}


def _from_archive(path: Path) -> dict[str, bytes]:
    zstd = shutil.which("zstd")
    if not zstd:
        raise ValueError("reading a .tar.zst needs the zstd executable; give the bundle's unpacked folder instead")
    found: dict[str, bytes] = {}
    with subprocess.Popen([zstd, "-dc", str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as unzip:
        with tarfile.open(fileobj=unzip.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                parts = member.name.split("/", 1)
                name = parts[1] if len(parts) == 2 else parts[0]
                if name in WANTED and name not in found:
                    handle = archive.extractfile(member)
                    found[name] = handle.read() if handle is not None else b""
                if len(found) == len(WANTED):
                    break
        unzip.stdout.close()
        unzip.kill()
    return found


def members(path) -> dict[str, bytes]:
    path = Path(str(path or "").strip()).expanduser()
    if not str(path) or not path.exists():
        raise ValueError(f"no bundle at {path}: give the path of a study bundle on this host, its .tar.zst or folder")
    found = _from_folder(path) if path.is_dir() else _from_archive(path)
    if STUDY not in found or LAWS not in found:
        raise ValueError(f"{path} is not a study bundle with its laws table (study.json and {LAWS})")
    return found


def _dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        found = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        found = None
    return found if isinstance(found, dict) else {}


def read(path) -> dict:
    found = members(path)
    meta = json.loads(found[STUDY])
    specs, scoring = {}, []
    with gzip.open(io.BytesIO(found[LAWS]), "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            law, spec = str(row["candidate_id"]), _dict(row.get("spec"))
            if spec:
                specs[law] = spec
            score = int(_dict(row.get("law_score")).get("score") or 0)
            if score > 0 and spec:
                scoring.append({"law": law, "campaign": str(row.get("campaign_id")), "score": score,
                                "number": row.get("candidate_number")})
    focus = json.loads(found[FOCUS]) if FOCUS in found else {}
    regions = []
    for region in (focus.get("regions") or []):
        holders = [str(law) for law in region.get("laws") or [] if str(law) in specs]
        if holders:
            regions.append(dict(region, holders=holders))
    scoring.sort(key=lambda e: (-e["score"], int(e["campaign"]) if e["campaign"].isdigit() else 0,
                                e["number"] or 0, e["law"]))
    return {"name": Path(str(path)).name.removesuffix(".tar.zst").removesuffix("_tar.zst"),
            "built_utc": meta.get("built_utc"), "study": str(meta.get("study_id") or meta.get("study") or ""),
            "science": _dict(meta.get("science")), "specs": specs, "scoring": scoring, "regions": regions}


def seeded_campaign(repo, study: str) -> str:
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if str(design.get("study")) == str(study) and design.get("kind") == KIND:
            return str(campaign["campaign_id"])
    raise ValueError(f"study {study}'s design has no seeded campaign: a seed goes into a study designed for one")


def _science_of_this_folder() -> dict:
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def _in(repo, campaign_id: str) -> set[str]:
    return {str(row["candidate_id"]) for row in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (str(campaign_id),)).fetchall()}


def seed(repo, path, *, science: dict | None = None) -> dict:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import focus_regions as R
    from graph_scale_dynamics.reporting import science_contract
    state = focus.load(repo)
    if state is None:
        raise ValueError("this folder has no focus yet: a seed joins the focus of a study designed for one")
    bundle = read(path)
    ours = _science_of_this_folder() if science is None else science
    compared = science_contract.same(bundle["science"], ours)
    if not compared["same"]:
        raise ValueError(f"bundle {bundle['name']} was read by another science than this folder's "
                         f"({', '.join(compared['differ']) or 'no science hash in it'}): its readings do not carry here")
    campaign = seeded_campaign(repo, state["study"])
    known = _in(repo, campaign)
    added, mismatched = 0, 0

    def put(law: str) -> bool:
        nonlocal added, mismatched
        if law in known:
            return True
        spec = dsl.normalize(bundle["specs"][law])
        if dsl.fingerprint(spec) != law:
            mismatched += 1
            return False
        focus._insert(repo, campaign, spec)
        known.add(law)
        added += 1
        return True

    for entry in bundle["scoring"]:
        put(entry["law"])
    regions = state.setdefault("regions", [])
    places = state.setdefault("region_of", {})
    taken = {int(r["number"]) for r in regions}
    already = {(str((r.get("seeded_from") or {}).get("study")), int((r.get("seeded_from") or {}).get("number", -1))): r
               for r in regions if r.get("seeded_from")}
    joined, grown = [], []
    for region in bundle["regions"]:
        source = (bundle["study"], int(region.get("number") or 0))
        holders = [law for law in region["holders"] if put(law)]
        if not holders:
            continue
        if source in already:
            known_region = already[source]
            wider = R.joined(known_region["ranges"], dict(region.get("ranges") or {}))
            more = [law for law in holders if law not in known_region["laws"]]
            if wider != known_region["ranges"] or more:
                known_region["ranges"] = wider
                known_region["laws"] += more
                known_region["members"] = max(int(known_region.get("members") or 0), int(region.get("members") or 0))
                grown.append(known_region["name"])
            continue
        number = int(region.get("number") or 0)
        if number < 1 or number in taken:
            number = max(taken | {int(state.get("region_count") or 0)}) + 1
        taken.add(number)
        state["region_count"] = max(int(state.get("region_count") or 0), number)
        made = {"number": number, "name": f"{R.PREFIX}{number}", "kind": region.get("kind"), "laws": holders,
                "labels": list(region.get("labels") or []), "members": int(region.get("members") or len(holders)),
                "ranges": dict(region.get("ranges") or {}), "alike_to": region.get("alike_to"),
                "boundaries": list(region.get("boundaries") or []), "joined": [], "mapped_utc": region.get("mapped_utc"),
                "seeded_from": {"study": bundle["study"], "bundle": bundle["name"], "number": int(region.get("number") or 0),
                                "name": region.get("name"), "at": utc_now()}}
        regions.append(made)
        for law in holders:
            places[law] = number
            if any(d.get("law") == law for d in state["done"]):
                continue
            state["done"].append({"law": law, "of": campaign, "label": f"{bundle['name']}:{law[:10]}",
                                  "stage": MAPPED, "kind": region.get("kind"), "alike_to": region.get("alike_to"),
                                  "region": made["name"], "why": f"mapped in {bundle['name']} as {region.get('name')}",
                                  "seeded": bundle["name"]})
        joined.append(made["name"])
    record = {"bundle": bundle["name"], "built_utc": bundle["built_utc"], "study": bundle["study"],
              "science": bundle["science"].get("sha256"), "scoring": len(bundle["scoring"]), "laws_added": added,
              "regions": joined, "regions_grown": grown, "mismatched": mismatched, "at": utc_now(),
              "campaign": campaign}
    state.setdefault("seeded", []).append(record)
    state["events"].append({"at": utc_now(), "seeded": bundle["name"], "laws": added, "regions": len(joined)})
    focus.save(repo, state)
    return record


__all__ = ["CONTRACT", "KIND", "members", "read", "seed", "seeded_campaign"]
