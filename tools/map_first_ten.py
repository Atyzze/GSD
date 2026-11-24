#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402
from graph_scale_dynamics.research import neighbourhood as N  # noqa: E402

CONTRACT = "gsd-map-first-ten-1"
SURVEY = ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json"


def unpacked(path: Path) -> Path:
    if path.is_file():
        from read_bundle import scratch_dir
        from read_bundle import unpacked as unpack
        return unpack(path, scratch_dir("gsd-map-first-ten-"))
    return path


def design_laws(study: str) -> dict[str, dict]:
    from graph_scale_dynamics.operations import study_design as SD
    design = SD.design_for(ROOT, study)
    base = SD.without_terms(design, json.loads(SURVEY.read_text(encoding="utf-8")), log=lambda *_a: None)
    out = {}
    for index, entry in enumerate(design["campaigns"]):
        campaign = SD.campaign_spec(design, base, entry, index)
        for law in SD.fixed_laws(design, entry, campaign, ROOT):
            out[str(law["candidate_id"])] = law["spec"]
    return out


def ledger_specs(root: Path) -> dict[str, dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint, normalize
    from law_rows import spec_of
    out = {}
    for path in sorted(root.glob("campaign_*_reports_*/28-decision-engine.json")):
        body = json.loads(path.read_text(encoding="utf-8")).get("body") or {}
        for row in (body.get("law_ledger") or {}).get("rows") or []:
            law, compact = str(row.get("candidate_id")), row.get("spec")
            if not isinstance(compact, dict):
                continue
            try:
                spec = normalize(spec_of(compact))
            except (KeyError, TypeError, ValueError):
                continue
            if fingerprint(spec) == law:
                out[law] = spec
    return out


def laws_of(root: Path, study: str | None) -> dict[str, dict]:
    import catalogue_reading as R
    found = R.read(root)
    specs = ledger_specs(root)
    if study:
        try:
            specs.update(design_laws(study))
        except (OSError, ValueError, KeyError):
            pass
    scores = {row["law"]: row for row in found["score"]["rows"]}
    out = {}
    for law, entry in found["by_law"].items():
        kinds = {int(n): kind for n, kind in entry["kinds"].items()}
        at = [n for n in kinds if n <= 4096]
        row = scores.get(law) or {}
        out[law] = {"candidate_id": law, "spec": specs.get(law), "bundle": root.name, "kind": entry["kind"],
                    "deepest": entry["deepest"], "kinds": {str(n): k for n, k in sorted(kinds.items())},
                    "kind_at_4096": kinds[max(at)] if at else None, "score": int(row.get("score") or 0),
                    "to_n": row.get("to_n"), "by": row.get("by"), "chain": row.get("chain")}
    return out


def first_ten(bundles: list[tuple[Path, str | None]], top: int = N.TOP) -> dict:
    every: dict[str, dict] = {}
    for root, study in bundles:
        for law, entry in laws_of(root, study).items():
            have = every.get(law)
            if have is None or (entry["score"], entry["deepest"]) > (have["score"], have["deepest"]):
                every[law] = dict(entry, spec=entry["spec"] or (have or {}).get("spec"))
            elif have["spec"] is None and entry["spec"] is not None:
                have["spec"] = entry["spec"]
    ranked = sorted((e for e in every.values() if e["score"] > L.FROZEN_SCORE),
                    key=lambda e: (-e["score"], -int(e["to_n"] or 0), e["candidate_id"]))
    unbuilt = [e["candidate_id"] for e in ranked if e["spec"] is None]
    chosen = [e for e in ranked if e["spec"] is not None][:top]
    others = [e for e in every.values() if e["spec"] is not None]
    holders = []
    for index, entry in enumerate(chosen, start=1):
        partner = N.nearest_of_another_kind(entry["spec"], entry["kind_at_4096"],
                                            [e for e in others if e["candidate_id"] != entry["candidate_id"]])
        holders.append({"label": f"M{index:02d}", **{k: entry[k] for k in (
            "candidate_id", "score", "to_n", "by", "chain", "kind", "kind_at_4096", "kinds", "deepest", "bundle", "spec")},
            "partner": None if partner is None else {k: partner[k] for k in (
                "candidate_id", "kind", "kind_at_4096", "deepest", "bundle", "distance", "spec")}})
    return {"contract": CONTRACT, "score": L.CONTRACT, "from": [root.name for root, _ in bundles],
            "rule": ("the laws of the bundles together, each read by `tools/catalogue_reading.py` under the score in "
                     "force; a law in two bundles keeps its higher score; the ten that score above "
                     f"{L.FROZEN_SCORE} and whose law is rebuilt exactly (by its fingerprint), by score, then depth, then "
                     "id; each one's partner the nearest law of the same terms and dynamics whose kind at 4,096 differs, "
                     "by the root mean square of each parameter's relative difference"),
            "laws_read": len(every), "scoring_above_one": len(ranked), "not_rebuilt": unbuilt, "holders": holders}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the ten best laws of the bundles, each with its nearest law of "
                                                 "another kind: where a study's map starts")
    parser.add_argument("bundles", nargs="+", help="a bundle (.tar.zst or its folder), optionally STUDY=path to "
                                                   "rebuild that study's designed laws exactly")
    parser.add_argument("--write", help="the JSON to write")
    args = parser.parse_args(argv)
    bundles = []
    for given in args.bundles:
        study, _, path = given.partition("=") if "=" in given else (None, None, given)
        bundles.append((unpacked(Path(path)), study))
    found = first_ten(bundles)
    text = json.dumps(found, indent=1, ensure_ascii=False) + "\n"
    if args.write:
        Path(args.write).write_text(text, encoding="utf-8")
    for holder in found["holders"]:
        partner = holder["partner"]
        print(f"{holder['label']} {holder['candidate_id'][:12]} score {holder['score']} to {holder['to_n']} "
              f"{holder['kind']} (at 4,096 {holder['kind_at_4096']}) from {holder['bundle'][:9]}; partner "
              + ("none" if partner is None else f"{partner['candidate_id'][:12]} {partner['kind_at_4096']} at "
                                                f"{partner['distance']}"))
    print(f"{found['laws_read']} laws read, {found['scoring_above_one']} above {L.FROZEN_SCORE}, "
          f"{len(found['not_rebuilt'])} not rebuilt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

