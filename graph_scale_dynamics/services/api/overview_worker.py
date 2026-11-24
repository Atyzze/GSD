from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.services.api.overview import build_overview


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--exploration", action="store_true")
    parser.add_argument("--past", action="store_true")
    args = parser.parse_args(argv)
    from graph_scale_dynamics.operations.subprocesses import yield_to_the_fleet
    yield_to_the_fleet()
    with Repo(args.db) as repo:
        repo.publish_runtime_imports("overview-worker")
        full = build_overview(repo, args.campaign,
                              include_exploration=args.exploration,
                              include_past=args.past)
    payload = {
        "campaign_id": str(args.campaign),
        "dashboard_response": {"heavy_pending": False, "contract": "gsd-dashboard-heavy-file-1"},
        "dashboard_sections": full.get("dashboard_sections") or {},
    }
    if args.exploration:
        payload["exploration_map"] = full.get("exploration_map") or {"included": False, "nodes": []}
    if args.past:
        payload["past"] = full.get("past") or []
        payload["past_research"] = full.get("past_research") or {"included": False, "available_count": 0}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
