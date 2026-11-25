from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.services.api import study_scope as S


def _landscape(cid: str, scores: list[int]) -> dict:
    return {"campaign_id": cid, "revision": f"r{cid}", "generated_utc": f"2026-10-28T1{cid}:00:00Z",
            "analysis_version": "analysis-4.0.0", "limits": {}, "score_model": {"id": "x"},
            "selection": {"headline": "one campaign"},
            "counts": {"measured_candidates": len(scores), "tier_candidates": {"0": len(scores), "1": 0}},
            "exposure": {"opportunities": 10, "selected": 2},
            "dimension_points": [{"candidate_id": f"{cid}-{i}"} for i in range(len(scores))],
            "top_candidates": [{"candidate_id": f"{cid}-{i}", "law_score": {"score": s, "to_n": 4096}}
                               for i, s in enumerate(scores)]}


def test_the_landscapes_of_every_batch_are_one_map():
    merged = S.merge_landscapes([_landscape("1", [17, 0]), _landscape("2", [26, 3, 0])])
    assert merged["campaign_id"] == S.STUDY and merged["batches"] == ["1", "2"]
    assert len(merged["dimension_points"]) == 5 and {p["campaign_id"] for p in merged["dimension_points"]} == {"1", "2"}
    assert [row["law_score"]["score"] for row in merged["top_candidates"]] == [26, 17, 3, 0, 0], "ranked over all"
    assert merged["counts"]["measured_candidates"] == 5 and merged["counts"]["tier_candidates"] == {"0": 5, "1": 0}
    assert merged["exposure"] == {"opportunities": 20, "selected": 4}
    assert "all 2 batches" in merged["selection"]["headline"]
    assert merged["revision"] == S.revision_of(["r1", "r2"]), "it moves when any batch's landscape moves"


def test_the_rung_ladder_adds_what_adds_and_weighs_what_does_not():
    one = [{"n": 4096, "laws": 10, "completed": 30, "running": 2, "median_seconds": 100.0, "max_seconds": 300.0,
            "rung_seconds_total": 3000.0, "compute_share": 1.0, "stopped_by_rule": {"empty": 3}}]
    two = [{"n": 4096, "laws": 5, "completed": 10, "running": 1, "median_seconds": 200.0, "max_seconds": 900.0,
            "rung_seconds_total": 1000.0, "compute_share": 1.0, "stopped_by_rule": {"empty": 1, "too_dense": 2}},
           {"n": 16384, "laws": 1, "completed": 3, "running": 0, "median_seconds": 50.0, "max_seconds": 60.0,
            "rung_seconds_total": 4000.0, "compute_share": 0.8}]
    rows = {row["n"]: row for row in S.merge_ladder([one, two])}
    at = rows[4096]
    assert (at["laws"], at["completed"], at["running"], at["rung_seconds_total"]) == (15, 40, 3, 4000.0)
    assert at["median_seconds"] == 125.0, "weighted by the graphs each batch completed: (100 x 30 + 200 x 10) / 40"
    assert at["max_seconds"] == 900.0 and at["stopped_by_rule"] == {"empty": 4, "too_dense": 2}
    assert at["compute_share"] == 0.5 and rows[16384]["compute_share"] == 0.5, "the share read again over the sum"


def test_the_overviews_join_the_live_work_and_keep_the_fleet_s_own():
    a = {"campaign_id": "1", "status": "active", "active": [{"candidate_id": "x"}], "proposed": [],
         "rung_distribution": [], "analysis_backlog": 3, "runtime_counts": {"graph_jobs_created": 5},
         "analysis_queue": {"queued": 2}, "services": {"api": "fleet"}}
    b = dict(a, campaign_id="2", active=[{"candidate_id": "y"}], analysis_backlog=4,
             runtime_counts={"graph_jobs_created": 7}, analysis_queue={"queued": 1})
    merged = S.merge_overviews([a, b])
    assert merged["campaign_id"] == S.STUDY and merged["batches"] == ["1", "2"]
    assert [row["candidate_id"] for row in merged["active"]] == ["x", "y"]
    assert [row["campaign_id"] for row in merged["active"]] == ["1", "2"]
    assert S.merge_overviews([dict(a, active=[{"candidate_id": "z", "campaign_id": "9"}])])["active"][0][
        "campaign_id"] == "9", "a row that names its own campaign keeps it"
    assert merged["analysis_backlog"] == 7 and merged["runtime_counts"] == {"graph_jobs_created": 12}
    assert merged["analysis_queue"] == {"queued": 3} and merged["services"] == {"api": "fleet"}


