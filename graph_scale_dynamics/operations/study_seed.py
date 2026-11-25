from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations import focus_regions as R
from graph_scale_dynamics.operations import law_code as LC

CONTRACT = "gsd-study-seed-2"
KIND = "seed"
STUDY, LAWS, FOCUS = "study.json", "tables/laws.ndjson.gz", "focus.json"
WANTED = (STUDY, LAWS, FOCUS)
MAPPED = "mapped"
LET_GO_REGIONS = "regions_let_go"
LET_GO_WHY = "set aside: let go with its bundle"


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


def name_of(path) -> str:
    return Path(str(path)).name.removesuffix(".tar.zst").removesuffix("_tar.zst")


def read(path) -> dict:
    found = members(path)
    meta = json.loads(found[STUDY])
    study = str(meta.get("study_id") or meta.get("study") or "")
    specs, scoring, codes = {}, [], {}
    with gzip.open(io.BytesIO(found[LAWS]), "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            law, spec = str(row["candidate_id"]), _dict(row.get("spec"))
            campaign = str(row.get("campaign_id"))
            codes.setdefault(law, row.get("code") or LC.code(study, campaign, row.get("graph"), law))
            if spec:
                specs[law] = spec
            score = int(_dict(row.get("law_score")).get("score") or 0)
            if score > 0 and spec:
                scoring.append({"law": law, "campaign": campaign, "score": score,
                                "number": row.get("candidate_number"), "code": codes[law]})
    focus = json.loads(found[FOCUS]) if FOCUS in found else {}
    regions = []
    for region in (focus.get("regions") or []):
        holders = [str(law) for law in region.get("laws") or [] if str(law) in specs]
        if holders:
            regions.append(dict(region, holders=holders,
                                labels=[LC.upgraded(label, study) for label in region.get("labels") or []]))
    scoring.sort(key=lambda e: (-e["score"], int(e["campaign"]) if e["campaign"].isdigit() else 0,
                                e["number"] or 0, e["law"]))
    return {"name": name_of(path), "built_utc": meta.get("built_utc"), "build": meta.get("build_number"),
            "study": study, "science": _dict(meta.get("science")), "specs": specs, "scoring": scoring,
            "regions": regions, "codes": codes, "sha256": hashlib.sha256(found[LAWS]).hexdigest()}


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


def selected(record: dict) -> bool:
    return record.get("selected", True) is not False


def records(state: dict | None) -> list[dict]:
    out: dict[str, dict] = {}
    for record in (state or {}).get("seeded") or []:
        name = str(record.get("bundle") or "")
        if name in out:
            kept = out[name]
            kept["laws_added"] = int(kept.get("laws_added") or 0) + int(record.get("laws_added") or 0)
            kept["regions"] = list(kept.get("regions") or []) + [r for r in record.get("regions") or []
                                                                 if r not in (kept.get("regions") or [])]
            kept.setdefault("again", []).append(record.get("at"))
            for key in ("laws", "sha256", "selected"):
                if record.get(key) is not None:
                    kept[key] = record[key]
            continue
        out[name] = dict(record)
    return list(out.values())


def campaign_of(state: dict | None) -> str | None:
    return next((str(r["campaign"]) for r in records(state) if r.get("campaign")), None)


def standing(state: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for record in records(state):
        if not selected(record):
            continue
        for law, entry in (record.get("laws") or {}).items():
            out[str(law)] = dict(entry, bundle=record["bundle"], study=record.get("study"))
    return out


def let_go(state: dict | None) -> set[str]:
    held, gone = set(), set()
    for record in records(state):
        laws = set((record.get("laws") or {}).keys()) | set(record.get("laws_let_go") or [])
        (held if selected(record) else gone).update(laws)
    return gone - held


def origin_of(state: dict | None, law: str) -> dict | None:
    found = None
    for record in records(state):
        entry = (record.get("laws") or {}).get(str(law))
        if entry is not None and (found is None or selected(record) or not found["selected"]):
            found = dict(entry, bundle=record["bundle"], study=record.get("study"), selected=selected(record))
    return found


def bundles_let_go(state: dict | None) -> set[str]:
    return {str(r["bundle"]) for r in records(state) if not selected(r)}


def _sources(region: dict) -> list[str]:
    if "sources" not in region:
        region["sources"] = [str(region["seeded_from"]["bundle"])] if region.get("seeded_from") else []
    return region["sources"]


def _fresh_number(state: dict, wanted: int) -> int:
    taken = {int(r["number"]) for r in state.get("regions") or []}
    if wanted >= 1 and wanted not in taken:
        state["region_count"] = max(int(state.get("region_count") or 0), wanted)
        return wanted
    number = max(taken | {int(state.get("region_count") or 0)}) + 1
    state["region_count"] = number
    return number


def _place(state: dict, region: dict) -> None:
    places = state.setdefault("region_of", {})
    for law in region["laws"]:
        places[law] = region["number"]


def _planned(state: dict, bundle: dict, known: set[str], campaign: str) -> dict:
    from graph_scale_dynamics.dsl import dsl
    viable, mismatched, specs = set(known), set(), {}

    def ok(law: str) -> bool:
        if law in viable:
            return True
        if law in mismatched:
            return False
        spec = dsl.normalize(bundle["specs"][law])
        if dsl.fingerprint(spec) != law:
            mismatched.add(law)
            return False
        specs[law] = spec
        viable.add(law)
        return True

    for entry in bundle["scoring"]:
        ok(entry["law"])
    already = {(str((r.get("seeded_from") or {}).get("study")), int((r.get("seeded_from") or {}).get("number", -1))): r
               for r in state.get("regions") or [] if r.get("seeded_from")}
    joined, grown = [], []
    for region in bundle["regions"]:
        holders = [law for law in region["holders"] if ok(law)]
        if not holders:
            continue
        source = (bundle["study"], int(region.get("number") or 0))
        if source in already:
            known_region = already[source]
            wider = R.joined(known_region["ranges"], dict(region.get("ranges") or {}))
            more = [law for law in holders if law not in known_region["laws"]]
            if wider != known_region["ranges"] or more:
                grown.append((known_region, wider, more, region))
            continue
        joined.append((region, holders))
    return {"insert": specs, "mismatched": len(mismatched), "joined": joined, "grown": grown,
            "scoring": [e for e in bundle["scoring"] if e["law"] in viable]}


def _record_of(state: dict, name: str) -> dict | None:
    return next((r for r in records(state) if r.get("bundle") == name), None)


def _put_record(state: dict, record: dict) -> None:
    state["seeded"] = [r for r in records(state) if r.get("bundle") != record["bundle"]] + [record]


def refusal(state: dict | None, bundle: dict) -> str | None:
    record = _record_of(state or {}, bundle["name"])
    if record is not None and selected(record) and record.get("laws") is not None:
        return (f"bundle {bundle['name']} was read already ({str(record.get('at') or '')[:16].replace('T', ' ')} "
                f"UTC): its laws and regions are in this study's map")
    twin = next((r for r in records(state) if selected(r) and r.get("sha256") == bundle.get("sha256")
                 and r.get("bundle") != bundle["name"]), None)
    if twin is not None:
        return (f"bundle {bundle['name']} is identical to {twin['bundle']}, already in this study's map (the same laws "
                f"table, sha256 {str(bundle.get('sha256'))[:12]})")
    return None


def seed(repo, path, *, science: dict | None = None) -> dict:
    from graph_scale_dynamics.operations import focus
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
    refused = refusal(state, bundle)
    if refused:
        raise ValueError(refused)
    earlier = _record_of(state, bundle["name"])
    if earlier is not None and earlier.get("laws") is not None and not selected(earlier):
        return choose(repo, bundle["name"])
    campaign = seeded_campaign(repo, state["study"])
    plan = _planned(state, bundle, _in(repo, campaign), campaign)
    laws = {e["law"]: {"score": e["score"], "code": e["code"]} for e in plan["scoring"]}
    if earlier is None and not plan["insert"] and not plan["joined"] and not plan["grown"]:
        raise ValueError(f"bundle {bundle['name']} adds nothing: its {len(bundle['scoring'])} scoring laws are in "
                         f"this study's map already and its regions add none"
                         + (f" ({plan['mismatched']} laws whose spec is not their id left out)"
                            if plan["mismatched"] else ""))
    for spec in plan["insert"].values():
        focus._insert(repo, campaign, spec)
    regions = state.setdefault("regions", [])
    names, grown = [], []
    for known_region, wider, more, _given in plan["grown"]:
        known_region["ranges"] = wider
        known_region["laws"] += more
        known_region["members"] = max(int(known_region.get("members") or 0), int(_given.get("members") or 0))
        if bundle["name"] not in _sources(known_region):
            _sources(known_region).append(bundle["name"])
        _place(state, known_region)
        grown.append(known_region["name"])
    for region, holders in plan["joined"]:
        number = _fresh_number(state, int(region.get("number") or 0))
        made = {"number": number, "name": f"{R.PREFIX}{number}", "kind": region.get("kind"), "laws": holders,
                "labels": list(region.get("labels") or []), "members": int(region.get("members") or len(holders)),
                "ranges": dict(region.get("ranges") or {}), "alike_to": region.get("alike_to"),
                "boundaries": list(region.get("boundaries") or []), "joined": [], "mapped_utc": region.get("mapped_utc"),
                "sources": [bundle["name"]],
                "seeded_from": {"study": bundle["study"], "bundle": bundle["name"], "number": int(region.get("number") or 0),
                                "name": region.get("name"), "at": utc_now()}}
        regions.append(made)
        _place(state, made)
        for law in holders:
            if any(d.get("law") == law for d in state["done"]):
                continue
            state["done"].append({"law": law, "of": campaign, "label": bundle["codes"].get(law) or law[:10],
                                  "stage": MAPPED, "kind": region.get("kind"), "alike_to": region.get("alike_to"),
                                  "region": made["name"], "why": f"mapped in {bundle['name']} as {region.get('name')}",
                                  "seeded": bundle["name"]})
        names.append(made["name"])
    record = dict(earlier or {}, bundle=bundle["name"], built_utc=bundle["built_utc"], study=bundle["study"],
                  science=bundle["science"].get("sha256"), sha256=bundle["sha256"], scoring=len(bundle["scoring"]),
                  laws_added=int((earlier or {}).get("laws_added") or 0) + len(plan["insert"]),
                  regions=list((earlier or {}).get("regions") or []) + names,
                  regions_grown=list((earlier or {}).get("regions_grown") or []) + grown,
                  mismatched=plan["mismatched"], campaign=campaign, selected=True, laws=laws)
    record.setdefault("at", utc_now())
    if earlier is not None:
        record["read_again"] = utc_now()
    _put_record(state, record)
    state["events"].append({"at": utc_now(), "seeded": bundle["name"], "laws": len(plan["insert"]),
                            "regions": len(names), **({"read_again": True} if earlier is not None else {})})
    focus.save(repo, state)
    return dict({k: v for k, v in record.items() if k != "laws"}, laws_added=len(plan["insert"]), regions=names,
                regions_grown=grown, laws_standing=len(laws), read_again=earlier is not None)


def _let_go_of(state: dict, name: str) -> list[str]:
    off = []
    let = state.setdefault(LET_GO_REGIONS, [])
    for region in list(state.get("regions") or []):
        sources = _sources(region)
        if name not in sources:
            continue
        sources.remove(name)
        if region.get("seeded_from") and not sources and not region.get("joined"):
            state["regions"].remove(region)
            let.append(region)
            places = state.setdefault("region_of", {})
            for law in region["laws"]:
                if places.get(law) == region["number"]:
                    places.pop(law)
            off.append(region["name"])
    return off


def _take_back(state: dict, record: dict) -> list[str]:
    back = []
    name = record["bundle"]
    for region in list(state.get(LET_GO_REGIONS) or []):
        if (region.get("seeded_from") or {}).get("bundle") != name:
            continue
        state[LET_GO_REGIONS].remove(region)
        number = _fresh_number(state, int(region["number"]))
        region.update(number=number, name=f"{R.PREFIX}{number}", sources=[name])
        state.setdefault("regions", []).append(region)
        _place(state, region)
        back.append(region["name"])
    for region in state.get("regions") or []:
        if region["name"] in (record.get("regions_grown") or []) and name not in _sources(region):
            _sources(region).append(name)
    return back


def release(repo, name: str) -> dict:
    from graph_scale_dynamics.operations import focus
    state = focus.load(repo)
    record = _record_of(state or {}, str(name))
    if record is None:
        raise ValueError(f"no bundle {name!r} was read into this study's map")
    if not selected(record):
        return {"bundle": record["bundle"], "let_go": [], "already": True}
    if record.get("laws") is None:
        raise ValueError(f"bundle {name} was read before its laws were recorded one by one: tick it and synchronize "
                         f"once with the bundle in the import folder, then untick it")
    record["selected"], record["let_go_utc"] = False, utc_now()
    _put_record(state, record)
    off = _let_go_of(state, record["bundle"])
    gone = let_go(state)
    dropped = [law for law, entry in list(state.get("contenders", {}).items())
               if law in gone and str(entry.get("of")) == str(record.get("campaign"))]
    for law in dropped:
        state["contenders"].pop(law)
    current = state.get("current")
    if current and current["law"] in gone and str(current.get("of")) == str(record.get("campaign")) \
            and current.get("stage") not in focus.ENDED:
        focus._end(state, current, focus.UNCONFIRMED, f"{LET_GO_WHY} {record['bundle']}")
        focus._finish(repo, state, current)
    state["events"].append({"at": utc_now(), "let_go": record["bundle"], "regions": off, "depth": len(dropped)})
    focus.save(repo, state)
    return {"bundle": record["bundle"], "regions_off": off, "laws_let_go": len(gone), "depth_dropped": len(dropped)}


def choose(repo, name: str) -> dict:
    from graph_scale_dynamics.operations import focus
    state = focus.load(repo)
    record = _record_of(state or {}, str(name))
    if record is None or record.get("laws") is None:
        raise ValueError(f"bundle {name!r} must be read from the import folder to come into this study's map")
    if selected(record):
        return {"bundle": record["bundle"], "already": True}
    record["selected"], record["chosen_again_utc"] = True, utc_now()
    _put_record(state, record)
    back = _take_back(state, record)
    state["done"] = [d for d in state["done"] if d.get("why") != f"{LET_GO_WHY} {record['bundle']}"]
    state["events"].append({"at": utc_now(), "chosen_again": record["bundle"], "regions": back})
    focus.save(repo, state)
    return dict({k: v for k, v in record.items() if k != "laws"}, regions_back=back, laws_standing=len(record["laws"]))


__all__ = ["CONTRACT", "KIND", "bundles_let_go", "campaign_of", "choose", "let_go", "members", "name_of", "origin_of",
           "read", "records", "refusal", "release", "seed", "seeded_campaign", "selected", "standing"]
