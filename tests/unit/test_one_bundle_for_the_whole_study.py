from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile

import pytest

from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.operations.campaign_control import shipped_spec
from graph_scale_dynamics.operations.report_home import root_for
from graph_scale_dynamics.reporting import study_bundle as B
from graph_scale_dynamics.research.gate_tree import build_gate_tree
from graph_scale_dynamics.research.report_bundle import REPORT_CODES

pytestmark = pytest.mark.skipif(shutil.which("zstd") is None, reason="the bundle codec is zstd")

TREE = build_gate_tree({"A": [{"decision_id": "1", "at_n": 256, "action": "stop", "rule": "empty", "facts": {}}],
                        "B": [{"decision_id": "2", "at_n": 256, "action": "run_next", "rule": "base_block",
                               "facts": {"salted": ["empty"]}}]})


def _report_root(base, campaign_id, *, state="COMPLETE", evidence=True):
    root = root_for(base, campaign_id)
    (root / "reports").mkdir(parents=True)
    revision, cycle = f"rev{campaign_id}abcdef", f"cycle-{campaign_id}"
    for code in REPORT_CODES:
        body = {"bundle_revision": revision, "report_cycle_id": cycle, "body": {"n": code}}
        if code == B.DECISION_REPORT_CODE:
            body["body"] = {"gate_tree": TREE}
        (root / "reports" / f"{code}.json").write_text(json.dumps(body))
    (root / "manifest.json").write_text(json.dumps({
        "campaign_id": campaign_id, "cycle_state": state, "bundle_revision": revision, "bundle_cycle_id": cycle,
        "generation_finished_utc": "2026-09-27T10:00:00Z"}))
    if evidence:
        (root / "evidence").mkdir()
        (root / "evidence" / "probe_calibration.json").write_text(json.dumps({"contract": "the table"}))
    return root


ANCHOR = {"contract": "anchor-1", "candidate_id": "a" * 64, "campaign_id": "2", "status": "probe_around",
          "readings": [{"n": 65536, "d_s": 2.19, "mean_degree": 4.03, "residual": -0.84}]}


class Conn:
    def execute(self, sql, params=()):
        class Result:
            def fetchone(self):
                return {"c": 5000} if "COUNT(*)" in sql else None

            def fetchall(self):
                return [{"document": json.dumps(ANCHOR)}] if "FROM anchors" in sql else []
        return Result()


class Repo:
    def __init__(self):
        specs = dict(S.quadrant_specs(shipped_spec()))
        self.specs = {str(i + 1): spec for i, spec in enumerate(specs.values())}
        self.flags = {f"{S.LAW_BUDGET_PREFIX}{cid}": "5000" for cid in self.specs}
        self.flags[f"{S.BUDGET_REACHED_PREFIX}1"] = json.dumps({"at": "2026-09-27T09:00:00Z"})
        self.conn = Conn()

    def campaign(self, campaign_id):
        spec = self.specs.get(str(campaign_id))
        return None if spec is None else {"campaign_id": str(campaign_id), "status": "active", "spec": spec,
                                          "workers_target": 8, "created_utc": "2026-09-26T18:00:00Z"}

    def get_flag(self, key, default=None):
        return self.flags.get(key, default)

    def all_campaigns(self):
        return [self.campaign(cid) for cid in self.specs]

    def campaign_link(self, campaign_id):
        return None

    def campaign_pending_work(self, campaign_id):
        return False


def _members(path):
    return {name: payload for name, _kind, payload in _listing(path)}


def _listing(path):
    with subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE) as unzstd:
        data = unzstd.stdout.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        return [(m.name, m.type, archive.extractfile(m).read() if m.isfile() else None) for m in archive]


def _recorded(base, study="GSD533"):
    from graph_scale_dynamics.operations import study_record as R
    R.write(base.parent, study=study, kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lambda *_: None)
    return base