class _Handler:
    def __init__(self):
        self.sent = None

    def _json(self, payload, status=200):
        self.sent = (status, payload)

    def _send_file(self, path, _kind):
        self.sent = (200, json.loads(Path(path).read_text()))

    def _access_payload(self):
        return {"admin": False}

    def _privileged(self):
        return False


def test_the_route_merges_in_a_child_and_says_what_it_waits_for(tmp_path):
    bodies = {}
    for cid, scores in (("1", [5]), ("2", [9])):
        body = tmp_path / f"landscape-{cid}.json"
        body.write_text(json.dumps(_landscape(cid, scores)))
        bodies[cid] = body
    scheduled = []
    scope = S.Scope(batches=lambda: ["1", "2"],
                    landscape_status=lambda cid: (bodies[cid], None, {"revision": f"r{cid}"}, 1.0, False, None),
                    schedule_landscape=scheduled.append, landscape_ttl=60.0,
                    cached_overview=lambda key: ({"campaign_id": key[0], "active": []}, 1.0, False, None),
                    schedule_overview=scheduled.append, overview_ttl=60.0, host_snapshot=lambda: {},
                    incidents=lambda handler: [], cache_root=tmp_path, python=__import__("sys").executable,
                    root=Path(__file__).resolve().parents[2])
    handler = _Handler()
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert handler.sent[0] == 202 and handler.sent[1]["pending"], "nothing merged yet: the page waits"
    with scope.merging:
        pass
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert handler.sent[0] == 200 and handler.sent[1]["revision"] == S.revision_of(["r1", "r2"])
    scope.serve(handler, "landscape", {})
    assert [row["law_score"]["score"] for row in handler.sent[1]["top_candidates"]] == [9, 5]
    scope.serve(handler, "overview", {})
    assert handler.sent[1]["campaign_id"] == S.STUDY and handler.sent[1]["dashboard_response"]["pending"] is False
    assert scheduled == [], "fresh caches: nothing refreshed for the study's sake"
    empty = S.Scope(batches=lambda: [], landscape_status=None, schedule_landscape=None, landscape_ttl=1.0,
                    cached_overview=None, schedule_overview=None, overview_ttl=1.0, host_snapshot=None,
                    incidents=None, cache_root=tmp_path, python="python3", root=tmp_path)
    empty.serve(handler, "overview", {})
    assert handler.sent[0] == 404


def test_the_batches_are_the_campaigns_with_a_law_budget_the_arm_among_them():
    import threading

    from graph_scale_dynamics.services.api.dashboard_workers import DashboardWorkers

    campaigns = [{"campaign_id": "10", "status": "active", "spec_json": "{}"},
                 {"campaign_id": "2", "status": "active", "spec_json": "{}"},
                 {"campaign_id": "6", "status": "active", "spec_json": json.dumps({"study_design": {"arm": "natural"}})},
                 {"campaign_id": "7", "status": "active", "spec_json": "{}"},
                 {"campaign_id": "3", "status": "archived", "spec_json": "{}"}]
    budgets = [{"key": f"law_budget:{cid}"} for cid in ("10", "2", "6", "3")]

    class Repo:
        class conn:
            @staticmethod
            def execute(sql, params=()):
                rows = budgets if "FROM control" in sql else campaigns
                return type("Rows", (), {"fetchall": staticmethod(lambda: rows)})()

        def close(self):
            pass

    workers = DashboardWorkers(Repo, threading.BoundedSemaphore(1))
    assert workers.batches() == ["2", "6", "10"], "the pilot arm in (654); the hand-fed control and an archived batch out"


def test_the_focus_s_and_the_seed_s_campaigns_of_the_study_join_its_batches_on_home():
    import threading

    from graph_scale_dynamics.services.api.dashboard_workers import DashboardWorkers

    design = lambda study, kind=None: json.dumps({"study_design": dict({"study": study}, **({"kind": kind} if kind else {}))})
    campaigns = [{"campaign_id": "1", "status": "active", "spec_json": design("176", "blind")},
                 {"campaign_id": "2", "status": "active", "spec_json": design("176", "blind")},
                 {"campaign_id": "11", "status": "active", "spec_json": "{}"},
                 {"campaign_id": "12", "status": "active", "spec_json": design("176", "focus")},
                 {"campaign_id": "13", "status": "active", "spec_json": design("176", "focus")},
                 {"campaign_id": "14", "status": "active", "spec_json": design("176", "seed")},
                 {"campaign_id": "15", "status": "active", "spec_json": design("175", "focus")},
                 {"campaign_id": "16", "status": "archived", "spec_json": design("176", "focus")}]
    budgets = [{"key": f"law_budget:{cid}"} for cid in ("1", "2")]

    class Repo:
        class conn:
            @staticmethod
            def execute(sql, params=()):
                rows = budgets if "FROM control" in sql else campaigns
                return type("Rows", (), {"fetchall": staticmethod(lambda: rows)})()

        def close(self):
            pass

    workers = DashboardWorkers(Repo, threading.BoundedSemaphore(1))
    assert workers.batches() == ["1", "2", "12", "13", "14"], (
        "the study's focus and seed campaigns beside its batches; the controls, another study's focus and an archived one out")


