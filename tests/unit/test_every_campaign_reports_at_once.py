from __future__ import annotations

import json

from graph_scale_dynamics.services.reporter import study_run as S

GIB = 1024 ** 3


def test_the_layout_shares_the_cores_and_the_memory_between_the_campaigns(tmp_path):
    layout = S.plan(["1", "2", "3", "4", "5", "6"], tmp_path, cores=32, available=64 * GIB)
    assert layout["at_once"] == 6 and layout["report_workers_each"] == 5, layout["why"]
    for campaign in "123456":
        root = tmp_path / f"live_campaign_{campaign}"
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps({"cycle": {"snapshot_decompressed_bytes": 3 * GIB}}))
    layout = S.plan(["1", "2", "3", "4", "5", "6"], tmp_path, cores=32, available=64 * GIB)
    assert layout["at_once"] == 2 and layout["report_workers_each"] == 16, "15 GiB each: two fit in 70% of 64"
    assert "1 15.0 GiB" in layout["why"] and "0 measured" in layout["why"]


def test_each_campaign_is_charged_its_own_and_a_measure_beats_a_guess(tmp_path):
    def root(campaign, **files):
        folder = tmp_path / f"live_campaign_{campaign}"
        folder.mkdir(exist_ok=True)
        for name, body in files.items():
            (folder / name).write_text(json.dumps(body))
    for campaign in "1234":
        root(campaign, **{"manifest.json": {"cycle": {"snapshot_decompressed_bytes": 5 * GIB}}})
    root("5", **{"manifest.json": {"cycle": {"snapshot_decompressed_bytes": 100 * 1024 ** 2}}})
    layout = S.plan(list("123456"), tmp_path, cores=32, available=80 * GIB)
    assert layout["order"][:4] == list("1234") and layout["costs"]["5"] == 3 * GIB, layout["why"]
    assert layout["at_once"] == 2, "25 GiB each guessed: two fit in 56 GiB, then the small ones beside them"
    for campaign in "1234":
        root(campaign, **{S.COST_NAME: {"worker_peak_bytes": 8 * GIB, "child_private_peak_bytes": GIB // 4,
                                        "transport": S.TRANSPORT}})
    layout = S.plan(list("123456"), tmp_path, cores=32, available=80 * GIB)
    assert layout["at_once"] == 6 and "4 measured" in layout["why"], layout["why"]
    assert layout["costs"]["1"] == int(1.25 * (8 * GIB + GIB // 2)), (
        "the worker and one child at the floor; without what it held after its snapshot, as if at its peak")


def test_the_campaigns_start_in_the_order_of_their_numbers(tmp_path):
    for campaign, gib in (("1", 4), ("2", 6), ("3", 5), ("4", 4), ("6", 0)):
        root = tmp_path / f"live_campaign_{campaign}"
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps({"cycle": {"snapshot_decompressed_bytes": gib * GIB}}))
    layout = S.plan(["6", "2", "1", "4", "3"], tmp_path, cores=32, available=40 * GIB)
    assert layout["order"] == ["1", "2", "3", "4", "6"], layout["why"]
    assert layout["at_once"] == 1, "30 GiB guessed for the largest: one of them in 28 GiB, counted on the largest"


def test_a_campaign_whose_rows_have_not_moved_keeps_its_reports(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from graph_scale_dynamics.db import repo as repo_module
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.research import report_pipeline
    folder = tmp_path / "live_campaign_5"
    folder.mkdir()
    manifest = {"cycle_state": "COMPLETE", "build_number": BUILD_NUMBER, "generation_finished_utc": "t",
                "report_revisions": {"report_revision": "abc"}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(repo_module, "Repo", lambda db: nullcontext(object()))
    now = {"report_revision": "abc"}
    monkeypatch.setattr(report_pipeline, "report_revision_preflight", lambda repo, c: now)
    assert "unchanged since its cycle" in S.unchanged(tmp_path, "5", "folder")
    now["report_revision"] = "abd"
    assert S.unchanged(tmp_path, "5", "folder") is None
    manifest["build_number"] = BUILD_NUMBER - 1
    now["report_revision"] = "abc"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert S.unchanged(tmp_path, "5", "folder") is None, "a new build's reports are built by the new build"


def test_the_channel_writes_where_the_api_would_and_says_how_far_it_is(tmp_path):
    channel = S.LocalChannel("7", tmp_path / "live_campaign_7", db="folder", progress=tmp_path / "7.json",
                             request_id="r1", workers=4)
    assert json.loads((tmp_path / "7.json").read_text())["state"] == "requested"
    assert channel.state("7")["trigger_source"] == "quiet", "its reports are built side by side"
    channel.publish("7", "05", {"body": {"x": 1}})
    assert json.loads((tmp_path / "live_campaign_7" / "reports" / "05.json").read_text())["body"] == {"x": 1}
    channel.phase("7", state="running", stage="report 5/28", started=True,
                  diagnostics={"cycle": {"report_pool": {"workers": 4}}})
    seen = json.loads((tmp_path / "7.json").read_text())
    assert (seen["state"], seen["stage"], seen["report_pool"]) == ("running", "report 5/28", {"workers": 4})
    workers, why = channel.pool_size("quiet", {"resident_bytes": 1 * GIB}, 28)
    assert 1 <= workers <= 4 and "share of 4 cores" in why
