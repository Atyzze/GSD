from __future__ import annotations

import json
import shutil

import pytest

from graph_scale_dynamics.operations import quiet_report as Q
from graph_scale_dynamics.reporting import study_bundle as B
from graph_scale_dynamics.reporting import study_front as F
from tests.unit.test_one_bundle_for_the_whole_study import Repo, _members, _recorded, _report_root

needs_zstd = pytest.mark.skipif(shutil.which("zstd") is None, reason="the bundle codec is zstd")


def _study(entry, base) -> dict:
    stem = entry["filename"][:-len(".tar.zst")]
    return json.loads(_members(B.bundles_dir(base) / entry["filename"])[f"{stem}/study.json"])


@needs_zstd
def test_a_cycle_that_did_not_finish_in_the_request_is_missing_not_an_older_one_bundled(tmp_path):
    base = _recorded(tmp_path / "F" / "var" / "reports")
    for cid in ("1", "2"):
        _report_root(base, cid)
    entry = B.build(base, Repo(), ["1", "2"], finished=["1"])
    assert [c["campaign_id"] for c in entry["campaigns"]] == ["1"]
    assert {m["campaign_id"]: m["why"] for m in entry["missing"]}["2"] == "its report cycle did not finish in this request"


@needs_zstd
def test_an_incoherent_part_is_named_and_the_rest_are_bundled(tmp_path):
    base = _recorded(tmp_path / "F" / "var" / "reports")
    _report_root(base, "1")
    root = _report_root(base, "2")
    body = json.loads((root / "reports" / "05.json").read_text())
    (root / "reports" / "05.json").write_text(json.dumps(dict(body, report_cycle_id="another cycle")))
    entry = B.build(base, Repo(), ["1", "2"])
    assert [c["campaign_id"] for c in entry["campaigns"]] == ["1"]
    why = {m["campaign_id"]: m["why"] for m in entry["missing"]}["2"]
    assert why.startswith("its reports are not one cycle"), why


def test_the_ledgers_are_written_only_once_the_archive_is(tmp_path, monkeypatch):
    base = _recorded(tmp_path / "F" / "var" / "reports")
    _report_root(base, "1")

    def fails(_target, members):
        for _ in members:
            raise OSError("the disk filled")

    monkeypatch.setattr(B, "_write_tar_zstd", fails)
    with pytest.raises(OSError):
        B.build(base, Repo(), ["1"])
    var = base.parent
    assert not (var / "salt" / "ledger.json").exists(), "no ledger from a bundle that was never made"


@needs_zstd
def test_every_campaign_of_the_folder_not_asked_for_is_named_with_its_status(tmp_path):
    base = _recorded(tmp_path / "F" / "var" / "reports")
    _report_root(base, "1")
    repo = Repo()
    closed = dict(repo.campaign("2"), status="closed")
    repo.campaign = lambda cid, _was=repo.campaign: closed if str(cid) == "2" else _was(cid)
    entry = B.build(base, repo, ["1"])
    absent = {m["campaign_id"]: m for m in entry["missing"]}
    assert absent["2"]["status"] == "closed" and absent["2"]["why"].startswith("not in this request: campaign 2 is closed")
    assert set(absent) == {cid for cid in repo.specs if cid != "1"}, "every one, never left out without a word"


@needs_zstd
def test_the_rows_read_after_the_fleet_resumed_say_so(tmp_path):
    base = _recorded(tmp_path / "F" / "var" / "reports")
    _report_root(base, "1")
    entry = B.build(base, Repo(), ["1"], finished=["1"], resumed_utc="2026-10-29T01:00:00Z")
    study = _study(entry, base)
    read = study["read_utc"]
    assert read["fleet_resumed_utc"] == "2026-10-29T01:00:00Z" and {"counts", "tables", "anchors"} <= set(read)
    front = (B.bundles_dir(base) / entry["front"]).read_text()
    assert "after the fleet was resumed at 2026-10-29T01:00:00Z" in front and "may run ahead of the reports" in front


def test_the_front_page_counts_each_graph_once_and_names_who_is_not_in_its_sums():
    campaigns = [{"campaign_id": "1", "laws": 10, "graphs": 12, "graphs_finished": 9, "state": "running"}]
    page = F.render(study={"study_id": "256", "built_utc": "x"}, campaigns=campaigns, links={},
                    missing=[{"campaign_id": "4", "why": "its report cycle did not finish in this request"}])
    assert "10 laws and 9 graphs" in page, "a seed run again as a longer chain is one graph"
    assert "campaign 4 is not in these sums: its report cycle did not finish in this request" in page
    old = F.render(study={"study_id": "255", "built_utc": "x"}, campaigns=[dict(campaigns[0], graphs_finished=None)],
                   links={})
    assert "10 laws and 12 graphs" in old, "a bundle from before the field reads what it has"


class _Flags:
    def __init__(self, record=None):
        self.flags = {} if record is None else {Q.QUIET_REPORT_KEY: json.dumps(record)}

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def test_a_quiet_report_holds_the_fleet_until_its_reports_are_done():
    for stage in Q.HOLDING_STAGES:
        assert "holds the fleet quiet" in Q.holding(_Flags({"stage": stage, "request_id": "r"}))
    assert Q.holding(_Flags({"stage": Q.RESUMING})) is None and Q.holding(_Flags({"stage": Q.DONE})) is None
    assert Q.holding(_Flags({"stage": Q.REPORTING, "only": True})) is None, "one campaign's cycle paused nothing"
    assert Q.holding(_Flags()) is None

    from graph_scale_dynamics.services.api import campaign_manager as CM
    for action in ("resume", "workers", "allocate", "fleet_resume", "reopen"):
        payload, code = CM.handle(_Flags({"stage": Q.REPORTING, "request_id": "r"}),
                                  {"action": action, "campaign_id": "1"})
        assert code == 409 and "holds the fleet quiet" in payload["error"], action


def test_a_runner_that_cannot_start_gives_the_fleet_back(monkeypatch):
    def cannot(_record):
        raise OSError("no space left on device")

    monkeypatch.setattr(Q, "start_study_run", cannot)
    repo = _Flags({"stage": Q.DRAINING, "only": True, "campaign_id": "1", "campaigns": ["1"], "request_id": "r"})
    record = Q.step(repo)
    assert record["stage"] == Q.RESUMING
    assert "the study runner could not start: OSError: no space left on device" in record["error"]


def test_a_designed_study_s_laws_are_read_at_their_own_temperature(tmp_path):
    from graph_scale_dynamics.research import advice as A
    drawn = {"quadrant": {"zero_temperature": "drawn"}}
    assert A.regime(drawn, {"zero": True}) == "zero temperature" and A.regime(drawn, {"zero": None}) == "not set"
    assert A.regime({"quadrant": {"zero_temperature": False}}) == "finite temperature"

    from graph_scale_dynamics.reporting import study_explorer as E
    law = E._law("a" * 64, None, {"spec": {"zero_temperature": True}}, {}, {})
    assert law["zero"] is True and "zero" in [key for key, *_ in E.LAW_FIELDS]