def test_a_batch_that_never_arrives_and_a_failing_merge_say_why_and_wait(tmp_path, monkeypatch):
    missing = tmp_path / "landscape-2.json"
    body = tmp_path / "landscape-1.json"
    body.write_text(json.dumps(_landscape("1", [5])))
    status = {"1": (body, None, {"revision": "r1"}, 1.0, False, None),
              "2": (missing, None, None, None, False, "MemoryError: the landscape worker ran out")}
    scope = S.Scope(batches=lambda: ["1", "2"], landscape_status=lambda cid: status[cid],
                    schedule_landscape=lambda cid: None, landscape_ttl=60.0, cached_overview=None,
                    schedule_overview=None, overview_ttl=60.0, host_snapshot=lambda: {}, incidents=lambda handler: [],
                    cache_root=tmp_path, python="python3", root=tmp_path)
    handler = _Handler()
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert handler.sent[1]["errors"] == {"2": "MemoryError: the landscape worker ran out"}
    missing.write_text(json.dumps(_landscape("2", [9])))
    status["2"] = (missing, None, {"revision": "r2"}, 1.0, False, None)
    started = []
    monkeypatch.setattr(S.threading, "Thread", lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})())
    scope.merge_failed = {"revision": S.revision_of(["r1", "r2"]), "at": __import__("time").monotonic(),
                          "error": "ValueError: bad landscape"}
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert started == [], "a merge that just failed for this revision is not started again at once"
    assert handler.sent[1]["last_refresh_error"] == "ValueError: bad landscape"
    scope.merge_failed["at"] -= S.MERGE_RETRY_SECONDS + 1
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert len(started) == 1, "after the wait it is tried again"


def test_every_batch_brings_each_laws_best_lattice_start_to_the_one_map():
    def chain_point(cid: str, law: str, by: str | None, chain: str | None) -> dict:
        return {"candidate_id": law, "d_s_estimate": 2.0, "law_score": {"score": 17, "by": by, "chain": chain},
                "landscape_band_with_lattices": "einstein", "settled_probes_with_lattices": ["d_s", "d_V", "d_B", "d_w"]}
    one, two = _landscape("1", [17]), _landscape("2", [3])
    one["every_chain"] = {"contract": "c", "names": ["empty", "random", "triangular"],
                          "points": {"triangular": [chain_point("1", "1-0", "kept", "triangular"),
                                                    chain_point("1", "1-9", "empty", "empty")],
                                     "random": [chain_point("1", "1-0", "kept", "triangular")]},
                          "counts": {"triangular": {"measured_candidates": 2}}}
    two["every_chain"] = {"contract": "c", "names": ["empty", "random", "triangular", "square"],
                          "points": {"triangular": [chain_point("2", "1-0", "lattice", "triangular")]},
                          "counts": {"triangular": {"measured_candidates": 1}}}
    every = S.merge_landscapes([one, two])["every_chain"]
    assert every["names"] == ["empty", "random", "triangular", "square"]
    assert [(p["campaign_id"], p["candidate_id"]) for p in every["points"]["triangular"]] == [("1", "1-0"), ("2", "1-0")]
    assert every["points"]["random"] == [], "only the start a law's score names is carried"
    assert every["counts"]["triangular"]["measured_candidates"] == 3


def test_a_marker_is_filled_by_the_score_that_sets_its_band():
    from graph_scale_dynamics.services.api.landscape_worker import score_bands
    point = {"law_score": {"score": 17, "by": "kept", "chain": "triangular", "parts": {
        "empty": {"value": 2.0, "to_n": 16384, "items": {"d_s": 2, "d_V": 1, "d_B": 0, "d_w": 0, "einstein": 0}},
        "kept": {"value": 17.0, "to_n": 65536, "items": {"d_s": 3, "d_V": 3, "d_B": 3, "d_w": 3, "einstein": 3}}}}}
    score_bands(point)
    assert point["landscape_band"] == "contracting" and point["settled_probes"] == ["d_s"]
    assert point["landscape_band_with_lattices"] == "einstein"
    assert point["settled_probes_with_lattices"] == ["d_s", "d_V", "d_B", "d_w"]


