from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.scheduling.base_block import (
    base_sizes, is_base_block_campaign)

REBUILD_CONTRACT = "gsd-phenotype-rebuild-1"


def _summaries_for(repo: Repo, campaign_id: str, candidate_id: str,
                   analysis_version: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in repo.rung_summaries(candidate_id, analysis_version,
                                   campaign_id=campaign_id) or []:
        summary = row.get("summary")
        if isinstance(summary, dict) and row.get("n") is not None:
            out[int(row["n"])] = summary
    return out


def rebuild_phenotypes(db: Path, *, campaign_id: str | None = None,
                       apply: bool = False, limit: int | None = None) -> dict:
    from graph_scale_dynamics.db.decision_store import best_runs
    from graph_scale_dynamics.decisions.evidence import (
        _b143_rung_sampling_state, _build_four_rung_phenotype)

    report = {
        "contract": REBUILD_CONTRACT, "apply": bool(apply),
        "campaigns": 0, "candidates": 0,
        "skipped_not_base_block": 0, "skipped_incomplete_base_block": 0,
        "skipped_no_summaries": 0, "failed": 0,
        "rebuilt": 0, "unchanged": 0, "changed": 0,
        "gained_extension": 0, "extension_rungs": {}, "changed_examples": [],
    }
    with Repo(db) as repo:
        campaigns = [c for c in repo.all_campaigns()
                     if campaign_id is None or c["campaign_id"] == campaign_id]
        report["campaigns"] = len(campaigns)
        for campaign in campaigns:
            spec = campaign.get("spec") or {}
            if not is_base_block_campaign(spec):
                report["skipped_not_base_block"] += 1
                continue
            required = [int(n) for n in base_sizes(spec)]
            analysis_version = repo.campaign_analysis_contract(campaign["campaign_id"])
            for candidate in repo.candidates(campaign["campaign_id"]):
                if limit is not None and report["candidates"] >= limit:
                    break
                report["candidates"] += 1
                cid = candidate["candidate_id"]
                summaries = _summaries_for(repo, campaign["campaign_id"], cid, analysis_version)
                if not summaries:
                    report["skipped_no_summaries"] += 1
                    continue
                if not set(required).issubset(set(summaries)):
                    report["skipped_incomplete_base_block"] += 1
                    continue
                try:
                    history = [m.get("metrics") or {} for m in best_runs(
                        repo.measurements(cid, analysis_version, campaign["campaign_id"]))]
                    states = {n: _b143_rung_sampling_state(spec, n, summaries[n], history)
                              for n in required}
                    phenotype = _build_four_rung_phenotype(spec, summaries, states)
                except Exception as exc:
                    report["failed"] += 1
                    if len(report["changed_examples"]) < 5:
                        report["changed_examples"].append(
                            {"candidate_id": cid[:16], "error": f"{type(exc).__name__}: {exc}"})
                    continue
                stored = repo.base_block_phenotype(
                    cid, analysis_version, campaign_id=campaign["campaign_id"]) or {}
                before = stored.get("phenotype") if isinstance(stored, dict) else None
                extension = list(phenotype.get("extension_sizes") or [])
                if extension:
                    report["gained_extension"] += 1
                    key = ",".join(str(n) for n in extension)
                    report["extension_rungs"][key] = report["extension_rungs"].get(key, 0) + 1
                same = (isinstance(before, dict)
                        and json.dumps(before, sort_keys=True)
                        == json.dumps(phenotype, sort_keys=True))
                if same:
                    report["unchanged"] += 1
                else:
                    report["changed"] += 1
                    if len(report["changed_examples"]) < 8:
                        report["changed_examples"].append({
                            "candidate_id": cid[:16],
                            "extension_sizes": extension,
                            "had_phenotype": isinstance(before, dict),
                        })
                if apply:
                    repo.upsert_base_block_phenotype(
                        campaign["campaign_id"], cid, str(analysis_version),
                        str(phenotype.get("contract")), phenotype)
                    report["rebuilt"] += 1
    return report


def render(report: dict) -> str:
    lines = [
        f"phenotype rebuild ({'APPLIED' if report['apply'] else 'dry run'})",
        f"  campaigns {report['campaigns']}   candidates {report['candidates']}",
        f"  would change {report['changed']}   identical {report['unchanged']}"
        f"   written {report['rebuilt']}",
        f"  gaining an extension block: {report['gained_extension']}",
    ]
    for rungs, count in sorted(report["extension_rungs"].items()):
        lines.append(f"     rungs {rungs}: {count} laws")
    skipped = (report["skipped_no_summaries"] + report["skipped_incomplete_base_block"]
               + report["skipped_not_base_block"])
    lines.append(f"  skipped {skipped}   failed {report['failed']}")
    if report["changed_examples"]:
        lines.append("  examples:")
        for e in report["changed_examples"]:
            lines.append("     " + json.dumps(e))
    if not report["apply"]:
        lines.append("  nothing was written; re-run with --apply")
    return "\n".join(lines)
