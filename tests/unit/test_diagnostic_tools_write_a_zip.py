from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verify_claims():
    return _load("verify_claims")


def test_the_tool_writes_a_zip_where_the_operator_can_reach_it(verify_claims, capsys):
    code = verify_claims.main([])
    written = Path(capsys.readouterr().out.strip().splitlines()[-1])
    try:
        assert written.is_file() and written.suffix == ".zip"
        assert "scratch" not in written.parts
        assert written.parent == ROOT / "var" / "diagnostics"
        with zipfile.ZipFile(written) as bundle:
            assert set(bundle.namelist()) == {"summary.json", "claims.jsonl", "ABOUT.txt"}
            summary = json.loads(bundle.read("summary.json"))
            rows = [json.loads(line) for line in
                    bundle.read("claims.jsonl").decode().splitlines() if line.strip()]
        assert summary["readings"], "the summary must lead with its readings"
        assert "scratch" in summary, "the scratch join is recorded as metadata"
        assert rows and all("verdict" in row and "measured" in row for row in rows)
        assert code == 1, (
            "the offline lane is a gate and one tree claim is known false, so it "
            "has to exit non-zero")
    finally:
        written.unlink(missing_ok=True)


def test_the_tool_opens_no_database_and_reads_no_campaign(verify_claims, tmp_path, capsys):
    out = tmp_path / "claims.zip"
    verify_claims.main(["--out", str(out)])
    with zipfile.ZipFile(out) as bundle:
        summary = json.loads(bundle.read("summary.json"))
    assert list(summary["by_lane"]) == ["tree"] and summary["errors"] == []


def test_the_tool_honours_an_explicit_out_and_leaves_no_partial(verify_claims, tmp_path, capsys):
    out = tmp_path / "claims.zip"
    verify_claims.main(["--out", str(out)])
    assert out.is_file()
    assert not out.with_suffix(".partial").exists()
    assert str(out) in capsys.readouterr().out


def test_the_scratch_join_is_metadata_and_never_a_path(verify_claims, tmp_path):
    out = tmp_path / "claims.zip"
    verify_claims.main(["--out", str(out)])
    with zipfile.ZipFile(out) as bundle:
        summary = json.loads(bundle.read("summary.json"))
    assert isinstance(summary["scratch"], dict)


def test_the_trial_only_deletes_what_it_made():
    trial = _load("trial_campaign_manager")
    assert trial.MARKER, "the trial must mark what it creates"

    class Repo:
        def __init__(self):
            self.campaigns = {"7": {"change_reason": f"made by {trial.MARKER}"},
                              "8": {"change_reason": "the operator's own"},
                              "9": {"change_reason": f"made by {trial.MARKER}"}}
            self.stopped, self.deleted = [], []

        def campaign(self, campaign_id):
            return self.campaigns.get(campaign_id)

        def stop_campaign_work(self, campaign_id, reason):
            self.stopped.append(campaign_id)

        def delete_campaign(self, campaign_id, force=False):
            self.deleted.append((campaign_id, force))

    repo = Repo()
    run = trial.Trial.__new__(trial.Trial)
    run.repo, run.created = repo, ["7", "8", "404"]
    assert run.clean_up(keep=True) == [] and repo.deleted == []
    assert run.clean_up(keep=False) == ["7"]
    assert repo.stopped == ["7"] and repo.deleted == [("7", True)], "only what this run made and marked"


def test_the_trial_asserts_a_ladder_no_campaign_produces_by_accident():
    trial = _load("trial_campaign_manager")
    assert len(trial.SEEDED_LADDER) >= 3
    assert len(set(trial.SEEDED_LADDER.values())) == len(trial.SEEDED_LADDER), (
        "two rungs with the same count let a payload that reads the wrong rung pass")


def test_the_trial_cleans_up_every_campaign_it_made(monkeypatch):
    trial = _load("trial_campaign_manager")
    made = iter(["7", "8"])
    monkeypatch.setattr(trial.manager, "handle", lambda repo, body: ({"ok": True, "campaign_id": next(made)}, 200))

    class _Repo:
        deleted: list = []

        def campaign(self, campaign_id):
            return {"change_reason": f"{trial.MARKER}: x"} if campaign_id in ("7", "8") else None

        def stop_campaign_work(self, campaign_id, reason):
            return 0

        def delete_campaign(self, campaign_id, force):
            self.deleted.append(campaign_id)

    run = trial.Trial(_Repo())
    run.author("1", trial.TOO_SMALL)
    run.author("1", trial.FEASIBLE)
    assert run.created == ["7", "8"] and run.clean_up(keep=False) == ["7", "8"]