def test_the_study_bundle_holds_every_campaign_whole_beside_the_study_and_the_trees(tmp_path):
    base = _recorded(tmp_path / "F533" / "var" / "reports")
    for cid in ("1", "2"):
        _report_root(base, cid)
    _report_root(base, "3", state="PARTIAL", evidence=False)
    entry = B.build(base, Repo(), ["1", "2", "3", "4"], request_id="r-1")

    assert entry["study_id"] == "GSD533", "the study the folder recorded"
    assert [c["campaign_id"] for c in entry["campaigns"]] == ["1", "2"]
    assert entry["campaigns"][0]["label"] == "zero temperature, mean degree to 16"
    assert {m["campaign_id"]: m["why"] for m in entry["missing"]} == {
        "3": "its last report cycle is PARTIAL", "4": "no report manifest"}, "never silently left out"

    archive = B.bundles_dir(base) / entry["filename"]
    members = _members(archive)
    stem = entry["filename"][:-len(".tar.zst")]
    study = json.loads(members[f"{stem}/study.json"])
    assert study["contract"] == B.STUDY_BUNDLE_CONTRACT and study["request_id"] == "r-1"
    first = study["campaigns"][0]
    assert first["quadrant"] == {"zero_temperature": True, "dense_cap": 16.0,
                                 "label": "zero temperature, mean degree to 16"}
    assert (first["law_budget"], first["laws_held"]) == (5000, 5000)
    assert first["state"] == S.DONE, "at its budget with nothing in flight"
    assert first["gate_tree"]["withheld_by_gate"] == {"empty": 1}
    assert first["gate_tree"]["let_through_by_gate"] == {"empty": 1}
    for campaign in study["campaigns"]:
        part = campaign["bundle"]
        assert part.startswith(f"campaign_{campaign['campaign_id']}_reports_")
        assert f"{stem}/{part}/bundle.json" in members and f"{stem}/{part}/28-decision-engine.json" in members
        assert f"{stem}/{part}/evidence/probe_calibration.json" in members, "each part is a whole bundle"
    anchors = json.loads(members[f"{stem}/anchors.json"])
    assert anchors["anchors"] == [ANCHOR] and anchors["by_status"] == {"probe_around": 1}
    assert study["anchors"] == {"count": 1, "by_status": {"probe_around": 1}, "file": "anchors.json"}
    explorer = members[f"{stem}/explorer.html"]
    assert explorer.startswith(b"<!doctype html>") and b'data-contract="gsd-study-explorer-1"' in explorer
    assert (B.bundles_dir(base) / entry["explorer"]).read_bytes() == explorer, "beside the archive too"
    assert f"{stem}/null_atlas.json" not in members and f"{stem}/salt_ledger.json" not in members, (
        "786: nothing is carried between studies, so the bundle holds no atlas and no salt ledger")
    assert "null_atlas" not in study and "salt" not in study

    front = members[f"{stem}/index.html"].decode()
    assert 'data-contract="gsd-study-front-1"' in front and 'href="explorer.html"' in front
    for part in (c["bundle"] for c in study["campaigns"]):
        assert f'href="{part}/"' in front, "each campaign's part is linked from the page inside the archive"
    advice = json.loads(members[f"{stem}/advice.json"])
    assert advice["contract"] == "gsd-study-advice-1" and "unavailable" not in advice, advice.get("unavailable")
    assert study["advice"]["file"] == "advice.json" and study["front_page"] == "index.html"
    beside = (B.bundles_dir(base) / entry["front"]).read_text()
    assert f'href="{stem}.explorer.html"' in beside and f'href="{stem}.tar.zst"' in beside, (
        "the copy beside the archive points at the files beside it")
    assert json.loads((B.bundles_dir(base) / entry["advice"]).read_text()) == advice

    trees = members[f"{stem}/gate_trees.html"].decode()
    assert 'data-contract="gsd-gate-trees-page-1"' in trees and '"links":{"explorer":"explorer.html"' in trees
    assert 'href="gate_trees.html"' in front and f'href="{stem}.gate_trees.html"' in beside
    beside_trees = (B.bundles_dir(base) / entry["gates"]).read_text()
    assert f'"explorer":"{stem}.explorer.html"' in beside_trees, "the copy beside opens the explorer beside it"
    assert not [name for name in members if name.endswith(".svg")], "pages, not pictures (578)"
    assert "svg" not in entry and "maps" not in entry and not list(B.bundles_dir(base).glob("*.svg"))
    listing = _listing(archive)
    assert [name.split("/", 1)[1] for name, _kind, _payload in listing[:6]] == [
        "index.html", "explorer.html", "gate_trees.html", "study.json", "advice.json", "anchors.json"], (
        "the study's own files first: an unpacker that stops early has them")
    assert all(kind == tarfile.REGTYPE for _name, kind, _payload in listing), "every member a plain file"

    index = B.read_index(base)
    assert index["bundles"][0]["filename"] == entry["filename"] and index["study_id"] == "GSD533"
    assert not list(B.bundles_dir(base).glob("*.partial"))


def test_the_study_is_the_one_its_first_start_recorded_not_the_folder_s_name(tmp_path):
    from graph_scale_dynamics.operations import study_record as R
    base = tmp_path / "251" / "main" / "var" / "reports"
    assert B.study_id(base) == "default"
    R.write(base.parent, study="256", kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lambda *_: None)
    assert B.study_id(base) == "256"


