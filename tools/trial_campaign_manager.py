#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from graph_scale_dynamics.db.connection import resolve_target
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.scheduling import term_selection
    from graph_scale_dynamics.services.api import campaign_manager as manager
    from graph_scale_dynamics.services.proposer import blind
except ImportError as missing:
    print(f"trial_campaign_manager needs the project's environment ({missing}). Run it as\n"
          "    uv run python tools/trial_campaign_manager.py", file=sys.stderr)
    raise SystemExit(2)

MARKER = "trial_campaign_manager"

SEEDED_LADDER = {4096: 7, 65536: 4, 262144: 2, 1048576: 1}

INFEASIBLE = ["triangle_count", "square_count", "induced_square_count"]

TOO_SMALL = ["degree_square_sum"]

FEASIBLE = ["degree_square_sum", "edge_count", "triangle_count"]


class Trial:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.steps: list[dict] = []
        self.created: list[str] = []

    def step(self, name: str, ok: bool, detail: object = None) -> bool:
        self.steps.append({"step": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def parent(self) -> dict | None:
        rows = sorted(self.repo.all_campaigns(), key=lambda row: str(row["created_utc"]))
        return rows[0] if rows else None

    def author(self, parent_id: str, terms: list[str]) -> tuple[dict, int]:
        made, code = manager.handle(self.repo, {
            "action": "create", "parent_campaign_id": parent_id,
            "operator_whitelist": terms, "reason": f"{MARKER}: {' '.join(terms)}"})
        if code == 200 and made.get("ok") and str(made["campaign_id"]) not in self.created:
            self.created.append(str(made["campaign_id"]))
        return made, code

    def seed_ladder(self, campaign_id: str) -> None:
        spec = {"dsl_version": 1, "init": "empty",
                "terms": [{"op": "degree_square_sum", "params": {},
                           "coeff": {"c0": 0.5, "scale": "one"}}],
                "dynamics": {"kind": "equilibrium", "beta": 1.0,
                             "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 30}}
        laws = [uuid.uuid4().hex[:16] for _ in range(max(SEEDED_LADDER.values()))]
        for law in laws:
            self.repo.insert_candidate(law, campaign_id, spec, "equilibrium", 1,
                                       "BASE_BLOCK_RUNNING")
        for rung, count in sorted(SEEDED_LADDER.items()):
            for law in laws[:count]:
                self.repo.insert_job(
                    job_id=uuid.uuid4().hex, campaign_id=campaign_id, candidate_id=law,
                    kind="simulate", stage="base", n=rung, seed=1, replicate=0,
                    spec=spec, priority=100, sealed=False, requested_by=MARKER)

    def run(self) -> None:
        parent = self.parent()
        if parent is None:
            self.step("a campaign to clone from exists", False,
                      "this folder holds no campaign; start one with "
                      "`main.py campaign start --spec campaign_engine_survey.json` first")
            return
        parent_id = str(parent["campaign_id"])
        self.step("a campaign to clone from exists", True, {"campaign_id": parent_id})

        full = term_selection.preflight(list(parent["spec"].get("operator_whitelist") or []),
                                        (parent["spec"].get("search_policy") or {}).get("grid"),
                                        parent["spec"].get("complexity_budget"))
        self.step("the parent's own term set draws laws", full["status"] == "PASS",
                  {"yield": full["sample"].get("yield_fraction")})

        refused, code = self.author(parent_id, INFEASIBLE)
        self.step("an infeasible term selection is refused", code != 200 and "error" in refused,
                  refused.get("error"))

        small, small_code = self.author(parent_id, TOO_SMALL)
        self.step("a term set smaller than the campaign's pool is created, to survey its whole space",
                  small_code == 200 and bool(small.get("ok")), small.get("error") or small.get("campaign_id"))

        made, code = self.author(parent_id, FEASIBLE)
        created_ok = code == 200 and made.get("ok")
        self.step("a feasible term selection creates a campaign", created_ok, made)
        if not created_ok:
            return
        campaign_id = str(made["campaign_id"])
        stored = self.repo.campaign(campaign_id)["spec"].get("operator_whitelist")
        self.step("the campaign stores the terms that were chosen", list(stored) == FEASIBLE,
                  {"stored": stored, "chosen": FEASIBLE})

        check = term_selection.preflight(
            FEASIBLE, (parent["spec"].get("search_policy") or {}).get("grid"),
            parent["spec"].get("complexity_budget"), draws=200, seed=3)
        rng = random.Random(3)
        drawn = 0
        for _ in range(200):
            try:
                blind.blind_law(rng, FEASIBLE,
                                (parent["spec"].get("search_policy") or {}).get("grid"),
                                complexity_budget=parent["spec"].get("complexity_budget"),
                                max_attempts=40)
                drawn += 1
            except blind.GridError:
                pass
        predicted = float(check["sample"]["yield_fraction"])
        self.step("the preflight's yield matches the drawer's", abs(predicted - drawn / 200) < 0.1,
                  {"preflight": predicted, "drawn": drawn / 200})

        used: set[str] = set()
        for _ in range(120):
            try:
                law = blind.blind_law(rng, FEASIBLE,
                                      (parent["spec"].get("search_policy") or {}).get("grid"),
                                      complexity_budget=parent["spec"].get("complexity_budget"))
            except blind.GridError:
                continue
            used |= {str(term["op"]) for term in law["terms"]}
        self.step("every drawn law uses only the selected terms", used <= set(FEASIBLE),
                  {"used": sorted(used), "selected": FEASIBLE})

        basis = term_selection.catalogue()
        wedge = next(row for row in basis if row["op"] == "wedge_count")
        self.step("wedge_count is reported as exactly the terms it reduces to",
                  wedge["reduces_to"] == ["degree_square_sum", "edge_count"], wedge["reduces_to"])

        self.seed_ladder(campaign_id)
        before = self.repo.claim_job("trial", ("simulate",), campaigns=(campaign_id,))
        if before is not None:
            self.repo.release_job(before["job_id"], "trial", int(before["lease_generation"]))
        paused = control.pause(self.repo, campaign_id, reason=MARKER)
        during = self.repo.claim_job("trial", ("simulate",), campaigns=(campaign_id,))
        self.step("a queued job is claimable before the pause and not during it",
                  before is not None and during is None and paused["ok"],
                  {"before": before is not None, "during": during is not None})
        self.step("the pause is visible as a state rather than as idleness",
                  control.derived_state(self.repo.campaign(campaign_id)) == "paused")
        self.step("the pause stops the proposer too", self.repo.campaign_extend_only(campaign_id))

        from graph_scale_dynamics.services.proposer.main import proposal_targets
        actives = self.repo.active_campaigns()
        targeted = {str(row["campaign_id"]) for row in
                    proposal_targets(actives, self.repo.extend_only_campaigns())}
        self.step("every active campaign that is open gets proposals",
                  all(str(row["campaign_id"]) in targeted or
                      self.repo.campaign_extend_only(str(row["campaign_id"]))
                      for row in actives),
                  {"active": [str(r["campaign_id"]) for r in actives],
                   "targeted": sorted(targeted)})

        control.set_workers(self.repo, campaign_id, 3)
        after_share = self.repo.campaign(campaign_id)["workers_target"]
        control.set_workers(self.repo, campaign_id, None)
        self.step("a campaign's share of the fleet can be changed after it exists",
                  after_share == 3 and self.repo.campaign(campaign_id)["workers_target"] is None)
        before_terms = list(self.repo.campaign(campaign_id)["spec"]["operator_whitelist"])
        manager.handle(self.repo, {"action": "workers", "campaign_id": campaign_id,
                                   "workers_target": 5,
                                   "operator_whitelist": ["edge_count"]})
        self.step("changing a share cannot change the term set",
                  list(self.repo.campaign(campaign_id)["spec"]["operator_whitelist"]) == before_terms,
                  before_terms)

        control.resume(self.repo, campaign_id, reason=MARKER)
        after = self.repo.claim_job("trial", ("simulate",), campaigns=(campaign_id,))
        if after is not None:
            self.repo.release_job(after["job_id"], "trial", int(after["lease_generation"]))
        self.step("resume opens the claim door again", after is not None)
        self.step("resume restores the extend-only switch it found",
                  self.repo.campaign_extend_only(campaign_id) is False)

        self.repo.stop_campaign_work(campaign_id, reason=MARKER)
        closed = self.repo.campaign(campaign_id)
        kept = self.repo.conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE campaign_id=?", (campaign_id,)).fetchone()["c"]
        self.step("closing a campaign keeps its work rows",
                  closed["status"] == "closed" and int(kept) == sum(SEEDED_LADDER.values()),
                  {"status": closed["status"], "jobs": int(kept)})

        overview = manager.overview(self.repo)
        row = next((item for item in overview["campaigns"]
                    if item["campaign_id"] == campaign_id), None)
        measured = {int(item["n"]): int(item["laws"]) for item in (row or {}).get("rungs", [])}
        top = [int(item["n"]) for item in (row or {}).get("top_rungs", [])]
        self.step("the page's rung ladder is the one that was seeded",
                  measured == SEEDED_LADDER, {"measured": measured, "seeded": SEEDED_LADDER})
        self.step("the deepest three rungs are reported deepest first",
                  top == [1048576, 262144, 65536]
                  and (row or {}).get("deepest_n") == 1048576
                  and (row or {}).get("deepest_laws") == SEEDED_LADDER[1048576],
                  {"top_rungs": top, "deepest_n": (row or {}).get("deepest_n")})
        self.step("the page shows the campaign's own term set",
                  list((row or {}).get("terms") or []) == FEASIBLE, (row or {}).get("terms"))

        refusal, refusal_code = manager.handle(self.repo, {"action": "delete",
                                                           "campaign_id": campaign_id})
        controls = (row or {}).get("controls") or {}
        self.step("the page deletes a campaign only with its id typed back, and never archives one",
                  refusal_code == 400 and "confirm" in str(refusal.get("error", ""))
                  and not controls.get("archive"),
                  {"refusal": refusal.get("error"), "controls": controls})

    def clean_up(self, keep: bool) -> list[str]:
        if keep:
            return []
        removed = []
        for campaign_id in self.created:
            campaign = self.repo.campaign(campaign_id)
            if campaign is None or MARKER not in str(campaign.get("change_reason") or ""):
                continue
            self.repo.stop_campaign_work(campaign_id, reason=MARKER)
            self.repo.delete_campaign(campaign_id, force=True)
            removed.append(campaign_id)
        return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/trial_campaign_manager.py: see docs/TOOLS.md")
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    parser.add_argument("--keep", action="store_true",
                        help="leave the campaigns this trial created in the folder")
    args = parser.parse_args(argv)

    target = resolve_target("folder", auto_provision=False)
    try:
        init_db(target)
    except Exception as unreachable:
        print(f"could not reach the folder's database: {unreachable}", file=sys.stderr)
        return 2
    with Repo(target) as repo:
        trial = Trial(repo)
        try:
            trial.run()
        except Exception as error:
            trial.step("the trial ran to the end", False, f"{type(error).__name__}: {error}")
        removed = trial.clean_up(args.keep)

    failed = [step for step in trial.steps if not step["ok"]]
    result = {"contract": "gsd-campaign-manager-trial-1", "steps": trial.steps,
              "created": trial.created, "deleted": removed,
              "passed": len(trial.steps) - len(failed), "failed": len(failed),
              "dsl_terms": len(dsl.OPERATORS)}
    if args.json:
        print(json.dumps(result, indent=1, default=str))
    else:
        for step in trial.steps:
            print(f"  {'ok  ' if step['ok'] else 'FAIL'}  {step['step']}")
            if not step["ok"]:
                print(f"          {json.dumps(step['detail'], default=str)[:400]}")
        print(f"\n{result['passed']} passed, {result['failed']} failed")
        if trial.created:
            print(("kept " if args.keep else "deleted ") + ", ".join(trial.created))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
