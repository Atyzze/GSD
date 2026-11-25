#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-laws-of-a-bundle-1"


def bundle_laws(bundle: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with gzip.open(Path(bundle) / "tables" / "laws.ndjson.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            out[str(row["candidate_id"])] = row
    return out


def rebuilt(tree: Path, study: str, campaigns: dict[str, str], design_sha256: str | None = None) -> dict[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.research.law_identity import equilibrium_identity
    from graph_scale_dynamics.services.proposer.blind import blind_batch, identity_version, law_stream
    design = SD.design_for(tree, study)
    if design is None:
        raise SystemExit(f"this tree holds no design for study {study}")
    if design_sha256 and design["sha256"] != design_sha256:
        raise SystemExit(f"study {study}'s design in this tree is not the one its bundle ran ({design['sha256'][:12]} "
                         f"here, {design_sha256[:12]} there): its laws would be drawn from another design")
    base = json.loads((Path(tree) / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                      .read_text(encoding="utf-8"))
    base = SD.without_terms(design, base, log=lambda *_: None)
    out: dict[str, dict] = {}
    for index, entry in enumerate(design["campaigns"]):
        if entry["kind"] != SD.BLIND:
            continue
        campaign_id = campaigns.get(str(index))
        if campaign_id is None:
            continue
        spec = SD.campaign_spec(design, base, entry, index)
        seed = SD.seed_of(design, index)
        grid = (spec.get("search_policy") or {}).get("grid")
        version = identity_version(grid)
        budget = spec.get("complexity_budget")
        laws = blind_batch(random.Random(0), int(design["law_budget"]), list(spec.get("operator_whitelist") or dsl.OPERATORS),
                           grid, set(), set(), fingerprint=dsl.fingerprint,
                           physical_identity=lambda law, v=version: equilibrium_identity(law, version=v)[0],
                           complexity_budget=int(budget) if budget is not None else None,
                           streams=lambda i, s=seed: law_stream(s, i), first_index=0)
        for law in laws:
            normalized = dsl.normalize(law)
            out[dsl.fingerprint(normalized)] = {"campaign_id": campaign_id, "spec": normalized, "search_seed": seed,
                                                "batch": entry["label"]}
    return out


def controls() -> dict[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import standing_controls as C
    criterion = C.load_criterion()
    if criterion is None:
        return {}
    return {law["candidate_id"]: {"spec": dsl.normalize(law["spec"]), "label": law.get("label")}
            for law in C.laws(criterion)}


def campaigns_of(bundle: Path) -> tuple[str, dict[str, str], str | None]:
    study = json.loads((Path(bundle) / "study.json").read_text(encoding="utf-8"))
    found, sha = {}, None
    for campaign in study.get("campaigns") or []:
        design = campaign.get("study_design") or {}
        if design.get("campaign") is not None:
            found[str(design["campaign"])] = str(campaign["campaign_id"])
            sha = sha or design.get("design_sha256")
    if not found:
        found = {str(int(c["campaign_id"]) - 1): str(c["campaign_id"]) for c in study.get("campaigns") or []
                 if str(c.get("campaign_id", "")).isdigit()}
    return str(study["study_id"]), found, sha


def read(bundle: Path, tree: Path = ROOT) -> dict:
    study, campaigns, sha = campaigns_of(bundle)
    have = bundle_laws(bundle)
    made = rebuilt(tree, study, campaigns, sha)
    for law, control in controls().items():
        if law in have and law not in made:
            made[law] = {"campaign_id": str(have[law]["campaign_id"]), "spec": control["spec"]}
    carried = {law for law, row in have.items() if row.get("spec")}
    by_campaign: dict[str, dict] = {}
    for law, row in have.items():
        entry = by_campaign.setdefault(str(row["campaign_id"]), {"laws": 0, "carried": 0, "rebuilt": 0, "missing": []})
        entry["laws"] += 1
        entry["carried"] += law in carried
        if law in made and made[law]["campaign_id"] == str(row["campaign_id"]):
            entry["rebuilt"] += 1
        elif law not in carried:
            entry["missing"].append(law)
    return {"contract": CONTRACT, "bundle": Path(bundle).name, "study": study, "campaigns": by_campaign,
            "laws": len(have), "rebuilt": sum(e["rebuilt"] for e in by_campaign.values()),
            "carried": len(carried), "missing": sum(len(e["missing"]) for e in by_campaign.values()),
            "specs": {law: made[law]["spec"] if law in made else have[law].get("spec") for law in have
                      if law in made or law in carried}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="every law of a study's bundle, whole: carried by the bundle or "
                                                 "drawn again from its design's search seeds and checked by fingerprint")
    parser.add_argument("bundle")
    parser.add_argument("--out", help="write one row per law (campaign, id, spec) as gzipped JSON lines")
    args = parser.parse_args(argv)
    found = read(Path(args.bundle))
    for campaign, entry in sorted(found["campaigns"].items(), key=lambda kv: (len(kv[0]), kv[0])):
        print(f"campaign {campaign}: {entry['laws']:,} laws, {entry['carried']:,} carried whole, "
              f"{entry['rebuilt']:,} drawn again (a blind batch from its design's seed, a control from its criterion), {len(entry['missing']):,} neither")
    print(f"{found['laws']:,} laws: {len(found['specs']):,} whole, {found['missing']:,} not")
    if args.out:
        have = bundle_laws(Path(args.bundle))
        with gzip.open(args.out, "wt", encoding="utf-8") as stream:
            for law, spec in sorted(found["specs"].items()):
                stream.write(json.dumps({"campaign_id": have[law]["campaign_id"], "candidate_id": law, "spec": spec},
                                        sort_keys=True) + "\n")
        print(args.out)
    return 0 if found["missing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
