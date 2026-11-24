from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class _ControlRepo:
    EXTEND_ONLY_PREFIX = "extend_only:"

    def __init__(self):
        self.flags: dict[str, str] = {}

    def set_flag(self, key, value):
        self.flags[str(key)] = str(value)

    def get_flag(self, key, default=""):
        return self.flags.get(str(key), default)


def _repo_methods(repo):
    from graph_scale_dynamics.db.repo import Repo

    for name in ("set_campaign_extend_only", "campaign_extend_only"):
        setattr(repo, name, getattr(Repo, name).__get__(repo, type(repo)))
    return repo


def test_the_switch_is_stored_where_it_can_be_set_without_a_resync():
    repo = _repo_methods(_ControlRepo())
    assert repo.campaign_extend_only("1") is False
    assert repo.set_campaign_extend_only("1", True) is True
    assert repo.flags == {"extend_only:1": "1"}
    assert repo.campaign_extend_only("1") is True
    repo.set_campaign_extend_only("1", False)
    assert repo.campaign_extend_only("1") is False


def test_the_proposer_reads_the_flag_set_not_the_campaign_row():
    from graph_scale_dynamics.services.proposer.main import extend_only, proposal_targets

    actives = [{"campaign_id": "1"}, {"campaign_id": "2"}]
    assert extend_only(actives[0]) is False, "no flag, no spec: open"
    assert extend_only(actives[0], frozenset({"1"})) is True
    assert [c["campaign_id"] for c in proposal_targets(actives, frozenset({"1"}))] == ["2"]
    assert [c["campaign_id"] for c in proposal_targets(actives, frozenset({"1", "2"}))] == []


def test_a_spec_can_still_declare_it_at_creation():
    from graph_scale_dynamics.services.proposer.main import extend_only

    assert extend_only({"campaign_id": "9", "spec": {"search": {"extend_only": True}}}) is True


def test_the_command_refuses_an_unknown_campaign_and_sets_a_known_one(monkeypatch, capsys):
    from types import SimpleNamespace

    import main as gsd_main
    switched = []

    class Repo:
        def __init__(self, db):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def campaign(self, campaign_id):
            return {"campaign_id": campaign_id} if campaign_id == "3" else None

        def set_campaign_extend_only(self, campaign_id, on):
            switched.append((campaign_id, on))
            return on

    monkeypatch.setattr(gsd_main, "Repo", Repo)
    monkeypatch.setattr(gsd_main, "init_db", lambda db: None)
    monkeypatch.setattr(gsd_main, "paths", lambda args: ("db", None, None))
    assert gsd_main.cmd_extend_only(SimpleNamespace(campaign="9", on=True, off=False)) == 2
    assert "refused: no campaign 9" in capsys.readouterr().err and switched == []
    assert gsd_main.cmd_extend_only(SimpleNamespace(campaign="3", on=True, off=False)) == 0
    assert switched == [("3", True)] and "now extend-only" in capsys.readouterr().out
