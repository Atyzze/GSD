from contextlib import contextmanager

import pytest

import main


class _Repo:
    def __init__(self, children=()):
        self.children, self.calls = list(children), []

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id} if campaign_id in ("7", "8") else None

    def dependent_campaigns(self, campaign_id):
        return self.children if campaign_id == "7" else []

    def stop_campaign_work(self, campaign_id, reason):
        self.calls.append(("stop", campaign_id))
        return 2

    def delete_campaign(self, campaign_id, force=False, progress=None):
        self.calls.append(("delete", campaign_id, force))
        return {"campaigns": 1}

    def get_flag(self, key, default=""):
        return default


@pytest.fixture(autouse=True)
def _no_maintenance_lock(monkeypatch):
    from graph_scale_dynamics.operations import maintenance

    @contextmanager
    def exclusive(repo):
        yield

    monkeypatch.setattr(maintenance, "exclusive_maintenance", exclusive)


def test_a_campaign_is_deleted_from_the_command_line_after_its_work_is_stopped():
    assert main.build_parser().parse_args(["campaign", "delete", "7"]).sub == "delete"
    repo = _Repo()
    assert main._delete_campaign_easy(repo, "7", yes=True) == 0
    assert repo.calls == [("stop", "7"), ("delete", "7", True)]


def test_an_unknown_campaign_or_one_with_children_is_not_deleted():
    repo = _Repo(children=[{"child_campaign_id": "8"}])
    assert main._delete_campaign_easy(repo, "9", yes=True) == 2
    assert main._delete_campaign_easy(repo, "7", yes=True) == 2 and repo.calls == []
    assert main._delete_campaign_easy(repo, "7", yes=True, cascade=True) == 0
    assert repo.calls == [("stop", "8"), ("delete", "8", True), ("stop", "7"), ("delete", "7", True)]


def test_a_campaign_is_closed_by_one_name():
    parser = main.build_parser()
    assert parser.parse_args(["campaign", "close", "7"]).sub == "close"
    with pytest.raises(SystemExit):
        parser.parse_args(["campaign", "stop", "7"])