def test_a_second_study_bundle_is_added_and_nothing_is_deleted(tmp_path, monkeypatch):
    base = tmp_path / "F" / "var" / "reports"
    _report_root(base, "1")
    stamps = iter(["2026-09-27T10:00:00Z", "2026-09-28T10:00:00Z"])
    monkeypatch.setattr(B, "_utc", lambda: next(stamps))
    first = B.build(base, Repo(), ["1"])
    second = B.build(base, Repo(), ["1"])
    assert [b["filename"] for b in B.read_index(base)["bundles"]] == [second["filename"], first["filename"]]
    assert (B.bundles_dir(base) / first["filename"]).is_file()


def test_the_calibration_and_the_first_read_take_a_study_bundle(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    base = _recorded(tmp_path / "F533" / "var" / "reports")
    _report_root(base, "1")
    _report_root(base, "2")
    entry = B.build(base, Repo(), ["1", "2"])
    archive = B.bundles_dir(base) / entry["filename"]
    root = Path(__file__).resolve().parents[2]

    def tool(name):
        spec = importlib.util.spec_from_file_location(f"tool_{name}", root / "tools" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    assert tool("collect_calibration")._from_bundle(archive) == {"contract": "the table"}
    assert tool("read_bundle").main([str(archive)]) == 0
    out = capsys.readouterr().out
    assert "study GSD533" in out and "campaign 1 (zero temperature, mean degree to 16)" in out
    assert out.count("bundle campaign_") == 2, "then every campaign's part, as a bundle of its own"


def test_the_web_process_lists_and_serves_the_study_beside_the_campaign_roots(tmp_path):
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    from graph_scale_dynamics.services.web.main import build_handler

    base = tmp_path / "GSD533" / "var" / "reports"
    _report_root(base, "1")
    entry = B.build(base, Repo(), ["1"])
    handler = build_handler(api_host="127.0.0.1", api_port=9, bind_host="127.0.0.1", allowed_hosts=(),
                            base_path="", report_root=root_for(base, "1"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def get(path):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    try:
        status, _, body = get("/api/reports/study")
        index = json.loads(body)
        assert status == 200 and index["bundles"][0]["filename"] == entry["filename"]
        assert index["download_prefix"] == "/reports/study/bundles/"
        status, headers, body = get(index["download_prefix"] + entry["filename"])
        assert status == 200 and headers["Content-Type"] == "application/zstd"
        assert "attachment" in headers["Content-Disposition"]
        assert body == (B.bundles_dir(base) / entry["filename"]).read_bytes()
        status, headers, _ = get(index["download_prefix"] + entry["gates"])
        assert status == 200 and headers["Content-Type"].startswith("text/html"), "the gate trees' page (578)"
        assert get("/reports/study/../live_campaign_1/manifest.json")[0] == 404, "only the bundles folder"
        assert get("/reports/study/bundles/../../live_campaign_1/manifest.json")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_a_folder_s_focus_goes_into_its_bundle_whole_and_named_on_the_study_s_page(tmp_path):
    from graph_scale_dynamics.operations import focus
    base = _recorded(tmp_path / "F533" / "var" / "reports")
    _report_root(base, "1")
    repo = Repo()
    state = {"contract": focus.CONTRACT, "study": "GSD533", "campaigns": {"N": "12", "S": "13", "D": "14"},
             "current": {"law": "ab" * 32, "label": "C3-G7363", "stage": focus.BOUNDARIES, "points": {}},
             "done": [{"law": "cd" * 32, "stage": focus.MAPPED, "region": "GG#1"}],
             "regions": [{"number": 1, "name": "GG#1", "kind": "ring", "ranges": {"beta": [0.18, 0.2]}}]}
    repo.flags[focus.FLAG] = json.dumps(state)
    entry = B.build(base, repo, ["1"], request_id="r-2")
    stem = entry["filename"][:-len(".tar.zst")]
    members = _members(B.bundles_dir(base) / entry["filename"])
    named = dict(state, current=dict(state["current"], label="SGSD533-C3-G7363"))
    found = json.loads(members[f"{stem}/focus.json"])
    assert found.pop("zone_now")["contract"] == "gsd-zone-now-1", "with what ran when it was made (884)"
    assert found == named, "whole, every law named by its study, campaign and graph"
    assert json.loads(members[f"{stem}/study.json"])["focus"] == {
        "file": "focus.json", "contract": focus.CONTRACT, "campaigns": state["campaigns"], "done": 1, "regions": ["GG#1"],
        "law": "ab" * 32, "label": "SGSD533-C3-G7363", "stage": focus.BOUNDARIES}