def _ledger(read: int) -> dict:
    return {"contract": "gsd-let-through-ledger-1", "decisions_read": read, "ab_share": 0.5,
            "gates": {"empty": {"256": {"held": read, "let_through": 1}}}}


def test_the_study_view_carries_the_gates_ledger_the_freshest_batch_read():
    one, two, three = _landscape("1", [1]), _landscape("2", [2]), _landscape("3", [3])
    one["gates_ledger"], two["gates_ledger"], three["gates_ledger"] = _ledger(40), _ledger(41), None
    merged = S.merge_landscapes([one, two, three])
    assert merged["gates_ledger"]["decisions_read"] == 41, "every batch reads the whole study's ledger; the freshest wins"
    assert S.merge_landscapes([_landscape("1", [1])])["gates_ledger"] is None


def _keys_of_a_batch_s_landscape() -> set:
    import ast
    import inspect

    from graph_scale_dynamics.services.api import landscape_worker
    tree = ast.parse(inspect.getsource(landscape_worker.build_landscape))
    returned = [node.value for node in ast.walk(tree) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    assert returned, "build_landscape returns a dict literal"
    return {key.value for key in returned[-1].keys if isinstance(key, ast.Constant)}


MERGE_LEAVES_OUT = {
    "refused_candidates": "kept empty in a batch too",
    "every_chain": "merged by merge_every_chain",
}


def test_the_study_view_keeps_every_key_a_batch_s_landscape_has():
    batch = {key: None for key in _keys_of_a_batch_s_landscape()}
    body = dict(_landscape("1", [1]), **{k: v for k, v in batch.items() if k not in _landscape("1", [1])})
    merged = S.merge_landscapes([body])
    lost = sorted(key for key in batch if key not in merged and key not in MERGE_LEAVES_OUT)
    assert not lost, f"the study view drops what Home reads from a batch's landscape: {lost} (789 lost the gates' ledger so)"


def test_each_batch_scores_its_own_laws_so_the_study_view_adds_their_scored_counts():
    def scored(read, count, best, campaign):
        return {"decisions_read": read, "scored_from": [campaign], "scored_at_least": False,
                "gates": {"starts_alike": {"4096": {"let_through": 9, "scored": count, "best_score": best,
                                                    "best_law": [campaign, "x"] if best else None}}}}
    merged = S.merge_ledgers([scored(10, 2, 30.0, "1"), scored(12, 1, 71.0, "2"), scored(11, 0, None, "3")])
    entry = merged["gates"]["starts_alike"]["4096"]
    assert (entry["scored"], entry["best_score"], entry["best_law"]) == (3, 71.0, ["2", "x"])
    assert merged["scored_from"] == ["1", "2", "3"] and merged["decisions_read"] == 12


def test_a_batch_never_built_is_built_before_one_gone_stale_so_ten_batches_all_arrive(tmp_path):
    ids = [str(k) for k in range(1, 11)]
    ages = {cid: None for cid in ids}
    bodies = {cid: tmp_path / f"landscape-{cid}.json" for cid in ids}
    slot = {"busy": None}
    built = []

    def status(cid):
        made = ages[cid] is not None
        return (bodies[cid], None, {"revision": f"r{cid}"} if made else None, ages[cid], slot["busy"] == cid, None)

    def schedule(cid):
        if slot["busy"] is not None:
            return False
        slot["busy"] = cid
        return True

    scope = S.Scope(batches=lambda: ids, landscape_status=status, schedule_landscape=schedule, landscape_ttl=16.0,
                    cached_overview=None, schedule_overview=None, overview_ttl=16.0, host_snapshot=lambda: {},
                    incidents=lambda handler: [], cache_root=tmp_path, python="python3", root=tmp_path)
    handler = _Handler()
    for _poll in range(40):
        scope.serve(handler, "landscape", {"meta": ["1"]})
        done = slot["busy"]
        if done is not None:
            for cid in ids:
                if ages[cid] is not None:
                    ages[cid] += 20.0
            ages[done] = 0.0
            bodies[done].write_text(json.dumps(_landscape(done, [1])))
            built.append(done)
            slot["busy"] = None
        if all(age is not None for age in ages.values()):
            break
    assert built[:10] == ids, "every batch built once before any is built again (844 rebuilt 1 and 2 for ever)"
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert handler.sent[1]["waiting_for"] == []
    assert slot["busy"] == "1", "batch 1, built longest ago, goes first again"
    slot["busy"] = None
    ages.update({cid: 20.0 + int(cid) for cid in ids})
    scope.serve(handler, "landscape", {"meta": ["1"]})
    assert slot["busy"] == "10", "then the stalest first"
